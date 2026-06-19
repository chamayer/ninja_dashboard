-- Inventory module.
--
-- Inventory owns device/source identity, metadata quality, and merge/conflict
-- review. Compliance can consume these resolved facts later, but these views
-- are intentionally additive and do not move or rewrite compliance dashboards.

CREATE SCHEMA IF NOT EXISTS ninja_inventory;

CREATE OR REPLACE VIEW ninja_inventory.v_source_observations_current AS
WITH latest AS (
    SELECT DISTINCT ON (
        po.platform,
        po.source_id,
        COALESCE(NULLIF(po.platform_device_id, ''), po.hostname)
    )
        po.observation_id,
        po.source_run_id,
        po.observed_at,
        po.platform,
        po.source_id,
        po.source_name,
        po.resolved_client_id AS customer_id,
        po.resolved_client_name AS customer_name,
        po.platform_group_name AS platform_customer_name,
        po.platform_group_id AS platform_customer_id,
        po.platform_device_id,
        po.hostname,
        po.norm_name,
        po.match_name,
        regexp_replace(split_part(lower(coalesce(po.hostname, '')), '.', 1), '[^a-z0-9]', '', 'g') AS loose_hostname,
        po.device_type,
        po.os_name,
        po.domain_name,
        po.is_online,
        po.last_seen_at,
        po.raw_data,
        nd.serial_number AS ninja_serial_number,
        nd.manufacturer AS ninja_manufacturer,
        nd.model AS ninja_model
    FROM ninja_agent_compliance.platform_observations po
    LEFT JOIN ninja_core.devices nd
      ON po.platform = 'Ninja'
     AND nd.id::text = po.platform_device_id
    ORDER BY
        po.platform,
        po.source_id,
        COALESCE(NULLIF(po.platform_device_id, ''), po.hostname),
        po.observed_at DESC,
        po.observation_id DESC
),
extracted AS (
    SELECT
        latest.*,
        NULLIF(btrim(COALESCE(
            latest.ninja_serial_number,
            latest.raw_data #>> '{system,serialNumber}',
            latest.raw_data ->> 'serialNumber',
            latest.raw_data ->> 'serial_number',
            latest.raw_data ->> 'serial'
        )), '') AS serial_number,
        NULLIF(btrim(COALESCE(
            latest.ninja_manufacturer,
            latest.raw_data #>> '{system,manufacturer}',
            latest.raw_data ->> 'manufacturer'
        )), '') AS manufacturer,
        NULLIF(btrim(COALESCE(
            latest.ninja_model,
            latest.raw_data #>> '{system,model}',
            latest.raw_data ->> 'model'
        )), '') AS model
    FROM latest
),
classified AS (
    SELECT
        e.*,
        lower(btrim(coalesce(e.serial_number, ''))) AS serial_norm
    FROM extracted e
)
SELECT
    observation_id,
    source_run_id,
    observed_at,
    platform,
    source_id,
    source_name,
    customer_id,
    customer_name,
    platform_customer_name,
    platform_customer_id,
    platform_device_id,
    hostname,
    norm_name,
    match_name,
    loose_hostname,
    device_type,
    os_name,
    CASE
        WHEN os_name ILIKE '%Windows Server 2025%' THEN 'Windows Server 2025'
        WHEN os_name ILIKE '%Windows Server 2022%' THEN 'Windows Server 2022'
        WHEN os_name ILIKE '%Windows Server 2019%' THEN 'Windows Server 2019'
        WHEN os_name ILIKE '%Windows Server 2016%' THEN 'Windows Server 2016'
        WHEN os_name ILIKE '%Windows Server%' THEN 'Windows Server (other)'
        WHEN os_name ILIKE '%Windows 11%' THEN 'Windows 11'
        WHEN os_name ILIKE '%Windows 10%' THEN 'Windows 10'
        WHEN os_name ILIKE '%Windows%' THEN 'Windows (other)'
        WHEN os_name ILIKE '%macOS 26%' THEN 'macOS 26'
        WHEN os_name ILIKE '%macOS 15%' THEN 'macOS 15'
        WHEN os_name ILIKE '%macOS 14%' THEN 'macOS 14'
        WHEN os_name ILIKE '%macOS 13%' THEN 'macOS 13'
        WHEN os_name ILIKE '%macOS%' OR os_name ILIKE '%OS X%' OR os_name ILIKE '%Darwin%' THEN 'macOS (other)'
        WHEN os_name ILIKE '%Linux%' THEN 'Linux'
        WHEN COALESCE(NULLIF(os_name, ''), '') = '' THEN 'Unknown'
        ELSE 'Other'
    END AS os_family,
    domain_name,
    is_online,
    last_seen_at,
    serial_number,
    CASE
        WHEN serial_number IS NULL THEN 'missing'
        WHEN serial_norm IN (
            'none',
            'unknown',
            'null',
            '0',
            'default string',
            'to be filled by o.e.m.',
            'to be filled by oem',
            'system serial number',
            '0123456789',
            '123-1234-123',
            'chassis serial number',
            'invalid'
        ) THEN 'invalid_placeholder'
        WHEN length(serial_norm) < 4 THEN 'invalid_short'
        ELSE 'valid'
    END AS serial_quality,
    CASE
        WHEN serial_number IS NULL THEN 'No serial number was reported by this source'
        WHEN serial_norm IN (
            'none',
            'unknown',
            'null',
            '0',
            'default string',
            'to be filled by o.e.m.',
            'to be filled by oem',
            'system serial number',
            '0123456789',
            '123-1234-123',
            'chassis serial number',
            'invalid'
        ) THEN 'Placeholder serial reported by source'
        WHEN length(serial_norm) < 4 THEN 'Serial is too short to use safely'
        ELSE 'Usable serial'
    END AS serial_quality_reason,
    manufacturer,
    model,
    raw_data
