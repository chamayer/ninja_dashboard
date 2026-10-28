"""Drop the metabase_ro role (PLAN-022 B2).

Metabase was retired on 2026-10-12 (ADR 0005). The role kept its read grants
for a Metabase rollback with no end date; the user closed that window on
2026-10-28. Measured in production that day: NOLOGIN, no members, no owned
objects, and dependencies only in this database (269 relation grants, 6
default-privilege entries, 5 schema grants), so `DROP OWNED` removes every
grant and default privilege before `DROP ROLE`.

Fresh databases still create the role in 0006 because older migrations grant
to it; this migration then drops it. Migrations after this one must not name
it (enforced by test_no_metabase_ro_after_retirement).
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
DO $drop$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'metabase_ro') THEN
        EXECUTE 'DROP OWNED BY metabase_ro';
        EXECUTE 'DROP ROLE metabase_ro';
    END IF;
END
$drop$;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0358_drop_parity_report_and_legacy_job_key"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
