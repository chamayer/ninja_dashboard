"""Migration 0118 — os_name -> os_family becomes data.

Per ADR-0012 §6 a domain mapping is operator-maintainable data, not a
constant. This taxonomy was hardcoded twice and the copies had drifted:

  - `_OS_FAMILY_PATTERNS` in `ingest/normalize.py` matched macOS versions by
    substring; the SQL CASE ladder in migration 0023 matched by prefix.
  - The SQL copy was missing the `darwin` pattern entirely.

Both are replaced by `operations.os_family_mappings`, mirroring the existing
`os_group_mappings` shape (pattern / value / priority, first match wins).

Behaviour change, deliberate: the function now returns NULL rather than
'Unknown' for a NULL or empty os_name. 'Unknown' was our fallback presented as
a value, and when it reached the claim layer it won authority for 488 devices
whose real family was known. Both live SQL callers already guard NULL
(`ingest/core/devices.py`), so no caller observes the change.

The seeded patterns reproduce the union of the two previous copies exactly,
using the Python substring semantics as authoritative since that copy fed the
claim pipeline.
"""

from typing import ClassVar

from django.db import migrations, models

# (pattern, os_family) in priority order — first match wins.
# Ported verbatim from _OS_FAMILY_PATTERNS, with `%...%` LIKE semantics
# matching the Python `needle in value.lower()` test it replaces.
_SEED: tuple[tuple[str, str], ...] = (
    ("%windows server 2025%", "Windows Server 2025"),
    ("%windows server 2022%", "Windows Server 2022"),
    ("%windows server 2019%", "Windows Server 2019"),
    ("%windows server 2016%", "Windows Server 2016"),
    ("%windows server 2012 r2%", "Windows Server 2012 R2"),
    ("%windows server 2012%", "Windows Server 2012"),
    ("%windows server 2008 r2%", "Windows Server 2008 R2"),
    ("%windows server 2008%", "Windows Server 2008"),
    ("%windows server%", "Windows Server (other)"),
    ("%windows 11%", "Windows 11"),
    ("%windows 10%", "Windows 10"),
    ("%windows 8.1%", "Windows 8.1"),
    ("%windows 8%", "Windows 8"),
    ("%windows 7%", "Windows 7"),
    ("%windows%", "Windows (other)"),
    ("%macos 26%", "macOS 26"),
    ("%macos 15%", "macOS 15"),
    ("%macos 14%", "macOS 14"),
    ("%macos 13%", "macOS 13"),
    ("%macos 12%", "macOS 12"),
    ("%macos 11%", "macOS 11"),
    ("%macos 10%", "macOS 10"),
    ("%macos%", "macOS (other)"),
    ("%os x%", "macOS (other)"),
    ("%darwin%", "macOS (other)"),
    ("%linux%", "Linux"),
    ("%ubuntu%", "Linux"),
    ("%centos%", "Linux"),
    ("%debian%", "Linux"),
    ("%red hat%", "Linux"),
)

_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION operations.os_family(os_name text)
RETURNS text
LANGUAGE sql
STABLE
AS $$
    SELECT CASE
        WHEN $1 IS NULL OR btrim($1) = '' THEN NULL
        ELSE COALESCE(
            (SELECT m.os_family
               FROM operations.os_family_mappings m
              WHERE $1 ILIKE m.pattern
              ORDER BY m.priority, m.id
              LIMIT 1),
            'Other'
        )
    END
$$;
"""

# Restores the 0023 definition so a downgrade is not left without a function.
_FUNCTION_REVERSE_SQL = """
CREATE OR REPLACE FUNCTION operations.os_family(os_name text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT CASE
        WHEN $1 IS NULL OR $1 = '' THEN 'Unknown'
        WHEN $1 ILIKE '%Windows Server 2025%' THEN 'Windows Server 2025'
        WHEN $1 ILIKE '%Windows Server 2022%' THEN 'Windows Server 2022'
        WHEN $1 ILIKE '%Windows Server 2019%' THEN 'Windows Server 2019'
        WHEN $1 ILIKE '%Windows Server 2016%' THEN 'Windows Server 2016'
        WHEN $1 ILIKE '%Windows Server 2012 R2%' THEN 'Windows Server 2012 R2'
        WHEN $1 ILIKE '%Windows Server 2012%' THEN 'Windows Server 2012'
        WHEN $1 ILIKE '%Windows Server 2008 R2%' THEN 'Windows Server 2008 R2'
        WHEN $1 ILIKE '%Windows Server 2008%' THEN 'Windows Server 2008'
        WHEN $1 ILIKE '%Windows Server%' THEN 'Windows Server (other)'
        WHEN $1 ILIKE '%Windows 11%' THEN 'Windows 11'
        WHEN $1 ILIKE '%Windows 10%' THEN 'Windows 10'
        WHEN $1 ILIKE '%Windows 8.1%' THEN 'Windows 8.1'
        WHEN $1 ILIKE '%Windows 8%' THEN 'Windows 8'
        WHEN $1 ILIKE '%Windows 7%' THEN 'Windows 7'
        WHEN $1 ILIKE '%Windows%' THEN 'Windows (other)'
        WHEN $1 ILIKE 'macOS 26%' THEN 'macOS 26'
        WHEN $1 ILIKE 'macOS 15%' THEN 'macOS 15'
        WHEN $1 ILIKE 'macOS 14%' THEN 'macOS 14'
        WHEN $1 ILIKE 'macOS 13%' THEN 'macOS 13'
        WHEN $1 ILIKE 'macOS 12%' THEN 'macOS 12'
        WHEN $1 ILIKE 'macOS 11%' THEN 'macOS 11'
        WHEN $1 ILIKE 'macOS 10%' THEN 'macOS 10'
        WHEN $1 ILIKE '%macOS%' OR $1 ILIKE '%OS X%' THEN 'macOS (other)'
        WHEN $1 ILIKE '%Linux%' OR $1 ILIKE '%Ubuntu%' THEN 'Linux'
        ELSE 'Other'
    END
$$;
"""

_GRANT_SQL = """
GRANT SELECT ON operations.os_family_mappings
    TO operations_app, ninja_ingest, operations_readonly, metabase_ro;
"""

_GRANT_REVERSE_SQL = """
REVOKE SELECT ON operations.os_family_mappings
    FROM operations_app, ninja_ingest, operations_readonly, metabase_ro;
"""


def _seed(apps, schema_editor):
    Mapping = apps.get_model("operations", "OsFamilyMapping")
    Mapping.objects.bulk_create(
        [
            Mapping(pattern=p, os_family=f, priority=(i + 1) * 10)
            for i, (p, f) in enumerate(_SEED)
        ]
    )


def _unseed(apps, schema_editor):
    apps.get_model("operations", "OsFamilyMapping").objects.all().delete()


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0117_audited_restricted_evidence_reveal"),
    ]

    operations: ClassVar[list] = [
        migrations.CreateModel(
            name="OsFamilyMapping",
            fields=[
                ("id", models.SmallAutoField(primary_key=True, serialize=False)),
                ("pattern", models.CharField(max_length=120)),
                ("os_family", models.CharField(max_length=40)),
                ("priority", models.PositiveIntegerField(default=100)),
            ],
            options={
                "db_table": "os_family_mappings",
                "ordering": ("priority", "pattern"),
            },
        ),
        migrations.RunPython(_seed, _unseed),
        migrations.RunSQL(_GRANT_SQL, _GRANT_REVERSE_SQL),
        migrations.RunSQL(_FUNCTION_SQL, _FUNCTION_REVERSE_SQL),
    ]
