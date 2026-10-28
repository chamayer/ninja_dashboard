"""Consistency check for ``operations.device_requirement_state`` (ADR-0035).

The evaluator's coverage pass writes the verdicts in the transaction that
writes its findings (migration 0332); nothing else writes them. This module
only audits them against the open missing/stale findings.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def summarize_state(cur: Any, tenant_id: int = 1) -> list:
    """Read-only explanation counts; raw drift and its history remain untouched.

    Only a current assessment written by requirement reconciliation can explain
    deliberate retention. Unknown lifecycle evidence and arbitrary blocked rows
    are not silently accepted. Source/identity issues still need their normal
    operational review; this report does not authorize repairs or closure.
    """
    cur.execute(
        """
        WITH observed AS (
            SELECT n.device_id,n.entity_type,n.platform,n.disagreement,
                   EXISTS (
                       SELECT 1 FROM operations.condition_assessments a
                       JOIN operations.condition_policy_versions p
                         ON p.active AND p.version=a.policy_version
                        AND p.digest=a.policy_digest
                        WHERE a.tenant_id=%s AND a.row_kind='entity'
                          AND a.finding_id=n.finding_id
                          AND a.participant_kind='device'
                          AND a.participant_id=n.device_id
                          AND a.participant_role='affected'
                          AND a.reevaluation_key LIKE 'requirement-reconcile:%%'
                          AND a.assessed_at >= now() -
                              (p.policy->>'freshness_hours')::integer * interval '1 hour'
                          AND NOT (COALESCE(a.response->'blockers','[]'::jsonb)
                                   ? 'lifecycle:unmeasured')
                          AND (
                            ((a.response->>'may_clear')::boolean IS FALSE
                             AND a.response->>'disposition' IN ('blocked','suppressed')
                             AND (
                              a.response->'reasons' ? 'existing_operator_suppression'
                              OR a.response->'reasons' ? 'offline:extended_absence'
                              OR a.response->'reasons' ? 'offline:reported_without_duration'
                              OR a.response->'reasons' ? 'identity:unsettled_group'
                              OR EXISTS (
                                  SELECT 1 FROM operations.admin_findings root
                                  WHERE root.tenant_id=a.tenant_id
                                    AND root.status IN ('open','acknowledged','investigating')
                                    AND a.response->'blockers' ? root.condition_key
                                    AND root.condition_key LIKE 'source_failure:binding:%%'
                              )
                             ))
                            OR (
                              (a.response->>'may_clear')::boolean IS TRUE
                              AND a.response->>'disposition' = 'eligible'
                              AND EXISTS (
                                SELECT 1 FROM operations.devices d
                                JOIN operations.finding_state fs
                                  ON fs.tenant_id=d.tenant_id
                                 AND fs.finding_id=n.finding_id
                                 AND fs.attention='covered'
                                JOIN operations.findings root
                                  ON root.tenant_id=d.tenant_id
                                 AND root.id=ANY(fs.covered_by)
                                 AND root.subject_type='device' AND root.subject_id=d.id
                                JOIN operations.finding_types rt
                                  ON rt.id=root.finding_type_id AND rt.name='device_offline'
                                WHERE d.tenant_id=a.tenant_id AND d.id=n.device_id
                                  AND d.lifecycle_status='pending_cleanup'
                                  AND d.deleted_at IS NULL
                                  AND root.status IN ('open','acknowledged','investigating')
                                  AND root.last_detected_at >= a.assessed_at
                                  AND root.finding_details->>'lifecycle_reason'='contact_policy'
                                  AND root.finding_details->>'fully_offline_since' IS NOT NULL
                                  AND NOT EXISTS (
                                    SELECT 1 FROM operations.device_operator_decisions dec
                                    WHERE dec.tenant_id=d.tenant_id AND dec.device_id=d.id
                                      AND dec.dimension='in_use_confirmed'
                                      AND dec.value='true'::jsonb
                                  )
                              )
                            )
                          )
                   ) AS guarded
              FROM operations.device_requirement_state_disagreements(%s) n
        ), entries AS (
            SELECT device_id,entity_type,platform,disagreement,bool_and(guarded) AS guarded
              FROM observed GROUP BY device_id,entity_type,platform,disagreement
        )
        SELECT disagreement,
               CASE WHEN guarded THEN 'retained_by_current_guard'
                    ELSE 'requires_review' END AS explanation,
               count(*) AS entries
          FROM entries GROUP BY disagreement,guarded ORDER BY disagreement,guarded
        """,
        (tenant_id, tenant_id),
    )
    return cur.fetchall()


def check_state(cur: Any, tenant_id: int = 1) -> int:
    """Record every disagreement between verdicts and open findings; return the open count.

    Disagreements are kept in ``device_requirement_state_drift`` until they
    clear. They are not repaired: the evaluator is the authority, so each one
    is a defect to explain, not a value to overwrite.
    """
    cur.execute(
        "SELECT to_regprocedure('operations.check_device_requirement_state(bigint)') IS NOT NULL"
    )
    row = cur.fetchone()
    if not bool(next(iter(row.values())) if isinstance(row, dict) else row[0]):
        return 0
    cur.execute("SELECT operations.check_device_requirement_state(%s)", (tenant_id,))
    row = cur.fetchone()
    count = int(next(iter(row.values())) if isinstance(row, dict) else row[0])
    if count:
        log.warning(
            "requirement state drift: %d open disagreement(s) with findings", count
        )
    return count
