"""Hudu documentation-platform collector.

Hudu is a source *and* an aggregator: each asset carries `cards[]` holding
other vendors' records verbatim (Ninja, Auvik). Ninja is already an
aggregator in the same sense (`ingest/core/devices.py`) — Hudu's only extra
axis is that the originating vendor differs from the collecting one.

Consequences, all measured (see `.work/plan.md`):

* Hudu contributes no independent identity evidence. A card is a *pointer*
  ("I am Ninja device 296"), so device attachment is a direct lookup and this
  connector never participates in identity resolution or `device_links`.
* Cards are resolved and clustered on the resulting `device_id`, never on
  names: a Hyper-V VM object is named independently of its guest OS
  (`QB`/`QBSERVER`), so name comparison yields confident wrong answers.
* Cards that no longer resolve are superseded Ninja records, not errors.
* Relayed vendors that Operations does not ingest directly stay second-hand:
  recorded, never promoted to first-party evidence.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx
from psycopg.types.json import Json

from ingest.device_map import load_device_map
from ingest.sources import SourceConfig

log = logging.getLogger(__name__)

_PAGE_SIZE = 100
# Safety bound. 12k assets ≈ 122 pages today; a runaway pager means Hudu is
# ignoring `page`, and silently looping forever is worse than failing.
_MAX_PAGES = 400
_TIMEOUT = 60

# Excluded by policy, not by allowlist: People records are personal data and
# deliver nothing until a Users surface exists. The exclusion is reported in
# the run summary so it stays visible rather than silently absent.
_EXCLUDED_LAYOUTS = {"people"}

# Vendors Operations ingests directly. A card from anything else is
# second-hand: kept and marked, never treated as first-party evidence.
_INTEGRATED_VENDORS = {"ninja"}


def fetch(source: SourceConfig, observed_at: datetime) -> list[dict]:
    if not source.base_url or not source.api_token:
        raise RuntimeError("Hudu source requires base_url and api_token_secret_ref")

    base_url = source.base_url.rstrip("/")
    headers = {"X-Api-Key": source.api_token, "Accept": "application/json"}

    # Resolved once per run: every card lookup is served from memory.
    ninja_map = load_device_map("Ninja")

    with httpx.Client(timeout=_TIMEOUT, headers=headers) as client:
        layouts = _fetch_layouts(client, base_url)
        excluded_ids = {
            lid for lid, name in layouts.items() if name.strip().lower() in _EXCLUDED_LAYOUTS
        }
        assets = _fetch_assets(client, base_url)

    observations: list[dict] = []
    skipped_excluded = 0
    stats = {"linked": 0, "divergent": 0, "stale": 0, "unlinked": 0}
    unintegrated: dict[str, int] = {}

    for asset in assets:
        if asset.get("asset_layout_id") in excluded_ids:
            skipped_excluded += 1
            continue

        relayed, verdict, device_id, client_id = _resolve_cards(asset, ninja_map)
        for entry in relayed:
            if not entry["integrated"]:
                unintegrated[entry["source"]] = unintegrated.get(entry["source"], 0) + 1

        stats[verdict] = stats.get(verdict, 0) + 1
        layout_id = asset.get("asset_layout_id")

        observations.append({
            "observed_at": observed_at,
            "platform": "Hudu",
            "source_id": source.source_id,
            "source_name": source.source_name,
            "source_client_name": source.client_name,
            # Hudu company drives client resolution through the existing
            # client_links / org-container machinery — no bespoke path.
            "platform_group_name": asset.get("company_name") or "",
            "platform_group_id": str(asset.get("company_id") or ""),
            "platform_device_id": str(asset.get("id") or ""),
            "hostname": asset.get("name") or "",
            "device_type": None,   # never inferred; Hudu states no role
            "os_name": None,
            "domain_name": None,
            "is_online": None,
            "last_seen_at": None,
            # Honoured because doc.asset is not an identity-signal type.
            "resolved_device_id": device_id,
            "resolved_client_id": client_id,
            "canonical_extra": {
                "hudu_layout_id": layout_id,
                "hudu_layout": layouts.get(layout_id) or "",
                "hudu_url": asset.get("url") or "",
                "archived": bool(asset.get("archived")),
                "serial_number": (asset.get("primary_serial") or None),
                "link_verdict": verdict,
                "provenance": _provenance(relayed),
                "relayed": relayed,
            },
            "raw_data": Json(asset),
        })

    log.info(
        "hudu: assets=%d observed=%d excluded_people=%d linked=%d divergent=%d "
        "stale=%d unlinked=%d unintegrated=%s",
        len(assets), len(observations), skipped_excluded,
        stats["linked"], stats["divergent"], stats["stale"], stats["unlinked"],
        unintegrated or "{}",
    )
    return observations


def _fetch_layouts(client: httpx.Client, base_url: str) -> dict[int, str]:
    resp = client.get(f"{base_url}/api/v1/asset_layouts")
    resp.raise_for_status()
    payload = resp.json() or {}
    return {
        int(row["id"]): row.get("name") or ""
        for row in (payload.get("asset_layouts") or [])
        if row.get("id") is not None
    }


def _fetch_assets(client: httpx.Client, base_url: str) -> list[dict]:
    """Fetch every asset across all layouts.

    Raises on any page failure. A partial fetch must never reach the writer:
    the caller treats a successful return as a complete snapshot and would
    otherwise reconcile absence against missing pages.
    """
    assets: list[dict] = []
    for page in range(1, _MAX_PAGES + 1):
        resp = client.get(
            f"{base_url}/api/v1/assets",
            params={"page": page, "page_size": _PAGE_SIZE},
        )
        resp.raise_for_status()
        batch = (resp.json() or {}).get("assets") or []
        assets.extend(batch)
        if len(batch) < _PAGE_SIZE:
            return assets
    raise RuntimeError(
        f"Hudu asset pagination exceeded {_MAX_PAGES} pages — refusing partial snapshot"
    )


def _resolve_cards(
    asset: dict,
    ninja_map: dict[str, tuple[Any, Any]],
) -> tuple[list[dict], str, Any, Any]:
    """Resolve integrator cards to a device.

    Returns (relayed, verdict, device_id, client_id). Verdict is one of
    `linked`, `divergent`, `stale`, `unlinked`.
    """
    relayed: list[dict] = []
    devices: dict[Any, Any] = {}   # device_id -> client_id
    saw_integrated_card = False

    for card in asset.get("cards") or []:
        vendor = (card.get("integrator_name") or "").strip().lower()
        if not vendor:
            continue
        # Ninja keys on integer sync_id; Auvik leaves it null and uses the
        # string sync_identifier. Both are the vendor's own primary key.
        key = card.get("sync_id") or card.get("sync_identifier")
        if key is None:
            continue
        key = str(key)
        sync_type = (card.get("sync_type") or "").strip().lower()
        # Ninja emits location cards alongside device cards, and its location
        # ids live in a SEPARATE namespace from device ids — location 1 and
        # device 1 are unrelated. Resolving a non-device card against the
        # device map silently attaches documentation to an arbitrary machine
        # (observed: a Hudu "Main Office" record linked to device hyperv-lab).
        # Non-device cards stay recorded as relay evidence but never resolve.
        is_device_card = sync_type == "device"
        integrated = vendor in _INTEGRATED_VENDORS
        resolved_device = None

        if integrated and is_device_card:
            saw_integrated_card = True
            hit = ninja_map.get(key) if vendor == "ninja" else None
            if hit:
                resolved_device, resolved_client = hit
                devices[resolved_device] = resolved_client

        relayed.append({
            "source": vendor,
            "key": key,
            "sync_type": sync_type,
            "integrated": integrated,
            "resolved_device_id": str(resolved_device) if resolved_device else None,
        })

    if len(devices) == 1:
        device_id, client_id = next(iter(devices.items()))
        return relayed, "linked", device_id, client_id
    if len(devices) > 1:
        # One page documenting two machines. Attaching either would be a
        # guess, so attach neither and let the finding carry the conflict.
        return relayed, "divergent", None, None
    if saw_integrated_card:
        # Had first-party pointers, none survive: the documented machine is
        # gone from its managing source.
        return relayed, "stale", None, None
    return relayed, "unlinked", None, None


def _provenance(relayed: list[dict]) -> str:
    """`second_hand` only when every relay is from an unintegrated vendor.

    Derived rather than stored as a scalar: 178 assets carry cards from two
    vendors at once, so a single column cannot express this without silently
    omitting them.
    """
    if relayed and all(not entry["integrated"] for entry in relayed):
        return "second_hand"
    return "first_party"
