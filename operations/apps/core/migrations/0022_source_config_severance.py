"""Migration 0022 — operations-native source config + unmatched_source_groups.

Track 0 severance (BLUEPRINT.md). Three steps:

1. Creates operations.unmatched_source_groups — review queue for source
   groups (S1 sites, LMI groups) that resolve to no operations client.

2. Copies every enabled ninja_agent_compliance.platform_sources row into
   source_instances.config (platform, source_key, base_url, secret env-var
   *refs* — values stay in the server .env). Creates SourceInstance +
   SourceBinding rows where the 0015/0017 tenant seeds don't cover it
   (e.g. per-client ScreenConnect instances). After this, ingest loads
   source config exclusively from operations.* via ingest/sources.py.

3. Seeds operations.client_links from ninja_agent_compliance
   .client_platform_links for shared platforms (external_id = platform
   group id). Existing links win on conflict. Also removes the
   self-referential links the old ingest keying wrote for shared sources
   (external_id = the client's own UUID).

Reads the legacy schema — allowed: migrations are cutover machinery, not
runtime dependency. Skips gracefully when the legacy schema is absent.
"""

from __future__ import annotations

import uuid

from django.db import migrations

INTERNAL_COLLECTOR_INSTANCE_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")

_PLATFORM_ALIASES = {
    "ninja": "Ninja",
    "sentinelone": "SentinelOne",
    "s1": "SentinelOne",
    "logmein": "LogMeIn",
    "lmi": "LogMeIn",
    "screenconnect": "ScreenConnect",
    "sc": "ScreenConnect",
}

# ScreenConnect legacy links key platform_group_id on the legacy int client
# id — meaningless in operations (SC resolves via client-scoped instances).
_SKIP_LINK_PLATFORMS = {"ScreenConnect"}


def _canonical_platform(value: str) -> str:
    key = (value or "").strip().replace(" ", "").lower()
    return _PLATFORM_ALIASES.get(key, (value or "").strip())


def create_unmatched_source_groups(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        """
        CREATE TABLE IF NOT EXISTS operations.unmatched_source_groups (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     BIGINT NOT NULL,
            source_id     SMALLINT NOT NULL REFERENCES operations.sources(id),
            external_id   TEXT NOT NULL,
            external_name TEXT NOT NULL DEFAULT '',
            device_count  INTEGER NOT NULL DEFAULT 0,
            status        TEXT NOT NULL DEFAULT 'pending',
            first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            resolved_at   TIMESTAMPTZ,
            resolved_by   TEXT,
            CONSTRAINT uq_unmatched_source_groups
                UNIQUE (tenant_id, source_id, external_id)
        );
        """
    )
    schema_editor.execute(
        "CREATE INDEX IF NOT EXISTS idx_unmatched_source_groups_status"
        " ON operations.unmatched_source_groups (tenant_id, status);"
    )
    schema_editor.execute(
        "ALTER TABLE operations.unmatched_source_groups OWNER TO operations_migrate;"
    )
    for role in ("operations_app", "ninja_ingest", "operations_readonly"):
        schema_editor.execute(
            f"GRANT SELECT, INSERT, UPDATE ON operations.unmatched_source_groups TO {role};"
        )


