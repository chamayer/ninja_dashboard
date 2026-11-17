"""Maintained Coverage facts; serving cutover remains gated."""

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
CREATE TABLE operations.coverage_read_revision (
 tenant_id bigint PRIMARY KEY CHECK (tenant_id = 1), revision bigint NOT NULL DEFAULT 0
);
INSERT INTO operations.coverage_read_revision(tenant_id) VALUES (1);
CREATE TABLE operations.coverage_read_publication (
 tenant_id bigint PRIMARY KEY CHECK (tenant_id = 1), revision bigint NOT NULL,
 published_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
 active_device_days integer NOT NULL CHECK (active_device_days BETWEEN 1 AND 365),
 metadata jsonb NOT NULL
);
CREATE TABLE operations.coverage_computer_read_current (
 tenant_id bigint NOT NULL CHECK (tenant_id = 1), device_id uuid NOT NULL,
 computer jsonb NOT NULL, hudu jsonb NOT NULL, PRIMARY KEY(tenant_id, device_id)
);
CREATE TABLE operations.coverage_cell_read_current (
 tenant_id bigint NOT NULL CHECK (tenant_id = 1), device_id uuid NOT NULL,
 platform text NOT NULL, requirement_status text, source_status text,
 rule_status text NOT NULL, status text NOT NULL,
 source_online boolean, source_contact_at timestamptz,
 observation_current boolean, requirements_evaluated_at timestamptz,
 PRIMARY KEY(tenant_id, device_id, platform),
 FOREIGN KEY(tenant_id, device_id) REFERENCES operations.coverage_computer_read_current
 ON DELETE CASCADE
);
CREATE INDEX coverage_cell_selection ON operations.coverage_cell_read_current
 (tenant_id, platform, status, device_id);
CREATE INDEX coverage_rule_selection ON operations.coverage_cell_read_current
 (tenant_id, platform, rule_status, device_id);

ALTER TABLE operations.coverage_read_revision ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.coverage_read_revision FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.coverage_read_revision
 USING (tenant_id = operations.current_tenant_id())
 WITH CHECK (tenant_id = operations.current_tenant_id());
REVOKE ALL ON operations.coverage_read_revision FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT SELECT ON operations.coverage_read_revision TO operations_app, operations_readonly, ninja_ingest;
GRANT SELECT, INSERT, UPDATE, DELETE ON operations.coverage_read_revision TO operations_view_owner;

ALTER TABLE operations.coverage_read_publication ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.coverage_read_publication FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.coverage_read_publication
 USING (tenant_id = operations.current_tenant_id())
 WITH CHECK (tenant_id = operations.current_tenant_id());
REVOKE ALL ON operations.coverage_read_publication FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT SELECT ON operations.coverage_read_publication TO operations_app, operations_readonly, ninja_ingest;
GRANT SELECT, INSERT, UPDATE, DELETE ON operations.coverage_read_publication TO operations_view_owner;

ALTER TABLE operations.coverage_computer_read_current ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.coverage_computer_read_current FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.coverage_computer_read_current
 USING (tenant_id = operations.current_tenant_id())
 WITH CHECK (tenant_id = operations.current_tenant_id());
REVOKE ALL ON operations.coverage_computer_read_current FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT SELECT ON operations.coverage_computer_read_current TO operations_app, operations_readonly, ninja_ingest;
GRANT SELECT, INSERT, UPDATE, DELETE ON operations.coverage_computer_read_current TO operations_view_owner;

ALTER TABLE operations.coverage_cell_read_current ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.coverage_cell_read_current FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.coverage_cell_read_current
 USING (tenant_id = operations.current_tenant_id())
 WITH CHECK (tenant_id = operations.current_tenant_id());
REVOKE ALL ON operations.coverage_cell_read_current FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT SELECT ON operations.coverage_cell_read_current TO operations_app, operations_readonly, ninja_ingest;
GRANT SELECT, INSERT, UPDATE, DELETE ON operations.coverage_cell_read_current TO operations_view_owner;

