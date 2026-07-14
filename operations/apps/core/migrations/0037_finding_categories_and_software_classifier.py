"""Migration 0037 — finding categories + software classifier scaffolding.

Adds the data model + seeded data for P4 Track 3 (software findings):

  * `finding_categories` — admin-editable reference table classifying
    finding types. Backfilled with the six operational categories:
    coverage, identity, lifecycle, platform_health, data_quality,
    software. Existing FindingType rows are categorized in-place.
  * `finding_types.category_id` — nullable FK; every existing seeded
    type gets categorized by this migration.
  * `SoftwareClassifierRule` — data-driven regex patterns per rule type
    (suspicious_name / install_path_suspicious / eol_runtime). Seeded
    from the legacy `analyze_inventory` heuristics; operators can add /
    edit / disable via admin UI without a deploy.
  * `SoftwareDecision` — client becomes NULLABLE, adds a `device` FK.
    Scope tier for decisions: device > client > global.
  * 8 software finding types seeded with category='software' — matches
    Track 3 §3.1 rule list.
  * `SoftwareCatalog` seeded with av / rmm / remote_access product
    keyword lists + trusted publishers + whitelist entries (port from
    legacy analyze_inventory + metabase_bootstrap SQL cards).
"""

from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


_FINDING_CATEGORIES = [
    ("coverage",         "Required agents / platforms present per policy", 10),
    ("identity",         "Device or client identity issues (dup, drift, mismatch)", 20),
    ("lifecycle",        "Device lifecycle events (offline, retired, role changes)", 30),
    ("software",         "Software installations flagged by the classifier", 40),
    ("platform_health",  "Operations platform health (source failures, etc.)", 90),
    ("data_quality",     "Data-quality problems (unmapped fields, missing metadata)", 95),
]

# name → category
_TYPE_CATEGORY = {
    # coverage
    "missing_required_platform":  "coverage",
    "stale_required_platform":    "coverage",
    # lifecycle
    "device_offline":             "lifecycle",
    "device_long_offline":        "lifecycle",   # retained, no re-emission
    "device_stale_data":          "lifecycle",
    "device_missing_from_source": "lifecycle",
    "device_role_conflict":       "lifecycle",
    "device_unenrolled":          "lifecycle",
    # identity
    "duplicate_platform_record":  "identity",
    "cross_client_conflict":      "identity",    # retained, no re-emission
    "client_link_collision":      "identity",
    "client_name_conflict":       "identity",
    "client_unattached_group":    "identity",
    # platform_health
    "source_failure":             "platform_health",
    # data_quality
    "unmapped_node_class":        "data_quality",
    # (software findings seeded below)
}


_SOFTWARE_FINDING_TYPES = [
    ("suspicious_name",
     "high", "entity", "platform.software_findings",
     "Software name matches a suspicious-name pattern (crack/keygen/miner/etc)."),
    ("install_path_suspicious",
     "high", "entity", "platform.software_findings",
     "Software installed from an unusual location (temp / downloads / recycle / hex path)."),
    ("unauthorized_av",
     "high", "entity", "platform.software_findings",
     "Anti-virus product installed that isn't in the client's sanctioned set."),
    ("unauthorized_rmm",
     "high", "entity", "platform.software_findings",
     "RMM product installed that isn't in the client's sanctioned set."),
    ("unauthorized_remote_access",
     "high", "entity", "platform.software_findings",
     "Remote-access product installed that isn't in the client's sanctioned set."),
    ("multi_av_conflict",
     "high", "entity", "platform.software_findings",
     "Two or more anti-virus products present on one device — conflict / performance risk."),
    ("rare_recent",
     "medium", "entity", "platform.software_findings",
     "Software installed on ≤2 devices fleet-wide within the last 30 days."),
    ("eol_runtime",
     "medium", "entity", "platform.software_findings",
     "Software matches a known end-of-life runtime (unsupported, security risk)."),
]


