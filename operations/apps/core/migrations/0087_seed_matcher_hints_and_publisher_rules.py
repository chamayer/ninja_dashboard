"""Seed publisher aliases + publisher-scope category rules + intel
matcher hints. Every seed is a plain row in the admin-maintainable
tables, editable and extensible without a deploy.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


_PUBLISHER_ALIASES = [
    # raw pattern → canonical publisher
    ("Microsoft%",          "Microsoft"),
    ("%Microsoft Corp%",    "Microsoft"),
    ("%Microsoft, Inc%",    "Microsoft"),
    ("Adobe%",              "Adobe"),
    ("Google%",             "Google"),
    ("Alphabet%",           "Google"),
    ("Oracle%",             "Oracle"),
    ("Sun Microsystems%",   "Oracle"),
    ("Mozilla%",            "Mozilla"),
    ("Apple%",              "Apple"),
    ("Autodesk%",           "Autodesk"),
    ("Cisco%",              "Cisco"),
    ("Citrix%",             "Citrix"),
    ("VMware%",             "VMware"),
    ("Broadcom%",           "Broadcom / Symantec"),
    ("Symantec%",           "Broadcom / Symantec"),
    ("Kaspersky%",          "Kaspersky"),
    ("McAfee%",             "McAfee"),
    ("SentinelOne%",        "SentinelOne"),
    ("Trend Micro%",        "Trend Micro"),
    ("Bitdefender%",        "Bitdefender"),
    ("CrowdStrike%",        "CrowdStrike"),
    ("Sophos%",             "Sophos"),
    ("Malwarebytes%",       "Malwarebytes"),
    ("NinjaOne%",           "NinjaOne"),
    ("NinjaRMM%",           "NinjaOne"),
    ("LogMeIn%",            "LogMeIn / GoTo"),
    ("GoTo%",               "LogMeIn / GoTo"),
    ("ConnectWise%",        "ConnectWise"),
    ("TeamViewer%",         "TeamViewer"),
    ("AnyDesk%",            "AnyDesk"),
    ("Splashtop%",          "Splashtop"),
    ("Datto%",              "Datto"),
    ("VMware%",             "VMware"),
    ("Dell%",               "Dell"),
    ("HP Inc%",             "HP Inc."),
    ("Hewlett-Packard%",    "HP Inc."),
    ("HP Enterprise%",      "HPE"),
    ("Lenovo%",             "Lenovo"),
    ("Intel Corporation%",  "Intel"),
    ("NVIDIA%",             "NVIDIA"),
    ("AMD%",                "AMD"),
    ("Realtek%",            "Realtek"),
    ("Synaptics%",          "Synaptics"),
    ("Zoom Video%",         "Zoom"),
    ("Slack%",              "Slack (Salesforce)"),
    ("Salesforce%",         "Salesforce"),
    ("Notion%",             "Notion"),
    ("Dropbox%",            "Dropbox"),
    ("Box%",                "Box"),
    ("GitHub%",             "GitHub / Microsoft"),
    ("GitLab%",             "GitLab"),
    ("JetBrains%",          "JetBrains"),
    ("Python Software%",    "Python Software Foundation"),
    ("Node.js%",            "Node.js Foundation"),
    ("Docker%",             "Docker"),
    ("Elastic%",            "Elastic"),
]


# Canonical MSP taxonomy — a small, stable token set used across every
# category surface. Editable via Django admin per rule; do not
# invent new tokens without a real reason (the category chip strip
# on the software pages only pins up tokens that recur across the
# fleet).
#
#   system              — OS components, Windows updates
#   driver              — hardware drivers (chipset, GPU, NIC, audio)
#   security            — anti-malware / EDR / firewall / endpoint protection
#   av                  — specifically antivirus (subset of security)
#   edr                 — specifically endpoint detection & response
#   browser             — web browsers
#   productivity        — office suites, PDF, email clients
#   communication       — Teams, Zoom, Slack, chat, meetings
#   media               — video / audio players, editors
#   development         — IDEs, SDKs, compilers, dev tooling
#   runtime             — .NET, Java, Python, Node runtimes
#   remote-access       — TeamViewer, AnyDesk, RDP tools
#   management          — RMM, monitoring, systems management
#   rmm                 — specifically RMM tooling
#   backup              — Veeam, Acronis, backup agents
#   virtualization      — VMware, Docker, Hyper-V, containers
#   storage             — cloud file sync (Dropbox, OneDrive)
#   networking          — VPN clients, network monitors
#   database            — SQL Server, PostgreSQL, DB tooling
#   engineering         — CAD, technical design (Autodesk-style)
#   utility             — compression, disk / system utilities
_PUBLISHER_CATEGORIES = [
    ("Microsoft",                  ["system", "productivity"],           50),
    ("Adobe",                      ["productivity", "media"],            50),
    ("Google",                     ["browser", "productivity"],          50),
    ("Mozilla",                    ["browser"],                          50),
    ("Apple",                      ["system", "productivity"],           40),
    ("Autodesk",                   ["productivity", "engineering"],      40),
    ("Cisco",                      ["networking", "communication"],      40),
    ("Citrix",                     ["remote-access", "virtualization"],  50),
    ("VMware",                     ["virtualization"],                   50),
    ("Broadcom / Symantec",        ["security", "av"],                   50),
    ("Kaspersky",                  ["security", "av"],                   60),
    ("McAfee",                     ["security", "av"],                   60),
    ("SentinelOne",                ["security", "edr"],                  60),
    ("Trend Micro",                ["security", "av"],                   60),
    ("Bitdefender",                ["security", "av"],                   60),
    ("CrowdStrike",                ["security", "edr"],                  60),
    ("Sophos",                     ["security", "av"],                   60),
    ("Malwarebytes",               ["security", "av"],                   60),
    ("NinjaOne",                   ["management", "rmm"],                60),
    ("LogMeIn / GoTo",             ["remote-access", "management"],      60),
    ("ConnectWise",                ["management", "rmm", "remote-access"], 60),
    ("TeamViewer",                 ["remote-access"],                    60),
    ("AnyDesk",                    ["remote-access"],                    60),
    ("Splashtop",                  ["remote-access"],                    60),
    ("Datto",                      ["management", "backup"],             60),
    ("Zoom",                       ["communication"],                    40),
    ("Slack (Salesforce)",         ["communication"],                    40),
    ("Salesforce",                 ["productivity"],                     30),
    ("Notion",                     ["productivity"],                     30),
    ("Dropbox",                    ["storage", "productivity"],          30),
    ("Box",                        ["storage", "productivity"],          30),
    ("GitHub / Microsoft",         ["development"],                      40),
    ("GitLab",                     ["development"],                      40),
    ("JetBrains",                  ["development"],                      40),
    ("Python Software Foundation", ["development", "runtime"],           40),
    ("Node.js Foundation",         ["development", "runtime"],           40),
    ("Docker",                     ["development", "virtualization"],    40),
    ("Elastic",                    ["development", "management"],        30),
    ("Intel",                      ["driver"],                           30),
    ("NVIDIA",                     ["driver"],                           30),
    ("AMD",                        ["driver"],                           30),
    ("Realtek",                    ["driver"],                           30),
    ("Synaptics",                  ["driver"],                           30),
    ("Dell",                       ["system", "driver"],                 30),
    ("HP Inc.",                    ["system", "driver"],                 30),
    ("HPE",                        ["system", "driver"],                 30),
    ("Lenovo",                     ["system", "driver"],                 30),
]


_MATCHER_HINTS = [
    # Vendors whose product token is generic enough that a name needs
    # a third distinctive token to earn a CVE match.
    ("require_third_token", "microsoft"),
    ("require_third_token", "adobe"),
    ("require_third_token", "google"),
    ("require_third_token", "oracle"),
    ("require_third_token", "ibm"),
    ("require_third_token", "cisco"),
    ("require_third_token", "vmware"),
    ("require_third_token", "citrix"),

    # Sub-component patterns that inherit their parent product's risk;
    # skip CVE matching directly.
    ("ignore_sub_component", r"(?i)shared\s+mui"),
    ("ignore_sub_component", r"(?i)shared\s+setup\s+metadata"),
    ("ignore_sub_component", r"(?i)proofing(?:\s+tools)?"),
    ("ignore_sub_component", r"(?i)click[- ]to[- ]run\s+localization"),
    ("ignore_sub_component", r"(?i)click[- ]to[- ]run\s+extensibility"),
    ("ignore_sub_component", r"(?i)click[- ]to[- ]run\s+licensing"),
    ("ignore_sub_component", r"(?i)runtime\s+redistributable"),
    ("ignore_sub_component", r"(?i)osm\s+(?:ux\s+)?mui"),
    ("ignore_sub_component", r"(?i)outils\s+de\s+v[eé]rification"),
    ("ignore_sub_component", r"(?i)herramientas\s+de\s+correcci[oó]n"),
    ("ignore_sub_component", r"(?i)language\s+pack"),
    ("ignore_sub_component", r"(?i)mui\s+\(?[a-z]+\)?"),
    ("ignore_sub_component", r"(?i)\bactionsserver\b"),
    ("ignore_sub_component", r"(?i)\bonenotevirtualprinter\b"),
    ("ignore_sub_component", r"(?i)office\s+64-?bit\s+components?"),
    ("ignore_sub_component", r"(?i)office\s+32-?bit\s+components?"),
]


def apply(apps, schema_editor):
    PublisherAlias = apps.get_model("operations", "PublisherAlias")
    PublisherCategory = apps.get_model("operations", "PublisherCategory")
    IntelMatcherHint = apps.get_model("operations", "IntelMatcherHint")

    for raw, canonical in _PUBLISHER_ALIASES:
        PublisherAlias.objects.get_or_create(
            raw_pattern=raw,
            defaults={"canonical_publisher": canonical, "enabled": True},
        )
    for pattern, categories, priority in _PUBLISHER_CATEGORIES:
        PublisherCategory.objects.get_or_create(
            publisher_pattern=pattern,
            defaults={"categories": categories, "priority": priority, "enabled": True},
        )
    for kind, pattern in _MATCHER_HINTS:
        IntelMatcherHint.objects.get_or_create(
            kind=kind, pattern=pattern,
            defaults={"enabled": True},
        )


def rollback(apps, schema_editor):
    PublisherAlias = apps.get_model("operations", "PublisherAlias")
    PublisherCategory = apps.get_model("operations", "PublisherCategory")
    IntelMatcherHint = apps.get_model("operations", "IntelMatcherHint")
    PublisherAlias.objects.filter(
        raw_pattern__in=[r for r, _c in _PUBLISHER_ALIASES]
    ).delete()
    PublisherCategory.objects.filter(
        publisher_pattern__in=[p for p, _c, _pr in _PUBLISHER_CATEGORIES]
    ).delete()
    IntelMatcherHint.objects.filter(
        pattern__in=[p for _k, p in _MATCHER_HINTS]
    ).delete()


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0086_intel_matcher_hints_publisher_alias_categories"),
    ]

    operations: ClassVar[list] = [
        migrations.RunPython(apply, rollback),
    ]
