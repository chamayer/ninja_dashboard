"""Ninja software inventory: complete lists in, set-based apply out.

Ninja's ``/queries/software`` returns a device's complete software list, for
one device, a set of devices (``df=id in (...)``) or the whole fleet, at about
0.1 s per device or 2.5-8 minutes for the fleet (measured 2026-10-13). Both
entry points use it:

* the **device worker** fetches the devices named by Ninja software events
  (added, removed, updated) in batches;
* the **fleet check** fetches every device once a day and catches anything the
  events missed.

Either way the response is a set of complete per-device lists. Pages stream
into a temporary table and are applied in a few statements in one transaction:

* new and changed installations are written and open a history interval;
* unchanged installations refresh their last-seen time;
* an installation a listed device no longer reports is **removed**: marked
  stale with when and why, and its history interval closed. Ninja is the
  authority, so removals apply directly;
* a device with no rows in the response did not report a list, so nothing of
  it is removed (absence of data is not removal);
* a device whose list suddenly shrinks sharply (an agent glitch, not a real
  uninstall wave) has its removals **held** until an administrator releases
  them; additions and changes still apply. The thresholds are settings.

Removals also require a complete response: if paging stopped before Ninja's
reported total, nothing is removed in that run.

Per device, ``operations.software_inventory_devices`` records when Ninja last
collected the list (the row ``timestamp``; measured to differ per device, from
under two hours to months, so it is the device's collection time), when we
received it, how many programs it held, and any hold.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ingest import db
from ingest.observations import MATERIAL_HASH_VERSION, material_hash
from ingest.runlog import run_log
from shared import software_settings

log = logging.getLogger(__name__)

TENANT_ID = 1
NINJA_SOURCE_BINDING_ID = uuid.UUID("00000000-0000-4000-8000-000000000011")
PAGE_SIZE = 5000
MAX_PAGES = 1000
_GUC = f"SET LOCAL operations.tenant_id = {TENANT_ID}"
REMOVED_REASON = "ninja.inventory.not_listed"

LISTING_COLUMNS = (
    "seq",
    "client_id",
    "device_id",
    "canonical_name",
    "publisher",
    "version",
    "install_location",
    "install_date",
    "product_code",
    "size_bytes",
    "is_system_component",
    "material_hash",
)
_LISTING_TYPES = (
    "int8",
    "uuid",
    "uuid",
    "text",
    "text",
    "text",
    "text",
    "text",
    "text",
    "int8",
    "bool",
    "bytea",
)


@dataclass
class ApplyResult:
    seen: int = 0
    unresolved: int = 0
    devices: int = 0
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    removed: int = 0
    held_devices: int = 0
    relinked: int = 0
    complete: bool = True

    @property
    def material_changed(self) -> bool:
        return bool(self.new or self.changed or self.removed or self.relinked)

    def summary(self) -> str:
        return (
            f"seen={self.seen} unresolved={self.unresolved} devices={self.devices} "
            f"new={self.new} changed={self.changed} unchanged={self.unchanged} "
            f"removed={self.removed} relinked={self.relinked} "
            f"held_devices={self.held_devices} complete={self.complete}"
        )

    def describe(self, scope: str) -> str:
        """One plain-English line for the Jobs pages."""
        if not self.devices:
            return f"{scope}: no computer reported a software list."
        text = (
            f"{scope}: {self.devices:,} computers refreshed. Programs: {self.new:,} new, "
            f"{self.changed:,} changed, {self.removed:,} removed, {self.unchanged:,} unchanged."
        )
        if self.relinked:
            text += f" {self.relinked:,} version links corrected."
        if self.held_devices:
            text += f" {self.held_devices:,} computers held for review."
        if self.unresolved:
            text += f" {self.unresolved:,} rows were on Ninja devices not linked to a computer."
        if not self.complete:
            text += " Ninja stopped early, so nothing was removed."
        return text

    def as_result(self, scope: str) -> dict[str, Any]:
        return {
            "summary": self.describe(scope),
            "computers": self.devices,
            "new": self.new,
            "changed": self.changed,
            "removed": self.removed,
            "unchanged": self.unchanged,
            "version_links_corrected": self.relinked,
            "held_computers": self.held_devices,
            "unlinked_rows": self.unresolved,
            "complete": self.complete,
        }


# ── Fetch ───────────────────────────────────────────────────────────


def pages(
    client: Any,
    params: Mapping[str, Any] | None = None,
    on_page: Callable[[int, int | None], None] | None = None,
) -> Iterator[tuple[list, bool]]:
    """Yield ``(results, complete)`` per page of ``/queries/software``.

    ``complete`` is true only on the final page, and only when paging reached
    Ninja's reported total. Unlike the shared pager, an early stop is reported,
    never silent, because removals depend on it.
    """
    cursor_name: str | None = None
    received = 0
    last_offset = -1
    # Ninja's last page can come back empty without a cursor, so the total it
    # reported on earlier pages is what completeness is measured against.
    known_total: int | None = None
    for _ in range(MAX_PAGES):
        query = dict(params or {})
        query["pageSize"] = PAGE_SIZE
        if cursor_name is not None:
            query["cursor"] = cursor_name
        response = client.get("/queries/software", query) or {}
        results = response.get("results") or []
        received += len(results)
        cursor = response.get("cursor") or {}
        offset, total, name = (
            cursor.get("offset"),
            cursor.get("count"),
            cursor.get("name"),
        )
        if total is not None:
            known_total = total
        reached = known_total is None or received >= known_total
        if on_page is not None:
            on_page(received, known_total)
        if not results or not name:
            yield results, reached
            return
        if total is not None and offset is not None and offset + len(results) >= total:
            yield results, reached
            return
        if offset is not None and offset <= last_offset:
            log.warning(
                "inventory.software: cursor offset stalled at %s; stopping", offset
            )
            yield results, False
            return
        if offset is not None:
            last_offset = offset
        cursor_name = name
        yield results, False
    log.warning(
        "inventory.software: page cap %d reached after %d rows", MAX_PAGES, received
    )
    yield [], False


def collected_time(value: Any) -> datetime | None:
    """Ninja's per-row collection time (epoch seconds or milliseconds)."""
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if number > 1e11:
        number /= 1000
    return datetime.fromtimestamp(number, tz=UTC)