_CLASSIFIER_RULES = [
    # suspicious_name — regex, case-insensitive at query time
    ("suspicious_name", r"\bkeygen\b", True, "Software labeled 'keygen'"),
    ("suspicious_name", r"\bcrack(ed)?\b", True, "Cracked software"),
    ("suspicious_name", r"\bhack(er|tool)?\b", True, "Hacking tool"),
    ("suspicious_name", r"\bexploit\b", True, "Exploit toolkit"),
    ("suspicious_name", r"\b(coin|xmr)?miner\b", True, "Cryptocurrency miner"),
    ("suspicious_name", r"\bkeylog(ger)?\b", True, "Keylogger"),
    ("suspicious_name", r"\bloader\b", True, "Malware loader"),
    ("suspicious_name", r"\brat\b", True, "Remote-access trojan"),
    ("suspicious_name", r"\btoolbar\b", True, "Browser toolbar / adware"),
    ("suspicious_name", r"setup\d{6,}", True, "Numeric-suffix installer (dropper)"),
    # install_path_suspicious — regex on location
    ("install_path_suspicious", r"[\\/]temp[\\/]", True, "Temp directory"),
    ("install_path_suspicious", r"appdata[\\/]local[\\/]temp", True, "AppData Local Temp"),
    ("install_path_suspicious", r"[\\/]downloads[\\/]", True, "Downloads folder"),
    ("install_path_suspicious", r"[\\/]desktop[\\/]", True, "Desktop"),
    ("install_path_suspicious", r"[\\/]\\$recycle\\.bin[\\/]", True, "Recycle bin"),
    ("install_path_suspicious", r"[\\/][0-9a-f]{16,}[\\/]", True, "Hex-only directory name"),
    # eol_runtime — literal name substrings (is_regex=false)
    ("eol_runtime", "Java 6", False, "Java SE 6 EOL 2013"),
    ("eol_runtime", "Java 7", False, "Java SE 7 EOL 2015"),
    ("eol_runtime", "Java 8", False, "Java SE 8 EOL 2019 (public)"),
    ("eol_runtime", "Adobe Flash Player", False, "Flash EOL 2020"),
    ("eol_runtime", "Adobe Shockwave", False, "Shockwave EOL 2019"),
    ("eol_runtime", "Silverlight", False, "Silverlight EOL 2021"),
    ("eol_runtime", "Internet Explorer", False, "IE EOL 2022"),
    ("eol_runtime", ".NET Framework 3.5", False, ".NET 3.5 legacy"),
    ("eol_runtime", "Python 2", False, "Python 2 EOL 2020"),
]


