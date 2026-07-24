-- =============================================================================
-- 071_device_patch_activity_grants.sql
-- Follow-up to 070: grant SELECT on ninja_patches.device_patch_activity to the
-- three roles that already read every other ninja_patches matview
-- (operations_app, operations_readonly, metabase_ro). Without these grants
-- the Operations request that reads the matview fails with
-- InsufficientPrivilege.
-- =============================================================================

GRANT SELECT ON ninja_patches.device_patch_activity TO operations_app;
GRANT SELECT ON ninja_patches.device_patch_activity TO operations_readonly;
GRANT SELECT ON ninja_patches.device_patch_activity TO metabase_ro;
