-- 117: drop the frozen legacy Ninja snapshot tables (PLAN-022 A2).
--
-- The generic observation store replaced them in 0.103.0 (ADR 0010). Nothing
-- has written either table since 2026-08-03, and their only readers were the
-- one-off backfill and restoration tools, removed in the same change. They
-- held about 21.4 GB. Both were exported with pg_dump before this migration
-- (archive location recorded in PLAN-022). No view or foreign key depends on
-- them. PLAN-022 lifts ADR 0010's bar on deleting legacy snapshots.

DROP TABLE IF EXISTS ninja_core.device_snapshots;
DROP TABLE IF EXISTS ninja_core.device_health_snapshots;
