-- Speed up Triage "Message Contains" searches over patch activity text.
-- The dashboard uses substring ILIKE filters for operators looking for
-- repeated error wording across many devices.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS activities_message_trgm_idx
ON ninja_activities.activities
USING gin (message gin_trgm_ops)
WHERE message IS NOT NULL;

CREATE INDEX IF NOT EXISTS activities_type_time_device_idx
ON ninja_activities.activities (activity_type, activity_time DESC, device_id);
