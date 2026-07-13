"""Migration 0028 — Track C batch C2.

Adds:
  * client_links.created_at + created_reason (auditable link provenance)
  * client_candidates table (open/accepted/mapped/excluded)
  * three finding types (client_name_conflict, client_link_collision,
    client_unattached_group)
  * legacy import of client_aliases (267 rows) → client_name_aliases
  * legacy import of org_excludes (7 rows) → client_org_excludes
"""

from __future__ import annotations

import logging
import re
import uuid

import django.db.models.deletion
from django.db import connection, migrations, models

log = logging.getLogger(__name__)

_ORG_STRIP_RE = re.compile(r"[\s\-_.]")


def _norm(name: str | None) -> str:
    return _ORG_STRIP_RE.sub("", (name or "")).lower().strip()


_TIER_RANK = {"manual": 0, "seed": 1, "alignment": 2, "source": 3}


def _map_legacy_tier(source: str) -> str:
    return "source" if source == "ninja" else source


_FINDING_TYPES = (
    (
        "client_name_conflict",
        "medium",
        "entity",
        "platform.client_resolver",
        True,
        "A mapped client_link is now seeing a different display name from "
        "its source. Rename the client, add an alias, or re-map the link.",
    ),
    (
        "client_link_collision",
        "high",
        "admin",
        "platform.client_resolver",
        False,
        "A single source group name matches two or more clients. Ambiguous — "
        "the resolver cannot attach; operator must pick one client or add "
        "a tie-breaking alias.",
    ),
    (
        "client_unattached_group",
        "medium",
        "admin",
        "platform.client_resolver",
        True,
        "A source group is producing observations but is not mapped to any "
        "client. Accept, map, or exclude the corresponding client candidate.",
    ),
)


