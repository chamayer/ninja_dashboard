-- Seed a `review_digest` notification route so the daily Review
-- digest job has somewhere to deliver. Disabled by default — turn on
-- in the Setup dashboard once the matching env var
-- (AGENT_COMPLIANCE_REVIEW_DIGEST_WEBHOOK_URL) is set on the host.

INSERT INTO ninja_agent_compliance.notification_routes
    (route_key, route_type, display_name, target_ref, config, enabled)
VALUES
    ('review_digest', 'webhook', 'Review digest',
     'AGENT_COMPLIANCE_REVIEW_DIGEST_WEBHOOK_URL', '{}'::jsonb, false)
ON CONFLICT (route_key) DO NOTHING;
