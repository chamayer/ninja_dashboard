"""Domain-owned Home totals from current Coverage evaluator verdicts."""

from __future__ import annotations

from django.db import connection, transaction

from .computer_reads import current_computer_sql


def home_summary() -> dict:
    """Count current Computers by the highest-priority Coverage verdict.

    Missing is red, stale is separate, and any remaining applicable satisfied
    verdict is green. Exempt-only Computers are excluded; non-applicable and
    unevaluated Computers are neutral. This is current state; Home has no
    Coverage trend because the evaluator retains no historical verdict total.
    """
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL operations.tenant_id = 1")
        cursor.execute(
            f"""
            WITH current_computers AS (
                SELECT device.device_id
                  FROM operations.v_device device
                  JOIN operations.computer_client_ownership owner
                    ON owner.tenant_id = device.tenant_id
                   AND owner.device_id = device.device_id
                   AND owner.effective_client_id = device.client_id
                   AND owner.state IN ('resolved', 'decision_protected')
                 WHERE device.tenant_id = 1
                   AND {current_computer_sql('device')}
            ), per_computer AS (
                SELECT computer.device_id,
                       COUNT(state.device_id) > 0 AS has_state,
                       COALESCE(BOOL_OR(state.verdict = 'missing'), FALSE) AS missing,
                       COALESCE(BOOL_OR(state.verdict = 'stale'), FALSE) AS stale,
                       COALESCE(BOOL_OR(state.verdict = 'satisfied'), FALSE) AS satisfied,
                       COALESCE(BOOL_OR(state.verdict = 'exempt'), FALSE) AS exempt,
                       COALESCE(BOOL_OR(state.verdict IN (
                           'outside_coverage', 'os_unknown', 'pending_cleanup', 'not_evaluated'
                       )), FALSE) AS not_applicable,
                       MAX(state.evaluated_at) AS evaluated_at
                  FROM current_computers computer
                  LEFT JOIN operations.device_requirement_state state
                    ON state.tenant_id = 1 AND state.device_id = computer.device_id
                 GROUP BY computer.device_id
            )
            SELECT COUNT(*) FILTER (WHERE missing)::int AS not_meeting,
                   COUNT(*) FILTER (WHERE NOT missing AND stale)::int AS stale,
                   COUNT(*) FILTER (WHERE NOT missing AND NOT stale AND satisfied)::int AS meeting,
                   COUNT(*) FILTER (
                       WHERE NOT missing AND NOT stale AND NOT satisfied
                         AND (NOT has_state OR not_applicable)
                   )::int AS neutral,
                   COUNT(*) FILTER (
                       WHERE has_state AND exempt AND NOT missing AND NOT stale
                         AND NOT satisfied AND NOT not_applicable
                   )::int AS exempt,
                   MAX(evaluated_at) AS evaluated_at
              FROM per_computer
            """
        )
        not_meeting, stale, meeting, neutral, exempt, evaluated_at = cursor.fetchone()
    return {
        "meeting": meeting,
        "not_meeting": not_meeting,
        "stale": stale,
        "neutral": neutral,
        "exempt": exempt,
        "evaluated_at": evaluated_at,
    }
