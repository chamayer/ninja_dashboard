"""Project a source-owned installation through the current Computer and owner."""

from typing import ClassVar

from django.db import migrations

SQL = """
ALTER TABLE operations.source_record_software_current
    ADD COLUMN software_version_id bigint REFERENCES catalog.software_versions(id) ON DELETE SET NULL;
CREATE INDEX source_software_unlinked_catalog
    ON operations.source_record_software_current (tenant_id, source_record_id, canonical_name)
    WHERE software_version_id IS NULL AND stale_since IS NULL;
CREATE INDEX source_software_linked_catalog
    ON operations.source_record_software_current (tenant_id, software_version_id)
    WHERE software_version_id IS NOT NULL;

CREATE FUNCTION operations.clear_outdated_source_software_version() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, operations
AS $fn$
BEGIN
    IF (NEW.publisher, NEW.version) IS DISTINCT FROM (OLD.publisher, OLD.version) THEN
        NEW.software_version_id := NULL;
    END IF;
    RETURN NEW;
END
$fn$;
REVOKE ALL ON FUNCTION operations.clear_outdated_source_software_version() FROM PUBLIC;
CREATE TRIGGER clear_outdated_source_software_version
    BEFORE UPDATE OF publisher, version ON operations.source_record_software_current
    FOR EACH ROW EXECUTE FUNCTION operations.clear_outdated_source_software_version();

CREATE VIEW operations.v_current_source_installations WITH (security_barrier = true) AS
WITH current_ninja AS (
    SELECT device.tenant_id, current_link.source_record_id,
           device.id AS device_id, owner.effective_client_id AS client_id
      FROM operations.devices device
      JOIN operations.computer_client_ownership owner
        ON owner.tenant_id = device.tenant_id AND owner.device_id = device.id
       AND owner.effective_client_id = device.client_id
      CROSS JOIN LATERAL (
          WITH primary_links AS MATERIALIZED (
              SELECT subject.id AS source_record_id, link.source_instance_id,
                     observation.external_namespace, observation.entity_type, observation.canonical_data
                FROM operations.entity_source_links link
                JOIN operations.source_record_subjects subject
                  ON subject.tenant_id = link.tenant_id AND subject.id = link.source_subject_id
                JOIN operations.entity_observation_current observation
                  ON observation.tenant_id = subject.tenant_id
                 AND observation.observation_id = subject.observation_id AND observation.device_id = device.id
               WHERE link.tenant_id = device.tenant_id AND link.entity_id = device.entity_id
                 AND subject.subject_kind = 'record' AND link.entity_class_id = 'device'
                 AND observation.active AND observation.platform = 'Ninja'
                 AND NOT operations.is_companion_stream(
                     link.tenant_id, link.source_instance_id, link.external_namespace)
               LIMIT 2
          )
          SELECT primary_link.source_record_id
            FROM primary_links primary_link
            JOIN operations.source_instances instance
              ON instance.tenant_id = device.tenant_id AND instance.id = primary_link.source_instance_id
            LEFT JOIN LATERAL (
                SELECT mapping.counts_as_current_computer_evidence
                  FROM operations.source_record_lifecycle_mappings mapping
                 WHERE mapping.enabled AND (mapping.source_id IS NULL OR mapping.source_id = instance.source_id)
                   AND (mapping.external_namespace = '' OR mapping.external_namespace = primary_link.external_namespace)
                   AND (mapping.entity_type = '' OR mapping.entity_type = primary_link.entity_type)
                   AND primary_link.canonical_data -> mapping.canonical_field = mapping.match_value
                 ORDER BY mapping.priority, mapping.id
                 LIMIT 1
            ) lifecycle ON true
           WHERE (SELECT count(*) FROM primary_links) = 1
             AND coalesce(lifecycle.counts_as_current_computer_evidence, true)
      ) current_link
     WHERE device.tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint
       AND device.deleted_at IS NULL AND device.lifecycle_status <> 'retired'
       AND owner.state IN ('resolved', 'decision_protected')
)
SELECT inventory.tenant_id, inventory.source_record_id, current_ninja.device_id,
       current_ninja.client_id,
       md5(jsonb_build_array(inventory.tenant_id, inventory.source_record_id, inventory.canonical_name)::text)
           ::uuid AS installation_uuid,
       inventory.canonical_name, inventory.publisher, inventory.install_location,
       inventory.stale_since, NULL::timestamptz AS deleted_at,
       inventory.display_name, inventory.version, inventory.install_date,
       inventory.product_code, inventory.size_bytes, inventory.is_system_component,
       inventory.first_observed_at, inventory.last_observed_at, inventory.refreshed_at,
       inventory.stale_reason, inventory.software_version_id, inventory.material_hash
  FROM current_ninja
  JOIN operations.source_record_software_current inventory
    ON inventory.tenant_id = current_ninja.tenant_id
   AND inventory.source_record_id = current_ninja.source_record_id;
ALTER VIEW operations.v_current_source_installations OWNER TO operations_migrate;
REVOKE ALL ON operations.v_current_source_installations
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT SELECT ON operations.v_current_source_installations TO operations_app, ninja_ingest;

CREATE VIEW operations.v_installation_finding_subjects WITH (security_barrier = true) AS
    SELECT tenant_id, device_id, client_id, installation_uuid, stale_since, deleted_at
      FROM operations.v_current_source_installations
    UNION ALL
    SELECT legacy.tenant_id, legacy.device_id, legacy.client_id, legacy.installation_uuid,
           legacy.stale_since, legacy.deleted_at
      FROM operations.software_installations_current legacy
     WHERE legacy.tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint
       AND NOT EXISTS (
           SELECT 1 FROM operations.retired_installation_subjects retired
            WHERE retired.tenant_id = legacy.tenant_id AND retired.installation_uuid = legacy.installation_uuid
       )
       AND EXISTS (
           SELECT 1 FROM operations.v_current_source_installations source
            WHERE source.tenant_id = legacy.tenant_id AND source.device_id = legacy.device_id
              AND source.client_id = legacy.client_id AND source.canonical_name = legacy.canonical_name
              AND source.stale_since IS NULL
              AND (source.publisher, source.version, source.install_location)
                  IS NOT DISTINCT FROM (legacy.publisher, legacy.version, legacy.install_location)
       );
ALTER VIEW operations.v_installation_finding_subjects OWNER TO operations_migrate;
REVOKE ALL ON operations.v_installation_finding_subjects
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT SELECT ON operations.v_installation_finding_subjects TO operations_app, ninja_ingest;

CREATE FUNCTION operations.queue_installation_scope_change() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_tenant bigint;
    v_sources uuid[];
BEGIN
    IF TG_TABLE_NAME = 'entity_source_links' THEN
        IF TG_OP = 'DELETE' THEN
            v_tenant := OLD.tenant_id;
            v_sources := ARRAY[OLD.source_subject_id];
        ELSE
            v_tenant := NEW.tenant_id;
            v_sources := ARRAY[NEW.source_subject_id];
        END IF;
    ELSE
        v_tenant := NEW.tenant_id;
        SELECT array_agg(link.source_subject_id) INTO v_sources
          FROM operations.devices device
          JOIN operations.entity_source_links link
            ON link.tenant_id = device.tenant_id AND link.entity_id = device.entity_id
         WHERE device.tenant_id = v_tenant AND device.id = NEW.device_id
           AND link.entity_class_id = 'device';
    END IF;
    IF v_sources IS NULL OR v_tenant IS DISTINCT FROM 1 OR v_tenant IS DISTINCT FROM
        nullif(current_setting('operations.tenant_id', true), '')::bigint THEN
        RETURN NULL;
    END IF;
    INSERT INTO operations.software_reclassification_targets AS target
        (tenant_id, target_key, canonical_name, source)
    SELECT v_tenant, left('name:' || lower(canonical_name), 300), min(canonical_name), 'inventory'
      FROM operations.source_record_software_current
     WHERE tenant_id = v_tenant AND source_record_id = ANY(v_sources)
       AND stale_since IS NULL AND canonical_name <> ''
     GROUP BY left('name:' || lower(canonical_name), 300)
    ON CONFLICT (tenant_id, target_key, source) WHERE consumed_at IS NULL
    DO UPDATE SET generation = target.generation + 1;
    RETURN NULL;
END
$fn$;
ALTER FUNCTION operations.queue_installation_scope_change() OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.queue_installation_scope_change()
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
CREATE TRIGGER queue_installation_new_link AFTER INSERT ON operations.entity_source_links
    FOR EACH ROW WHEN (NEW.entity_class_id = 'device' AND NEW.source_subject_id IS NOT NULL)
    EXECUTE FUNCTION operations.queue_installation_scope_change();
CREATE TRIGGER queue_installation_moved_link AFTER UPDATE OF entity_id ON operations.entity_source_links
    FOR EACH ROW WHEN (NEW.entity_class_id = 'device' AND NEW.source_subject_id IS NOT NULL
                       AND OLD.entity_id IS DISTINCT FROM NEW.entity_id)
    EXECUTE FUNCTION operations.queue_installation_scope_change();
CREATE TRIGGER queue_installation_closed_link AFTER DELETE ON operations.entity_source_links
    FOR EACH ROW WHEN (OLD.entity_class_id = 'device' AND OLD.source_subject_id IS NOT NULL)
    EXECUTE FUNCTION operations.queue_installation_scope_change();
CREATE TRIGGER queue_installation_owner_scope
    AFTER UPDATE OF effective_client_id, state ON operations.computer_client_ownership
    FOR EACH ROW WHEN (NEW.state IN ('resolved', 'decision_protected')
                       AND (OLD.effective_client_id IS DISTINCT FROM NEW.effective_client_id
                            OR OLD.state IS DISTINCT FROM NEW.state))
    EXECUTE FUNCTION operations.queue_installation_scope_change();
"""

REVERSE_SQL = """
DROP TRIGGER queue_installation_owner_scope ON operations.computer_client_ownership;
DROP TRIGGER queue_installation_closed_link ON operations.entity_source_links;
DROP TRIGGER queue_installation_moved_link ON operations.entity_source_links;
DROP TRIGGER queue_installation_new_link ON operations.entity_source_links;
DROP FUNCTION operations.queue_installation_scope_change();
DROP VIEW operations.v_installation_finding_subjects;
DROP VIEW operations.v_current_source_installations;
DROP TRIGGER clear_outdated_source_software_version ON operations.source_record_software_current;
DROP FUNCTION operations.clear_outdated_source_software_version();
DROP INDEX operations.source_software_unlinked_catalog;
DROP INDEX operations.source_software_linked_catalog;
ALTER TABLE operations.source_record_software_current DROP COLUMN software_version_id;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0432_ninja_record_supersession"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(SQL, REVERSE_SQL)]
