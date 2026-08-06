"""Platform-level source observation writer.

Any source connector that produces entity_observations rows calls through here.
`SourceConfig.source_binding_id` and `SourceConfig.entity_type` drive the write —
no platform-specific branching. Registering a new source means seeding its
operations.source_bindings row; no code changes required here.

Fetchers are the only thing keyed by platform (they are code, not config).
Everything else is config-driven via ingest.sources.

Client resolution order per observation:
  1. Client-scoped source instance (SourceConfig.client_id) — e.g. per-client
     ScreenConnect instances.
  2. source-link lookup on (source, platform_group_id) — e.g. S1 site id,
     LMI group id.
  3. Resolved device's client (fallback, requires identity match).
Groups that resolve no client are recorded in
operations.unmatched_source_groups for operator review.

Containers are entities too (BLUEPRINT Track C): every source group seen in
a run is written as one `org` observation keyed by its stable group id.
Fetchers may return container-only rows (`_org_only: True` with
platform_group_id/platform_group_name) so groups with zero devices are
still observed.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime
from typing import Any

from psycopg.types.json import Json

from ingest import db
from ingest.connectors import hudu, logmein, screenconnect, sentinelone
from ingest.identity import identity_entity_types
from ingest.identity.fast_path import resolve_device_fast
from ingest.normalize import (
    extract_macs,
    normalize_hostname,
    normalize_org_name,
    os_family,
)
from ingest.observation_runs import begin_run, complete_run, reconcile_complete_run
from ingest.observations import write_current_rows
from ingest.sources import SourceConfig

log = logging.getLogger(__name__)

_TENANT_ID = 1
_INTERNAL_COLLECTOR_INSTANCE_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")

_FETCHERS = {
    "SentinelOne":   sentinelone.fetch,
    "ScreenConnect": screenconnect.fetch,
    "LogMeIn":       logmein.fetch,
    "Hudu":          hudu.fetch,
}

# Sources outside the identity-signal set carry no independent identity
# evidence: they either already know their device or have none. Gating here
# rather than branching per platform means any future non-identity source
# inherits the behaviour. The set lives in ingest.identity because the
# resolver enforces the same rule on its own read path.


def is_identity_source(source: SourceConfig) -> bool:
    """True when this source's observations establish per-device identity.

    Callers use this to partition collection cadence: identity sources are
    live agent telemetry and want a short cycle, documentation sources change
    slowly. See `.work/backlog.md` — honouring `source_bindings.schedule` is
    the durable replacement for cadence-by-capability.

    Opens its own connection because callers partition a source list outside
    any transaction. The underlying lookup is cached per process, so this
    costs one query per run, not one per source.
    """
    with db.transaction() as cur:
        cur.execute(f"SET LOCAL operations.tenant_id = {_TENANT_ID}")
        return source.entity_type in identity_entity_types(cur)


def run_source_observations(
    sources: list[SourceConfig],
    observed_at: datetime,
) -> dict[str, int]:
    """Fetch all registered sources and write to entity_observations.

    Sources with no fetcher registered or no source_binding_id are skipped.
    Per-source exceptions are isolated so one bad source never blocks others.
    Returns counts written per platform.
    """
    batch_id = uuid.uuid4()
    counts: dict[str, int] = {}
    for source in sources:
        # Not every registered source is collected here — Ninja has its own
        # pipeline (run_ninja_observations_once). Skipping is silent on
        # purpose: recording it as a failed run marked Ninja red on the
        # Sources page while it was collecting fine, and _source_failure_guard
        # then excluded Ninja from coverage evaluation entirely.
        if source.platform not in _FETCHERS:
            continue
        if not source.source_binding_id or not source.entity_type:
            log.warning(
                "source_observations: %s has no operations binding — skipping",
                source.source_name,
            )
            continue
        try:
            rows = _FETCHERS[source.platform](source, observed_at)
            written = _write_observations(source, rows, batch_id, observed_at)
            counts[source.platform] = counts.get(source.platform, 0) + written
            _record_source_run(source, observed_at, ok=True, rows=written)
            log.info(
                "source_observations: source=%s written=%d", source.source_name, written
            )
        except Exception as exc:
            _record_source_run(
                source, observed_at, ok=False, rows=0, error=str(exc)[:2000]
            )
            log.exception(
                "source_observations: source %s failed — continuing", source.source_name
            )
    return counts


def _record_source_run(
    source: SourceConfig, started_at: datetime, ok: bool, rows: int, error: str = ""
) -> None:
    """Record the source run in operations.run_log (evaluator source guard)."""
    kind = f"source.{source.platform}.{source.source_key}".rstrip(".")[:80]
    try:
        with db.transaction() as cur:
            cur.execute(f"SET LOCAL operations.tenant_id = {_TENANT_ID}")
            cur.execute(
                """
                INSERT INTO operations.run_log
                    (id, tenant_id, kind, subject_ref, started_at, ended_at,
                     ok, rows, error)
                VALUES (gen_random_uuid(), %s, %s, '{}'::jsonb,
                        %s, NOW(), %s, %s, %s)
                """,
                (_TENANT_ID, kind, started_at, ok, rows, error),
            )
    except Exception:
        log.exception("source_observations: run_log write failed — continuing")


def _load_placeholder_names(cur) -> set[str]:
    """Placeholder container names live in data (Track C principle 4)."""
    cur.execute(
        "SELECT normalized_name FROM operations.placeholder_org_names"
        " WHERE tenant_id = %s",
        (_TENANT_ID,),
    )
    return {row[0] for row in cur.fetchall()}


def _load_client_links(cur, source: SourceConfig) -> dict[str, uuid.UUID]:
    """Return {external_id: client_id} for this source's attached groups.

    Reads `operations.v_client_source_link` over `entity_source_links`, which
    `sync_entity_source_links_from_observations()` derives from observation
    evidence at each collection boundary. The retired `client_links` table was
    written at the end of this same transaction, so this lookup has always
    served links established by earlier cycles; the derived table has the same
    staleness.
    """
    if not source.ops_source_id:
        return {}
    cur.execute(
        """
        SELECT external_id, client_id
        FROM operations.v_client_source_link
        WHERE tenant_id = %s AND source_id = %s
        """,
        (_TENANT_ID, source.ops_source_id),
    )
    return {row[0]: row[1] for row in cur.fetchall()}


# `_upsert_client_links` stood here. It minted a `client_links` row per
# resolved source group, and its docstring stated the competing authority
# plainly: "The link is the source of truth once created ... client_id is
# never reassigned by ingest." Migration 0123 retires that table; attachment
# follows observation evidence, which means a group that genuinely moves
# between clients now moves with it instead of being pinned by whichever
# cycle created the row first.


def _record_unmatched_groups(
    cur,
    source: SourceConfig,
    unmatched: dict[str, tuple[str, int]],
    placeholder_names: set[str],
) -> None:
    """Upsert operator-review rows for source groups that resolved no client."""
    if not source.ops_source_id:
        return
    for group_id, (group_name, device_count) in unmatched.items():
        if normalize_org_name(group_name) in placeholder_names:
            continue
        cur.execute(
            """
            INSERT INTO operations.unmatched_source_groups
                (tenant_id, source_id, external_id, external_name, device_count)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, source_id, external_id)
            DO UPDATE SET
                external_name = COALESCE(NULLIF(EXCLUDED.external_name, ''),
                                         operations.unmatched_source_groups.external_name),
                device_count  = EXCLUDED.device_count,
                last_seen_at  = now()
            """,
            (_TENANT_ID, source.ops_source_id, group_id, group_name or "", device_count),
        )


def _write_observations(
    source: SourceConfig,
    rows: list[dict[str, Any]],
    batch_id: uuid.UUID,
    observed_at: datetime,
) -> int:
    if not rows:
        return 0

    obs_rows: list[dict[str, Any]] = []
    resolved_groups: dict[str, tuple[uuid.UUID, str]] = {}  # group_id → (client, name)
    unmatched_groups: dict[str, tuple[str, int]] = {}       # group_id → (name, count)
    # group_id -> [name, count, external namespace, stable external id]
    all_groups: dict[str, list] = {}
    container_contracts: set[tuple[str, str]] = set()
    with db.transaction() as cur:
        cur.execute(f"SET LOCAL operations.tenant_id = {_TENANT_ID}")
        snapshot_scope = source.source_key or source.source_name
        run_id, source_instance_id = begin_run(
            cur, _TENANT_ID, source.source_binding_id, snapshot_scope,
            observed_at, expected_rows=len(rows),
        )
        if source_instance_id != source.source_instance_id:
            raise RuntimeError("source binding resolved to an unexpected source instance")
        link_map = _load_client_links(cur, source)
        placeholder_names = _load_placeholder_names(cur)
        for row in rows:
            if row.get("_org_only"):
                # Container-only record (e.g. a group with zero devices) —
                # registers the group for the org observation, no device row.
                gid = str(row.get("platform_group_id") or "").strip()
                gname = (row.get("platform_group_name") or "").strip()
                container_namespace = str(
                    row.get("container_external_namespace") or ""
                ).strip()
                container_external_id = str(
                    row.get("container_external_id") or gid
                ).strip()
                if not container_namespace or not container_external_id:
                    raise ValueError(
                        "container-only rows require a stable namespace and external ID"
                    )
                container_contracts.add(
                    (container_namespace, container_external_id)
                )
                if gid and gid not in all_groups:
                    all_groups[gid] = [
                        gname, 0, container_namespace, container_external_id
                    ]
                continue
            entity_key = str(row.get("platform_device_id") or "")
            if not entity_key:
                continue
            external_namespace = str(row.get("external_namespace") or "").strip()
            if not external_namespace:
                raise ValueError("connector row is missing external_namespace")
            hostname = row.get("hostname") or ""
            raw = row.get("raw_data") or {}
            if isinstance(raw, Json):
                raw = raw.obj  # connectors wrap payloads for the legacy writer
            if not isinstance(raw, dict):
                raw = {}
            guest_info = raw.get("GuestInfo") if isinstance(raw.get("GuestInfo"), dict) else {}
            serial = (
                raw.get("serialNumber")
                or raw.get("biosSerialNumber")
                or raw.get("serial_number")
                or guest_info.get("MachineSerialNumber")
                or None
            )
            os_name = row.get("os_name") or None
            canonical_data: dict[str, Any] = {
                "hostname":      hostname,
                "platform":      source.platform,
                "entity_type":   source.entity_type,
                # platform_group_id lets the client resolver backfill
                # device observations once the org attaches to a client.
                "platform_group_id": str(row.get("platform_group_id") or ""),
                "last_seen_at":  (
                    row["last_seen_at"].isoformat() if row.get("last_seen_at") else None
                ),
                "is_online":     row.get("is_online"),
                "serial_number": serial,
                "macs":          extract_macs(raw),
                # None when the source gives no explicit signal — never guessed.
                "device_role":   row.get("device_type"),
                "os_name":       os_name,
                # os_family() returns "Unknown" for a null os_name. Calling it
                # unconditionally turned that fallback into a source claim:
                # 7,920 claims of "Unknown" across two sources, winning
                # authority for 488 devices whose real family was known.
                # A source that states no OS asserts nothing about its family.
                "os_family":     os_family(os_name) if os_name else None,
                "domain":        row.get("domain_name"),
            }
            if raw.get("IsDup") is not None:
                canonical_data["is_dup"] = bool(raw["IsDup"])
            # Connectors may contribute source-specific canonical fields the
            # generic projection above cannot know about (e.g. an aggregator's
            # relay provenance). Applied last so a connector can correct a
            # field the generic extraction guessed wrong.
            extra = row.get("canonical_extra")
            if isinstance(extra, dict):
                canonical_data.update(extra)
            obs_hash = hashlib.sha256(
                f"{entity_key}:{observed_at.isoformat()}".encode()
            ).digest()

            group_id = str(row.get("platform_group_id") or "").strip()
            group_name = (row.get("platform_group_name") or "").strip()
            container_namespace = str(
                row.get("container_external_namespace") or ""
            ).strip()
            container_external_id = str(
                row.get("container_external_id") or group_id
            ).strip()
            if group_id or not source.is_shared:
                if not container_namespace or not container_external_id:
                    raise ValueError(
                        "connector row is missing its stable container identity"
                    )
                container_contracts.add(
                    (container_namespace, container_external_id)
                )

            # 1. Client-scoped instance wins.
            client_id = source.client_id
            # 2. client_links mapping on the source group.
            if client_id is None and group_id:
                client_id = link_map.get(group_id)

            if source.entity_type in identity_entity_types(cur):
                device_id = resolve_device_fast(
                    cur, _TENANT_ID, source.platform, entity_key,
                    entity_type=source.entity_type,
                    serial=serial,
                    hostname=normalize_hostname(hostname) or None,
                    client_id=client_id,
                )
            else:
                # Non-identity source: the connector already knows its device
                # (or knows it has none). Running the resolver here would let
                # a documentation record mint or merge canonical identity.
                device_id = row.get("resolved_device_id")
                if client_id is None:
                    client_id = row.get("resolved_client_id")
            # 3. Fall back to the resolved device's client.
            if client_id is None and device_id:
                cur.execute(
                    "SELECT client_id FROM operations.devices"
                    " WHERE id = %s AND deleted_at IS NULL",
                    (device_id,),
                )
                dev_row = cur.fetchone()
                client_id = dev_row[0] if dev_row else None

            if group_id or not source.is_shared:
                if client_id:
                    resolved_groups[group_id] = (client_id, group_name)
                elif group_id:
                    name, count = unmatched_groups.get(group_id, (group_name, 0))
                    unmatched_groups[group_id] = (name or group_name, count + 1)
            if group_id:
                entry = all_groups.setdefault(
                    group_id,
                    [group_name, 0, container_namespace, container_external_id],
                )
                if entry[2:] != [container_namespace, container_external_id]:
                    raise ValueError("connector emitted conflicting container identities")
                entry[0] = entry[0] or group_name
                entry[1] += 1

            obs_rows.append({
                "observation_id":        uuid.uuid4(),
                "tenant_id":             _TENANT_ID,
                "client_id":             client_id,
                "device_id":             device_id,
                "collector_instance_id": _INTERNAL_COLLECTOR_INSTANCE_ID,
                "source_binding_id":     source.source_binding_id,
                "source_instance_id":    source_instance_id,
                "last_seen_binding_id":  source.source_binding_id,
                "external_namespace":    external_namespace,
                "parent_external_namespace": "",
                "parent_external_id":    "",
                "external_id":           entity_key,
                "entity_type":           source.entity_type,
                "entity_key":            entity_key,
                "platform":              source.platform,
                "subplatform":           "",
                "observed_at":           observed_at,
                "raw_data":              Json(raw),
                "canonical_data":        Json(canonical_data),
                "batch_id":              batch_id,
                "observation_hash":      obs_hash,
                "collector_version":     "",
                "schema_version":        1,
            })

        # One `org` observation per container per run (BLUEPRINT Track C.2).
        # entity_key = stable group id (never the display name). Attachment
        # here is rung 1 only (existing id-link / client-scoped instance);
        # rungs 2-4 belong to the client resolver (C2).
        device_row_count = len(obs_rows)
        if not source.is_shared:
            if len(container_contracts) != 1:
                raise ValueError(
                    "client-scoped source must emit one stable container identity"
                )
            container_namespace, container_external_id = next(
                iter(container_contracts)
            )
            org_containers = {
                source.source_key or source.source_name: [
                    source.source_name, device_row_count,
                    container_namespace, container_external_id,
                ]
            }
        else:
            org_containers = all_groups
        for gid, (gname, gcount, container_namespace, container_external_id) in (
            org_containers.items()
        ):
            if not gid:
                continue
            org_client_id = (
                source.client_id if not source.is_shared else link_map.get(gid)
            )
            normalized = normalize_org_name(gname)
            obs_rows.append({
                "observation_id":        uuid.uuid4(),
                "tenant_id":             _TENANT_ID,
                "client_id":             org_client_id,
                "device_id":             None,
                "collector_instance_id": _INTERNAL_COLLECTOR_INSTANCE_ID,
                "source_binding_id":     source.source_binding_id,
                "source_instance_id":    source_instance_id,
                "last_seen_binding_id":  source.source_binding_id,
                "external_namespace":    container_namespace,
                "parent_external_namespace": "",
                "parent_external_id":    "",
                "external_id":           container_external_id,
                "entity_type":           "org",
                "entity_key":            gid,
                "platform":              source.platform,
                "subplatform":           "",
                "observed_at":           observed_at,
                "raw_data":              Json({}),
                "canonical_data":        Json({
                    "name":            gname,
                    "normalized_name": normalized,
                    "platform":        source.platform,
                    "entity_type":     "org",
                    "device_count":    gcount,
                    "is_placeholder":  normalized in placeholder_names,
                }),
                "batch_id":              batch_id,
                # entity_type prefixed so an org key can never collide with a
                # device key in the same batch.
                "observation_hash":      hashlib.sha256(
                    f"org:{gid}:{observed_at.isoformat()}".encode()
                ).digest(),
                "collector_version":     "",
                "schema_version":        1,
            })

        written = 0
        current_rows = []
        if obs_rows:
            for row in obs_rows:
                current = dict(row)
                current["parent_source_key"] = ""
                current["last_seen_at"] = row["observed_at"]
                current["last_received_at"] = row["observed_at"]
                current["active"] = True
                current["withdrawn_at"] = None
                current["snapshot_scope"] = snapshot_scope
                current["last_snapshot_run_id"] = run_id
                current["raw_hash"] = hashlib.sha256(
                    str(row["raw_data"]).encode("utf-8")
                ).digest()
                current_rows.append(current)
            written = write_current_rows(cur, current_rows)
        is_complete_snapshot = not getattr(source, "is_partial_snapshot", False)
        complete_run(
            cur,
            run_id,
            written,
            is_complete_snapshot=is_complete_snapshot,
            identity_rows=current_rows,
        )
        if is_complete_snapshot:
            reconcile_complete_run(cur, run_id)
            # A group is unmatched only if NO row in the batch resolved it.
            for gid in resolved_groups:
                unmatched_groups.pop(gid, None)
            _record_unmatched_groups(cur, source, unmatched_groups, placeholder_names)
    return len(obs_rows)