def seed_finding_types(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for (name, sev, klass, module, auto, desc) in _FINDING_TYPES:
        schema_editor.execute(
            """
            INSERT INTO operations.finding_types
                (name, default_severity, finding_class, source_module,
                 auto_resolvable, runbook_path, description)
            VALUES (%s, %s, %s, %s, %s, '', %s)
            ON CONFLICT (name) DO NOTHING
            """,
            [name, sev, klass, module, auto, desc],
        )


def unseed_finding_types(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for row in _FINDING_TYPES:
        schema_editor.execute(
            "DELETE FROM operations.finding_types WHERE name = %s", [row[0]]
        )


def import_legacy_aliases(apps, schema_editor):
    """Copy ninja_agent_compliance.client_aliases into client_name_aliases.

    Legacy is per-platform (alias_type ∈ org_name/site_name/group_name);
    operations is global by normalized name. On collision keep the row
    whose tier ranks highest; skip conflicting client mappings with a
    warning so operator can resolve.
    """
    if schema_editor.connection.vendor != "postgresql":
        return
    Client = apps.get_model("operations", "Client")
    ClientNameAlias = apps.get_model("operations", "ClientNameAlias")

    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT to_regclass('ninja_agent_compliance.client_aliases'),
                   to_regclass('ninja_agent_compliance.clients')
            """
        )
        aliases_tbl, clients_tbl = cur.fetchone()
        if not aliases_tbl or not clients_tbl:
            return

        cur.execute("SELECT client_id, client_name FROM ninja_agent_compliance.clients")
        legacy_map: dict[int, object] = {}
        for ac_id, ac_name in cur.fetchall():
            try:
                legacy_map[ac_id] = Client.objects.get(tenant_id=1, display_name=ac_name)
            except Client.DoesNotExist:
                continue

        cur.execute(
            """
            SELECT a.alias_value, a.client_id, a.source
            FROM ninja_agent_compliance.client_aliases a
            JOIN ninja_agent_compliance.clients c ON c.client_id = a.client_id
            WHERE a.enabled AND c.enabled AND c.source <> 'demoted'
            """
        )
        rows = cur.fetchall()

    # (normalized_name) → (tier, client_id, alias)
    picked: dict[str, tuple[str, object, str]] = {}
    conflicts: list[str] = []
    for alias_value, ac_id, source in rows:
        client = legacy_map.get(ac_id)
        if client is None:
            continue
        normalized = _norm(alias_value)
        if not normalized:
            continue
        tier = _map_legacy_tier(source)
        existing = picked.get(normalized)
        if existing is None:
            picked[normalized] = (tier, client, alias_value)
            continue
        ex_tier, ex_client, _ = existing
        if _TIER_RANK[tier] < _TIER_RANK[ex_tier]:
            if ex_client.id != client.id:
                conflicts.append(
                    f"alias {alias_value!r} → tier {tier}/{client.display_name} "
                    f"overrides {ex_tier}/{ex_client.display_name}"
                )
            picked[normalized] = (tier, client, alias_value)
        elif ex_client.id != client.id:
            conflicts.append(
                f"alias {alias_value!r} conflict: {ex_tier}/{ex_client.display_name} "
                f"vs {tier}/{client.display_name} — skipping later"
            )

    # Never shadow the client's own display_name with an alias row.
    client_norms = {
        _norm(c.display_name): c.id
        for c in Client.objects.filter(tenant_id=1)
    }
    for normalized, (tier, client, alias) in picked.items():
        if client_norms.get(normalized) == client.id:
            continue
        ClientNameAlias.objects.update_or_create(
            tenant_id=1, normalized_name=normalized,
            defaults={
                "id": uuid.uuid4(),
                "client_id": client.id,
                "alias": alias,
                "tier": tier,
                "enabled": True,
                "created_reason": "imported from ninja_agent_compliance.client_aliases",
            },
        )
    for msg in conflicts:
        log.warning("client_aliases import: %s", msg)


def unimport_legacy_aliases(apps, schema_editor):
    ClientNameAlias = apps.get_model("operations", "ClientNameAlias")
    ClientNameAlias.objects.filter(
        tenant_id=1,
        created_reason="imported from ninja_agent_compliance.client_aliases",
    ).delete()


def import_legacy_org_excludes(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    ClientOrgExclude = apps.get_model("operations", "ClientOrgExclude")

    with connection.cursor() as cur:
        cur.execute("SELECT to_regclass('ninja_agent_compliance.org_excludes')")
        if not cur.fetchone()[0]:
            return
        cur.execute(
            "SELECT pattern, COALESCE(notes, '') "
            "FROM ninja_agent_compliance.org_excludes WHERE enabled"
        )
        rows = cur.fetchall()

    for pattern, notes in rows:
        normalized = _norm(pattern)
        if not normalized:
            continue
        ClientOrgExclude.objects.get_or_create(
            tenant_id=1, normalized_name=normalized,
            defaults={
                "id": uuid.uuid4(),
                "reason": (notes or "imported from ninja_agent_compliance.org_excludes")[:240],
                "created_by": "migration_0028",
                "enabled": True,
            },
        )


def unimport_legacy_org_excludes(apps, schema_editor):
    ClientOrgExclude = apps.get_model("operations", "ClientOrgExclude")
    ClientOrgExclude.objects.filter(tenant_id=1, created_by="migration_0028").delete()


_CANDIDATE_RLS_SQL = """
ALTER TABLE operations.client_candidates ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.client_candidates
    USING (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON operations.client_candidates TO operations_app;
GRANT SELECT, INSERT, UPDATE ON operations.client_candidates TO ninja_ingest;
GRANT SELECT ON operations.client_candidates TO operations_readonly;
GRANT SELECT ON operations.client_candidates TO metabase_ro;
"""

_CANDIDATE_RLS_REVERSE_SQL = (
    "DROP POLICY IF EXISTS tenant_isolation ON operations.client_candidates;"
)

_CLIENT_LINKS_ADD_SQL = """
ALTER TABLE operations.client_links
    ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE operations.client_links
    ADD COLUMN created_reason VARCHAR(120) NOT NULL DEFAULT '';
"""

_CLIENT_LINKS_DROP_SQL = """
ALTER TABLE operations.client_links DROP COLUMN IF EXISTS created_reason;
ALTER TABLE operations.client_links DROP COLUMN IF EXISTS created_at;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0027_client_name_tables"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="clientlink",
                    name="created_at",
                    field=models.DateTimeField(auto_now_add=True),
                ),
                migrations.AddField(
                    model_name="clientlink",
                    name="created_reason",
                    field=models.CharField(blank=True, default="", max_length=120),
                ),
            ],
            database_operations=[
                migrations.RunSQL(_CLIENT_LINKS_ADD_SQL, _CLIENT_LINKS_DROP_SQL),
            ],
        ),
        migrations.CreateModel(
            name="ClientCandidate",
            fields=[
                ("version", models.PositiveIntegerField(default=1)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("normalized_name", models.CharField(max_length=240)),
                ("display_name", models.CharField(blank=True, default="", max_length=240)),
                ("status", models.CharField(choices=[("open", "Open"), ("accepted", "Accepted"), ("mapped", "Mapped"), ("excluded", "Excluded")], default="open", max_length=16)),
                ("seen_count", models.PositiveIntegerField(default=1)),
                ("first_seen_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField(auto_now=True)),
                ("source_refs", models.JSONField(blank=True, default=list)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("resolved_by", models.CharField(blank=True, default="", max_length=120)),
                ("resolved_reason", models.CharField(blank=True, default="", max_length=240)),
                ("resolved_client", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="resolved_candidates", to="operations.client")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="operations.tenant")),
            ],
            options={
                "db_table": "client_candidates",
                "constraints": [models.UniqueConstraint(fields=("tenant", "normalized_name"), name="uq_client_candidates_tenant_normalized")],
            },
        ),
        migrations.RunSQL(_CANDIDATE_RLS_SQL, _CANDIDATE_RLS_REVERSE_SQL),
        migrations.RunPython(seed_finding_types, unseed_finding_types),
        migrations.RunPython(import_legacy_aliases, unimport_legacy_aliases),
        migrations.RunPython(import_legacy_org_excludes, unimport_legacy_org_excludes),
    ]