FROM classified;

CREATE OR REPLACE VIEW ninja_inventory.v_unresolved_source_records_current AS
WITH src AS (
    SELECT
        o.*,
        lower(trim(coalesce(o.platform_customer_name, ''))) AS platform_customer_norm
    FROM ninja_inventory.v_source_observations_current o
),
excluded AS (
    SELECT
        s.*,
        e.pattern AS exclude_pattern,
        e.source AS exclude_source,
        e.notes AS exclude_notes
    FROM src s
    LEFT JOIN ninja_agent_compliance.org_excludes e
      ON e.enabled
     AND e.pattern = s.platform_customer_norm
)
SELECT
    platform,
    source_id,
    source_name,
    platform_customer_name,
    platform_customer_id,
    hostname,
    platform_device_id,
    os_name,
    serial_number,
    serial_quality,
    last_seen_at,
    observed_at,
    CASE
        WHEN customer_id IS NULL AND exclude_pattern IS NOT NULL THEN 'excluded_customer_name'
        WHEN customer_id IS NULL THEN 'unmapped_customer'
        WHEN exclude_pattern IS NOT NULL THEN 'excluded_customer_name'
        ELSE 'resolved'
    END AS record_state,
    CASE
        WHEN customer_id IS NULL AND exclude_pattern IS NOT NULL THEN
            COALESCE(NULLIF(exclude_notes, ''), 'Customer/group name is excluded but still visible here')
        WHEN customer_id IS NULL THEN 'No enabled customer/platform alias or platform link resolves this source record'
        WHEN exclude_pattern IS NOT NULL THEN
            COALESCE(NULLIF(exclude_notes, ''), 'Customer/group name is excluded but still visible here')
        ELSE ''
    END AS reason
FROM excluded
WHERE customer_id IS NULL
   OR exclude_pattern IS NOT NULL
ORDER BY observed_at DESC, platform, platform_customer_name, hostname;