CREATE FUNCTION operations.invalidate_coverage_read() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, operations
SET operations.tenant_id = '1' AS $fn$
BEGIN
 UPDATE operations.coverage_read_revision SET revision = revision + 1 WHERE tenant_id = 1;
 RETURN NULL;
END $fn$;
REVOKE ALL ON FUNCTION operations.invalidate_coverage_read() FROM PUBLIC;
CREATE TRIGGER coverage_read_changed AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE
ON operations.devices FOR EACH STATEMENT EXECUTE FUNCTION operations.invalidate_coverage_read();
CREATE TRIGGER coverage_read_changed AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE
ON operations.clients FOR EACH STATEMENT EXECUTE FUNCTION operations.invalidate_coverage_read();
CREATE TRIGGER coverage_read_changed AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE
ON operations.computer_client_ownership FOR EACH STATEMENT EXECUTE FUNCTION operations.invalidate_coverage_read();
CREATE TRIGGER coverage_read_changed AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE
ON operations.device_operator_decisions FOR EACH STATEMENT EXECUTE FUNCTION operations.invalidate_coverage_read();
CREATE TRIGGER coverage_read_changed AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE
ON operations.device_requirement_state FOR EACH STATEMENT EXECUTE FUNCTION operations.invalidate_coverage_read();
CREATE TRIGGER coverage_read_changed AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE
ON operations.entity_observation_current FOR EACH STATEMENT EXECUTE FUNCTION operations.invalidate_coverage_read();
CREATE TRIGGER coverage_read_changed AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE
ON operations.source_instances FOR EACH STATEMENT EXECUTE FUNCTION operations.invalidate_coverage_read();
CREATE TRIGGER coverage_read_changed AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE
ON operations.sources FOR EACH STATEMENT EXECUTE FUNCTION operations.invalidate_coverage_read();
CREATE TRIGGER coverage_read_changed AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE
ON operations.source_record_lifecycle_mappings FOR EACH STATEMENT EXECUTE FUNCTION operations.invalidate_coverage_read();
CREATE TRIGGER coverage_read_changed AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE
ON operations.agents FOR EACH STATEMENT EXECUTE FUNCTION operations.invalidate_coverage_read();
CREATE TRIGGER coverage_read_changed AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE
ON operations.evaluator_config FOR EACH STATEMENT EXECUTE FUNCTION operations.invalidate_coverage_read();

CREATE FUNCTION operations.refresh_coverage_read(p_tenant bigint, p_days integer)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations AS $fn$
DECLARE v_revision bigint; v_at timestamptz := statement_timestamp(); v_total integer;
BEGIN
 IF p_tenant IS DISTINCT FROM 1 OR p_tenant IS DISTINCT FROM operations.current_tenant_id()
    OR p_days IS NULL OR p_days NOT BETWEEN 1 AND 365 THEN
   RAISE EXCEPTION 'Invalid Coverage publication context';
 END IF;
 IF NOT pg_try_advisory_xact_lock(560422, 1) THEN RETURN 0; END IF;
 SELECT revision INTO STRICT v_revision FROM operations.coverage_read_revision WHERE tenant_id = p_tenant;
 -- A single statement derives both fact sets from one source snapshot.
 DELETE FROM operations.coverage_computer_read_current WHERE tenant_id = p_tenant;

