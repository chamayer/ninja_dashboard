"""Shared SQL predicates for operator-level condition priority rules."""

from __future__ import annotations


def critical_priority_clause(finding_alias: str) -> str:
    """Return a predicate excluding lower findings blocked by a live Critical.

    The predicate is deliberately scoped to the same canonical subject or an
    overlapping non-context participant. It also proves that the Critical
    finding has current executable assessments for its complete participant
    set, so stale or pending Critical findings cannot block work.
    """
    return f"""
                   AND (
                       {finding_alias}.severity NOT IN ('medium', 'low', 'info')
                       OR NOT EXISTS (
                       SELECT 1
                         FROM operations.findings blocker
                        WHERE blocker.tenant_id = {finding_alias}.tenant_id
                          AND blocker.id <> {finding_alias}.id
                          AND blocker.severity = 'critical'
                          AND blocker.status IN ('open', 'acknowledged', 'investigating')
                          AND (blocker.snoozed_until IS NULL OR blocker.snoozed_until <= now())
                          AND (
                              (blocker.subject_type = {finding_alias}.subject_type
                               AND blocker.subject_id = {finding_alias}.subject_id)
                              OR EXISTS (
                                  SELECT 1
                                    FROM operations.condition_participants bp
                                    JOIN operations.condition_participants fp
                                      ON fp.tenant_id = bp.tenant_id
                                     AND fp.row_kind = bp.row_kind
                                     AND fp.participant_kind = bp.participant_kind
                                     AND fp.participant_id = bp.participant_id
                                     AND fp.participant_role = bp.participant_role
                                   WHERE bp.tenant_id = blocker.tenant_id
                                     AND bp.row_kind = 'entity'
                                     AND bp.finding_id = blocker.id
                                     AND bp.participant_role <> 'context'
                                     AND fp.finding_id = {finding_alias}.id
                                     AND fp.participant_role <> 'context'
                              )
                          )
                          AND (
                              EXISTS (
                              SELECT 1
                                FROM operations.condition_assessments ba
                                JOIN operations.condition_policy_versions bpv
                                  ON bpv.version = ba.policy_version AND bpv.active
                               WHERE ba.tenant_id = blocker.tenant_id
                                 AND ba.row_kind = 'entity'
                                 AND ba.finding_id = blocker.id
                                 AND ba.participant_kind = 'condition'
                                 AND (ba.response->>'may_execute')::boolean IS TRUE
                                 AND ba.assessed_at >= now() -
                                     (bpv.policy->>'freshness_hours')::integer * interval '1 hour'
                              )
                              OR EXISTS (
                                  SELECT 1
                                    FROM operations.condition_participants expected_scope
                                   WHERE expected_scope.tenant_id = blocker.tenant_id
                                     AND expected_scope.row_kind = 'entity'
                                     AND expected_scope.finding_id = blocker.id
                                     AND expected_scope.participant_role <> 'context'
                              )
                          )
                          AND NOT EXISTS (
                              SELECT 1
                                FROM operations.condition_participants expected
                               WHERE expected.tenant_id = blocker.tenant_id
                                 AND expected.row_kind = 'entity'
                                 AND expected.finding_id = blocker.id
                                 AND expected.participant_role <> 'context'
                                 AND NOT EXISTS (
                                     SELECT 1
                                       FROM operations.condition_assessments pa
                                       JOIN operations.condition_policy_versions pp
                                         ON pp.version = pa.policy_version AND pp.active
                                      WHERE pa.tenant_id = expected.tenant_id
                                        AND pa.row_kind = expected.row_kind
                                        AND pa.finding_id = expected.finding_id
                                        AND pa.participant_kind = expected.participant_kind
                                        AND pa.participant_id = expected.participant_id
                                        AND pa.participant_role = expected.participant_role
                                        AND (pa.response->>'may_execute')::boolean IS TRUE
                                        AND pa.assessed_at >= now() -
                                            (pp.policy->>'freshness_hours')::integer * interval '1 hour'
                                 )
                          )
                       )
                   )
    """