def normalize(item: Mapping[str, Any]) -> dict[str, Any] | None:
    """One Ninja row as an installation; None when it names no software."""
    name = (item.get("name") or "").strip()
    if not name:
        return None
    # The hash decides whether an installation materially changed. It must stay
    # byte-identical to every earlier hash, so the four fields keep exactly the
    # previous normalization (install_date is the raw value). product_code,
    # size_bytes and is_system_component describe the product, not the
    # installation, and are deliberately not part of it (migration 091).
    material = {
        "publisher": (item.get("publisher") or "").strip() or None,
        "version": (item.get("version") or "").strip() or None,
        "location": (item.get("location") or "").strip() or None,
        "install_date": item.get("installDate"),
    }
    install_date = material["install_date"]
    return {
        "canonical_name": name.lower(),
        "publisher": material["publisher"],
        "version": material["version"],
        "install_location": material["location"],
        "install_date": str(install_date) if install_date not in (None, "") else None,
        "product_code": (item.get("productCode") or "").strip() or None,
        "size_bytes": item.get("size") or None,
        "is_system_component": item.get("isSystemComponent"),
        "material_hash": material_hash(material),
    }


@dataclass
class _Stream:
    seen: int = 0
    unresolved: int = 0
    complete: bool = False


def stream_rows(
    batches: Iterable[tuple[list, bool]],
    device_map: Mapping[str, tuple[uuid.UUID, uuid.UUID]],
    collected: dict[uuid.UUID, datetime],
    stream: _Stream,
) -> Iterator[tuple]:
    """Resolved rows in ``LISTING_COLUMNS`` order; per-device collection times."""
    seq = 0
    for results, complete in batches:
        stream.complete = complete
        for item in results:
            stream.seen += 1
            resolution = device_map.get(str(item.get("deviceId", "")))
            if resolution is None:
                stream.unresolved += 1
                continue
            row = normalize(item)
            if row is None:
                continue
            device_id, client_id = resolution
            stamp = collected_time(item.get("timestamp"))
            if stamp is not None and (
                device_id not in collected or stamp > collected[device_id]
            ):
                collected[device_id] = stamp
            seq += 1
            yield (seq, client_id, device_id, *(row[c] for c in LISTING_COLUMNS[3:]))