WITH computers AS MATERIALIZED (
    SELECT d.id, d.client_id, c.slug, c.display_name,
           coalesce(d.canonical_hostname, '') AS hostname, d.canonical_hostname AS sort_hostname,
           coalesce(d.os_family, '') AS os_family, d.device_type, d.device_role,
           d.lifecycle_status, coalesce(session.is_online_any, false) AS online,
           session.last_contact_at,
           coalesce(decision.value, '{}'::jsonb) ? 'agent.edr' AS s1_exempt,
           coalesce(nullif(c.offline_after_days, 0), p_days) AS offline_days,
           c.offline_after_days AS client_offline_days
    FROM operations.devices d
    JOIN operations.computer_client_ownership owner
      ON owner.tenant_id = d.tenant_id AND owner.device_id = d.id
     AND owner.effective_client_id = d.client_id
     AND owner.state IN ('resolved', 'decision_protected')
    JOIN operations.clients c ON c.id = d.client_id
    LEFT JOIN operations.device_session_current session
      ON session.tenant_id = d.tenant_id AND session.device_id = d.id
    LEFT JOIN operations.device_operator_decisions decision
      ON decision.tenant_id = d.tenant_id AND decision.device_id = d.id
     AND decision.dimension = 'exemptions'
    WHERE d.tenant_id = p_tenant AND d.deleted_at IS NULL
      AND d.lifecycle_status <> 'retired'
), presence AS MATERIALIZED (
    SELECT presence.device_id, presence.platform,
           bool_or(presence.reported_online) AS online,
           max(coalesce(presence.last_contact_at, presence.last_observed_at)) AS contact
    FROM operations.device_agent_presence_current presence
    WHERE presence.tenant_id = p_tenant
      AND (presence.entity_type LIKE 'agent.%' OR presence.entity_type = 'vm.guest')
      AND EXISTS (SELECT 1 FROM operations.devices current_device
                  WHERE current_device.tenant_id = presence.tenant_id
                    AND current_device.id = presence.device_id
                    AND current_device.deleted_at IS NULL
                    AND current_device.lifecycle_status <> 'retired')
    GROUP BY presence.device_id, presence.platform
), observations AS MATERIALIZED (
    SELECT observation.device_id, observation.source_name AS platform,
           bool_or(observation.observation_active) AS current
    FROM operations.v_device_observation_current observation
    WHERE observation.tenant_id = p_tenant
      AND (observation.entity_type LIKE 'agent.%' OR observation.entity_type = 'vm.guest')
      AND EXISTS (SELECT 1 FROM operations.devices current_device
                  WHERE current_device.tenant_id = observation.tenant_id
                    AND current_device.id = observation.device_id
                    AND current_device.deleted_at IS NULL
                    AND current_device.lifecycle_status <> 'retired')
    GROUP BY observation.device_id, observation.source_name
), hudu_input AS MATERIALIZED (
    SELECT original.*, row_number() OVER () AS input_position FROM (
SELECT hudu.observation_id, hudu.device_id, hudu.client_id,
                           hudu.hostname,
                           lifecycle.record_lifecycle = 'archived' AS is_archived,
                           hudu.has_relayed_cards AS has_links
                    FROM operations.v_hudu_computer_inventory_observation_current hudu
                    JOIN operations.devices device
                      ON device.tenant_id = hudu.tenant_id
                     AND device.id = hudu.device_id
                     AND device.deleted_at IS NULL
                     AND device.lifecycle_status <> 'retired'
                    JOIN operations.computer_client_ownership owner
                      ON owner.tenant_id = device.tenant_id AND owner.device_id = device.id
                     AND owner.effective_client_id = device.client_id
                     AND owner.effective_client_id = hudu.client_id
                     AND owner.state IN ('resolved', 'decision_protected')
                    LEFT JOIN LATERAL (
                        SELECT lifecycle.record_lifecycle
                        FROM operations.v_device_source_record_lifecycle_current lifecycle
                        WHERE lifecycle.tenant_id = hudu.tenant_id
                          AND lifecycle.observation_id = hudu.observation_id
                        OFFSET 0
                    ) lifecycle ON TRUE
    ) original
), hudu AS MATERIALIZED (
    SELECT record.device_id,
           count(*) FILTER (WHERE record.is_archived) AS archived,
           count(*) FILTER (WHERE record.is_archived IS NOT TRUE) AS current,
           bool_or(record.has_links) FILTER (WHERE record.is_archived IS NOT TRUE) AS current_links,
           bool_or(record.has_links) FILTER (WHERE record.is_archived) AS archived_links,
           jsonb_agg(to_jsonb(record) - 'input_position' ORDER BY input_position) AS records
    FROM hudu_input record GROUP BY record.device_id
), requirement_presence AS MATERIALIZED (
    SELECT device_id, entity_type,
           CASE WHEN grouping(platform) = 1 THEN 'any' ELSE platform END AS platform,
           bool_or(reported_online) AS online
    FROM operations.device_agent_presence_current WHERE tenant_id = p_tenant
    GROUP BY GROUPING SETS ((device_id, entity_type, platform), (device_id, entity_type))
), requirement_rows AS MATERIALIZED (
    SELECT state.device_id, state.platform,
           max(state.evaluated_at) OVER (PARTITION BY state.device_id, state.platform)
               AS requirements_evaluated_at,
           CASE state.verdict WHEN 'missing' THEN 'Missing' WHEN 'stale' THEN 'Stale'
               WHEN 'satisfied' THEN CASE WHEN coalesce(presence.online, false)
                                         THEN 'Online' ELSE 'Offline' END
               WHEN 'os_unknown' THEN 'N/A — OS unknown'
               WHEN 'pending_cleanup' THEN 'N/A — Cleanup' ELSE 'No agents' END AS status,
           CASE state.verdict WHEN 'missing' THEN 0 WHEN 'stale' THEN 1
                WHEN 'satisfied' THEN CASE WHEN coalesce(presence.online, false)
                                          THEN 4 ELSE 3 END ELSE 2 END AS priority
    FROM operations.device_requirement_state state
    JOIN computers computer ON computer.id = state.device_id
    LEFT JOIN requirement_presence presence ON presence.device_id = state.device_id
      AND presence.entity_type = state.entity_type AND presence.platform = state.platform
    WHERE state.tenant_id = p_tenant AND state.verdict <> 'exempt'
), requirement_keys AS MATERIALIZED (
    SELECT DISTINCT ON (device_id, platform) device_id, platform, status, priority,
           requirements_evaluated_at
    FROM requirement_rows ORDER BY device_id, platform, priority
), platforms AS MATERIALIZED (
    SELECT platform FROM (
        SELECT platform FROM presence UNION ALL SELECT platform FROM observations
        UNION ALL SELECT platform FROM requirement_keys
        UNION ALL SELECT 'Hudu' WHERE EXISTS (SELECT 1 FROM hudu)
    ) names
    GROUP BY platform
), record_statuses AS MATERIALIZED (
    SELECT computer.id AS device_id, platform.platform,
           requirement.status AS requirement_status,
           CASE WHEN presence.online THEN 'Online' WHEN presence.online = false THEN 'Offline'
                WHEN presence.device_id IS NOT NULL THEN 'Current' END AS source_status,
           CASE WHEN platform.platform = 'SentinelOne' AND computer.s1_exempt THEN 'Exempt'
                WHEN requirement.priority IN (0, 1, 2) THEN requirement.status
                WHEN requirement.priority IS NOT NULL THEN 'Required' ELSE 'N/A' END AS rule_status,
           CASE WHEN platform.platform = 'Hudu' THEN
                    CASE WHEN hudu.current > 0 THEN 'No status'
                         WHEN hudu.archived > 0 THEN 'Withdrawn' ELSE 'No record' END
                WHEN presence.online THEN 'Online'
                WHEN presence.online = false THEN
                    CASE WHEN presence.contact >= v_at - make_interval(days => computer.offline_days)
                         THEN 'Offline' ELSE 'Stale' END
                WHEN presence.device_id IS NOT NULL OR observations.current THEN 'No status'
                WHEN observations.current = false THEN 'Withdrawn' ELSE 'No record' END AS status,
           presence.online AS source_online, presence.contact AS source_contact_at,
           observations.current AS observation_current, requirement.requirements_evaluated_at
    FROM computers computer CROSS JOIN platforms platform
    LEFT JOIN presence ON presence.device_id = computer.id AND presence.platform = platform.platform
    LEFT JOIN observations ON observations.device_id = computer.id AND observations.platform = platform.platform
    LEFT JOIN hudu ON hudu.device_id = computer.id
    LEFT JOIN requirement_keys requirement
      ON requirement.device_id = computer.id AND requirement.platform = platform.platform
), write_computers AS (
 INSERT INTO operations.coverage_computer_read_current(tenant_id, device_id, computer, hudu)
 SELECT p_tenant, computer.id, to_jsonb(computer), coalesce(to_jsonb(hudu), '{}'::jsonb)
 FROM computers computer LEFT JOIN hudu ON hudu.device_id = computer.id RETURNING device_id
)
INSERT INTO operations.coverage_cell_read_current
SELECT p_tenant, cell.* FROM record_statuses cell
JOIN write_computers written ON written.device_id = cell.device_id;
GET DIAGNOSTICS v_total = ROW_COUNT;
PERFORM 1 FROM operations.coverage_read_revision
 WHERE tenant_id = p_tenant AND revision = v_revision FOR UPDATE;