CREATE OR REPLACE VIEW ninja_inventory.v_devices_current AS
WITH detail AS (
    SELECT
        d.client_id,
        d.client_name,
        d.norm_name,
        d.platform,
        d.platform_device_id,
        d.platform_hostname
    FROM ninja_agent_compliance.v_device_platform_detail_current d
    WHERE d.found
),
obs_for_device AS (
    SELECT
        d.client_id,
        d.norm_name,
        o.platform,
        o.platform_device_id,
        o.hostname,
        o.serial_number,
        o.serial_quality,
        o.manufacturer,
        o.model,
        o.last_seen_at
    FROM detail d
    JOIN ninja_inventory.v_source_observations_current o
      ON o.customer_id = d.client_id
     AND o.platform = d.platform
     AND (
          (NULLIF(o.platform_device_id, '') IS NOT NULL
           AND NULLIF(d.platform_device_id, '') IS NOT NULL
           AND o.platform_device_id = d.platform_device_id)
          OR o.norm_name = d.norm_name
          OR o.hostname = d.platform_hostname
     )
),
agg AS (
    SELECT
        client_id,
        norm_name,
        ARRAY_AGG(DISTINCT serial_number ORDER BY serial_number)
            FILTER (WHERE serial_number IS NOT NULL) AS serial_numbers,
        ARRAY_AGG(DISTINCT serial_quality ORDER BY serial_quality)
            FILTER (WHERE serial_quality IS NOT NULL) AS serial_qualities,
        ARRAY_AGG(DISTINCT manufacturer ORDER BY manufacturer)
            FILTER (WHERE manufacturer IS NOT NULL) AS manufacturers,
        ARRAY_AGG(DISTINCT model ORDER BY model)
            FILTER (WHERE model IS NOT NULL) AS models,
        MAX(last_seen_at) AS source_last_seen_at
    FROM obs_for_device
    GROUP BY client_id, norm_name
)
SELECT
    'inv:' || s.client_id::text || ':' || s.norm_name AS inventory_device_id,
    s.client_id AS customer_id,
    s.client_name AS customer_name,
    s.norm_name,
    s.hostname AS display_name,
    s.hostname AS primary_hostname,
    s.device_type,
    s.os_name,
    s.os_family,
    s.domain_name,
    COALESCE(a.serial_numbers, ARRAY[]::text[]) AS serial_numbers,
    COALESCE(a.serial_qualities, ARRAY[]::text[]) AS serial_qualities,
    COALESCE(a.manufacturers, ARRAY[]::text[]) AS manufacturers,
    COALESCE(a.models, ARRAY[]::text[]) AS models,
    s.required_platforms,
    s.present_platforms,
    s.active_platforms,
    s.missing_platforms,
    s.offline_platforms,
    s.source_failed_platforms,
    s.last_seen_anywhere,
    GREATEST(s.last_seen_anywhere, a.source_last_seen_at) AS inventory_last_seen_at,
    s.device_state AS compliance_state,
    CASE
        WHEN s.ignored THEN 'Ignored'
        WHEN s.needs_review THEN 'Review'
        WHEN s.is_unknown THEN 'Unknown'
        WHEN cardinality(s.present_platforms) = 0 THEN 'Unmanaged'
        WHEN s.device_state = 'Compliant' THEN 'Managed'
        WHEN cardinality(s.missing_platforms) > 0 THEN 'Missing Coverage'
        WHEN cardinality(s.offline_platforms) > 0 THEN 'Managed - Stale'
        ELSE 'Managed'
    END AS inventory_state,
    s.needs_review,
    s.review_reason,
    s.state_reason,
    s.recommended_action,
    s.ignored,
    s.s1_exempt,
    s.cross_customer_matches,
    s.evaluated_at
FROM ninja_agent_compliance.v_device_state_current s
LEFT JOIN agg a
  ON a.client_id = s.client_id
 AND a.norm_name = s.norm_name
ORDER BY s.client_name, s.hostname;

CREATE OR REPLACE VIEW ninja_inventory.v_serial_quality_current AS
SELECT
    platform,
    source_name,
    COALESCE(customer_name, 'Unresolved') AS customer_name,
    COALESCE(NULLIF(platform_customer_name, ''), 'Unknown') AS platform_customer_name,
    hostname,
    platform_device_id,
    serial_number,
    serial_quality,
    serial_quality_reason,
    manufacturer,
    model,
    os_name,
    last_seen_at
FROM ninja_inventory.v_source_observations_current
ORDER BY
    CASE serial_quality
        WHEN 'valid' THEN 3
        WHEN 'missing' THEN 1
        ELSE 0
    END,
    platform,
    customer_name,
    hostname;

