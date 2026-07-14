"""Migration 0031 — Track 2 (P2) dispatcher rules seed.

* Adds 'zendesk' to NotificationRoute.Channel (state + DB CHECK not
  enforced since Django doesn't emit constraints for TextChoices).
* Seeds NotificationRule rows (disabled) from legacy
  ninja_agent_compliance.alert_rules so the operator can review + enable
  them per finding_type.

Rules are created disabled so no traffic fires until an operator flips
them per BLUEPRINT Track 2.2 spec.
"""

from __future__ import annotations

import uuid

from django.db import connection, migrations, models


def seed_rules_from_legacy(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    NotificationRule = apps.get_model("operations", "NotificationRule")
    NotificationRoute = apps.get_model("operations", "NotificationRoute")
    FindingType = apps.get_model("operations", "FindingType")
    Client = apps.get_model("operations", "Client")

    with connection.cursor() as cur:
        cur.execute("SELECT to_regclass('ninja_agent_compliance.alert_rules')")
        if not cur.fetchone()[0]:
            return
        cur.execute(
            """
            SELECT r.finding_type, r.affected_platform, r.client_id,
                   r.device_scope, r.cooldown_hours, r.route_id
            FROM ninja_agent_compliance.alert_rules r
            WHERE r.enabled
            """
        )
        legacy_rules = cur.fetchall()
        cur.execute(
            """
            SELECT client_id, client_name FROM ninja_agent_compliance.clients
            """
        )
        legacy_clients = {row[0]: row[1] for row in cur.fetchall()}

    if not legacy_rules:
        return

    default_route = NotificationRoute.objects.filter(tenant_id=1).first()

    imported = 0
    for finding_type, platform, ac_client_id, device_scope, cooldown, _route_id in legacy_rules:
        try:
            ft = FindingType.objects.get(name=finding_type)
        except FindingType.DoesNotExist:
            continue

        client_obj = None
        if ac_client_id and ac_client_id in legacy_clients:
            client_obj = Client.objects.filter(
                tenant_id=1, display_name=legacy_clients[ac_client_id],
            ).first()

        match_criteria = {}
        if platform:
            match_criteria["platform"] = platform
        if device_scope and device_scope != "all":
            match_criteria["device_scope"] = device_scope

        NotificationRule.objects.get_or_create(
            tenant_id=1,
            finding_type=ft,
            client=client_obj,
            match_criteria=match_criteria,
            defaults={
                "id": uuid.uuid4(),
                "route": default_route,
                "cooldown_hours": cooldown or 24,
                "enabled": False,
            },
        )
        imported += 1


def unseed_rules(apps, schema_editor):
    NotificationRule = apps.get_model("operations", "NotificationRule")
    NotificationRule.objects.filter(tenant_id=1, enabled=False).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0030_coveragerequirement_version_state"),
    ]

    operations = [
        migrations.AlterField(
            model_name="notificationroute",
            name="channel",
            field=models.CharField(
                choices=[
                    ("email", "Email"),
                    ("slack", "Slack"),
                    ("teams", "Teams"),
                    ("webhook", "Webhook"),
                    ("zendesk", "Zendesk"),
                ],
                max_length=16,
            ),
        ),
        # Sync model state to existing DB `version` columns (same class of
        # drift as CoverageRequirement in 0030). No DB change needed.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="adminfinding",
                    name="version",
                    field=models.PositiveIntegerField(default=1),
                ),
                migrations.AddField(
                    model_name="identitycandidate",
                    name="version",
                    field=models.PositiveIntegerField(default=1),
                ),
                migrations.AddField(
                    model_name="notificationrule",
                    name="version",
                    field=models.PositiveIntegerField(default=1),
                ),
            ],
            database_operations=[],
        ),
        migrations.RunPython(seed_rules_from_legacy, unseed_rules),
    ]