# canonical_name → [categories]. Publisher hints filled in where the
# product's publisher is unambiguous. Small starter set; operators
# extend via admin UI + `catalog_seed` follow-ups.
_CATALOG_SEED = [
    # AV
    ("SentinelOne", ["av"], "SentinelOne, Inc."),
    ("SentinelOne Agent", ["av"], "SentinelOne, Inc."),
    ("Sophos Endpoint", ["av"], "Sophos"),
    ("Sophos Anti-Virus", ["av"], "Sophos"),
    ("ESET Endpoint Security", ["av"], "ESET"),
    ("ESET NOD32 Antivirus", ["av"], "ESET"),
    ("Bitdefender GravityZone", ["av"], "Bitdefender"),
    ("Bitdefender Endpoint Security Tools", ["av"], "Bitdefender"),
    ("Microsoft Defender for Endpoint", ["av"], "Microsoft"),
    ("Windows Defender", ["av"], "Microsoft"),
    ("Malwarebytes", ["av"], "Malwarebytes"),
    ("Webroot SecureAnywhere", ["av"], "Webroot"),
    ("Kaspersky Endpoint Security", ["av"], "Kaspersky"),
    ("Trend Micro OfficeScan", ["av"], "Trend Micro"),
    ("Trend Micro Apex One", ["av"], "Trend Micro"),
    ("Symantec Endpoint Protection", ["av"], "Broadcom"),
    ("Norton 360", ["av"], "Gen Digital"),
    ("McAfee Endpoint Security", ["av"], "Trellix"),
    ("CrowdStrike Falcon Sensor", ["av"], "CrowdStrike"),
    ("Carbon Black Cloud Sensor", ["av"], "VMware"),
    # RMM
    ("NinjaOne Agent", ["rmm"], "NinjaOne"),
    ("Ninja RMM Agent", ["rmm"], "NinjaOne"),
    ("Datto RMM Agent", ["rmm"], "Datto"),
    ("ConnectWise Automate", ["rmm"], "ConnectWise"),
    ("Kaseya VSA Agent", ["rmm"], "Kaseya"),
    ("N-central Agent", ["rmm"], "N-able"),
    ("Atera Agent", ["rmm"], "Atera"),
    ("Pulseway Agent", ["rmm"], "Pulseway"),
    ("SolarWinds N-central", ["rmm"], "SolarWinds"),
    # Remote access
    ("LogMeIn Client", ["remote_access"], "GoTo"),
    ("LogMeIn Rescue Applet", ["remote_access"], "GoTo"),
    ("ScreenConnect Client", ["remote_access"], "ConnectWise"),
    ("ConnectWise Control Client", ["remote_access"], "ConnectWise"),
    ("TeamViewer", ["remote_access"], "TeamViewer"),
    ("AnyDesk", ["remote_access"], "AnyDesk Software"),
    ("Splashtop Streamer", ["remote_access"], "Splashtop"),
    ("BeyondTrust Remote Support", ["remote_access"], "BeyondTrust"),
    ("Chrome Remote Desktop", ["remote_access"], "Google"),
    ("UltraViewer", ["remote_access"], ""),
    ("RustDesk", ["remote_access"], ""),
    # Trusted publishers (whitelist by publisher)
    ("Microsoft Corporation", ["trusted_publisher"], "Microsoft"),
    ("Adobe Inc.", ["trusted_publisher"], "Adobe"),
    ("Google LLC", ["trusted_publisher"], "Google"),
    ("Mozilla", ["trusted_publisher"], "Mozilla"),
    ("Apple Inc.", ["trusted_publisher"], "Apple"),
    ("Cisco Systems", ["trusted_publisher"], "Cisco"),
    ("Zoom Video Communications", ["trusted_publisher"], "Zoom"),
    # Whitelist common tools
    ("7-Zip", ["whitelist"], "Igor Pavlov"),
    ("Notepad++", ["whitelist"], "Notepad++"),
    ("Google Chrome", ["whitelist"], "Google"),
    ("Mozilla Firefox", ["whitelist"], "Mozilla"),
    ("Microsoft Edge", ["whitelist"], "Microsoft"),
]


