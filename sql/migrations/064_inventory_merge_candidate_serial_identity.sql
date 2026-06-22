-- Refine Inventory merge candidates:
-- A valid serial observed in multiple platforms is normal same-device
-- evidence. Only surface a serial merge candidate when that serial maps
-- to more than one reconciled inventory device for the same customer.

CREATE OR REPLACE VIEW ninja_inventory.v_merge_candidates_current_live AS
WITH valid_serial_devices AS (
    SELECT DISTINCT
        d.customer_id,
        d.customer_name,
        d.inventory_device_id,
        d.norm_name,
        d.display_name,
        o.serial_number
    FROM ninja_inventory.v_devices_current d
    JOIN ninja_inventory.v_source_observations_current o
      ON o.customer_id = d.customer_id
     AND o.serial_quality = 'valid'
     AND o.serial_number = ANY(d.serial_numbers)
),
serial_groups AS (
    SELECT
        vs.customer_id,
        vs.customer_name,
        vs.serial_number,
        COUNT(DISTINCT vs.inventory_device_id) AS inventory_device_count,
        COUNT(DISTINCT o.platform) AS platform_count,
        COUNT(DISTINCT vs.norm_name) AS norm_count,
        COUNT(DISTINCT o.platform || ':' || COALESCE(NULLIF(o.platform_device_id, ''), o.hostname)) AS record_count,
        ARRAY_AGG(DISTINCT o.platform ORDER BY o.platform) AS platforms,
        ARRAY_AGG(DISTINCT COALESCE(NULLIF(vs.display_name, ''), vs.norm_name) ORDER BY COALESCE(NULLIF(vs.display_name, ''), vs.norm_name)) AS hostnames,
        ARRAY_AGG(DISTINCT vs.norm_name ORDER BY vs.norm_name) AS norm_names,
        ARRAY_AGG(DISTINCT o.platform_device_id ORDER BY o.platform_device_id)
            FILTER (WHERE COALESCE(NULLIF(o.platform_device_id, ''), '') <> '') AS platform_device_ids,
        MAX(o.last_seen_at) AS last_seen_at
    FROM valid_serial_devices vs
    JOIN ninja_inventory.v_source_observations_current o
      ON o.customer_id = vs.customer_id
     AND o.serial_number = vs.serial_number
     AND o.serial_quality = 'valid'
    GROUP BY vs.customer_id, vs.customer_name, vs.serial_number
    HAVING COUNT(DISTINCT vs.inventory_device_id) > 1
),
serial_candidates AS (
    SELECT
        customer_id,
        customer_name,
        'serial_multiple_inventory_devices'::text AS candidate_type,
        serial_number AS match_key,
        platform_count,
        norm_count,
        record_count,
        platforms,
        hostnames,
        norm_names,
        COALESCE(platform_device_ids, ARRAY[]::text[]) AS platform_device_ids,
        last_seen_at,
        'Same valid serial maps to multiple reconciled inventory devices; review stale duplicate, rename, or manual merge'::text AS reason
    FROM serial_groups
),
hostname_candidates AS (
    SELECT
        client_id AS customer_id,
        client_name AS customer_name,
        'hostname_same_customer'::text AS candidate_type,
        loose_norm AS match_key,
        cardinality(platforms) AS platform_count,
        cardinality(norm_names) AS norm_count,
        cardinality(hostnames) AS record_count,
        platforms,
        hostnames,
        norm_names,
        ARRAY[]::text[] AS platform_device_ids,
        last_seen_at,
        'Hostname/Mac-safe same-device candidate from inventory/compliance identity rules'::text AS reason
    FROM ninja_agent_compliance.v_device_merge_candidates
)
SELECT *
FROM serial_candidates
UNION ALL
SELECT *
FROM hostname_candidates
ORDER BY customer_name, candidate_type, match_key;

SELECT ninja_inventory.refresh_current();
