"""The write boundary for live condition assessments.

Finding producers supply typed participants, signals, and coverage. This
module applies the shared pure engine and persists only the derived response;
legacy finding evidence and operator handling remain separate.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, replace

from django.db import connection, transaction
from shared.conditions.contracts import Condition, EvaluationCoverage, Participant, Signal
from shared.conditions.engine import assess
from shared.conditions.policy import Profile, parse_profile


def _json(value):
    return json.dumps(value, default=str, separators=(",", ":"))


def load_active_profile() -> Profile:
    """Load the active policy document from Operations, never from Git."""
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT version, digest, policy FROM operations.condition_policy_versions
            WHERE active ORDER BY version DESC LIMIT 1"""
        )
        row = cursor.fetchone()
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


def record_assessment(
    condition: Condition,
    signals: Iterable[Signal],
    coverage: EvaluationCoverage,
    *,
    now,
    reevaluation_key: str,
    participant: Participant | None = None,
) -> dict:
    """Evaluate and persist one condition scope.

    The caller must have established the tenant context used by Operations.
    ``may_clear`` additionally requires complete fresh coverage, so recovery
    cannot be authorized by a dependency transition alone.
    """
    if condition.tenant_id <= 0 or not reevaluation_key:
        raise ValueError("A tenant and reevaluation key are required")
    condition = _with_current_handling(condition)
    profile = load_active_profile()
    signals = tuple(signals)
    decision = assess(condition, profile, signals, now, participant)
    signal_watermark = hashlib.sha256(
        json.dumps(
            {
                "policy_digest": profile.digest,
                "coverage": asdict(coverage),
                "participant": asdict(participant) if participant else None,
                "handling": {
                    "status": condition.status,
                    "snoozed_until": condition.snoozed_until.isoformat()
                    if condition.snoozed_until
                    else None,
                },
                "participants": [asdict(item) for item in condition.participants],
                "signals": [asdict(signal) for signal in signals],
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()[:24]
    reevaluation_key = f"{reevaluation_key}:{signal_watermark}"
    response = asdict(decision)
    response["participant"] = asdict(participant) if participant else None
    response["may_clear"] = decision.may_execute and coverage.permits_clearing
    response["coverage_recovery_required"] = not coverage.permits_clearing
    coverage_data = asdict(coverage)
    currentness = {
        "evidence": signal_watermark,
        "scope": coverage_data,
        "membership": hashlib.sha256(
            _json([asdict(item) for item in condition.participants]).encode()
        ).hexdigest(),
        "handling": hashlib.sha256(
            _json({"status": condition.status, "snoozed_until": condition.snoozed_until}).encode()
        ).hexdigest(),
    }
    policy_version = profile.version
    identity = condition.identity
    participant_scope = (
        (participant.kind, str(participant.reference), participant.role)
        if participant is not None
        else ("condition", "00000000-0000-0000-0000-000000000000", "aggregate")
    )
    with transaction.atomic(), connection.cursor() as cursor:
        _validate_participants(cursor, condition)
        cursor.execute(
            """INSERT INTO operations.condition_assessments
                (tenant_id,row_kind,finding_id,participant_kind,participant_id,participant_role,
                 condition_identity,policy_version,policy_digest,
                 coverage,response,reevaluation_key,currentness)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s::jsonb)
                ON CONFLICT (tenant_id,row_kind,finding_id,participant_kind,participant_id,participant_role)
                DO UPDATE SET
                  condition_identity=EXCLUDED.condition_identity,
                  policy_version=EXCLUDED.policy_version,
                  policy_digest=EXCLUDED.policy_digest,
                  coverage=EXCLUDED.coverage,response=EXCLUDED.response,
                  reevaluation_key=EXCLUDED.reevaluation_key,currentness=EXCLUDED.currentness,
                  assessed_at=now()""",
            (
                condition.tenant_id,
                condition.row_kind,
                condition.row_id,
                participant_scope[0],
                participant_scope[1],
                participant_scope[2],
                identity,
                policy_version,
                profile.digest,
                _json(coverage_data),
                _json(response),
                reevaluation_key,
                _json(currentness),
            ),
        )
        cursor.execute(
            "SELECT operations.reconcile_condition_participants(%s,%s,%s,%s::jsonb)",
            (condition.tenant_id, condition.row_kind, condition.row_id,
             _json([asdict(item) for item in condition.participants])),
        )
    return response


def reevaluation_key(*parts: str) -> str:
    """Build a stable key from producer evidence watermarks."""
    if not parts or any(not part for part in parts):
        raise ValueError("Reevaluation keys require nonempty parts")
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def _with_current_handling(condition: Condition) -> Condition:
    """Read operator handling at the write boundary, not from a stale emitter."""
    table = "findings" if condition.row_kind == "entity" else "admin_findings"
    columns = "status, snoozed_until" if condition.row_kind == "entity" else "status, NULL"
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT {columns} FROM operations.{table} WHERE tenant_id=%s AND id=%s",
            (condition.tenant_id, condition.row_id),
        )
        row = cursor.fetchone()
    if row is None:
        return condition
    return replace(condition, status=row[0], snoozed_until=row[1])


def _validate_participants(cursor, condition: Condition) -> None:
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
        cursor.execute(
            f"SELECT {column}::text FROM operations.{table} "
            f"WHERE tenant_id=%s AND {column} = ANY(%s::uuid[])",
            (condition.tenant_id, list(references)),
        )
        found = {str(row[0]) for row in cursor.fetchall()}
        if references - found:
            raise ValueError(f"Participant references are missing or outside the tenant: {kind}")
