-- Include hostname/Mac-safe same-device candidates in the Inventory
-- merge-candidate queue. Serial candidates stay here too; Inventory
-- should be the single review surface for "same device?" evidence.

CREATE OR REPLACE VIEW ninja_inventory.v_merge_candidates_current AS
WITH src AS (
    SELECT *
    FROM ninja_inventory.v_source_observations_current
    WHERE customer_id IS NOT NULL
      AND serial_quality = 'valid'
),
serial_groups AS (
    SELECT
        customer_id,
        customer_name,
        serial_number,
        COUNT(DISTINCT platform) AS platform_count,
        COUNT(DISTINCT norm_name) AS norm_count,
        COUNT(DISTINCT platform || ':' || COALESCE(NULLIF(platform_device_id, ''), hostname)) AS record_count,
        ARRAY_AGG(DISTINCT platform ORDER BY platform) AS platforms,
        ARRAY_AGG(DISTINCT hostname ORDER BY hostname) AS hostnames,
        ARRAY_AGG(DISTINCT norm_name ORDER BY norm_name) AS norm_names,
        ARRAY_AGG(DISTINCT platform_device_id ORDER BY platform_device_id)
            FILTER (WHERE COALESCE(NULLIF(platform_device_id, ''), '') <> '') AS platform_device_ids,
        MAX(last_seen_at) AS last_seen_at
    FROM src
    GROUP BY customer_id, customer_name, serial_number
    HAVING COUNT(DISTINCT platform || ':' || COALESCE(NULLIF(platform_device_id, ''), hostname)) > 1
),
serial_candidates AS (
    SELECT
        customer_id,
        customer_name,
        'serial_same_customer'::text AS candidate_type,
        serial_number AS match_key,
        platform_count,
        norm_count,
        record_count,
        platforms,
        hostnames,
        norm_names,
        COALESCE(platform_device_ids, ARRAY[]::text[]) AS platform_device_ids,
        last_seen_at,
        CASE
            WHEN platform_count > 1 AND norm_count > 1 THEN 'Strong cross-platform same-device candidate by serial'
            WHEN platform_count > 1 THEN 'Cross-platform serial match'
            ELSE 'Same-platform serial duplicate; review stale/re-enrolled records'
        END AS reason
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
