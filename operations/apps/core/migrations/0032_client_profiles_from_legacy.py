"""Migration 0032 — legacy platform_requirements → per-client RequirementProfile.

Restores the legacy "declared policy = complete list of requirements" semantic
that migration 0017's array-to-rows expansion lost. Per BLUEPRINT C.6:

* For each client with a row in `ninja_agent_compliance.platform_requirements`,
  create a per-client `RequirementProfile` (name = "<client> policy"), populate
  its items from the `required_platforms` array per (device_scope), and set
  `Client.requirement_profile`.
* A.M. Rose (legacy required_platforms={}) gets a profile with ZERO items —
  the tenant explicitly declared "nothing required."
* Client-scoped `CoverageRequirement` rows (materialized artifacts from
  migration 0017 + C3c accept) are removed; the profile becomes the single
  source of truth. Global (client_id NULL) coverage_requirements stay as the
  fallback for clients without a profile.
"""

from __future__ import annotations

import uuid

from django.db import connection, migrations


_PLATFORM_ENTITY_TYPE = {
    "Ninja": "agent.rmm",
    "SentinelOne": "agent.edr",
    "LogMeIn": "agent.remote_access",
    "ScreenConnect": "agent.remote_access",
}


def migrate_to_profiles(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    RequirementProfile = apps.get_model("operations", "RequirementProfile")
    RequirementProfileItem = apps.get_model("operations", "RequirementProfileItem")
    Client = apps.get_model("operations", "Client")
    CoverageRequirement = apps.get_model("operations", "CoverageRequirement")

    with connection.cursor() as cur:
        cur.execute("SELECT to_regclass('ninja_agent_compliance.platform_requirements')")
        if not cur.fetchone()[0]:
            return

        # Legacy per-client rows.
        cur.execute(
            """
            SELECT client_id, device_scope, required_platforms
            FROM ninja_agent_compliance.platform_requirements
            WHERE enabled AND client_id IS NOT NULL
            """
        )
        legacy_rules = cur.fetchall()

        cur.execute("SELECT client_id, client_name FROM ninja_agent_compliance.clients")
        legacy_names = {row[0]: row[1] for row in cur.fetchall()}

        # Severity + gap defaults come from current global coverage_requirements
        # so migrated items keep whatever policy the operator had in place.
        cur.execute(
            """
            SELECT platform, severity, gap_after_hours,
                   confidence_probable, confidence_confirmed
            FROM operations.coverage_requirements
            WHERE tenant_id=1 AND client_id IS NULL AND enabled
            """
        )
        global_defaults = {row[0]: row for row in cur.fetchall()}

    # Group legacy rules by client.
    by_client: dict[int, list[tuple]] = {}
    for ac_client_id, scope, plats in legacy_rules:
        by_client.setdefault(ac_client_id, []).append((scope, list(plats)))

    _fallback = (None, "high", 24, 48, 168)

    for ac_client_id, rules in by_client.items():
        client_name = legacy_names.get(ac_client_id)
        if not client_name:
            continue
        client = Client.objects.filter(
            tenant_id=1, display_name=client_name, deleted_at__isnull=True,
        ).first()
        if client is None:
            continue

        profile_name = f"{client_name} policy"
        profile, _ = RequirementProfile.objects.get_or_create(
            tenant_id=1, name=profile_name,
            defaults={
                "id": uuid.uuid4(),
                "description": f"Migrated from legacy platform_requirements for {client_name}",
                "is_tenant_default": False,
            },
        )
        # Reset items so re-running the migration is idempotent.
        profile.items.all().delete()

        for scope, platforms in rules:
            for platform in platforms:
                entity_type = _PLATFORM_ENTITY_TYPE.get(platform)
                if not entity_type:
                    continue
                defaults = global_defaults.get(platform, _fallback)
                RequirementProfileItem.objects.create(
                    id=uuid.uuid4(),
                    tenant_id=1,
                    profile=profile,
                    entity_type=entity_type,
                    platform=platform,
                    device_scope=scope,
                    severity=defaults[1],
                    gap_after_hours=defaults[2],
                    confidence_probable=defaults[3],
                    confidence_confirmed=defaults[4],
                )
            # Empty required_platforms array (e.g. A.M. Rose) writes NO items.
            # An empty tier is a valid declaration — evaluator honors it.

        client.requirement_profile = profile
        client.save(update_fields=["requirement_profile"])

    # Client-scoped CoverageRequirement rows are now redundant — profile is
    # source of truth. Global rows (client_id NULL) remain for the fallback
    # (clients without a profile use them via the evaluator).
    CoverageRequirement.objects.filter(
        tenant_id=1, client__isnull=False,
    ).delete()


def reverse_migrate(apps, schema_editor):
    Client = apps.get_model("operations", "Client")
    RequirementProfile = apps.get_model("operations", "RequirementProfile")
    Client.objects.filter(
        tenant_id=1,
        requirement_profile__name__endswith=" policy",
    ).update(requirement_profile=None)
    RequirementProfile.objects.filter(
        tenant_id=1,
        name__endswith=" policy",
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0031_dispatcher_rules_seed"),
    ]

    operations = [
        migrations.RunPython(migrate_to_profiles, reverse_migrate),
    ]
