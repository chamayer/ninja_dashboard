"""Migration 0023 — Track 1 evaluator parity groundwork (BLUEPRINT.md).

1. devices.device_role ('server'/'workstation'/'unknown') — set from
   explicit source signals only (node_class, S1 machineType, OS name),
   never guessed. 'unknown' means no source has identified the role;
   such devices still get coverage-evaluated under the client defaults —
   role only matters when a requirement scopes device_scope.

2. devices.os_name / os_family — full OS string plus the abbreviated
   family (legacy taxonomy from sql/migrations/051), for aggregation
   and filtering. operations.os_family(text) mirrors
   ingest.normalize.os_family for set-based SQL updates.

3. devices.exemptions JSONB {entity_type: reason} — evaluator skips
   requirements whose entity_type is present (legacy NO AV exemption).

4. Seeds finding types: stale_required_platform, source_failure (admin),
   cross_client_conflict, device_role_conflict.

5. Backfills device_role/os_name/os_family + exemptions from ninja_core
   (same signals as ingest.core.devices._sync_operations_device_roles
   and the legacy NO AV tag/policy detection).

6. Grants ninja_ingest the DML it needs for device promotion and
   finding upserts.
"""

from __future__ import annotations

from django.db import migrations, models

_FINDING_TYPES = (
    # (name, finding_class, default_severity, description)
    ("stale_required_platform", "entity", "medium",
     "Required platform has observed the device before but not recently."),
    ("source_failure", "admin", "high",
     "A source collector's latest run failed or is overdue; its platform "
     "is skipped for coverage evaluation this cycle."),
    ("cross_client_conflict", "entity", "medium",
     "The same hostname resolves to devices under different clients."),
    ("device_role_conflict", "entity", "low",
     "Sources disagree on whether the device is a server or a "
     "workstation."),
)

_OS_FAMILY_FN = """
CREATE OR REPLACE FUNCTION operations.os_family(os_name text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $fn$
    SELECT CASE
        WHEN os_name IS NULL OR os_name = '' THEN 'Unknown'
        WHEN os_name ILIKE '%Windows Server 2025%' THEN 'Windows Server 2025'
        WHEN os_name ILIKE '%Windows Server 2022%' THEN 'Windows Server 2022'
        WHEN os_name ILIKE '%Windows Server 2019%' THEN 'Windows Server 2019'
        WHEN os_name ILIKE '%Windows Server 2016%' THEN 'Windows Server 2016'
        WHEN os_name ILIKE '%Windows Server 2012 R2%' THEN 'Windows Server 2012 R2'
        WHEN os_name ILIKE '%Windows Server 2012%' THEN 'Windows Server 2012'
        WHEN os_name ILIKE '%Windows Server 2008 R2%' THEN 'Windows Server 2008 R2'
        WHEN os_name ILIKE '%Windows Server 2008%' THEN 'Windows Server 2008'
        WHEN os_name ILIKE '%Windows Server%' THEN 'Windows Server (other)'
        WHEN os_name ILIKE '%Windows 11%' THEN 'Windows 11'
        WHEN os_name ILIKE '%Windows 10%' THEN 'Windows 10'
        WHEN os_name ILIKE '%Windows 8.1%' THEN 'Windows 8.1'
        WHEN os_name ILIKE '%Windows 8%' THEN 'Windows 8'
        WHEN os_name ILIKE '%Windows 7%' THEN 'Windows 7'
        WHEN os_name ILIKE '%Windows%' THEN 'Windows (other)'
        WHEN os_name ILIKE 'macOS 26%' THEN 'macOS 26'
        WHEN os_name ILIKE 'macOS 15%' THEN 'macOS 15'
        WHEN os_name ILIKE 'macOS 14%' THEN 'macOS 14'
        WHEN os_name ILIKE 'macOS 13%' THEN 'macOS 13'
        WHEN os_name ILIKE 'macOS 12%' THEN 'macOS 12'
        WHEN os_name ILIKE 'macOS 11%' THEN 'macOS 11'
        WHEN os_name ILIKE 'macOS 10%' THEN 'macOS 10'
        WHEN os_name ILIKE '%macOS%' OR os_name ILIKE '%OS X%'
          OR os_name ILIKE '%Darwin%' THEN 'macOS (other)'
        WHEN os_name ILIKE '%Linux%' OR os_name ILIKE '%Ubuntu%'
          OR os_name ILIKE '%CentOS%' OR os_name ILIKE '%Debian%'
          OR os_name ILIKE '%Red Hat%' THEN 'Linux'
        ELSE 'Other'
    END
$fn$;
"""


