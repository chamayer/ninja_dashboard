"""Ingest adapter for the repository shared conditions engine."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from shared.conditions.contracts import (
    Condition,
    EvaluationCoverage,
    Participant,
    Signal,
)
from shared.conditions.engine import assess
from shared.conditions.policy import Profile, parse_profile


def record_assessment(
    cur: Any,
    condition: Condition,
    signals: Iterable[Signal],
    coverage: EvaluationCoverage,
    *,
    now: datetime,
    reevaluation_key: str,
    participant: Participant | None = None,
) -> dict[str, Any]:
    """Evaluate and persist one participant scope in the current transaction."""
    if not reevaluation_key:
        raise ValueError("A reevaluation key is required")
    condition = _with_current_handling(cur, condition)
    _validate_participants(cur, condition)
    profile = load_active_profile(cur)
    signals = tuple(signals)
    decision = assess(condition, profile, signals, now, participant)
    signal_watermark = hashlib.sha256(
        json.dumps(
            {
                "policy_digest": profile.digest,
                "coverage": _as_json(coverage),
                "participant": _as_json(participant),
                "handling": {
                    "status": condition.status,
                    "snoozed_until": condition.snoozed_until.isoformat()
                    if condition.snoozed_until
                    else None,
                },
                "participants": [_as_json(item) for item in condition.participants],
                "signals": [
                    {
                        "prerequisite": signal.prerequisite,
                        "participant": _as_json(signal.participant),
                        "readiness": signal.readiness,
                        "reason": signal.reason,
                        "blocker_references": list(signal.blocker_references),
                    }
                    for signal in signals
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()[:24]
    reevaluation_key = f"{reevaluation_key}:{signal_watermark}"
    response = {
        "condition_identity": decision.condition_identity,
        "participant": _as_json(participant),
        "disposition": decision.disposition,
        "may_evaluate": decision.may_evaluate,
        "may_notify": decision.may_notify,
        "may_execute": decision.may_execute,
        "may_clear": decision.may_execute and coverage.permits_clearing,
        "coverage_recovery_required": not coverage.permits_clearing,
        "reasons": list(decision.reasons),
        "blockers": list(decision.blockers),
    }
    coverage_json = _as_json(coverage)
    currentness = {
        "evidence": signal_watermark,
        "scope": coverage_json,
        "membership": hashlib.sha256(
            json.dumps([_as_json(item) for item in condition.participants], sort_keys=True).encode()
        ).hexdigest(),
        "handling": hashlib.sha256(
            json.dumps({"status": condition.status, "snoozed_until": response.get("snoozed_until")}, sort_keys=True).encode()
        ).hexdigest(),
    }
    participant_scope = (
        (participant.kind, str(participant.reference), participant.role)
        if participant is not None
        else ("condition", "00000000-0000-0000-0000-000000000000", "aggregate")
    )
    cur.execute(
        """INSERT INTO operations.condition_assessments
        (tenant_id,row_kind,finding_id,participant_kind,participant_id,participant_role,
         condition_identity,policy_version,policy_digest,
         coverage,response,reevaluation_key,currentness)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (tenant_id,row_kind,finding_id,participant_kind,participant_id,participant_role)
        DO UPDATE SET
          condition_identity=EXCLUDED.condition_identity,
          policy_version=EXCLUDED.policy_version, policy_digest=EXCLUDED.policy_digest,
          coverage=EXCLUDED.coverage,
          response=EXCLUDED.response, reevaluation_key=EXCLUDED.reevaluation_key,
          currentness=EXCLUDED.currentness, assessed_at=now()""",
        (
            condition.tenant_id,
            condition.row_kind,
            condition.row_id,
            participant_scope[0],
            participant_scope[1],
            participant_scope[2],
            condition.identity,
            profile.version,
            profile.digest,
            Jsonb(coverage_json),
            Jsonb(response),
            reevaluation_key,
            Jsonb(currentness),
        ),
    )
    cur.execute(
        "SELECT operations.reconcile_condition_participants(%s,%s,%s,%s::jsonb)",
        (condition.tenant_id, condition.row_kind, condition.row_id,
         json.dumps([_as_json(item) for item in condition.participants])),
    )
    return response


def load_active_profile(cur: Any) -> Profile:
    """Load the active policy document from the database."""
    cur.execute(
        """SELECT version, digest, policy FROM operations.condition_policy_versions
        WHERE active ORDER BY version DESC LIMIT 1"""
    )
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("No active condition policy is configured")
    version = row["version"] if isinstance(row, dict) else row[0]
    stored_digest = row["digest"] if isinstance(row, dict) else row[1]
    policy = row["policy"] if isinstance(row, dict) else row[2]
    if isinstance(policy, str):
        policy = json.loads(policy)
    expected_digest = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
    if stored_digest != expected_digest:
        raise RuntimeError(f"Active condition policy {version} has an invalid digest")
    profile = parse_profile(policy)
    if profile.version != version:
        raise RuntimeError(f"Active condition policy version mismatch: {version}")
    return profile


def _with_current_handling(cur: Any, condition: Condition) -> Condition:
    """Use the persisted operator state when an emitter's snapshot is stale."""
    table = "findings" if condition.row_kind == "entity" else "admin_findings"
    columns = "status, snoozed_until" if condition.row_kind == "entity" else "status, NULL"
    cur.execute(
        f"SELECT {columns} FROM operations.{table} WHERE tenant_id=%s AND id=%s",
        (condition.tenant_id, condition.row_id),
    )
    row = cur.fetchone()
    if row is None:
        return condition
    return replace(condition, status=row[0], snoozed_until=row[1])


def _validate_participants(cur: Any, condition: Condition) -> None:
    """Reject owned participant references that are missing or cross-tenant."""
    tables = {
        "device": ("devices", "id"),
        "client": ("clients", "id"),
        "source_instance": ("source_instances", "id"),
        "source_binding": ("source_bindings", "id"),
        "collector_instance": ("collector_instances", "id"),
        "software_installation": ("software_installations_current", "installation_uuid"),
    }
    for kind, (table, column) in tables.items():
        references = {item.reference for item in condition.participants if item.kind == kind}
        if not references:
            continue
        cur.execute(
            f"SELECT {column}::text FROM operations.{table} "
            f"WHERE tenant_id=%s AND {column} = ANY(%s::uuid[])",
            (condition.tenant_id, list(references)),
        )
        found = {str(row[0]) for row in cur.fetchall()}
        missing = references - found
        if missing:
            raise ValueError(f"Participant references are missing or outside the tenant: {kind}")


def _as_json(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "__dataclass_fields__"):
        return {name: _as_json(getattr(value, name)) for name in value.__dataclass_fields__}
    if isinstance(value, tuple):
        return [_as_json(item) for item in value]
    return json.loads(json.dumps(value, default=str))