def seed_data(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    FindingCategory = apps.get_model("operations", "FindingCategory")
    FindingType = apps.get_model("operations", "FindingType")
    SoftwareClassifierRule = apps.get_model("operations", "SoftwareClassifierRule")
    SoftwareCatalog = apps.get_model("operations", "SoftwareCatalog")

    # 1. Seed categories
    cat_by_name = {}
    for name, desc, order in _FINDING_CATEGORIES:
        cat, _ = FindingCategory.objects.get_or_create(
            name=name,
            defaults={"description": desc, "display_order": order},
        )
        cat_by_name[name] = cat

    # 2. Backfill existing finding_types
    for ft in FindingType.objects.all():
        cat_name = _TYPE_CATEGORY.get(ft.name)
        if cat_name and cat_by_name.get(cat_name):
            ft.category = cat_by_name[cat_name]
            ft.save(update_fields=["category"])

    # 3. Seed software finding types
    software_cat = cat_by_name["software"]
    for name, severity, klass, module, desc in _SOFTWARE_FINDING_TYPES:
        FindingType.objects.get_or_create(
            name=name,
            defaults={
                "default_severity": severity,
                "finding_class": klass,
                "source_module": module,
                "auto_resolvable": True,
                "runbook_path": "",
                "description": desc,
                "category": software_cat,
            },
        )

    # 4. Seed classifier rules
    for rule_type, pattern, is_regex, note in _CLASSIFIER_RULES:
        SoftwareClassifierRule.objects.get_or_create(
            rule_type=rule_type,
            pattern=pattern,
            defaults={"is_regex": is_regex, "enabled": True, "note": note},
        )

    # 5. Seed software catalog (global, tenant=NULL)
    for canonical, categories, publisher in _CATALOG_SEED:
        SoftwareCatalog.objects.get_or_create(
            canonical_name=canonical,
            tenant=None,
            defaults={
                "categories": categories,
                "publisher_hint": publisher,
                "notes": "seeded by migration 0037",
            },
        )


def unseed(apps, schema_editor):
    FindingCategory = apps.get_model("operations", "FindingCategory")
    FindingType = apps.get_model("operations", "FindingType")
    SoftwareClassifierRule = apps.get_model("operations", "SoftwareClassifierRule")
    SoftwareCatalog = apps.get_model("operations", "SoftwareCatalog")
    FindingType.objects.filter(name__in=[n for n, *_ in _SOFTWARE_FINDING_TYPES]).delete()
    SoftwareClassifierRule.objects.all().delete()
    SoftwareCatalog.objects.filter(notes="seeded by migration 0037").delete()
    FindingType.objects.all().update(category=None)
    FindingCategory.objects.all().delete()


_RLS_SQL = """
ALTER TABLE operations.finding_categories ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_read ON operations.finding_categories FOR SELECT USING (TRUE);
GRANT SELECT ON operations.finding_categories TO operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT INSERT, UPDATE, DELETE ON operations.finding_categories TO operations_app;

ALTER TABLE operations.software_classifier_rules ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_read ON operations.software_classifier_rules FOR SELECT USING (TRUE);
GRANT SELECT ON operations.software_classifier_rules TO operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT INSERT, UPDATE, DELETE ON operations.software_classifier_rules TO operations_app;
"""

_RLS_REVERSE = """
DROP POLICY IF EXISTS tenant_read ON operations.finding_categories;
DROP POLICY IF EXISTS tenant_read ON operations.software_classifier_rules;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0036_presence_power_state"),
    ]

    operations = [
        migrations.CreateModel(
            name="FindingCategory",
            fields=[
                ("id", models.SmallAutoField(primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=32, unique=True)),
                ("description", models.CharField(blank=True, default="", max_length=240)),
                ("display_order", models.PositiveIntegerField(default=100)),
            ],
            options={"db_table": "finding_categories", "ordering": ("display_order", "name")},
        ),
        migrations.AddField(
            model_name="findingtype",
            name="category",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="finding_types",
                to="operations.findingcategory",
            ),
        ),
        migrations.CreateModel(
            name="SoftwareClassifierRule",
            fields=[
                ("id", models.SmallAutoField(primary_key=True, serialize=False)),
                ("rule_type", models.CharField(
                    choices=[
                        ("suspicious_name", "Suspicious name"),
                        ("install_path_suspicious", "Suspicious install path"),
                        ("eol_runtime", "End-of-life runtime"),
                    ],
                    max_length=32,
                )),
                ("pattern", models.CharField(max_length=255)),
                ("is_regex", models.BooleanField(default=True)),
                ("enabled", models.BooleanField(default=True)),
                ("note", models.CharField(blank=True, default="", max_length=240)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "software_classifier_rules",
                "ordering": ("rule_type", "pattern"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("rule_type", "pattern"),
                        name="uq_software_classifier_rules_type_pattern",
                    ),
                ],
            },
        ),
        migrations.AlterField(
            model_name="softwaredecision",
            name="client",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="software_decisions",
                to="operations.client",
            ),
        ),
        migrations.AddField(
            model_name="softwaredecision",
            name="device",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="software_decisions",
                to="operations.device",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="softwaredecision",
            name="uq_software_decisions_tenant_client_name",
        ),
        migrations.AddConstraint(
            model_name="softwaredecision",
            constraint=models.UniqueConstraint(
                fields=("tenant", "canonical_name"),
                condition=models.Q(("client__isnull", True), ("device__isnull", True)),
                name="uq_software_decisions_global",
            ),
        ),
        migrations.AddConstraint(
            model_name="softwaredecision",
            constraint=models.UniqueConstraint(
                fields=("tenant", "client", "canonical_name"),
                condition=models.Q(("client__isnull", False), ("device__isnull", True)),
                name="uq_software_decisions_client",
            ),
        ),
        migrations.AddConstraint(
            model_name="softwaredecision",
            constraint=models.UniqueConstraint(
                fields=("tenant", "device", "canonical_name"),
                condition=models.Q(("device__isnull", False)),
                name="uq_software_decisions_device",
            ),
        ),
        migrations.RunSQL(_RLS_SQL, _RLS_REVERSE),
        migrations.RunPython(seed_data, unseed),
    ]