def seed_finding_types(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    for name, finding_class, severity, description in _FINDING_TYPES:
        FindingType.objects.get_or_create(
            name=name,
            defaults={
                "finding_class": finding_class,
                "default_severity": severity,
                "source_module": "platform.evaluator",
                "auto_resolvable": True,
                "description": description,
            },
        )


def unseed_finding_types(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    FindingType.objects.filter(
        name__in=[t[0] for t in _FINDING_TYPES]
    ).delete()


def create_os_family_fn(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(_OS_FAMILY_FN)


def drop_os_family_fn(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("DROP FUNCTION IF EXISTS operations.os_family(text)")


def backfill_device_role(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute("SELECT to_regclass('ninja_core.devices')")
        if cur.fetchone()[0] is None:
            return

    schema_editor.execute(
        """
        UPDATE operations.devices d
        SET device_role = CASE
                WHEN UPPER(nd.node_class) LIKE '%%SERVER%%' THEN 'server'
                WHEN UPPER(nd.node_class) LIKE '%%WORKSTATION%%' THEN 'workstation'
                WHEN UPPER(nd.node_class) = 'MAC' THEN 'workstation'
                WHEN LOWER(COALESCE(nd.os_name, '')) LIKE '%%server%%' THEN 'server'
                WHEN LOWER(COALESCE(nd.os_name, '')) LIKE '%%windows%%' THEN 'workstation'
                WHEN LOWER(COALESCE(nd.os_name, '')) LIKE '%%macos%%'
                  OR LOWER(COALESCE(nd.os_name, '')) LIKE '%%os x%%' THEN 'workstation'
                ELSE d.device_role
            END,
            os_name   = COALESCE(nd.os_name, d.os_name),
            os_family = CASE
                WHEN nd.os_name IS NULL THEN d.os_family
                ELSE operations.os_family(nd.os_name)
            END,
            exemptions = CASE
                WHEN (nd.data -> 'tags')::text ILIKE '%%no av%%'
                  OR COALESCE(p.name, '') ILIKE '%%no av%%'
                  OR COALESCE(rp.name, '') ILIKE '%%no av%%'
                THEN d.exemptions || '{"agent.edr": "no_av_exempt"}'::jsonb
                ELSE d.exemptions
            END
        FROM operations.device_links dl
        JOIN operations.sources s ON s.id = dl.source_id AND s.name = 'Ninja'
        JOIN ninja_core.devices nd ON nd.id::text = dl.external_id
        LEFT JOIN ninja_core.policies p  ON p.id  = nd.policy_id
        LEFT JOIN ninja_core.policies rp ON rp.id = nd.role_policy_id
        WHERE dl.device_id = d.id
          AND dl.tenant_id = d.tenant_id
        """
    )


def grant_ingest_dml(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in (
        "devices", "device_links", "identity_candidates",
        "findings", "admin_findings", "run_log",
    ):
        schema_editor.execute(
            f"GRANT SELECT, INSERT, UPDATE ON operations.{table} TO ninja_ingest;"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0022_source_config_severance"),
    ]

    operations = [
        migrations.AddField(
            model_name="device",
            name="device_role",
            field=models.CharField(default="unknown", max_length=16),
        ),
        migrations.AddField(
            model_name="device",
            name="os_name",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="device",
            name="os_family",
            field=models.CharField(blank=True, default="", max_length=40),
        ),
        migrations.AddField(
            model_name="device",
            name="exemptions",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RunPython(create_os_family_fn, drop_os_family_fn),
        migrations.RunPython(seed_finding_types, unseed_finding_types),
        migrations.RunPython(backfill_device_role, migrations.RunPython.noop),
        migrations.RunPython(grant_ingest_dml, migrations.RunPython.noop),
    ]
