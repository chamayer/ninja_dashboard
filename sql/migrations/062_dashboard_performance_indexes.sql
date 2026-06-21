-- Dashboard performance indexes for compliance/inventory shared observation paths.

CREATE INDEX IF NOT EXISTS platform_observations_current_source_device_idx
ON ninja_agent_compliance.platform_observations (
    platform,
    source_id,
    (COALESCE(NULLIF(platform_device_id, ''), hostname)),
    observed_at DESC,
    observation_id DESC
);

CREATE INDEX IF NOT EXISTS platform_observations_customer_device_id_idx
ON ninja_agent_compliance.platform_observations (
    resolved_client_id,
    platform,
    platform_device_id,
    observed_at DESC
)
WHERE platform_device_id IS NOT NULL
  AND platform_device_id <> ''
  AND resolved_client_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS platform_observations_customer_norm_latest_idx
ON ninja_agent_compliance.platform_observations (
    resolved_client_id,
    norm_name,
    platform,
    observed_at DESC
)
WHERE resolved_client_id IS NOT NULL
  AND norm_name IS NOT NULL;

CREATE INDEX IF NOT EXISTS platform_observations_serial_number_raw_idx
ON ninja_agent_compliance.platform_observations (
    (lower(NULLIF(btrim(COALESCE(
        raw_data #>> '{system,serialNumber}',
        raw_data ->> 'serialNumber',
        raw_data ->> 'serial_number',
        raw_data ->> 'serial'
    )), '')))
)
WHERE COALESCE(
        raw_data #>> '{system,serialNumber}',
        raw_data ->> 'serialNumber',
        raw_data ->> 'serial_number',
        raw_data ->> 'serial'
    ) IS NOT NULL;