# ── Removal guard ──────────────────────────────────────────────────


def hold_reason(
    previous: Mapping[str, Any] | None, listed: int, cfg: Mapping[str, Any]
) -> str:
    """Why this device's removals must wait, or '' when they apply.

    A device seen for the first time has no confirmed list to compare with, so
    nothing is held (the first fleet check applies removals directly, as
    decided). A release requested after the hold lets the next list apply.
    """
    if not previous:
        return ""
    held_at = previous.get("held_at")
    released = previous.get("release_requested_at")
    if released is not None and (held_at is None or released >= held_at):
        return ""
    before = int(previous.get("listed_count") or 0)
    minimum = int(cfg["inventory_hold_min_programs"])
    shrink = int(cfg["inventory_hold_shrink_percent"])
    if before < minimum or listed * 100 > before * (100 - shrink):
        return ""
    return (
        f"Ninja listed {listed} programs; the previous list had {before}. "
        f"Removals wait for an administrator because the list shrank by "
        f"{shrink}% or more."
    )


# ── Apply ──────────────────────────────────────────────────────────

LISTING_SQL = """
CREATE TEMP TABLE inventory_listing ON COMMIT DROP AS
SELECT DISTINCT ON (device_id, canonical_name) *
  FROM inventory_raw
 ORDER BY device_id, canonical_name, seq DESC
"""

DEVICE_COUNTS_SQL = """
SELECT l.device_id, COUNT(*), s.listed_count, s.held_at, s.release_requested_at
  FROM inventory_listing l
  LEFT JOIN operations.software_inventory_devices s
    ON s.tenant_id = %(tenant_id)s AND s.device_id = l.device_id
 GROUP BY l.device_id, s.listed_count, s.held_at, s.release_requested_at
"""

REMOVE_SQL = """
WITH removed AS (
    UPDATE operations.software_installations_current c
       SET stale_since = %(at)s, stale_reason = %(reason)s, refreshed_at = %(at)s
      FROM inventory_devices d
     WHERE d.removals_allowed
       AND c.tenant_id = %(tenant_id)s AND c.device_id = d.device_id
       AND c.stale_since IS NULL AND c.deleted_at IS NULL
       AND NOT EXISTS (
           SELECT 1 FROM inventory_listing l
            WHERE l.device_id = c.device_id AND l.client_id = c.client_id
              AND l.canonical_name = c.canonical_name)
    RETURNING c.client_id, c.device_id, c.canonical_name
), closed AS (
    UPDATE operations.software_installation_history h
       SET effective_to = %(at)s, active = FALSE
      FROM removed r
     WHERE h.tenant_id = %(tenant_id)s AND h.source_binding_id = %(binding)s
       AND h.client_id = r.client_id AND h.device_id = r.device_id
       AND h.canonical_name = r.canonical_name AND h.effective_to IS NULL
    RETURNING 1
)
, targeted AS (
    INSERT INTO operations.software_reclassification_targets AS target
        (tenant_id, target_key, canonical_name, source)
    SELECT DISTINCT %(tenant_id)s, left('name:' || lower(canonical_name), 300), lower(canonical_name), 'inventory'
      FROM removed
     WHERE canonical_name <> ''
    ON CONFLICT (tenant_id, target_key, source) WHERE consumed_at IS NULL
    DO UPDATE SET generation = target.generation + 1
    RETURNING 1
)
SELECT (SELECT COUNT(*) FROM removed)
"""

