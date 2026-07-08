"""Migration 0017 — seed Ninja source binding + migrate AC config to operations.

Three steps:

1. Seeds Ninja RMM SourceInstance (id=10) and SourceBinding (id=11).
   Fixes the FK gap that would cause software.py to fail when software
   ingest starts writing entity_observations for Ninja.

2. Migrates ninja_agent_compliance.platform_requirements →
   operations.coverage_requirements, expanding the required_platforms
   array into one CoverageRequirement per platform per rule.
   Ninja is included as entity_type='agent.rmm' — not skipped — making
   device liveness detection generic and source-agnostic.
   Severity is pulled from alert_rules for the matching platform.

3. Migrates ninja_agent_compliance.notification_routes →
   operations.notification_routes (webhook/email). Zendesk routes map
   to webhook channel; review_digest is skipped (Metabase handles it).
"""

from __future__ import annotations

import uuid

from django.db import migrations

NINJA_SOURCE_INSTANCE_ID = uuid.UUID("00000000-0000-4000-8000-000000000010")
NINJA_SOURCE_BINDING_ID  = uuid.UUID("00000000-0000-4000-8000-000000000011")
INTERNAL_COLLECTOR_INSTANCE_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")

# Platform → entity_type mapping. Every required platform, including Ninja,
# is treated as an observable agent type — no special-casing.
_PLATFORM_ENTITY_TYPE = {
    "Ninja":         "agent.rmm",
    "SentinelOne":   "agent.edr",
    "ScreenConnect": "agent.remote_access",
    "LogMeIn":       "agent.remote_access",
}

# Fallback severity per platform if alert_rules has no match.
_PLATFORM_SEVERITY_DEFAULT = {
    "Ninja":         "critical",
    "SentinelOne":   "critical",
    "ScreenConnect": "high",
    "LogMeIn":       "high",
}

# Zendesk routes → webhook (Operations NotificationRoute has no Zendesk channel).
# review_digest is an analytical Metabase hook — skip it here.
_ROUTE_CHANNEL_MAP = {
    "webhook": "webhook",
    "email":   "email",
    "zendesk": "webhook",
}
_SKIP_ROUTE_KEYS = {"review_digest"}


def migrate_ac_config(apps, schema_editor):
    from django.db import connection

    Tenant             = apps.get_model("operations", "Tenant")
    Source             = apps.get_model("operations", "Source")
    CollectorInstance  = apps.get_model("operations", "CollectorInstance")
    SourceInstance     = apps.get_model("operations", "SourceInstance")
    SourceBinding      = apps.get_model("operations", "SourceBinding")
    Client             = apps.get_model("operations", "Client")
    CoverageRequirement = apps.get_model("operations", "CoverageRequirement")
    NotificationRoute  = apps.get_model("operations", "NotificationRoute")

    tenant            = Tenant.objects.get(id=1)
    internal_collector = CollectorInstance.objects.get(id=INTERNAL_COLLECTOR_INSTANCE_ID)

    # ── 1. Seed Ninja source binding ─────────────────────────────────
    ninja_source, _ = Source.objects.update_or_create(
        name="Ninja",
        defaults={"kind": "rmm", "capabilities": {"scope": "tenant", "implemented": True}},
    )
    ninja_instance, _ = SourceInstance.objects.update_or_create(
        id=NINJA_SOURCE_INSTANCE_ID,
        defaults={
            "tenant":   tenant,
            "source":   ninja_source,
            "client":   None,
            "config":   {"scope": "tenant"},
            "enabled":  True,
        },
    )
    SourceBinding.objects.update_or_create(
        id=NINJA_SOURCE_BINDING_ID,
        defaults={
            "tenant":              tenant,
            "source_instance":     ninja_instance,
            "collector_instance":  internal_collector,
            "schedule":            "",
            "enabled":             True,
        },
    )

    # ── 2. Build AC client_id → operations Client map ────────────────
    client_map: dict[int, object] = {}
    with connection.cursor() as cur:
        cur.execute("SELECT client_id, client_name FROM ninja_agent_compliance.clients")
        for ac_id, ac_name in cur.fetchall():
            try:
                client_map[ac_id] = Client.objects.get(tenant_id=1, display_name=ac_name)
            except Client.DoesNotExist:
                pass  # unmapped AC client — skip per-client overrides

    # ── 3. Build platform severity from alert_rules ───────────────────
    platform_severity: dict[str, str] = dict(_PLATFORM_SEVERITY_DEFAULT)
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT affected_platform, severity
            FROM ninja_agent_compliance.alert_rules
            WHERE finding_type = 'missing_required_platform'
              AND affected_platform IS NOT NULL
            """
        )
        for platform, severity in cur.fetchall():
            platform_severity[platform] = severity

    # ── 4. Migrate platform_requirements → coverage_requirements ──────
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT client_id, device_scope, required_platforms,
                   max_age_days, enabled
            FROM ninja_agent_compliance.platform_requirements
            ORDER BY requirement_id
            """
        )
        requirements = cur.fetchall()

    for ac_client_id, device_scope, required_platforms, max_age_days, enabled in requirements:
        ops_client = client_map.get(ac_client_id) if ac_client_id is not None else None
        gap_hours = (max_age_days or 30) * 24

        for platform in (required_platforms or []):
            entity_type = _PLATFORM_ENTITY_TYPE.get(platform)
            if not entity_type:
                continue

            severity = platform_severity.get(platform, "high")

            exists = CoverageRequirement.objects.filter(
                tenant_id=1,
                client=ops_client,
                entity_type=entity_type,
                platform=platform,
                device_scope=device_scope,
            ).exists()
            if exists:
                continue

            CoverageRequirement.objects.create(
                tenant_id=1,
                client=ops_client,
                entity_type=entity_type,
                platform=platform,
                device_scope=device_scope,
                severity=severity,
                gap_after_hours=gap_hours,
                confidence_probable=gap_hours * 2,
                confidence_confirmed=gap_hours * 3,
                enabled=enabled,
            )

    # ── 5. Migrate notification_routes ────────────────────────────────
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT route_key, route_type, display_name, target_ref, enabled
            FROM ninja_agent_compliance.notification_routes
            ORDER BY route_id
            """
        )
        routes = cur.fetchall()

    for route_key, route_type, display_name, target_ref, route_enabled in routes:
        if route_key in _SKIP_ROUTE_KEYS:
            continue
        channel = _ROUTE_CHANNEL_MAP.get(route_type, "webhook")
        target  = target_ref or route_key
        if NotificationRoute.objects.filter(tenant_id=1, target=target).exists():
            continue
        NotificationRoute.objects.create(
            tenant_id=1,
            client=None,
            finding_type=None,
            severity_min="info",
            channel=channel,
            target=target,
            mode="immediate",
        )


def reverse_ac_migration(apps, schema_editor):
    SourceBinding      = apps.get_model("operations", "SourceBinding")
    SourceInstance     = apps.get_model("operations", "SourceInstance")
    CoverageRequirement = apps.get_model("operations", "CoverageRequirement")
    NotificationRoute  = apps.get_model("operations", "NotificationRoute")

    SourceBinding.objects.filter(id=NINJA_SOURCE_BINDING_ID).delete()
    SourceInstance.objects.filter(id=NINJA_SOURCE_INSTANCE_ID).delete()
    CoverageRequirement.objects.filter(tenant_id=1).delete()
    NotificationRoute.objects.filter(tenant_id=1).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0016_agent_presence_current"),
    ]

    operations = [
        migrations.RunPython(migrate_ac_config, reverse_ac_migration),
    ]
