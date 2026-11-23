"""Maintain the unfiltered Software Installations first page."""

from typing import ClassVar

from django.db import migrations


# Only values read by v_current_source_installations and the page publication.
# Comparing transition sets avoids invalidating on unchanged bulk updates.
INPUT_COLUMNS = {
    "devices": "tenant_id, id, entity_id, client_id, deleted_at, lifecycle_status, canonical_hostname",
    "clients": "tenant_id, id, slug, display_name",
    "computer_client_ownership": "tenant_id, device_id, state, effective_client_id",
    "entity_source_links": (
        "tenant_id, id, entity_id, entity_class_id, source_subject_id, source_instance_id, external_namespace"
    ),
    "source_record_subjects": "tenant_id, id, subject_kind, observation_id",
    "entity_observation_current": (
        "tenant_id, observation_id, device_id, active, platform, external_namespace, entity_type, canonical_data"
    ),
    "source_instances": "tenant_id, id, source_id",
    "source_record_companion_streams": "source_id, external_namespace, enabled",
    "source_record_lifecycle_mappings": (
        "id, source_id, external_namespace, entity_type, canonical_field, match_value, "
        "counts_as_current_computer_evidence, priority, enabled"
    ),
    "source_record_software_current": (
        "tenant_id, source_record_id, canonical_name, display_name, publisher, version, "
        "install_date, install_location, last_observed_at, stale_since"
    ),
}

SCHEMA_SQL = """
CREATE TABLE operations.software_installations_read_changes (
    tenant_id bigint NOT NULL CHECK (tenant_id = 1),
    transaction_id xid8 NOT NULL,
    PRIMARY KEY (tenant_id, transaction_id)
);
CREATE TABLE operations.software_installations_first_page (
    tenant_id bigint PRIMARY KEY CHECK (tenant_id = 1),
    input_snapshot pg_snapshot NOT NULL,
    total bigint NOT NULL CHECK (total >= 0),
    page_rows jsonb NOT NULL,
    products text[] NOT NULL,
    publishers text[] NOT NULL,
    computers text[] NOT NULL
);
ALTER TABLE operations.software_installations_read_changes OWNER TO operations_migrate;
ALTER TABLE operations.software_installations_first_page OWNER TO operations_migrate;
ALTER TABLE operations.software_installations_read_changes ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.software_installations_read_changes FORCE ROW LEVEL SECURITY;
ALTER TABLE operations.software_installations_first_page ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.software_installations_first_page FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.software_installations_read_changes
    USING (tenant_id = operations.current_tenant_id())
    WITH CHECK (tenant_id = operations.current_tenant_id());
CREATE POLICY tenant_isolation ON operations.software_installations_first_page
    USING (tenant_id = operations.current_tenant_id())
    WITH CHECK (tenant_id = operations.current_tenant_id());
REVOKE ALL ON operations.software_installations_read_changes, operations.software_installations_first_page
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest, operations_view_owner;

INSERT INTO operations.change_history_registry
    (table_name, classification, reason, recorded_columns, secret_columns, key_columns,
     computer_column, computer_condition_column, computer_condition_value, client_column, is_global, capture)
VALUES
    ('software_installations_read_changes', 'exempt',
     'Transactional invalidation of a rebuildable Software publication',
     '{}', '{}', ARRAY['tenant_id', 'transaction_id'], NULL, NULL, NULL, NULL, false, NULL),
    ('software_installations_first_page', 'exempt',
     'Rebuildable Installations first page and filter choices',
     '{}', '{}', ARRAY['tenant_id'], NULL, NULL, NULL, NULL, false, NULL);

CREATE FUNCTION operations.invalidate_software_installations_read() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
SET operations.tenant_id = '1'
AS $fn$
DECLARE
    changed boolean;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        -- The projection columns are fixed by the migration's trigger arguments.
        EXECUTE format(
            'SELECT EXISTS (SELECT %1$s FROM old_inputs EXCEPT ALL SELECT %1$s FROM new_inputs)',
            TG_ARGV[0]
        ) INTO changed;
    ELSIF TG_OP IN ('INSERT', 'DELETE') THEN
        SELECT EXISTS (SELECT 1 FROM changed_inputs) INTO changed;
    ELSE
        changed := true;
    END IF;
    IF changed THEN
        INSERT INTO operations.software_installations_read_changes (tenant_id, transaction_id)
        VALUES (1, pg_current_xact_id()) ON CONFLICT DO NOTHING;
    END IF;
    RETURN NULL;
END
$fn$;
ALTER FUNCTION operations.invalidate_software_installations_read() OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.invalidate_software_installations_read()
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
"""


