"""Operations-native source configuration.

Loads SourceConfig rows from operations.sources / source_instances /
source_bindings. Replaces the legacy ninja_agent_compliance.platform_sources
loader — this module must never touch the ninja_agent_compliance schema.

source_instances.config JSONB carries the connection details:
  platform, source_key, is_shared, base_url, token_url, and secret env-var
  refs (api_token_ref, client_id_ref, client_secret_ref, ext_guid_ref,
  secret_key_ref, company_id_ref, psk_ref). Secret *values* live only in
  the server environment; config stores the variable names.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

from ingest import db
from ingest.normalize import canonical_platform

_KIND_ENTITY_TYPE = {
    "rmm": "agent.rmm",
    "edr": "agent.edr",
    "remote_access": "agent.remote_access",
}


@dataclass(frozen=True)
class SourceConfig:
    platform: str
    source_key: str
    source_name: str
    is_shared: bool
    enabled: bool
    base_url: str | None
    token_url: str | None
    api_token: str | None
    client_id_value: str | None
    client_secret: str | None
    ext_guid: str | None
    secret_key: str | None
    company_id: str | None
    psk: str | None
    ops_source_id: int
    source_instance_id: uuid.UUID
    source_binding_id: uuid.UUID | None
    entity_type: str | None
    client_id: uuid.UUID | None      # operations.clients.id for client-scoped instances
    client_name: str | None
    # Legacy platform_sources.source_id, carried through migration 0022 so
    # fetcher rows stay compatible with the legacy AC matrix until Track 6.
    source_id: int = 0


def _secret(ref: str | None) -> str | None:
    if not ref:
        return None
    return os.environ.get(ref)


def load_sources() -> list[SourceConfig]:
    """Return one SourceConfig per enabled source binding.

    Instances whose config carries no `platform` fall back to the
    operations.sources name (canonicalized).
    """
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """
            SELECT s.id            AS ops_source_id,
                   s.name          AS source_name_default,
                   s.kind          AS kind,
                   si.id           AS source_instance_id,
                   si.client_id    AS client_id,
                   c.display_name  AS client_name,
                   si.config       AS config,
                   sb.id           AS source_binding_id
            FROM operations.sources s
            JOIN operations.source_instances si ON si.source_id = s.id
            LEFT JOIN operations.clients c ON c.id = si.client_id
            LEFT JOIN operations.source_bindings sb
                   ON sb.source_instance_id = si.id AND sb.enabled
            WHERE si.tenant_id = 1
              AND si.enabled
            ORDER BY s.name, si.id
            """
        )
        rows = cur.fetchall()

    configs: list[SourceConfig] = []
    for (
        ops_source_id, source_name_default, kind,
        source_instance_id, client_id, client_name,
        config, source_binding_id,
    ) in rows:
        cfg = config or {}
        platform = canonical_platform(cfg.get("platform") or source_name_default)
        configs.append(
            SourceConfig(
                platform=platform,
                source_key=cfg.get("source_key") or "",
                source_name=cfg.get("source_name") or source_name_default,
                is_shared=bool(cfg.get("is_shared", True)),
                enabled=True,
                base_url=cfg.get("base_url"),
                token_url=cfg.get("token_url"),
                api_token=_secret(cfg.get("api_token_ref")),
                client_id_value=_secret(cfg.get("client_id_ref")),
                client_secret=_secret(cfg.get("client_secret_ref")),
                ext_guid=_secret(cfg.get("ext_guid_ref")),
                secret_key=_secret(cfg.get("secret_key_ref")),
                company_id=_secret(cfg.get("company_id_ref")),
                psk=_secret(cfg.get("psk_ref")),
                ops_source_id=ops_source_id,
                source_instance_id=source_instance_id,
                source_binding_id=source_binding_id,
                entity_type=_KIND_ENTITY_TYPE.get(kind),
                client_id=client_id,
                client_name=client_name,
                source_id=int(cfg.get("legacy_source_id") or 0),
            )
        )
    return configs