CREATE OR REPLACE VIEW ninja_inventory.v_identity_conflicts_current AS
WITH src AS (
    SELECT *
    FROM ninja_inventory.v_source_observations_current
),
serial_cross_customer AS (
    SELECT
        'serial_cross_customer'::text AS conflict_type,
        serial_number AS identity_key,
        COUNT(DISTINCT customer_id) AS customer_count,
        COUNT(DISTINCT platform || ':' || COALESCE(NULLIF(platform_device_id, ''), hostname)) AS record_count,
        ARRAY_AGG(DISTINCT COALESCE(customer_name, 'Unresolved') ORDER BY COALESCE(customer_name, 'Unresolved')) AS customers,
        ARRAY_AGG(DISTINCT platform ORDER BY platform) AS platforms,
        ARRAY_AGG(DISTINCT hostname ORDER BY hostname) AS hostnames,
        MAX(last_seen_at) AS last_seen_at,
        'Same valid serial appears under multiple customers; review customer mapping or moved asset'::text AS reason
    FROM src
    WHERE serial_quality = 'valid'
      AND customer_id IS NOT NULL
    GROUP BY serial_number
    HAVING COUNT(DISTINCT customer_id) > 1
),
serial_same_platform AS (
    SELECT
        'serial_duplicate_same_platform'::text AS conflict_type,
        serial_number AS identity_key,
        COUNT(DISTINCT customer_id) AS customer_count,
        COUNT(DISTINCT platform || ':' || COALESCE(NULLIF(platform_device_id, ''), hostname)) AS record_count,
        ARRAY_AGG(DISTINCT COALESCE(customer_name, 'Unresolved') ORDER BY COALESCE(customer_name, 'Unresolved')) AS customers,
        ARRAY_AGG(DISTINCT platform ORDER BY platform) AS platforms,
        ARRAY_AGG(DISTINCT hostname ORDER BY hostname) AS hostnames,
        MAX(last_seen_at) AS last_seen_at,
        'Same valid serial appears more than once in one platform/customer; review stale duplicate or re-enrollment'::text AS reason
    FROM src
    WHERE serial_quality = 'valid'
      AND customer_id IS NOT NULL
    GROUP BY customer_id, platform, serial_number
    HAVING COUNT(DISTINCT COALESCE(NULLIF(platform_device_id, ''), hostname)) > 1
),
hostname_cross_customer AS (
    SELECT
        'hostname_cross_customer'::text AS conflict_type,
        norm_name AS identity_key,
        COUNT(DISTINCT customer_id) AS customer_count,
        COUNT(DISTINCT platform || ':' || COALESCE(NULLIF(platform_device_id, ''), hostname)) AS record_count,
        ARRAY_AGG(DISTINCT COALESCE(customer_name, 'Unresolved') ORDER BY COALESCE(customer_name, 'Unresolved')) AS customers,
        ARRAY_AGG(DISTINCT platform ORDER BY platform) AS platforms,
        ARRAY_AGG(DISTINCT hostname ORDER BY hostname) AS hostnames,
        MAX(last_seen_at) AS last_seen_at,
        'Same normalized hostname appears under multiple customers; do not merge without review'::text AS reason
    FROM src
    WHERE customer_id IS NOT NULL
      AND norm_name IS NOT NULL
      AND norm_name <> ''
    GROUP BY norm_name
    HAVING COUNT(DISTINCT customer_id) > 1
),
platform_id_cross_customer AS (
    SELECT
        'platform_device_customer_conflict'::text AS conflict_type,
        platform || ':' || platform_device_id AS identity_key,
        COUNT(DISTINCT customer_id) AS customer_count,
        COUNT(DISTINCT platform || ':' || platform_device_id) AS record_count,
        ARRAY_AGG(DISTINCT COALESCE(customer_name, 'Unresolved') ORDER BY COALESCE(customer_name, 'Unresolved')) AS customers,
        ARRAY_AGG(DISTINCT platform ORDER BY platform) AS platforms,
        ARRAY_AGG(DISTINCT hostname ORDER BY hostname) AS hostnames,
        MAX(last_seen_at) AS last_seen_at,
        'Native platform device ID is associated with multiple customers; review platform-customer mapping'::text AS reason
    FROM src
    WHERE customer_id IS NOT NULL
      AND COALESCE(NULLIF(platform_device_id, ''), '') <> ''
    GROUP BY platform, platform_device_id
    HAVING COUNT(DISTINCT customer_id) > 1
)
SELECT * FROM serial_cross_customer
UNION ALL
SELECT * FROM serial_same_platform
UNION ALL
SELECT * FROM hostname_cross_customer
UNION ALL
SELECT * FROM platform_id_cross_customer
ORDER BY
    CASE conflict_type
        WHEN 'platform_device_customer_conflict' THEN 0
        WHEN 'serial_cross_customer' THEN 1
        WHEN 'serial_duplicate_same_platform' THEN 2
        ELSE 3
    END,
    customer_count DESC,
    record_count DESC,
    identity_key;

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
)
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
ORDER BY customer_name, serial_number;

CREATE OR REPLACE VIEW ninja_inventory.v_inventory_summary_current AS
SELECT 'Resolved devices'::text AS metric, COUNT(*)::bigint AS value
FROM ninja_inventory.v_devices_current
UNION ALL
SELECT 'Managed devices', COUNT(*)::bigint
FROM ninja_inventory.v_devices_current
WHERE inventory_state LIKE 'Managed%'
UNION ALL
SELECT 'Missing coverage', COUNT(*)::bigint
FROM ninja_inventory.v_devices_current
WHERE inventory_state = 'Missing Coverage'
UNION ALL
SELECT 'Unresolved source records', COUNT(*)::bigint
FROM ninja_inventory.v_unresolved_source_records_current
UNION ALL
SELECT 'Identity conflicts', COUNT(*)::bigint
FROM ninja_inventory.v_identity_conflicts_current
UNION ALL
SELECT 'Merge candidates', COUNT(*)::bigint
FROM ninja_inventory.v_merge_candidates_current
UNION ALL
SELECT 'Missing serial records', COUNT(*)::bigint
FROM ninja_inventory.v_serial_quality_current
WHERE serial_quality = 'missing'
UNION ALL
SELECT 'Invalid serial records', COUNT(*)::bigint
FROM ninja_inventory.v_serial_quality_current
WHERE serial_quality LIKE 'invalid%';
