"""Store each finding's attention when it is assessed, instead of recomputing it per view.

The Issues page used to roll every finding's per-participant assessments up into one
value (needs action, blocked, pending, covered) on each load: about 7 seconds of the
10 the 39,000 active findings cost. The roll-up depends only on stored assessments and
on whether a covering finding is still open, so it is stored on the finding:

* ``findings.attention`` and ``findings.attention_at``;
* ``operations.refresh_finding_attention(uuid[])``, the only definition of the rule;
* triggers on ``findings`` that refresh a finding when it opens, and refresh the
  findings it covers when its status changes (findings are closed by about 25 separate
  UPDATE statements, so a database trigger is the only complete hook);
* a one-time fill for the active findings.

Pause, resolve and "critical takes priority" are not stored: the page overlays them live.
Nothing else reads this column; notifications, source actions and the evaluators keep
reading assessments.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations, models

FORWARD_SQL = r"""
ALTER TABLE operations.findings
    ADD COLUMN IF NOT EXISTS attention text
        CONSTRAINT findings_attention_values
        CHECK (attention IN ('needs_action', 'blocked', 'pending', 'covered')),
    ADD COLUMN IF NOT EXISTS attention_at timestamptz;

CREATE INDEX IF NOT EXISTS idx_findings_attention_active
    ON operations.findings (tenant_id, attention)
    WHERE status IN ('open', 'acknowledged', 'investigating');

/* The roll-up rule, once. Same rule the Issues page used to compute per view:
 * every expected non-context participant has a current assessment and every one may
 * execute -> needs_action; any blocked -> blocked; a current covered_by assessment
 * whose covering finding is still open -> covered; anything else pending.
 * Pause is not part of it (the page overlays it live). Closed findings get NULL. */
CREATE OR REPLACE FUNCTION operations.compute_finding_attention(p_ids uuid[])
RETURNS TABLE (finding_id uuid, attention text)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
BEGIN
    IF p_ids IS NULL OR cardinality(p_ids) = 0 THEN
        RETURN;
    END IF;
    RETURN QUERY
    WITH pol AS (
        SELECT version, (policy->>'freshness_hours')::integer AS fresh_hours
          FROM operations.condition_policy_versions
         WHERE active ORDER BY version DESC LIMIT 1
    ), target AS (
        SELECT f.id, f.tenant_id, f.status
          FROM operations.findings f
         WHERE f.id = ANY(p_ids)
    ), expected AS (
        SELECT t.id,
               COALESCE(array_agg(DISTINCT cp.participant_kind || ':' || cp.participant_id::text
                                           || ':' || cp.participant_role
                         ORDER BY cp.participant_kind || ':' || cp.participant_id::text
                                           || ':' || cp.participant_role)
                        FILTER (WHERE cp.participant_role <> 'context'), ARRAY[]::text[]) AS participants
          FROM target t
     LEFT JOIN operations.condition_participants cp
            ON cp.tenant_id = t.tenant_id AND cp.row_kind = 'entity' AND cp.finding_id = t.id
         GROUP BY t.id
    ), assessed AS (
        SELECT a.finding_id,
               bool_or(a.participant_kind = 'condition'
                       AND (a.response->>'may_execute')::boolean IS TRUE) AS condition_execute,
               COALESCE(array_agg(DISTINCT a.participant_kind || ':' || a.participant_id::text
                                           || ':' || a.participant_role
                         ORDER BY a.participant_kind || ':' || a.participant_id::text
                                           || ':' || a.participant_role)
                        FILTER (WHERE a.participant_kind <> 'condition'), ARRAY[]::text[]) AS participants,
               COALESCE(array_agg(DISTINCT a.participant_kind || ':' || a.participant_id::text
                                           || ':' || a.participant_role
                         ORDER BY a.participant_kind || ':' || a.participant_id::text
                                           || ':' || a.participant_role)
                        FILTER (WHERE a.participant_kind <> 'condition'
                                  AND (a.response->>'may_execute')::boolean IS TRUE),
                        ARRAY[]::text[]) AS executable_participants,
               bool_or(a.response->>'disposition' = 'blocked') AS blocked
          FROM operations.condition_assessments a
          JOIN target t ON t.id = a.finding_id AND t.tenant_id = a.tenant_id
          JOIN pol ON pol.version = a.policy_version
         WHERE a.row_kind = 'entity'
           AND a.participant_role <> 'context'
           AND a.assessed_at >= now() - pol.fresh_hours * interval '1 hour'
         GROUP BY a.finding_id
    ), covered_candidates AS MATERIALIZED (
        -- Findings with a current covered_by assessment, and the finding each names.
        SELECT a.finding_id, a.tenant_id,
               CASE WHEN b.v ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                    THEN b.v::uuid END AS parent_id
          FROM operations.condition_assessments a
          JOIN target t ON t.id = a.finding_id AND t.tenant_id = a.tenant_id
          JOIN pol ON pol.version = a.policy_version
         CROSS JOIN LATERAL jsonb_array_elements_text(a.response->'blockers') b(v)
         WHERE a.row_kind = 'entity'
           AND a.participant_role <> 'context'
           AND a.assessed_at >= now() - pol.fresh_hours * interval '1 hour'
           AND EXISTS (SELECT 1 FROM jsonb_array_elements_text(a.response->'reasons') r
                        WHERE r LIKE 'covered\_by:%')
    ), covering AS (
        -- ...kept only while the covering finding is still open.
        SELECT DISTINCT c.finding_id
          FROM covered_candidates c
         WHERE c.parent_id IS NOT NULL
           AND EXISTS (SELECT 1 FROM operations.findings p
                        WHERE p.id = c.parent_id AND p.tenant_id = c.tenant_id
                          AND p.status IN ('open', 'acknowledged', 'investigating'))
    ), result AS (
        SELECT t.id,
               CASE
                   WHEN t.status NOT IN ('open', 'acknowledged', 'investigating') THEN NULL
                   WHEN a.finding_id IS NULL THEN 'pending'
                   WHEN EXISTS (SELECT 1 FROM covering cv WHERE cv.finding_id = t.id) THEN 'covered'
                   WHEN (e.participants = ARRAY[]::text[] AND COALESCE(a.condition_execute, false))
                     OR (e.participants <> ARRAY[]::text[]
                         AND a.participants = e.participants
                         AND a.executable_participants = e.participants) THEN 'needs_action'
                   WHEN COALESCE(a.blocked, false) THEN 'blocked'
                   ELSE 'pending'
               END AS attention
          FROM target t
          JOIN expected e ON e.id = t.id
     LEFT JOIN assessed a ON a.finding_id = t.id
    )
    SELECT r.id, r.attention FROM result r;
