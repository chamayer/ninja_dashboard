-- Generic cross-customer name collisions are not an actionable finding.
-- The matrix still records `cross_client_conflict` for the debug surface
-- (`v_cross_client_conflicts` and customer/debug summary cards), and the
-- actionable case (same name missing a platform under one customer while
-- observed under another) is promoted by the device work queue. The
-- separate `cross_client_conflict` finding emission was removed from the
-- Python evaluator in v0.23.8.
--
-- Disable the matching alert rule so a route accidentally enabled on it
-- cannot fire. The rule row is left in place for clarity.

UPDATE ninja_agent_compliance.alert_rules
SET enabled = false
WHERE finding_type = 'cross_client_conflict';