# The stored rows are read for the listed computers first. Joined directly, the
# planner looks each installation up through the (client, title) index and
# filters out the client's other computers: 4.3 s and ~1.2M page reads per batch
# of 100 computers, against 0.36 s this way (measured 2026-10-13).
DELTA_SQL = """
CREATE TEMP TABLE inventory_delta ON COMMIT DROP AS
WITH stored AS MATERIALIZED (
    SELECT c.client_id, c.device_id, c.canonical_name, c.material_hash, c.stale_since
      FROM operations.software_installations_current c
     WHERE c.tenant_id = %(tenant_id)s
       AND c.device_id IN (SELECT device_id FROM inventory_devices)
)
SELECT l.*,
       CASE WHEN c.device_id IS NULL THEN 'new'
            WHEN c.material_hash IS DISTINCT FROM l.material_hash
              OR c.stale_since IS NOT NULL THEN 'changed'
            ELSE 'unchanged' END AS kind
  FROM inventory_listing l
  LEFT JOIN stored c
    ON c.client_id = l.client_id AND c.device_id = l.device_id
   AND c.canonical_name = l.canonical_name
"""

KIND_COUNTS_SQL = "SELECT kind, COUNT(*) FROM inventory_delta GROUP BY kind"

HISTORY_SQL = """
WITH closed AS (
    UPDATE operations.software_installation_history h
       SET effective_to = %(at)s, active = FALSE
      FROM inventory_delta d
     WHERE d.kind <> 'unchanged'
       AND h.tenant_id = %(tenant_id)s AND h.source_binding_id = %(binding)s
       AND h.device_id = d.device_id AND h.canonical_name = d.canonical_name
       AND h.effective_to IS NULL
    RETURNING 1
), seen AS (
    UPDATE operations.software_installation_history h
       SET last_seen_at = %(at)s, received_at = %(at)s
      FROM inventory_delta d
     WHERE d.kind = 'unchanged'
       AND h.tenant_id = %(tenant_id)s AND h.source_binding_id = %(binding)s
       AND h.client_id = d.client_id AND h.device_id = d.device_id
       AND h.canonical_name = d.canonical_name AND h.effective_to IS NULL
    RETURNING 1
)
SELECT (SELECT COUNT(*) FROM closed), (SELECT COUNT(*) FROM seen)
"""

OPEN_INTERVALS_SQL = """
INSERT INTO operations.software_installation_history (
    id, tenant_id, source_binding_id, client_id, device_id, canonical_name,
    publisher, version, install_location, install_date, material_hash,
    hash_algorithm_version, effective_from, effective_to, last_seen_at,
    received_at, active)
SELECT gen_random_uuid(), %(tenant_id)s, %(binding)s, d.client_id, d.device_id,
       d.canonical_name, d.publisher, d.version, d.install_location,
       d.install_date::date, d.material_hash, %(hash_version)s,
       %(at)s, NULL, %(at)s, %(at)s, TRUE
  FROM inventory_delta d
 WHERE d.kind <> 'unchanged'
"""

CURRENT_SQL = """
INSERT INTO operations.software_installations_current AS c (
    tenant_id, client_id, device_id, canonical_name, publisher, version,
    install_location, install_date, product_code, size_bytes, is_system_component,
    first_observed_at, last_observed_at, refreshed_at, stale_since, stale_reason,
    material_hash, hash_algorithm_version)
SELECT %(tenant_id)s, d.client_id, d.device_id, d.canonical_name, d.publisher,
       d.version, d.install_location, d.install_date::date,
       d.product_code, d.size_bytes, d.is_system_component,
       %(at)s, %(at)s, %(at)s, NULL, '', d.material_hash, %(hash_version)s
  FROM inventory_delta d
ON CONFLICT (tenant_id, client_id, device_id, canonical_name) DO UPDATE SET
    publisher = EXCLUDED.publisher,
    version = EXCLUDED.version,
    install_location = EXCLUDED.install_location,
    install_date = EXCLUDED.install_date,
    product_code = EXCLUDED.product_code,
    size_bytes = EXCLUDED.size_bytes,
    is_system_component = EXCLUDED.is_system_component,
    last_observed_at = EXCLUDED.last_observed_at,
    refreshed_at = EXCLUDED.refreshed_at,
    stale_since = NULL,
    stale_reason = '',
    material_hash = EXCLUDED.material_hash,
    hash_algorithm_version = EXCLUDED.hash_algorithm_version
"""