END
$function$;

/* Store the rolled-up value. The only writer of findings.attention. */
CREATE OR REPLACE FUNCTION operations.refresh_finding_attention(p_ids uuid[])
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE
    updated integer;
BEGIN
    UPDATE operations.findings f
       SET attention = r.attention, attention_at = now()
      FROM operations.compute_finding_attention(p_ids) r
     WHERE f.id = r.finding_id;
    GET DIAGNOSTICS updated = ROW_COUNT;
    RETURN updated;
END
$function$;

/* Every disagreement the consistency check finds is kept, with when and what it replaced. */
CREATE TABLE IF NOT EXISTS operations.finding_attention_drift (
    id bigserial PRIMARY KEY,
    tenant_id integer NOT NULL,
    finding_id uuid NOT NULL,
    finding_type text NOT NULL,
    stored_attention text,
    computed_attention text,
    found_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_finding_attention_drift_found
    ON operations.finding_attention_drift (found_at DESC);

/* Refresh the findings a status change touches: the finding itself, and every finding on
 * the same subject whose type is covered (directly or through a chain) by its type. */
CREATE OR REPLACE FUNCTION operations.refresh_attention_after_status_change()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE
    ids uuid[] := ARRAY[NEW.id];
BEGIN
    -- The refresh itself updates findings; never react to our own writes.
    IF pg_trigger_depth() > 1 THEN
        RETURN NULL;
    END IF;
    PERFORM operations.refresh_finding_attention(ids);
    PERFORM operations.refresh_finding_attention(coalesce((
        WITH RECURSIVE changed AS (
            SELECT f.subject_type, f.subject_id, ft.name AS type_name, f.tenant_id
              FROM operations.findings f
              JOIN operations.finding_types ft ON ft.id = f.finding_type_id
             WHERE f.id = ANY(ids)
        ), covered_types AS (
            SELECT DISTINCT c.subject_type, c.subject_id, c.tenant_id, ft.name
              FROM changed c
              JOIN operations.finding_types ft ON ft.covered_by ? c.type_name
            UNION
            SELECT ct.subject_type, ct.subject_id, ct.tenant_id, ft.name
              FROM covered_types ct
              JOIN operations.finding_types ft ON ft.covered_by ? ct.name
        )
        SELECT array_agg(DISTINCT f.id)
          FROM covered_types ct
          JOIN operations.finding_types ft ON ft.name = ct.name
          JOIN operations.findings f
            ON f.finding_type_id = ft.id AND f.tenant_id = ct.tenant_id
           AND f.subject_type = ct.subject_type AND f.subject_id = ct.subject_id
           AND f.status IN ('open', 'acknowledged', 'investigating')
    ), ARRAY[]::uuid[]));
    RETURN NULL;
END
$function$;

/* Row-level and limited to real status changes: the evaluators touch every finding
 * (last_seen_at) on each run, and that must cost nothing here. */
DROP TRIGGER IF EXISTS findings_attention_after_insert ON operations.findings;
CREATE TRIGGER findings_attention_after_insert
AFTER INSERT ON operations.findings
FOR EACH ROW EXECUTE FUNCTION operations.refresh_attention_after_status_change();

DROP TRIGGER IF EXISTS findings_attention_after_update ON operations.findings;
CREATE TRIGGER findings_attention_after_update
AFTER UPDATE OF status ON operations.findings
FOR EACH ROW WHEN (OLD.status IS DISTINCT FROM NEW.status)
EXECUTE FUNCTION operations.refresh_attention_after_status_change();

ALTER FUNCTION operations.compute_finding_attention(uuid[]) OWNER TO operations_migrate;
ALTER FUNCTION operations.refresh_finding_attention(uuid[]) OWNER TO operations_migrate;
ALTER TABLE operations.finding_attention_drift OWNER TO operations_migrate;
ALTER TABLE operations.finding_attention_drift ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.finding_attention_drift FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS finding_attention_drift_tenant_isolation ON operations.finding_attention_drift;
CREATE POLICY finding_attention_drift_tenant_isolation
ON operations.finding_attention_drift
USING (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint)
WITH CHECK (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint);
REVOKE ALL ON FUNCTION operations.compute_finding_attention(uuid[])
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.compute_finding_attention(uuid[])
    TO operations_app, ninja_ingest;
GRANT SELECT ON operations.finding_attention_drift TO operations_app, operations_readonly;
GRANT SELECT, INSERT ON operations.finding_attention_drift TO ninja_ingest;
GRANT USAGE ON SEQUENCE operations.finding_attention_drift_id_seq TO ninja_ingest;
ALTER FUNCTION operations.refresh_attention_after_status_change() OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.refresh_finding_attention(uuid[])
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
REVOKE ALL ON FUNCTION operations.refresh_attention_after_status_change()
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.refresh_finding_attention(uuid[])
    TO operations_app, ninja_ingest;
"""

FILL_SQL = r"""
SELECT set_config('operations.tenant_id', '1', TRUE);
SELECT operations.refresh_finding_attention(array_agg(id))
  FROM operations.findings
 WHERE status IN ('open', 'acknowledged', 'investigating');
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS findings_attention_after_update ON operations.findings;
DROP TRIGGER IF EXISTS findings_attention_after_insert ON operations.findings;
DROP FUNCTION IF EXISTS operations.refresh_attention_after_status_change();
DROP FUNCTION IF EXISTS operations.refresh_finding_attention(uuid[]);
DROP FUNCTION IF EXISTS operations.compute_finding_attention(uuid[]);
DROP TABLE IF EXISTS operations.finding_attention_drift;
DROP INDEX IF EXISTS operations.idx_findings_attention_active;
ALTER TABLE operations.findings DROP COLUMN IF EXISTS attention_at,
                                DROP COLUMN IF EXISTS attention;
"""


def fill(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(FILL_SQL)


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0296_slim_condition_policy"),
    ]

    operations: ClassVar[list] = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)],
            state_operations=[
                migrations.AddField(
                    model_name="finding",
                    name="attention",
                    field=models.CharField(blank=True, max_length=16, null=True),
                ),
                migrations.AddField(
                    model_name="finding",
                    name="attention_at",
                    field=models.DateTimeField(blank=True, null=True),
                ),
            ],
        ),
        migrations.RunPython(fill, migrations.RunPython.noop),
    ]