def drop_unmatched_source_groups(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("DROP TABLE IF EXISTS operations.unmatched_source_groups;")


def _legacy_table_exists(cursor, table: str) -> bool:
    cursor.execute("SELECT to_regclass(%s)", (f"ninja_agent_compliance.{table}",))
    return cursor.fetchone()[0] is not None


def migrate_source_config(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    from django.db import connection

    Tenant            = apps.get_model("operations", "Tenant")
    Source            = apps.get_model("operations", "Source")
    Client            = apps.get_model("operations", "Client")
    ClientLink        = apps.get_model("operations", "ClientLink")
    CollectorInstance = apps.get_model("operations", "CollectorInstance")
    SourceInstance    = apps.get_model("operations", "SourceInstance")
    SourceBinding     = apps.get_model("operations", "SourceBinding")

    with connection.cursor() as cur:
        if not _legacy_table_exists(cur, "platform_sources"):
            return

    tenant = Tenant.objects.get(id=1)
    internal_collector = CollectorInstance.objects.get(id=INTERNAL_COLLECTOR_INSTANCE_ID)

    # ── legacy AC client_id → operations Client (by name) ─────────────
    client_map: dict[int, object] = {}
    with connection.cursor() as cur:
        cur.execute("SELECT client_id, client_name FROM ninja_agent_compliance.clients")
        for ac_id, ac_name in cur.fetchall():
            try:
                client_map[ac_id] = Client.objects.get(tenant_id=1, display_name=ac_name)
            except Client.DoesNotExist:
                pass

    # ── platform_sources → source_instances.config ────────────────────
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT source_id, source_key, platform, source_name, client_id,
                   is_shared, base_url, token_url, api_token_secret_ref,
                   client_id_secret_ref, client_secret_ref,
                   ext_guid_secret_ref, secret_key_secret_ref,
                   company_id_secret_ref, psk_secret_ref
            FROM ninja_agent_compliance.platform_sources
            WHERE enabled
            ORDER BY source_id
            """
        )
        ps_rows = cur.fetchall()

    for (
        legacy_source_id, source_key, platform, source_name, legacy_client_id,
        is_shared, base_url, token_url, api_token_ref,
        client_id_ref, client_secret_ref, ext_guid_ref, secret_key_ref,
        company_id_ref, psk_ref,
    ) in ps_rows:
        platform = _canonical_platform(platform)
        source, _ = Source.objects.get_or_create(
            name=platform, defaults={"kind": "remote_access", "capabilities": {}}
        )
        config_payload = {
            "platform":         platform,
            "source_key":       source_key,
            "source_name":      source_name,
            "is_shared":        bool(is_shared),
            "base_url":         base_url,
            "token_url":        token_url,
            "api_token_ref":    api_token_ref,
            "client_id_ref":    client_id_ref,
            "client_secret_ref": client_secret_ref,
            "ext_guid_ref":     ext_guid_ref,
            "secret_key_ref":   secret_key_ref,
            "company_id_ref":   company_id_ref,
            "psk_ref":          psk_ref,
            "legacy_source_id": legacy_source_id,
            "legacy_client_id": legacy_client_id,
        }
        config_payload = {k: v for k, v in config_payload.items() if v is not None}

        instances = list(
            SourceInstance.objects.filter(tenant_id=1, source=source).order_by("id")
        )
        target = next(
            (si for si in instances if (si.config or {}).get("source_key") == source_key),
            None,
        )
        if target is None:
            # Claim an unconfigured tenant seed (0015/0017) before creating new.
            target = next(
                (si for si in instances if "source_key" not in (si.config or {})),
                None,
            )
        if target is None:
            target = SourceInstance(
                id=uuid.uuid4(), tenant=tenant, source=source,
                client=None, config={}, enabled=True,
            )

        merged = dict(target.config or {})
        merged.update(config_payload)
        target.config = merged
        if not is_shared and legacy_client_id in client_map:
            target.client = client_map[legacy_client_id]
        target.save()

        SourceBinding.objects.get_or_create(
            tenant_id=1,
            source_instance=target,
            collector_instance=internal_collector,
            defaults={"id": uuid.uuid4(), "schedule": "", "enabled": True},
        )

    # ── drop self-referential shared-source links (old ingest keying) ──
    with connection.cursor() as cur:
        cur.execute(
            """
            DELETE FROM operations.client_links
            WHERE tenant_id = 1 AND external_id = client_id::text
            """
        )

    # ── client_platform_links → client_links ──────────────────────────
    with connection.cursor() as cur:
        if not _legacy_table_exists(cur, "client_platform_links"):
            return
        cur.execute(
            """
            SELECT platform, platform_group_id, client_id, last_seen_name
            FROM ninja_agent_compliance.client_platform_links
            """
        )
        link_rows = cur.fetchall()

    sources_by_name = {s.name: s for s in Source.objects.all()}
    for platform, group_id, legacy_client_id, last_seen_name in link_rows:
        platform = _canonical_platform(platform)
        if platform in _SKIP_LINK_PLATFORMS:
            continue
        source = sources_by_name.get(platform)
        ops_client = client_map.get(legacy_client_id)
        if source is None or ops_client is None or not group_id:
            continue
        ClientLink.objects.get_or_create(
            tenant_id=1,
            source=source,
            external_id=str(group_id),
            defaults={
                "id": uuid.uuid4(),
                "client": ops_client,
                "external_name": last_seen_name or "",
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0021_agent_presence_device_type"),
    ]

    operations = [
        migrations.RunPython(create_unmatched_source_groups, drop_unmatched_source_groups),
        migrations.RunPython(migrate_source_config, migrations.RunPython.noop),
    ]