def _input_triggers():
    return "\n".join(
        f"""
CREATE TRIGGER software_installations_insert AFTER INSERT ON operations.{table}
    REFERENCING NEW TABLE AS changed_inputs
    FOR EACH STATEMENT EXECUTE FUNCTION operations.invalidate_software_installations_read();
CREATE TRIGGER software_installations_update AFTER UPDATE ON operations.{table}
    REFERENCING OLD TABLE AS old_inputs NEW TABLE AS new_inputs
    FOR EACH STATEMENT EXECUTE FUNCTION operations.invalidate_software_installations_read('{columns}');
CREATE TRIGGER software_installations_delete AFTER DELETE ON operations.{table}
    REFERENCING OLD TABLE AS changed_inputs
    FOR EACH STATEMENT EXECUTE FUNCTION operations.invalidate_software_installations_read();
CREATE TRIGGER software_installations_truncate AFTER TRUNCATE ON operations.{table}
    FOR EACH STATEMENT EXECUTE FUNCTION operations.invalidate_software_installations_read();
"""
        for table, columns in INPUT_COLUMNS.items()
    )


PUBLICATION_SQL = """
CREATE FUNCTION operations.read_software_installations_first_page(p_tenant bigint)
RETURNS TABLE (total bigint, page_rows jsonb, products text[], publishers text[], computers text[])
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, operations AS $fn$
    SELECT published.total, published.page_rows, published.products, published.publishers, published.computers
      FROM operations.software_installations_first_page published
     WHERE p_tenant = 1 AND p_tenant = operations.current_tenant_id() AND published.tenant_id = p_tenant
       AND NOT EXISTS (
           SELECT 1 FROM operations.software_installations_read_changes change
            WHERE change.tenant_id = p_tenant
              AND change.transaction_id >= pg_snapshot_xmin(published.input_snapshot)
              AND NOT pg_visible_in_snapshot(change.transaction_id, published.input_snapshot)
       )
       AND NOT EXISTS (
           SELECT 1 FROM operations.software_installations_read_changes own_change
            WHERE own_change.tenant_id = p_tenant
              AND own_change.transaction_id = pg_current_xact_id_if_assigned()
       )
$fn$;
ALTER FUNCTION operations.read_software_installations_first_page(bigint) OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.read_software_installations_first_page(bigint)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.read_software_installations_first_page(bigint) TO operations_app;

CREATE FUNCTION operations.refresh_software_installations_first_page(p_tenant bigint) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations AS $fn$
DECLARE
    v_snapshot pg_snapshot;
BEGIN
    IF p_tenant IS DISTINCT FROM 1 OR p_tenant IS DISTINCT FROM operations.current_tenant_id() THEN
        RAISE EXCEPTION 'Invalid Installations publication tenant';
    END IF;
    IF NOT pg_try_advisory_xact_lock(hashtextextended('operations.software.installations.first_page', 0))
       OR EXISTS (SELECT 1 FROM operations.read_software_installations_first_page(p_tenant)) THEN
        RETURN false;
    END IF;
    -- Capture provenance and inputs in the same statement snapshot. A writer
    -- that commits during this statement leaves an invalidation visible to
    -- later readers, including transactions assigned an earlier XID.
    WITH inventory AS MATERIALIZED (
        SELECT i.tenant_id, i.client_id, i.device_id, i.source_record_id,
               i.canonical_name, i.display_name, i.publisher, i.last_observed_at,
               d.canonical_hostname, c.slug, c.display_name AS client_display_name
          FROM operations.v_current_source_installations i
          JOIN operations.devices d ON d.tenant_id = i.tenant_id AND d.id = i.device_id
          JOIN operations.clients c ON c.tenant_id = i.tenant_id AND c.id = i.client_id
         WHERE i.tenant_id = p_tenant AND i.stale_since IS NULL
    ), page AS (
        SELECT * FROM inventory
         ORDER BY client_display_name, canonical_hostname, canonical_name, device_id
         LIMIT 100
    ), latest_products AS (
        SELECT canonical_name, max(last_observed_at) AS last_observed_at
          FROM inventory GROUP BY canonical_name
    )
    INSERT INTO operations.software_installations_first_page AS previous
        (tenant_id, input_snapshot, total, page_rows, products, publishers, computers)
    SELECT p_tenant, pg_current_snapshot(), (SELECT count(*) FROM inventory),
           coalesce((
               SELECT jsonb_agg(to_jsonb(page) || jsonb_build_object(
                   'version', detail.version, 'install_date', detail.install_date,
                   'install_location', detail.install_location
               ) ORDER BY page.client_display_name, page.canonical_hostname, page.canonical_name, page.device_id)
                 FROM page LEFT JOIN operations.source_record_software_current detail
                   ON detail.tenant_id = page.tenant_id AND detail.source_record_id = page.source_record_id
                  AND detail.canonical_name = page.canonical_name
           ), '[]'::jsonb),
           ARRAY(
               SELECT ARRAY[product.canonical_name,
                            coalesce(nullif(min(i.display_name), ''), product.canonical_name)]
                 FROM latest_products product JOIN inventory i USING (canonical_name, last_observed_at)
                GROUP BY product.canonical_name ORDER BY product.canonical_name
           ),
           ARRAY(SELECT DISTINCT publisher FROM inventory WHERE publisher <> '' ORDER BY publisher),
           ARRAY(
               SELECT ARRAY[client_display_name, canonical_hostname, device_id::text]
                 FROM (SELECT DISTINCT client_display_name, canonical_hostname, device_id FROM inventory) computers
                ORDER BY 1
           )
    ON CONFLICT (tenant_id) DO UPDATE
        SET input_snapshot = EXCLUDED.input_snapshot, total = EXCLUDED.total, page_rows = EXCLUDED.page_rows,
            products = EXCLUDED.products, publishers = EXCLUDED.publishers, computers = EXCLUDED.computers
    RETURNING previous.input_snapshot INTO v_snapshot;

    DELETE FROM operations.software_installations_read_changes
     WHERE tenant_id = p_tenant AND transaction_id < pg_snapshot_xmin(v_snapshot);
    RETURN true;
END
$fn$;
ALTER FUNCTION operations.refresh_software_installations_first_page(bigint) OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.refresh_software_installations_first_page(bigint)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.refresh_software_installations_first_page(bigint) TO ninja_ingest;
"""

FORWARD_SQL = SCHEMA_SQL + _input_triggers() + PUBLICATION_SQL
REVERSE_SQL = "\n".join(
    f"DROP TRIGGER software_installations_{event} ON operations.{table};"
    for table in INPUT_COLUMNS
    for event in ("insert", "update", "delete", "truncate")
) + """
DROP FUNCTION operations.refresh_software_installations_first_page(bigint);
DROP FUNCTION operations.read_software_installations_first_page(bigint);
DROP FUNCTION operations.invalidate_software_installations_read();
DROP TABLE operations.software_installations_first_page;
DROP TABLE operations.software_installations_read_changes;
DELETE FROM operations.change_history_registry
 WHERE table_name IN ('software_installations_first_page', 'software_installations_read_changes');
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0435_source_software_read_models"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
