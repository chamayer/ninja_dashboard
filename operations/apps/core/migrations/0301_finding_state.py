"""Stored finding state: ``operations.finding_state`` and the one function that writes it.

See ``.work/finding-state-design.md``. A finding's attention (needs action, blocked, pending,
covered) is rolled up from its assessments and the findings that cover it. It used to be
recomputed on every Issues page load, then stored in a column that only some writers refreshed
(the software reconcile writes assessments in bulk SQL and bypassed the Python hook). Now:

* ``finding_state`` holds one narrow row per finding that has been active, with the covering
  findings, the policy version and the compute time;
* ``refresh_finding_state(uuid[])`` is the only writer, with a bounded cascade to the findings
  a changed finding covers;
* database triggers call it in the same transaction as every input change: assessments,
  participants, and finding insert / status / severity. No code path can skip them.

Pause, closed status, freshness and policy version are not stored: the page reads them live as
cheap comparisons. "Critical takes priority" is no longer a state.
Everything built in 0297-0300 stays in place and unused until the cleanup migration.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations, models

FORWARD_SQL = r"""
CREATE TABLE IF NOT EXISTS operations.finding_state (
    finding_id uuid PRIMARY KEY REFERENCES operations.findings(id) ON DELETE CASCADE,
    tenant_id integer NOT NULL,
    finding_type_id integer NOT NULL,
    attention text CHECK (attention IN ('needs_action', 'blocked', 'pending', 'covered')),
    reason text NOT NULL,
    covered_by uuid[] NOT NULL DEFAULT ARRAY[]::uuid[],
    policy_version text,
    computed_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_finding_state_attention
    ON operations.finding_state (tenant_id, attention, finding_type_id)
    WHERE attention IS NOT NULL;
ALTER TABLE operations.finding_state OWNER TO operations_migrate;
ALTER TABLE operations.finding_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.finding_state FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS finding_state_tenant_isolation ON operations.finding_state;
CREATE POLICY finding_state_tenant_isolation ON operations.finding_state
    USING (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint)
    WITH CHECK (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint);
REVOKE ALL ON operations.finding_state FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.finding_state
    FROM operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.finding_state TO operations_app, ninja_ingest, operations_readonly;

/* Every disagreement the consistency check finds, with when and what it replaced. */
CREATE TABLE IF NOT EXISTS operations.finding_state_drift (
    id bigserial PRIMARY KEY,
    tenant_id integer NOT NULL,
    finding_id uuid NOT NULL,
    finding_type text NOT NULL,
    stored_attention text,
    computed_attention text,
    found_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_finding_state_drift_found
    ON operations.finding_state_drift (found_at DESC);
ALTER TABLE operations.finding_state_drift OWNER TO operations_migrate;
ALTER TABLE operations.finding_state_drift ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.finding_state_drift FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS finding_state_drift_tenant_isolation ON operations.finding_state_drift;
CREATE POLICY finding_state_drift_tenant_isolation ON operations.finding_state_drift
    USING (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint)
    WITH CHECK (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint);
GRANT SELECT ON operations.finding_state_drift TO operations_app, operations_readonly;
GRANT SELECT, INSERT ON operations.finding_state_drift TO ninja_ingest;
GRANT USAGE ON SEQUENCE operations.finding_state_drift_id_seq TO ninja_ingest;

/* The rule. Same roll-up as before: every expected non-context participant has a current
 * assessment that may execute -> needs_action; any blocked -> blocked; a current covered_by
 * assessment whose covering finding is still open -> covered; otherwise pending. */
CREATE OR REPLACE FUNCTION operations.compute_finding_state(p_ids uuid[])
RETURNS TABLE (
    finding_id uuid, tenant_id integer, finding_type_id integer,
    attention text, reason text, covered_by uuid[], policy_version text
)
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
        SELECT v.version, (v.policy->>'freshness_hours')::integer AS fresh_hours
          FROM operations.condition_policy_versions v
         WHERE v.active ORDER BY v.version DESC LIMIT 1
    ), target AS (
        SELECT f.id, f.tenant_id, f.finding_type_id, f.status
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
        SELECT c.finding_id, array_agg(DISTINCT c.parent_id ORDER BY c.parent_id) AS parents,
               min(pt.name) AS parent_type
          FROM covered_candidates c
          JOIN operations.findings p
            ON p.id = c.parent_id AND p.tenant_id = c.tenant_id
           AND p.status IN ('open', 'acknowledged', 'investigating')
          JOIN operations.finding_types pt ON pt.id = p.finding_type_id
         WHERE c.parent_id IS NOT NULL
         GROUP BY c.finding_id
    )
    SELECT t.id, t.tenant_id, t.finding_type_id,
           CASE
               WHEN t.status NOT IN ('open', 'acknowledged', 'investigating') THEN NULL
               WHEN a.finding_id IS NULL THEN 'pending'
               WHEN cv.finding_id IS NOT NULL THEN 'covered'
               WHEN (e.participants = ARRAY[]::text[] AND COALESCE(a.condition_execute, false))
                 OR (e.participants <> ARRAY[]::text[]
                     AND a.participants = e.participants
                     AND a.executable_participants = e.participants) THEN 'needs_action'
               WHEN COALESCE(a.blocked, false) THEN 'blocked'
               ELSE 'pending'
           END,
           CASE
               WHEN t.status NOT IN ('open', 'acknowledged', 'investigating') THEN 'closed'
               WHEN a.finding_id IS NULL THEN 'no_current_assessment'
               WHEN cv.finding_id IS NOT NULL THEN 'covered_by:' || cv.parent_type
               WHEN (e.participants = ARRAY[]::text[] AND COALESCE(a.condition_execute, false))
                 OR (e.participants <> ARRAY[]::text[]
                     AND a.participants = e.participants
                     AND a.executable_participants = e.participants) THEN 'ready'
               WHEN COALESCE(a.blocked, false) THEN 'blocked_by_evidence'
               ELSE 'incomplete_assessment'
           END,
           COALESCE(cv.parents, ARRAY[]::uuid[]),
           (SELECT pol.version FROM pol)
      FROM target t
      JOIN expected e ON e.id = t.id
 LEFT JOIN assessed a ON a.finding_id = t.id
 LEFT JOIN covering cv ON cv.finding_id = t.id;
END
$function$;

/* The only writer of finding_state. Refreshes the given findings, then (bounded) the findings
 * that a finding becoming active or closed covers or uncovers. Rows are upserted in id order
 * so concurrent refreshes cannot deadlock. */
CREATE OR REPLACE FUNCTION operations.refresh_finding_state(p_ids uuid[])
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE
    todo uuid[] := p_ids;
    done uuid[] := ARRAY[]::uuid[];
    flipped uuid[];
    total integer := 0;
    n integer;
    depth integer := 0;
BEGIN
    WHILE todo IS NOT NULL AND cardinality(todo) > 0 AND depth < 4 LOOP
        WITH previous AS (
            SELECT s.finding_id, s.attention FROM operations.finding_state s
             WHERE s.finding_id = ANY(todo)
        ), computed AS (
            SELECT * FROM operations.compute_finding_state(todo) c ORDER BY c.finding_id
        ), written AS (
            INSERT INTO operations.finding_state AS s
                (finding_id, tenant_id, finding_type_id, attention, reason, covered_by,
                 policy_version, computed_at)
            SELECT c.finding_id, c.tenant_id, c.finding_type_id, c.attention, c.reason,
                   c.covered_by, c.policy_version, now()
              FROM computed c
            ON CONFLICT (finding_id) DO UPDATE
               SET tenant_id = EXCLUDED.tenant_id, finding_type_id = EXCLUDED.finding_type_id,
                   attention = EXCLUDED.attention, reason = EXCLUDED.reason,
                   covered_by = EXCLUDED.covered_by, policy_version = EXCLUDED.policy_version,
                   computed_at = EXCLUDED.computed_at
            RETURNING s.finding_id, s.attention
        )
        SELECT count(*),
               array_agg(w.finding_id) FILTER (
                   WHERE (p.attention IS NULL) IS DISTINCT FROM (w.attention IS NULL))
          INTO n, flipped
          FROM written w LEFT JOIN previous p ON p.finding_id = w.finding_id;
        total := total + n;
        done := done || todo;
        -- Findings that became active or closed cover or uncover the findings their type covers.
        todo := (
            WITH RECURSIVE changed AS (
                SELECT f.subject_type, f.subject_id, ft.name AS type_name, f.tenant_id
                  FROM operations.findings f
                  JOIN operations.finding_types ft ON ft.id = f.finding_type_id
                 WHERE f.id = ANY(COALESCE(flipped, ARRAY[]::uuid[]))
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
             WHERE NOT (f.id = ANY(done))
        );
        depth := depth + 1;
    END LOOP;
    RETURN total;
END
$function$;

/* Triggers: every input change refreshes the state in the same transaction. */
CREATE OR REPLACE FUNCTION operations.finding_state_after_assessments()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, operations
AS $function$
BEGIN
    PERFORM operations.refresh_finding_state((
        SELECT array_agg(DISTINCT n.finding_id) FROM new_rows n
         WHERE n.row_kind = 'entity' AND n.finding_id IS NOT NULL));
    RETURN NULL;
END
$function$;

CREATE OR REPLACE FUNCTION operations.finding_state_after_participants()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, operations
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM operations.refresh_finding_state((
            SELECT array_agg(DISTINCT o.finding_id) FROM old_rows o
             WHERE o.row_kind = 'entity' AND o.finding_id IS NOT NULL));
    ELSE
        PERFORM operations.refresh_finding_state((
            SELECT array_agg(DISTINCT n.finding_id) FROM new_rows n
             WHERE n.row_kind = 'entity' AND n.finding_id IS NOT NULL));
    END IF;
    RETURN NULL;
END
$function$;

CREATE OR REPLACE FUNCTION operations.finding_state_after_findings_insert()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, operations
AS $function$
BEGIN
    PERFORM operations.refresh_finding_state((SELECT array_agg(n.id) FROM new_rows n));
    RETURN NULL;
END
$function$;

CREATE OR REPLACE FUNCTION operations.finding_state_after_finding_change()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, operations
AS $function$
BEGIN
    PERFORM operations.refresh_finding_state(ARRAY[NEW.id]);
    RETURN NULL;
END
$function$;

DROP TRIGGER IF EXISTS finding_state_assessments_insert ON operations.condition_assessments;
CREATE TRIGGER finding_state_assessments_insert
AFTER INSERT ON operations.condition_assessments
REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT EXECUTE FUNCTION operations.finding_state_after_assessments();
DROP TRIGGER IF EXISTS finding_state_assessments_update ON operations.condition_assessments;
CREATE TRIGGER finding_state_assessments_update
AFTER UPDATE ON operations.condition_assessments
REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT EXECUTE FUNCTION operations.finding_state_after_assessments();

DROP TRIGGER IF EXISTS finding_state_participants_insert ON operations.condition_participants;
CREATE TRIGGER finding_state_participants_insert
AFTER INSERT ON operations.condition_participants
REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT EXECUTE FUNCTION operations.finding_state_after_participants();
DROP TRIGGER IF EXISTS finding_state_participants_update ON operations.condition_participants;
CREATE TRIGGER finding_state_participants_update
AFTER UPDATE ON operations.condition_participants
REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT EXECUTE FUNCTION operations.finding_state_after_participants();
DROP TRIGGER IF EXISTS finding_state_participants_delete ON operations.condition_participants;
CREATE TRIGGER finding_state_participants_delete
AFTER DELETE ON operations.condition_participants
REFERENCING OLD TABLE AS old_rows
FOR EACH STATEMENT EXECUTE FUNCTION operations.finding_state_after_participants();

DROP TRIGGER IF EXISTS finding_state_findings_insert ON operations.findings;
CREATE TRIGGER finding_state_findings_insert
AFTER INSERT ON operations.findings
REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT EXECUTE FUNCTION operations.finding_state_after_findings_insert();
/* Row-level and limited to real changes: the evaluators touch every finding (last_seen_at). */
DROP TRIGGER IF EXISTS finding_state_findings_change ON operations.findings;
CREATE TRIGGER finding_state_findings_change
AFTER UPDATE OF status, severity ON operations.findings
FOR EACH ROW WHEN (OLD.status IS DISTINCT FROM NEW.status
                   OR OLD.severity IS DISTINCT FROM NEW.severity)
EXECUTE FUNCTION operations.finding_state_after_finding_change();

DO $privileges$
DECLARE
    fn text;
BEGIN
    FOREACH fn IN ARRAY ARRAY[
        'operations.compute_finding_state(uuid[])',
        'operations.refresh_finding_state(uuid[])',
        'operations.finding_state_after_assessments()',
        'operations.finding_state_after_participants()',
        'operations.finding_state_after_findings_insert()',
        'operations.finding_state_after_finding_change()'
    ] LOOP
        EXECUTE format('ALTER FUNCTION %s OWNER TO operations_migrate', fn);
        EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC, operations_app, ninja_ingest, '
                       'operations_readonly, metabase_ro', fn);
    END LOOP;
END
$privileges$;
GRANT EXECUTE ON FUNCTION operations.compute_finding_state(uuid[]) TO operations_app, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.refresh_finding_state(uuid[]) TO operations_app, ninja_ingest;
"""

FILL_SQL = r"""
SELECT set_config('operations.tenant_id', '1', TRUE);
SELECT operations.refresh_finding_state(array_agg(id))
  FROM operations.findings
 WHERE status IN ('open', 'acknowledged', 'investigating');
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS finding_state_findings_change ON operations.findings;
DROP TRIGGER IF EXISTS finding_state_findings_insert ON operations.findings;
DROP TRIGGER IF EXISTS finding_state_participants_delete ON operations.condition_participants;
DROP TRIGGER IF EXISTS finding_state_participants_update ON operations.condition_participants;
DROP TRIGGER IF EXISTS finding_state_participants_insert ON operations.condition_participants;
DROP TRIGGER IF EXISTS finding_state_assessments_update ON operations.condition_assessments;
DROP TRIGGER IF EXISTS finding_state_assessments_insert ON operations.condition_assessments;
DROP FUNCTION IF EXISTS operations.finding_state_after_finding_change();
DROP FUNCTION IF EXISTS operations.finding_state_after_findings_insert();
DROP FUNCTION IF EXISTS operations.finding_state_after_participants();
DROP FUNCTION IF EXISTS operations.finding_state_after_assessments();
DROP FUNCTION IF EXISTS operations.refresh_finding_state(uuid[]);
DROP FUNCTION IF EXISTS operations.compute_finding_state(uuid[]);
DROP TABLE IF EXISTS operations.finding_state_drift;
DROP TABLE IF EXISTS operations.finding_state;
"""


def fill(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(FILL_SQL)


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0300_finding_states_view_fast"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(fill, migrations.RunPython.noop),
        migrations.CreateModel(
            name="StoredFindingState",
            fields=[
                (
                    "finding",
                    models.OneToOneField(
                        db_column="finding_id",
                        on_delete=models.deletion.DO_NOTHING,
                        primary_key=True,
                        related_name="stored_state",
                        serialize=False,
                        to="operations.finding",
                    ),
                ),
                ("tenant_id", models.IntegerField()),
                ("finding_type_id", models.IntegerField()),
                ("attention", models.CharField(max_length=16, null=True)),
                ("reason", models.CharField(max_length=60)),
                ("policy_version", models.CharField(max_length=80, null=True)),
                ("computed_at", models.DateTimeField()),
            ],
            options={"db_table": "finding_state", "managed": False},
        ),
    ]
