-- Materialize Inventory current facts so Metabase does not recompute
-- source identity, serial extraction, conflicts, and merge candidates
-- on every dashboard load.

CREATE SCHEMA IF NOT EXISTS ninja_inventory;

DO $$
BEGIN
    IF to_regclass('ninja_inventory.v_source_observations_current') IS NOT NULL
       AND to_regclass('ninja_inventory.v_source_observations_current_live') IS NULL THEN
        ALTER VIEW ninja_inventory.v_source_observations_current
        RENAME TO v_source_observations_current_live;
    END IF;

    IF to_regclass('ninja_inventory.v_unresolved_source_records_current') IS NOT NULL
       AND to_regclass('ninja_inventory.v_unresolved_source_records_current_live') IS NULL THEN
        ALTER VIEW ninja_inventory.v_unresolved_source_records_current
        RENAME TO v_unresolved_source_records_current_live;
    END IF;

    IF to_regclass('ninja_inventory.v_devices_current') IS NOT NULL
       AND to_regclass('ninja_inventory.v_devices_current_live') IS NULL THEN
        ALTER VIEW ninja_inventory.v_devices_current
        RENAME TO v_devices_current_live;
    END IF;

    IF to_regclass('ninja_inventory.v_serial_quality_current') IS NOT NULL
       AND to_regclass('ninja_inventory.v_serial_quality_current_live') IS NULL THEN
        ALTER VIEW ninja_inventory.v_serial_quality_current
        RENAME TO v_serial_quality_current_live;
    END IF;

    IF to_regclass('ninja_inventory.v_identity_conflicts_current') IS NOT NULL
       AND to_regclass('ninja_inventory.v_identity_conflicts_current_live') IS NULL THEN
        ALTER VIEW ninja_inventory.v_identity_conflicts_current
        RENAME TO v_identity_conflicts_current_live;
    END IF;

    IF to_regclass('ninja_inventory.v_merge_candidates_current') IS NOT NULL
       AND to_regclass('ninja_inventory.v_merge_candidates_current_live') IS NULL THEN
        ALTER VIEW ninja_inventory.v_merge_candidates_current
        RENAME TO v_merge_candidates_current_live;
    END IF;

    IF to_regclass('ninja_inventory.v_inventory_summary_current') IS NOT NULL
       AND to_regclass('ninja_inventory.v_inventory_summary_current_live') IS NULL THEN
        ALTER VIEW ninja_inventory.v_inventory_summary_current
        RENAME TO v_inventory_summary_current_live;
    END IF;
END $$;

CREATE MATERIALIZED VIEW IF NOT EXISTS ninja_inventory.source_observations_current AS
SELECT *
FROM ninja_inventory.v_source_observations_current_live
WITH DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS ninja_inventory.unresolved_source_records_current AS
SELECT *
FROM ninja_inventory.v_unresolved_source_records_current_live
WITH DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS ninja_inventory.devices_current AS
SELECT *
FROM ninja_inventory.v_devices_current_live
WITH DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS ninja_inventory.serial_quality_current AS
SELECT *
FROM ninja_inventory.v_serial_quality_current_live
WITH DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS ninja_inventory.identity_conflicts_current AS
SELECT *
FROM ninja_inventory.v_identity_conflicts_current_live
WITH DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS ninja_inventory.merge_candidates_current AS
SELECT *
FROM ninja_inventory.v_merge_candidates_current_live
WITH DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS ninja_inventory.inventory_summary_current AS
SELECT *
FROM ninja_inventory.v_inventory_summary_current_live
WITH DATA;

CREATE OR REPLACE VIEW ninja_inventory.v_source_observations_current AS
SELECT * FROM ninja_inventory.source_observations_current;

CREATE OR REPLACE VIEW ninja_inventory.v_unresolved_source_records_current AS
SELECT * FROM ninja_inventory.unresolved_source_records_current;

CREATE OR REPLACE VIEW ninja_inventory.v_devices_current AS
SELECT * FROM ninja_inventory.devices_current;

CREATE OR REPLACE VIEW ninja_inventory.v_serial_quality_current AS
SELECT * FROM ninja_inventory.serial_quality_current;

CREATE OR REPLACE VIEW ninja_inventory.v_identity_conflicts_current AS
SELECT * FROM ninja_inventory.identity_conflicts_current;

CREATE OR REPLACE VIEW ninja_inventory.v_merge_candidates_current AS
SELECT * FROM ninja_inventory.merge_candidates_current;

CREATE OR REPLACE VIEW ninja_inventory.v_inventory_summary_current AS
SELECT * FROM ninja_inventory.inventory_summary_current;

CREATE INDEX IF NOT EXISTS inventory_source_observations_platform_idx
ON ninja_inventory.source_observations_current (platform, source_name, observed_at DESC);

CREATE INDEX IF NOT EXISTS inventory_source_observations_customer_idx
ON ninja_inventory.source_observations_current (customer_id, customer_name, norm_name);

CREATE INDEX IF NOT EXISTS inventory_source_observations_serial_idx
ON ninja_inventory.source_observations_current (serial_quality, serial_number)
WHERE serial_number IS NOT NULL;

CREATE INDEX IF NOT EXISTS inventory_source_observations_device_id_idx
ON ninja_inventory.source_observations_current (platform, platform_device_id)
WHERE platform_device_id IS NOT NULL AND platform_device_id <> '';

CREATE INDEX IF NOT EXISTS inventory_devices_customer_state_idx
ON ninja_inventory.devices_current (customer_name, inventory_state, display_name);

CREATE INDEX IF NOT EXISTS inventory_devices_customer_norm_idx
ON ninja_inventory.devices_current (customer_id, norm_name);

CREATE INDEX IF NOT EXISTS inventory_devices_present_platforms_idx
ON ninja_inventory.devices_current USING GIN (present_platforms);

CREATE INDEX IF NOT EXISTS inventory_unresolved_platform_idx
ON ninja_inventory.unresolved_source_records_current (platform, observed_at DESC);

CREATE INDEX IF NOT EXISTS inventory_serial_quality_filters_idx
ON ninja_inventory.serial_quality_current (platform, customer_name, serial_quality, hostname);

CREATE INDEX IF NOT EXISTS inventory_identity_conflicts_sort_idx
ON ninja_inventory.identity_conflicts_current (
    customer_count DESC,
    record_count DESC,
    conflict_type,
    identity_key
);

CREATE INDEX IF NOT EXISTS inventory_merge_candidates_customer_idx
ON ninja_inventory.merge_candidates_current (customer_name, match_key);

CREATE OR REPLACE FUNCTION ninja_inventory.refresh_current()
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW ninja_inventory.source_observations_current;
    REFRESH MATERIALIZED VIEW ninja_inventory.unresolved_source_records_current;
    REFRESH MATERIALIZED VIEW ninja_inventory.devices_current;
    REFRESH MATERIALIZED VIEW ninja_inventory.serial_quality_current;
    REFRESH MATERIALIZED VIEW ninja_inventory.identity_conflicts_current;
    REFRESH MATERIALIZED VIEW ninja_inventory.merge_candidates_current;
    REFRESH MATERIALIZED VIEW ninja_inventory.inventory_summary_current;
END;
$$;