# A catalog link names one version. When the installed version changes, the old
# link would keep pointing at the previous version (measured 2026-10-13: 166,310
# of 586,435 live installations), so version-level findings and exposure read
# the wrong version. Clearing it lets the catalog projection, which links every
# unlinked installation by its current version, relink it in the same run.
RELINK_SQL = """
WITH relinked AS (
    UPDATE operations.software_installations_current c
       SET software_version_id = NULL
      FROM catalog.software_versions v
     WHERE c.tenant_id = %(tenant_id)s
       AND c.device_id IN (SELECT device_id FROM inventory_devices)
       AND v.id = c.software_version_id
       AND v.version IS DISTINCT FROM COALESCE(c.version, '')
    RETURNING c.canonical_name
), targeted AS (
    INSERT INTO operations.software_reclassification_targets AS target
        (tenant_id, target_key, canonical_name, source)
    SELECT DISTINCT %(tenant_id)s, left('name:' || lower(canonical_name), 300), lower(canonical_name), 'inventory'
      FROM relinked
     WHERE canonical_name <> ''
    ON CONFLICT (tenant_id, target_key, source) WHERE consumed_at IS NULL
    DO UPDATE SET generation = target.generation + 1
    RETURNING 1
)
SELECT (SELECT COUNT(*) FROM relinked)
"""

# The change feed for the software findings run: every title with a new or
# changed installation (removals and relinks are recorded by their own
# statements). The findings run reconciles only these titles.
# A change for a title already pending bumps its generation instead of being
# dropped, so a findings run that captured the row earlier cannot acknowledge
# it (PLAN-017 U04, migration 0349).
CHANGED_TITLES_SQL = """
INSERT INTO operations.software_reclassification_targets AS target
        (tenant_id, target_key, canonical_name, source)
    SELECT DISTINCT %(tenant_id)s, left('name:' || lower(canonical_name), 300), lower(canonical_name), 'inventory'
      FROM inventory_delta
     WHERE kind <> 'unchanged' AND canonical_name <> ''
    ON CONFLICT (tenant_id, target_key, source) WHERE consumed_at IS NULL
    DO UPDATE SET generation = target.generation + 1
    RETURNING 1
"""

DEVICES_SQL = """
INSERT INTO operations.software_inventory_devices AS s (
    tenant_id, device_id, collected_at, listed_at, listed_count, listed_by,
    held_at, held_reason, held_listed_count, held_previous_count,
    release_requested_at, release_requested_by)
SELECT %(tenant_id)s, d.device_id, d.collected_at, %(at)s, d.listed_count, %(listed_by)s,
       CASE WHEN d.hold_reason = '' THEN NULL ELSE %(at)s::timestamptz END,
       d.hold_reason,
       CASE WHEN d.hold_reason = '' THEN NULL ELSE d.listed_count END,
       NULL, NULL, ''
  FROM inventory_devices d
ON CONFLICT (tenant_id, device_id) DO UPDATE SET
    collected_at = COALESCE(EXCLUDED.collected_at, s.collected_at),
    listed_at = EXCLUDED.listed_at,
    listed_by = EXCLUDED.listed_by,
    -- A held device keeps its last confirmed count, so the next list is
    -- compared with it again and the hold persists until released.
    listed_count = CASE WHEN EXCLUDED.held_reason = '' THEN EXCLUDED.listed_count
                        ELSE s.listed_count END,
    held_at = CASE WHEN EXCLUDED.held_reason = '' THEN NULL
                   ELSE COALESCE(s.held_at, EXCLUDED.held_at) END,
    held_reason = EXCLUDED.held_reason,
    held_listed_count = EXCLUDED.held_listed_count,
    held_previous_count = CASE WHEN EXCLUDED.held_reason = '' THEN NULL
                               ELSE s.listed_count END,
    release_requested_at = CASE WHEN EXCLUDED.held_reason = '' THEN NULL
                                ELSE s.release_requested_at END,
    release_requested_by = CASE WHEN EXCLUDED.held_reason = '' THEN ''
                                ELSE s.release_requested_by END
"""


