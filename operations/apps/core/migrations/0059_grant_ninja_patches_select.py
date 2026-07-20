"""Migration 0059 — grant SELECT on ninja_patches to Operations roles.

Hotfix. Multiple Operations views (device_detail's patch-signal
join, and the 0.73/0.74 Patch Evidence / Trends / Activity Search
pages) query `ninja_patches.*` (managed by the ingest service),
but the Operations app roles have no SELECT there. Result:
`psycopg.errors.InsufficientPrivilege: permission denied for schema
ninja_patches`.

Grants USAGE on the schema + SELECT on every present table /
matview / view + default privileges so future tables in the schema
auto-inherit SELECT.
"""

from __future__ import annotations

from django.db import migrations


_GRANT_SQL = """
GRANT USAGE ON SCHEMA ninja_patches
    TO operations_app, operations_readonly, metabase_ro;

GRANT SELECT ON ALL TABLES IN SCHEMA ninja_patches
    TO operations_app, operations_readonly, metabase_ro;

-- Default privileges so tables / matviews added later inherit SELECT
-- without needing another migration. Applied for the role that
-- typically owns objects in ninja_patches (ninja_ingest); benign if
-- the role doesn't exist yet.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ninja_ingest') THEN
        EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE ninja_ingest '
                'IN SCHEMA ninja_patches '
                'GRANT SELECT ON TABLES '
                'TO operations_app, operations_readonly, metabase_ro';
    END IF;
END
$$;
"""

_REVOKE_SQL = """
REVOKE SELECT ON ALL TABLES IN SCHEMA ninja_patches
    FROM operations_app, operations_readonly, metabase_ro;
REVOKE USAGE ON SCHEMA ninja_patches
    FROM operations_app, operations_readonly, metabase_ro;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0058_reclassify_data_quality_findings_as_entity"),
    ]

    operations = [
        migrations.RunSQL(_GRANT_SQL, _REVOKE_SQL),
    ]
