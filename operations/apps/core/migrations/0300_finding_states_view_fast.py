"""Make the ``finding_states`` view fast: inline the freshness lookup, filter before computing.

Migration 0299 still took minutes on the Issues page. Two causes, both measured on the
production plan:

* ``finding_live_attention`` looked up the policy's freshness window with a subselect, so
  Postgres could not inline it and ran a query per row. The window is now passed in from
  one uncorrelated lookup, and the function has no subselect.
* The view's intermediate steps were materialized, so every query computed state for all
  582,000 findings (closed ones included) before filtering to the 39,000 active. They are
  marked ``NOT MATERIALIZED`` so the caller's status filter applies first.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
DROP VIEW IF EXISTS operations.finding_states;
DROP FUNCTION IF EXISTS operations.finding_live_attention(text, timestamptz, text, timestamptz);

CREATE OR REPLACE FUNCTION operations.finding_live_attention(
    p_status text, p_snoozed_until timestamptz, p_attention text, p_attention_at timestamptz,
    p_fresh_hours integer
) RETURNS text
LANGUAGE sql
STABLE
AS $function$
    SELECT CASE
        WHEN p_snoozed_until > now() THEN 'paused'
        WHEN p_status IN ('resolved', 'suppressed', 'wontfix') THEN ''
        WHEN p_attention IS NULL OR p_attention_at IS NULL
             OR p_attention_at < now() - p_fresh_hours * interval '1 hour' THEN 'pending'
        ELSE p_attention
    END
$function$;
ALTER FUNCTION operations.finding_live_attention(text, timestamptz, text, timestamptz, integer)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.finding_live_attention(text, timestamptz, text, timestamptz, integer)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.finding_live_attention(text, timestamptz, text, timestamptz, integer)
    TO operations_app, ninja_ingest, operations_readonly;

CREATE VIEW operations.finding_states
WITH (security_invoker = true) AS
WITH fresh AS MATERIALIZED (
    SELECT COALESCE((SELECT (policy->>'freshness_hours')::integer
                       FROM operations.condition_policy_versions
                      WHERE active ORDER BY version DESC LIMIT 1), 24) AS hours
), crit AS MATERIALIZED (
    SELECT c.id, c.tenant_id, ct.name AS finding_type, c.subject_type, c.subject_id
      FROM operations.findings c
      JOIN operations.finding_types ct ON ct.id = c.finding_type_id
     WHERE c.severity = 'critical'
       AND c.status IN ('open', 'acknowledged', 'investigating')
       AND operations.finding_live_attention(c.status, c.snoozed_until, c.attention, c.attention_at, (SELECT hours FROM fresh)) = 'needs_action'
), crit_parts AS MATERIALIZED (
    SELECT q.tenant_id, q.finding_id AS crit_id, q.participant_kind, q.participant_id
      FROM operations.condition_participants q
      JOIN crit ON crit.id = q.finding_id AND crit.tenant_id = q.tenant_id
     WHERE q.row_kind = 'entity' AND q.participant_role <> 'context'
), live AS NOT MATERIALIZED (
    SELECT f.id, f.tenant_id, f.finding_type_id, f.severity, f.status, f.snoozed_until,
           f.subject_type, f.subject_id,
           operations.finding_live_attention(f.status, f.snoozed_until, f.attention, f.attention_at, (SELECT hours FROM fresh)) AS live_attention
      FROM operations.findings f
), held AS NOT MATERIALIZED (
    SELECT l.id,
           (l.live_attention = 'needs_action'
            AND l.severity IN ('medium', 'low', 'info')
            AND (EXISTS (SELECT 1 FROM crit c
                          WHERE c.tenant_id = l.tenant_id
                            AND c.subject_type = l.subject_type AND c.subject_id = l.subject_id)
                 OR EXISTS (SELECT 1
                              FROM operations.condition_participants p
                              JOIN crit_parts q
                                ON q.tenant_id = p.tenant_id
                               AND q.participant_kind = p.participant_kind
                               AND q.participant_id = p.participant_id
                             WHERE p.finding_id = l.id AND p.tenant_id = l.tenant_id
                               AND p.row_kind = 'entity' AND p.participant_role <> 'context'))
           ) AS is_held
      FROM live l
)
SELECT l.id,
       l.tenant_id,
       l.finding_type_id,
       ft.name AS finding_type,
       l.severity,
       l.status,
       l.snoozed_until,
       l.subject_type,
       l.subject_id,
       CASE WHEN h.is_held THEN 'blocked' ELSE l.live_attention END AS attention,
       CASE WHEN h.is_held THEN (
           SELECT x.id FROM (
               SELECT c.id FROM crit c
                WHERE c.tenant_id = l.tenant_id
                  AND c.subject_type = l.subject_type AND c.subject_id = l.subject_id
               UNION ALL
               SELECT q.crit_id
                 FROM operations.condition_participants p
                 JOIN crit_parts q
                   ON q.tenant_id = p.tenant_id
                  AND q.participant_kind = p.participant_kind
                  AND q.participant_id = p.participant_id
                WHERE p.finding_id = l.id AND p.tenant_id = l.tenant_id
                  AND p.row_kind = 'entity' AND p.participant_role <> 'context'
           ) x(id) ORDER BY x.id LIMIT 1) END AS critical_finding_id,
       CASE WHEN h.is_held THEN (
           SELECT c2.finding_type FROM crit c2 WHERE c2.id = (
               SELECT x.id FROM (
                   SELECT c.id FROM crit c
                    WHERE c.tenant_id = l.tenant_id
                      AND c.subject_type = l.subject_type AND c.subject_id = l.subject_id
                   UNION ALL
                   SELECT q.crit_id
                     FROM operations.condition_participants p
                     JOIN crit_parts q
                       ON q.tenant_id = p.tenant_id
                      AND q.participant_kind = p.participant_kind
                      AND q.participant_id = p.participant_id
                    WHERE p.finding_id = l.id AND p.tenant_id = l.tenant_id
                      AND p.row_kind = 'entity' AND p.participant_role <> 'context'
               ) x(id) ORDER BY x.id LIMIT 1)) END AS critical_type,
       CASE WHEN h.is_held THEN (
           SELECT c3.subject_id FROM crit c3 WHERE c3.id = (
               SELECT x.id FROM (
                   SELECT c.id FROM crit c
                    WHERE c.tenant_id = l.tenant_id
                      AND c.subject_type = l.subject_type AND c.subject_id = l.subject_id
                   UNION ALL
                   SELECT q.crit_id
                     FROM operations.condition_participants p
                     JOIN crit_parts q
                       ON q.tenant_id = p.tenant_id
                      AND q.participant_kind = p.participant_kind
                      AND q.participant_id = p.participant_id
                    WHERE p.finding_id = l.id AND p.tenant_id = l.tenant_id
                      AND p.row_kind = 'entity' AND p.participant_role <> 'context'
               ) x(id) ORDER BY x.id LIMIT 1)) END AS critical_subject_id
  FROM live l
  JOIN operations.finding_types ft ON ft.id = l.finding_type_id
  JOIN held h ON h.id = l.id
;

ALTER VIEW operations.finding_states OWNER TO operations_migrate;
REVOKE ALL ON operations.finding_states FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.finding_states
    FROM operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.finding_states TO operations_app, ninja_ingest, operations_readonly;
"""

REVERSE_SQL = migrations.RunSQL.noop


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0299_finding_states_view_set_based"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