def _load_settings(cur: Any) -> dict[str, Any]:
    cur.execute(
        "SELECT config FROM operations.evaluator_config "
        "WHERE tenant_id = %s AND evaluator_name = 'software_classifier'",
        (TENANT_ID,),
    )
    row = cur.fetchone()
    return software_settings.effective(
        row[0] if row and isinstance(row[0], dict) else {}
    )


def device_decisions(
    counts: Iterable[tuple], complete: bool, cfg: Mapping[str, Any]
) -> list[tuple[uuid.UUID, int, bool, str]]:
    """``(device, listed, removals_allowed, hold_reason)`` per listed device."""
    decisions = []
    for device_id, listed, before, held_at, released in counts:
        previous = (
            None
            if before is None
            else {
                "listed_count": before,
                "held_at": held_at,
                "release_requested_at": released,
            }
        )
        reason = hold_reason(previous, int(listed), cfg)
        decisions.append((device_id, int(listed), complete and not reason, reason))
    return decisions


def apply(
    batches: Iterable[tuple[list, bool]],
    device_map: Mapping[str, tuple[uuid.UUID, uuid.UUID]],
    *,
    listed_by: str,
    observed_at: datetime | None = None,
) -> ApplyResult:
    """Stream Ninja pages into a temp table and apply them in one transaction."""
    at = observed_at or datetime.now(UTC)
    params = {
        "tenant_id": TENANT_ID,
        "binding": NINJA_SOURCE_BINDING_ID,
        "at": at,
        "reason": REMOVED_REASON,
        "hash_version": MATERIAL_HASH_VERSION,
        "listed_by": listed_by,
    }
    collected: dict[uuid.UUID, datetime] = {}
    stream = _Stream()
    result = ApplyResult()
    with db.transaction() as cur:
        cur.execute(_GUC)
        cfg = _load_settings(cur)
        cur.execute(
            "CREATE TEMP TABLE inventory_raw (seq bigint, client_id uuid, device_id uuid, "
            "canonical_name text, publisher text, version text, install_location text, "
            "install_date text, product_code text, size_bytes bigint, "
            "is_system_component boolean, material_hash bytea) ON COMMIT DROP"
        )
        with cur.copy(
            f"COPY inventory_raw ({', '.join(LISTING_COLUMNS)}) FROM STDIN"
        ) as copy:
            copy.set_types(list(_LISTING_TYPES))
            for row in stream_rows(batches, device_map, collected, stream):
                copy.write_row(row)
        result.seen, result.unresolved = stream.seen, stream.unresolved
        result.complete = stream.complete
        cur.execute(LISTING_SQL)
        cur.execute(
            "CREATE INDEX ON inventory_listing (device_id, client_id, canonical_name)"
        )
        cur.execute("ANALYZE inventory_listing")
        cur.execute(DEVICE_COUNTS_SQL, params)
        decisions = device_decisions(cur.fetchall(), stream.complete, cfg)
        if not decisions:
            return result
        result.devices = len(decisions)
        result.held_devices = sum(1 for decision in decisions if decision[3])
        cur.execute(
            "CREATE TEMP TABLE inventory_devices (device_id uuid PRIMARY KEY, "
            "collected_at timestamptz, listed_count integer, removals_allowed boolean, "
            "hold_reason text) ON COMMIT DROP"
        )
        with cur.copy(
            "COPY inventory_devices (device_id, collected_at, listed_count, "
            "removals_allowed, hold_reason) FROM STDIN"
        ) as copy:
            copy.set_types(["uuid", "timestamptz", "int4", "bool", "text"])
            for device_id, listed, allowed, reason in decisions:
                copy.write_row(
                    (device_id, collected.get(device_id), listed, allowed, reason)
                )
        cur.execute("ANALYZE inventory_devices")

        # Removals first: a device that moved client lists its titles under the
        # new client, and the old client's rows close before new intervals open.
        cur.execute(REMOVE_SQL, params)
        result.removed = int(cur.fetchone()[0])
        cur.execute(DELTA_SQL, params)
        cur.execute(KIND_COUNTS_SQL)
        kinds = dict(cur.fetchall())
        result.new = int(kinds.get("new", 0))
        result.changed = int(kinds.get("changed", 0))
        result.unchanged = int(kinds.get("unchanged", 0))
        cur.execute(HISTORY_SQL, params)
        cur.execute(OPEN_INTERVALS_SQL, params)
        cur.execute(CURRENT_SQL, params)
        cur.execute(RELINK_SQL, params)
        result.relinked = int(cur.fetchone()[0])
        cur.execute(CHANGED_TITLES_SQL, params)
        cur.execute(DEVICES_SQL, params)
    log.info("inventory.software apply (%s): %s", listed_by, result.summary())
    return result


