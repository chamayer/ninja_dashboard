"""Ingest adapter for the repository shared conditions engine."""

from __future__ import annotations

import json
from collections.abc import Iterable
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
    profile = load_active_profile(cur)
    decision = assess(condition, profile, tuple(signals), now, participant)
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
    participant_scope = (
        (participant.kind, str(participant.reference), participant.role)
        if participant is not None
        else ("condition", "00000000-0000-0000-0000-000000000000", "aggregate")
    )
    cur.execute(
        """INSERT INTO operations.condition_assessments
        (tenant_id,row_kind,finding_id,participant_kind,participant_id,participant_role,
         condition_identity,policy_version,
         coverage,response,reevaluation_key)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (tenant_id,row_kind,finding_id,participant_kind,participant_id,participant_role)
        DO UPDATE SET
          condition_identity=EXCLUDED.condition_identity,
          policy_version=EXCLUDED.policy_version, coverage=EXCLUDED.coverage,
          response=EXCLUDED.response, reevaluation_key=EXCLUDED.reevaluation_key,
          assessed_at=now()""",
        (
            condition.tenant_id,
            condition.row_kind,
            condition.row_id,
            participant_scope[0],
            participant_scope[1],
            participant_scope[2],
            condition.identity,
            profile.version,
            Jsonb(coverage_json),
            Jsonb(response),
            reevaluation_key,
        ),
    )
    cur.execute(
        """DELETE FROM operations.condition_participants
        WHERE tenant_id=%s AND row_kind=%s AND finding_id=%s""",
        (condition.tenant_id, condition.row_kind, condition.row_id),
    )
    cur.executemany(
        """INSERT INTO operations.condition_participants
        (tenant_id,row_kind,finding_id,participant_kind,participant_id,participant_role)
        VALUES (%s,%s,%s,%s,%s,%s)""",
        [
            (
                condition.tenant_id,
                condition.row_kind,
                condition.row_id,
                item.kind,
                item.reference,
                item.role,
            )
            for item in condition.participants
        ],
    )
    return response


def load_active_profile(cur: Any) -> Profile:
    """Load the active policy document from the database."""
    cur.execute(
        """SELECT policy FROM operations.condition_policy_versions
        WHERE active ORDER BY version DESC LIMIT 1"""
    )
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("No active condition policy is configured")
    policy = row["policy"] if isinstance(row, dict) else row[0]
    if isinstance(policy, str):
        policy = json.loads(policy)
    return parse_profile(policy)


def _as_json(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "__dataclass_fields__"):
        return {name: _as_json(getattr(value, name)) for name in value.__dataclass_fields__}
    if isinstance(value, tuple):
        return [_as_json(item) for item in value]
    return json.loads(json.dumps(value, default=str))
