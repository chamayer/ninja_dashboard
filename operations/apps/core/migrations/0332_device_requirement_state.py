"""Stored requirement verdicts: ``operations.device_requirement_state`` (ADR-0035).

The evaluator's coverage pass decides, for every Computer and effective
requirement, whether the requirement is satisfied, missing, stale, exempt, not
evaluated, or outside coverage. Until now only the failures were kept (as
findings), so the Computers page re-derived the whole rule and drifted from it:
on 2026-10-21 it reported 3,946 Hudu requirements missing that the evaluator
did not. Now:

* ``device_requirement_state`` holds one row per Computer and requirement with
  the verdict, the last qualifying observation, the condition key of the
  finding it produced, and when it was evaluated;
* ``write_device_requirement_state`` is the only writer (runtime roles can only
  read the table), called by the coverage pass in the transaction that writes
  its findings;
* ``check_device_requirement_state`` records every disagreement between the
  verdicts and the open missing/stale findings in
  ``device_requirement_state_drift``. It does not repair: the evaluator is the
  authority, so a disagreement is a defect to explain, kept until it clears.

Online/Offline is not stored: it is source evidence that the page reads live
from ``device_agent_presence_current``.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE TABLE operations.device_requirement_state (
    tenant_id bigint NOT NULL,
    device_id uuid NOT NULL,
    entity_type varchar(80) NOT NULL,
    platform varchar(80) NOT NULL,
    agent_id smallint NULL,
    verdict text NOT NULL CHECK (verdict IN (
        'satisfied', 'missing', 'stale', 'exempt', 'not_evaluated', 'outside_coverage')),
    last_observed_at timestamptz NULL,
    condition_key varchar(64) NULL,
    evaluated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, device_id, entity_type, platform)
);
CREATE INDEX idx_device_requirement_state_verdict
    ON operations.device_requirement_state (tenant_id, platform, verdict);
ALTER TABLE operations.device_requirement_state ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_read ON operations.device_requirement_state FOR SELECT
    USING (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint);
REVOKE ALL ON operations.device_requirement_state FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.device_requirement_state
    FROM operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.device_requirement_state
    TO operations_app, operations_readonly, ninja_ingest;

CREATE TABLE operations.device_requirement_state_drift (
    id bigserial PRIMARY KEY,
    tenant_id bigint NOT NULL,
    device_id uuid NOT NULL,
    entity_type varchar(80) NOT NULL,
    platform varchar(80) NOT NULL,
    disagreement text NOT NULL CHECK (disagreement IN (
        'missing_without_finding', 'stale_without_finding', 'finding_without_verdict')),
    verdict text NULL,
    finding_id uuid NULL,
    finding_type text NULL,
    first_found_at timestamptz NOT NULL DEFAULT now(),
    last_found_at timestamptz NOT NULL DEFAULT now(),
    cleared_at timestamptz NULL
);
CREATE UNIQUE INDEX uq_device_requirement_state_drift_open
    ON operations.device_requirement_state_drift
       (tenant_id, device_id, entity_type, platform, disagreement)
    WHERE cleared_at IS NULL;
CREATE INDEX idx_device_requirement_state_drift_found
    ON operations.device_requirement_state_drift (tenant_id, last_found_at DESC);
ALTER TABLE operations.device_requirement_state_drift ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_read ON operations.device_requirement_state_drift FOR SELECT
    USING (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint);
REVOKE ALL ON operations.device_requirement_state_drift FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.device_requirement_state_drift
    FROM operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.device_requirement_state_drift
    TO operations_app, operations_readonly, ninja_ingest;

INSERT INTO operations.change_history_registry (
    table_name, classification, reason, recorded_columns, secret_columns, key_columns,
    computer_column, computer_condition_column, computer_condition_value, client_column,
    is_global, capture
) VALUES
    ('device_requirement_state', 'exempt',
     'derived by the evaluator coverage pass on every run; rebuildable',
     '{}'::text[], '{}'::text[], '{}'::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('device_requirement_state_drift', 'history_store', 'stores history or run records',
     '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL)
ON CONFLICT (table_name) DO NOTHING;

-- Replaces the session tenant's verdicts with those of a coverage pass: every
-- Computer when p_devices is NULL, otherwise only the listed Computers.
CREATE FUNCTION operations.write_device_requirement_state(
    p_tenant bigint, p_devices uuid[], p_rows jsonb)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_count integer;
BEGIN
    IF p_tenant IS NULL
       OR p_tenant IS DISTINCT FROM nullif(current_setting('operations.tenant_id', true), '')::bigint THEN
        RAISE EXCEPTION 'write_device_requirement_state needs the session tenant';
    END IF;
    DELETE FROM operations.device_requirement_state
     WHERE tenant_id = p_tenant
       AND (p_devices IS NULL OR device_id = ANY (p_devices));
    INSERT INTO operations.device_requirement_state
        (tenant_id, device_id, entity_type, platform, agent_id, verdict,
         last_observed_at, condition_key, evaluated_at)
    SELECT DISTINCT ON (r.device_id, r.entity_type, r.platform)
           p_tenant, r.device_id, r.entity_type, r.platform, r.agent_id, r.verdict,
           r.last_observed_at, r.condition_key, now()
      FROM jsonb_to_recordset(COALESCE(p_rows, '[]'::jsonb)) AS r(
               device_id uuid, entity_type text, platform text, agent_id smallint,
               verdict text, last_observed_at timestamptz, condition_key text)
     WHERE p_devices IS NULL OR r.device_id = ANY (p_devices)
     ORDER BY r.device_id, r.entity_type, r.platform,
              array_position(ARRAY['missing', 'stale', 'not_evaluated', 'outside_coverage',
                                   'satisfied', 'exempt'], r.verdict);
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END
$fn$;

-- Every current disagreement between the verdicts and the open missing/stale
-- findings. Read only and invoker's rights, so row-level security applies to
-- the caller; the check below records them.
CREATE FUNCTION operations.device_requirement_state_disagreements(p_tenant bigint)
RETURNS TABLE (device_id uuid, entity_type text, platform text, disagreement text,
               verdict text, finding_id uuid, finding_type text)
LANGUAGE sql STABLE
SET search_path = pg_catalog, operations
AS $fn$
    WITH active AS (
        SELECT f.id, f.subject_id AS device_id,
               COALESCE(f.finding_details->>'entity_type', '') AS entity_type,
               COALESCE(f.finding_details->>'platform', '') AS platform,
               t.name::text AS finding_type,
               CASE t.name WHEN 'missing_required_platform' THEN 'missing' ELSE 'stale' END
                   AS expected_verdict
          FROM operations.findings f
          JOIN operations.finding_types t ON t.id = f.finding_type_id
         WHERE f.tenant_id = p_tenant
           AND f.subject_type = 'device'
           AND t.name IN ('missing_required_platform', 'stale_required_platform')
           AND f.status IN ('open', 'acknowledged', 'investigating', 'suppressed')
    )
    SELECT s.device_id, s.entity_type::text, s.platform::text,
           s.verdict || '_without_finding', s.verdict, NULL::uuid, NULL::text
      FROM operations.device_requirement_state s
     WHERE s.tenant_id = p_tenant
       AND s.verdict IN ('missing', 'stale')
       AND NOT EXISTS (SELECT 1 FROM active a
                        WHERE a.device_id = s.device_id AND a.platform = s.platform
                          AND a.expected_verdict = s.verdict)
    UNION ALL
    SELECT a.device_id, COALESCE(NULLIF(a.entity_type, ''), s.entity_type::text, ''),
           a.platform, 'finding_without_verdict', s.verdict, a.id, a.finding_type
      FROM active a
      LEFT JOIN operations.device_requirement_state s
        ON s.tenant_id = p_tenant AND s.device_id = a.device_id AND s.platform = a.platform
     WHERE s.verdict IS DISTINCT FROM a.expected_verdict
$fn$;

-- Opens a drift row per new disagreement, refreshes the ones still present and
-- clears the rest. Returns the number of open disagreements. Does nothing
-- before the first coverage pass has written verdicts.
CREATE FUNCTION operations.check_device_requirement_state(p_tenant bigint)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_count integer;
BEGIN
    IF p_tenant IS NULL
       OR p_tenant IS DISTINCT FROM nullif(current_setting('operations.tenant_id', true), '')::bigint THEN
        RAISE EXCEPTION 'check_device_requirement_state needs the session tenant';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM operations.device_requirement_state WHERE tenant_id = p_tenant) THEN
        RETURN 0;
    END IF;
    UPDATE operations.device_requirement_state_drift d
       SET cleared_at = now()
     WHERE d.tenant_id = p_tenant AND d.cleared_at IS NULL
       AND NOT EXISTS (
           SELECT 1 FROM operations.device_requirement_state_disagreements(p_tenant) n
            WHERE n.device_id = d.device_id AND n.entity_type = d.entity_type
              AND n.platform = d.platform AND n.disagreement = d.disagreement);
    INSERT INTO operations.device_requirement_state_drift AS d
        (tenant_id, device_id, entity_type, platform, disagreement, verdict,
         finding_id, finding_type)
    SELECT DISTINCT ON (n.device_id, n.entity_type, n.platform, n.disagreement)
           p_tenant, n.device_id, n.entity_type, n.platform, n.disagreement, n.verdict,
           n.finding_id, n.finding_type
      FROM operations.device_requirement_state_disagreements(p_tenant) n
     ORDER BY n.device_id, n.entity_type, n.platform, n.disagreement, n.finding_id
    ON CONFLICT (tenant_id, device_id, entity_type, platform, disagreement)
        WHERE cleared_at IS NULL
    DO UPDATE SET last_found_at = now(), verdict = EXCLUDED.verdict,
                  finding_id = EXCLUDED.finding_id, finding_type = EXCLUDED.finding_type;
    SELECT count(*) INTO v_count FROM operations.device_requirement_state_drift
     WHERE tenant_id = p_tenant AND cleared_at IS NULL;
    RETURN v_count;
END
$fn$;

REVOKE ALL ON FUNCTION operations.write_device_requirement_state(bigint, uuid[], jsonb)
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
REVOKE ALL ON FUNCTION operations.device_requirement_state_disagreements(bigint)
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
REVOKE ALL ON FUNCTION operations.check_device_requirement_state(bigint)
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.write_device_requirement_state(bigint, uuid[], jsonb),
                          operations.check_device_requirement_state(bigint)
    TO ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.device_requirement_state_disagreements(bigint)
    TO operations_app, operations_readonly, ninja_ingest;
"""

REVERSE_SQL = r"""
DROP FUNCTION IF EXISTS operations.check_device_requirement_state(bigint);
DROP FUNCTION IF EXISTS operations.device_requirement_state_disagreements(bigint);
DROP FUNCTION IF EXISTS operations.write_device_requirement_state(bigint, uuid[], jsonb);
DELETE FROM operations.change_history_registry
 WHERE table_name IN ('device_requirement_state', 'device_requirement_state_drift');
DROP TABLE IF EXISTS operations.device_requirement_state_drift;
DROP TABLE IF EXISTS operations.device_requirement_state;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0331_computer_naming_function_grants"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