# ── Entry points ───────────────────────────────────────────────────


def load_device_map() -> dict[str, tuple[uuid.UUID, uuid.UUID]]:
    with db.transaction() as cur:
        cur.execute(_GUC)
        cur.execute(
            """
            SELECT dl.external_id, dl.device_id, d.client_id
              FROM operations.v_device_source_link dl
              JOIN operations.devices d ON d.id = dl.device_id
              JOIN operations.sources s ON s.id = dl.source_id AND s.name = 'Ninja'
             WHERE dl.tenant_id = %s AND d.deleted_at IS NULL
            """,
            (TENANT_ID,),
        )
        return {
            external_id: (device_id, client_id)
            for external_id, device_id, client_id in cur.fetchall()
        }


def fleet_check(
    client: Any, count: Callable[[int, int | None, str], None] | None = None
) -> ApplyResult:
    """Fetch and apply every device's list (the daily completeness check).

    ``count`` receives (rows received, Ninja's reported total, unit) per page.
    """
    with run_log("inventory.software") as stats:
        device_map = load_device_map()
        if not device_map:
            raise RuntimeError(
                "No Ninja-linked computers; the fleet check has nothing to map"
            )
        on_page = (
            None
            if count is None
            else lambda received, total: count(
                received, total, "software rows from Ninja"
            )
        )
        result = apply(pages(client, on_page=on_page), device_map, listed_by="fleet")
        stats["rows_upserted"] = result.new + result.changed + result.unchanged
        stats["rows_inserted"] = result.new
        log.info("inventory.software fleet check: %s", result.summary())
        if not result.complete:
            raise RuntimeError(
                "Ninja paging stopped before its reported total; additions and changes "
                "were applied, removals were not."
            )
        return result


FRESHNESS_SQL = """
SELECT count(*) FILTER (WHERE s.collected_at >= now() - interval '24 hours'),
       count(*) FILTER (WHERE s.collected_at < now() - interval '24 hours'
                          AND s.collected_at >= now() - interval '7 days'),
       count(*) FILTER (WHERE s.collected_at < now() - interval '7 days'),
       count(*) FILTER (WHERE s.collected_at IS NULL),
       (SELECT count(DISTINCT i.device_id)
          FROM operations.software_installations_current i
         WHERE i.tenant_id = %(tenant_id)s AND i.deleted_at IS NULL AND i.stale_since IS NULL
           AND NOT EXISTS (SELECT 1 FROM operations.software_inventory_devices d
                            WHERE d.tenant_id = i.tenant_id AND d.device_id = i.device_id
                              AND d.listed_at >= %(since)s))
  FROM operations.software_inventory_devices s
 WHERE s.tenant_id = %(tenant_id)s AND s.listed_at >= %(since)s
"""