IF NOT FOUND THEN RAISE EXCEPTION 'Coverage inputs changed during publication' USING ERRCODE = '40001'; END IF;
INSERT INTO operations.coverage_read_publication
VALUES (p_tenant, v_revision, v_at,
 least(v_at + interval '60 seconds', coalesce((
 SELECT min(boundary) FROM (
   SELECT (computer->>'last_contact_at')::timestamptz
          + make_interval(days => (computer->>'offline_days')::integer)
          + interval '1 microsecond' AS boundary
   FROM operations.coverage_computer_read_current WHERE tenant_id = p_tenant
   UNION ALL
   SELECT coalesce(presence.last_contact_at, presence.last_observed_at) + make_interval(days => (computer.computer->>'offline_days')::integer)
          + interval '1 microsecond'
   FROM operations.coverage_computer_read_current computer
   JOIN operations.device_agent_presence_current presence
     ON presence.tenant_id = computer.tenant_id AND presence.device_id = computer.device_id
   WHERE computer.tenant_id = p_tenant
 ) deadlines WHERE boundary > v_at), v_at + interval '60 seconds')), p_days,
 jsonb_build_object(
   'platforms', coalesce((SELECT jsonb_agg(platform ORDER BY platform) FROM
      (SELECT DISTINCT platform FROM operations.coverage_cell_read_current WHERE tenant_id=p_tenant) names), '[]'),
   'os_families', coalesce((SELECT jsonb_agg(value ORDER BY value) FROM
      (SELECT DISTINCT computer->>'os_family' AS value FROM operations.coverage_computer_read_current WHERE tenant_id=p_tenant AND computer->>'os_family' <> '') names), '[]'),
   'device_types', coalesce((SELECT jsonb_agg(value ORDER BY value) FROM
      (SELECT DISTINCT computer->>'device_type' AS value FROM operations.coverage_computer_read_current WHERE tenant_id=p_tenant AND coalesce(computer->>'device_type','') <> '') names), '[]'),
   'device_roles', coalesce((SELECT jsonb_agg(value ORDER BY value) FROM
      (SELECT DISTINCT computer->>'device_role' AS value FROM operations.coverage_computer_read_current WHERE tenant_id=p_tenant AND coalesce(computer->>'device_role','') <> '') names), '[]'),
   'clients', coalesce((SELECT jsonb_agg(jsonb_build_array(id,slug,display_name)) FROM operations.clients WHERE tenant_id=p_tenant AND deleted_at IS NULL), '[]'),
   'agents', coalesce((SELECT jsonb_agg(name) FROM operations.agents WHERE entity_type LIKE 'agent.%'), '[]'),
   'source_record_counts', coalesce((SELECT jsonb_object_agg(source_name,record_count) FROM operations.read_coverage_source_record_counts(p_tenant)), '{}'),
   'requirements_evaluated_at', (SELECT max(requirements_evaluated_at) FROM operations.coverage_cell_read_current WHERE tenant_id=p_tenant)))
