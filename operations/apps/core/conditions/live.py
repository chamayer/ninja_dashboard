"""The write boundary for live condition assessments.

Finding producers supply typed participants, signals, and coverage. This
module applies the shared pure engine and persists only the derived response;
legacy finding evidence and operator handling remain separate.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict

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
            """SELECT policy FROM operations.condition_policy_versions
            WHERE active ORDER BY version DESC LIMIT 1"""
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("No active condition policy is configured")
    policy = row["policy"] if isinstance(row, dict) else row[0]
    return parse_profile(policy)


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
    profile = load_active_profile()
    signals = tuple(signals)
    decision = assess(condition, profile, signals, now, participant)
    response = asdict(decision)
    response["participant"] = asdict(participant) if participant else None
    response["may_clear"] = decision.may_execute and coverage.permits_clearing
    response["coverage_recovery_required"] = not coverage.permits_clearing
    coverage_data = asdict(coverage)
    policy_version = profile.version
    identity = condition.identity
    participant_scope = (
        (participant.kind, str(participant.reference), participant.role)
        if participant is not None
        else ("condition", "00000000-0000-0000-0000-000000000000", "aggregate")
    )
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO operations.condition_assessments
                (tenant_id,row_kind,finding_id,participant_kind,participant_id,participant_role,
                 condition_identity,policy_version,
                 coverage,response,reevaluation_key)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s)
                ON CONFLICT (tenant_id,row_kind,finding_id,participant_kind,participant_id,participant_role)
                DO UPDATE SET
                  condition_identity=EXCLUDED.condition_identity,
                  policy_version=EXCLUDED.policy_version,
                  coverage=EXCLUDED.coverage,response=EXCLUDED.response,
                  reevaluation_key=EXCLUDED.reevaluation_key,assessed_at=now()""",
            (
                condition.tenant_id,
                condition.row_kind,
                condition.row_id,
                participant_scope[0],
                participant_scope[1],
                participant_scope[2],
                identity,
                policy_version,
                _json(coverage_data),
                _json(response),
                reevaluation_key,
            ),
        )
        cursor.execute(
            """DELETE FROM operations.condition_participants
                WHERE tenant_id=%s AND row_kind=%s AND finding_id=%s""",
            (condition.tenant_id, condition.row_kind, condition.row_id),
        )
        cursor.executemany(
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


def reevaluation_key(*parts: str) -> str:
    """Build a stable key from producer evidence watermarks."""
    if not parts or any(not part for part in parts):
        raise ValueError("Reevaluation keys require nonempty parts")
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()