def freshness(since: datetime) -> dict[str, int]:
    """How old Ninja's lists were for the computers listed since ``since``.

    Also counts computers that still have installed software but sent no list,
    which keep their inventory (absence of data is not removal).
    """
    with db.transaction() as cur:
        cur.execute(_GUC)
        cur.execute(FRESHNESS_SQL, {"tenant_id": TENANT_ID, "since": since})
        within_day, within_week, older, unknown, silent = cur.fetchone()
    return {
        "collected_within_24h": int(within_day),
        "collected_1_to_7_days": int(within_week),
        "collected_over_7_days": int(older),
        "collected_unknown": int(unknown),
        "computers_not_reporting": int(silent),
    }


def describe_freshness(stats: Mapping[str, int]) -> str:
    listed = sum(
        stats[key]
        for key in (
            "collected_within_24h",
            "collected_1_to_7_days",
            "collected_over_7_days",
            "collected_unknown",
        )
    )
    if not listed:
        return ""
    text = (
        f"Ninja had collected {stats['collected_within_24h'] * 100 // listed}% of these lists "
        f"within 24 hours; {stats['collected_over_7_days']:,} were over 7 days old."
    )
    if stats["computers_not_reporting"]:
        text += (
            f" {stats['computers_not_reporting']:,} computers with installed software sent no "
            "list and keep their inventory."
        )
    return text


def device_filter(ninja_device_ids: Iterable[int]) -> str:
    return "id in (" + ",".join(str(int(value)) for value in ninja_device_ids) + ")"


def device_refresh(
    client: Any,
    ninja_device_ids: list[int],
    device_map: Mapping[str, tuple[uuid.UUID, uuid.UUID]],
) -> ApplyResult:
    """Fetch and apply the lists of the given Ninja devices in one request."""
    result = apply(
        pages(client, {"df": device_filter(ninja_device_ids)}),
        device_map,
        listed_by="device",
    )
    if not result.complete:
        raise RuntimeError(
            "Ninja paging stopped before its reported total; removals were not applied."
        )
    return result


def refresh_read_models() -> None:
    """Publish compact Software read models, then project the catalog.

    Both inventory entry points call this once per run, and only when the run
    changed something.

    The catalog projection runs *after* the matview refresh deliberately: it
    is newer, and a fault in it must not stop the established read models from
    publishing. Its own failure is raised rather than swallowed, and
    `run_log('software.catalog')` records the outcome either way.
    """
    for relation in (
        "operations.software_title_current",
        "operations.v_software_safety",
    ):
        with db.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {relation}")
        log.info("Refreshed materialized view %s", relation)

    # Imported here rather than at module scope: `software_catalog` reads this
    # table, and a top-level import would make the dependency circular.
    from ingest.software_catalog import project_software_catalog

    project_software_catalog()
    # Lifecycle facts are a projection of both the upstream corpus and the
    # local catalog. The scheduled corpus job covers the former; run the
    # same non-fetching projector here so newly observed versions are not left
    # waiting for the next corpus interval.
    try:
        from ingest.intel import eol_match

        eol_match.run_once()
    except Exception:
        log.exception("End-of-life projection after software catalog refresh failed")


def refresh_exposure_read_model() -> None:
    """Publish classified device/software exposure eligibility.

    Findings, source evidence, and condition assessments are the inputs.  This
    must run only after a successful classifier pass; approvals deliberately
    remain a live filter in ``v_device_software_exposure`` and need no refresh.
    """
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "REFRESH MATERIALIZED VIEW CONCURRENTLY "
            "operations.device_software_exposure_current"
        )
    log.info("Refreshed operations.device_software_exposure_current")