ON CONFLICT (tenant_id) DO UPDATE SET revision = excluded.revision,
 published_at = excluded.published_at, expires_at = excluded.expires_at,
 active_device_days = excluded.active_device_days, metadata = excluded.metadata;
RETURN v_total;
END $fn$;
ALTER FUNCTION operations.refresh_coverage_read(bigint, integer) OWNER TO operations_view_owner;
REVOKE ALL ON FUNCTION operations.refresh_coverage_read(bigint, integer) FROM PUBLIC, operations_app, operations_readonly;
GRANT EXECUTE ON FUNCTION operations.refresh_coverage_read(bigint, integer) TO ninja_ingest;

ALTER FUNCTION operations.refresh_device_agent_presence_current() RENAME TO refresh_device_agent_presence_current_before_coverage;
REVOKE ALL ON FUNCTION operations.refresh_device_agent_presence_current_before_coverage() FROM PUBLIC, operations_app, ninja_ingest, operations_readonly;
CREATE FUNCTION operations.refresh_device_agent_presence_current() RETURNS void LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations SET operations.tenant_id = '1' AS $fn$
BEGIN
 PERFORM operations.refresh_device_agent_presence_current_before_coverage();
 UPDATE operations.coverage_read_revision SET revision = revision + 1 WHERE tenant_id = 1;
