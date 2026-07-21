"""Migration 0062 — grant SELECT on ninja_activities to Operations roles.

Follow-up to 0059 (which granted ninja_patches). The device_detail
Activity tab merges Ninja's built-in event log
(`ninja_activities.activities`, populated by the ingest service)
into the per-device timeline. Without this grant the query raises
`InsufficientPrivilege: permission denied for schema ninja_activities`.
"""

from __future__ import annotations

from django.db import migrations


_GRANT_SQL = """
GRANT USAGE ON SCHEMA ninja_activities
    TO operations_app, operations_readonly, metabase_ro;

GRANT SELECT ON ALL TABLES IN SCHEMA ninja_activities
    TO operations_app, operations_readonly, metabase_ro;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ninja_ingest') THEN
        EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE ninja_ingest '
                'IN SCHEMA ninja_activities '
                'GRANT SELECT ON TABLES '
                'TO operations_app, operations_readonly, metabase_ro';
    END IF;
END
$$;
"""

_REVOKE_SQL = """
REVOKE SELECT ON ALL TABLES IN SCHEMA ninja_activities
    FROM operations_app, operations_readonly, metabase_ro;
REVOKE USAGE ON SCHEMA ninja_activities
    FROM operations_app, operations_readonly, metabase_ro;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0061_source_health_current"),
    ]

    operations = [
        migrations.RunSQL(_GRANT_SQL, _REVOKE_SQL),
    ]
