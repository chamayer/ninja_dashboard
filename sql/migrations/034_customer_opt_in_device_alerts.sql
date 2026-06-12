-- Device alerts are customer opt-in.
--
-- Global device-alert rules made sense for initial plumbing, but MSP
-- rollout needs controlled alerting: turn alerts on per customer from
-- the dashboard. Source/system alerts are intentionally not changed.

UPDATE ninja_agent_compliance.alert_rules
SET enabled = false,
    updated_at = now(),
    updated_by = 'migration_034_customer_opt_in'
WHERE client_id IS NULL
  AND finding_type IN (
      'missing_required_platform',
      'stale_required_platform',
      'cross_client_conflict'
  );