END $fn$;
REVOKE ALL ON FUNCTION operations.refresh_device_agent_presence_current() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.refresh_device_agent_presence_current() TO ninja_ingest, operations_app;

ALTER FUNCTION operations.refresh_device_session_current() RENAME TO refresh_device_session_current_before_coverage;
REVOKE ALL ON FUNCTION operations.refresh_device_session_current_before_coverage() FROM PUBLIC, operations_app, ninja_ingest, operations_readonly;
CREATE FUNCTION operations.refresh_device_session_current() RETURNS void LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations SET operations.tenant_id = '1' AS $fn$
BEGIN
 PERFORM operations.refresh_device_session_current_before_coverage();
 UPDATE operations.coverage_read_revision SET revision = revision + 1 WHERE tenant_id = 1;
END $fn$;
REVOKE ALL ON FUNCTION operations.refresh_device_session_current() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.refresh_device_session_current() TO ninja_ingest, operations_app;
"""

REVERSE_SQL = """DROP FUNCTION operations.refresh_device_agent_presence_current();
ALTER FUNCTION operations.refresh_device_agent_presence_current_before_coverage() RENAME TO refresh_device_agent_presence_current;
GRANT EXECUTE ON FUNCTION operations.refresh_device_agent_presence_current() TO ninja_ingest, operations_app;
DROP FUNCTION operations.refresh_device_session_current();
ALTER FUNCTION operations.refresh_device_session_current_before_coverage() RENAME TO refresh_device_session_current;
GRANT EXECUTE ON FUNCTION operations.refresh_device_session_current() TO ninja_ingest, operations_app;
DROP TRIGGER coverage_read_changed ON operations.evaluator_config;
DROP TRIGGER coverage_read_changed ON operations.agents;
DROP TRIGGER coverage_read_changed ON operations.source_record_lifecycle_mappings;
DROP TRIGGER coverage_read_changed ON operations.sources;
DROP TRIGGER coverage_read_changed ON operations.source_instances;
DROP TRIGGER coverage_read_changed ON operations.entity_observation_current;
DROP TRIGGER coverage_read_changed ON operations.device_requirement_state;
DROP TRIGGER coverage_read_changed ON operations.device_operator_decisions;
DROP TRIGGER coverage_read_changed ON operations.computer_client_ownership;
DROP TRIGGER coverage_read_changed ON operations.clients;
DROP TRIGGER coverage_read_changed ON operations.devices;
DROP FUNCTION operations.invalidate_coverage_read();
DROP FUNCTION operations.refresh_coverage_read(bigint, integer);
DROP TABLE operations.coverage_cell_read_current;
DROP TABLE operations.coverage_computer_read_current;
DROP TABLE operations.coverage_read_publication;
DROP TABLE operations.coverage_read_revision;"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list] = [("operations", "0421_software_input_claim_gate")]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
