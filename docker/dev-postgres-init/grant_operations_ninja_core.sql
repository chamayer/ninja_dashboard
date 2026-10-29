-- Local development only. Run after ingest creates ninja_core so the
-- Operations runtime role can read Ninja reference data on fresh databases.
GRANT USAGE ON SCHEMA ninja_core TO operations_app;
GRANT SELECT ON ALL TABLES IN SCHEMA ninja_core TO operations_app;
ALTER DEFAULT PRIVILEGES FOR ROLE ninja_dev IN SCHEMA ninja_core
    GRANT SELECT ON TABLES TO operations_app;
