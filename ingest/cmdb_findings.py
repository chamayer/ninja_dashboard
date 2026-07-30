"""Findings derived from CMDB observations (Hudu today).

Standalone rather than folded into `ingest/evaluator.py`: this reads
`cmdb.asset` observations only and writes only `operations.findings`, so it
cannot affect device identity, promotion, or any existing evaluator path.

Four conditions, all keyed off `canonical_data->>'link_verdict'`, which the
connector already computes and which was verified against production:

    linked      the page resolves to exactly one device        -> no finding
    stale       had source links, none resolve any more        -> cmdb_asset_stale
    divergent   resolves to 2+ devices                         -> split, see below
    unlinked    never had a link into an integrated source     -> no finding

`divergent` splits on evidence rather than being one condition:

* different serials  -> the CMDB linked a wrong machine (`cmdb_link_incorrect`).
  Observed cause is the CMDB's integration matching on a name prefix, e.g.
  `ADH-READY17` picking up both `adh-ready17` and `adh-ready1`.
* same hostname      -> Operations holds two device records for one machine
  (`duplicate_device_records`). Not a CMDB fault.

Findings must attach to something clickable in Operations, and `subject_id` is
NOT NULL with a closed `subject_type` list (client / device / client_user /
source_binding / collector_instance). There is no subject type for a CMDB
page, so page-level conditions are filed against the client with the affected
pages enumerated in `finding_details`.

Default is dry-run: nothing is written unless `dry_run=False` is passed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from ingest import db

log = logging.getLogger(__name__)

TENANT_ID = 1
_PLATFORM = "Hudu"

# Cap the page list embedded in a finding. A client with 200 stale pages does
# not need all 200 inlined; the count is authoritative and the drill-through
# lists the rest.
_MAX_DETAIL_ITEMS = 50


def _condition_key(*parts: Any) -> str:
    raw = ":".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def _finding_type_id(cur: Any, name: str) -> int:
    cur.execute("SELECT id FROM operations.finding_types WHERE name = %s", (name,))
    row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"finding type {name!r} is not registered — run migration 0091")
    return row[0]


def _upsert(
    cur: Any,
    *,
    tenant_id: int,
    finding_type_id: int,
    client_id: Any,
    subject_type: str,
    subject_id: uuid.UUID,
    condition_key: str,
    severity: str,
    now: datetime,
    details: dict[str, Any],
) -> None:
    """Upsert one finding.

    Deliberately not reusing `evaluator._upsert_finding`: that helper hardcodes
    `subject_type='device'`, and three of the four conditions here are not
    device-scoped. Conflict target, status handling and reopen semantics match
    it exactly so the two behave identically where they overlap.
    """
    cur.execute(
        """
        INSERT INTO operations.findings (
            id, version, tenant_id, finding_type_id, client_id,
            subject_type, subject_id, subject_layer, finding_details,
            condition_key, severity, confidence, status,
            first_seen_at, last_seen_at, last_detected_at
        ) VALUES (
            gen_random_uuid(), 1, %s, %s, %s,
            %s, %s, '', %s::jsonb,
            %s, %s, 'confirmed', 'open',
            %s, %s, %s
        )
        ON CONFLICT (tenant_id, condition_key)
            WHERE condition_key > '' AND status IN ('open', 'acknowledged')
        DO UPDATE SET
            finding_details  = EXCLUDED.finding_details,
            last_seen_at     = EXCLUDED.last_seen_at,
            last_detected_at = EXCLUDED.last_detected_at,
            status           = CASE
                WHEN findings.status = 'resolved' THEN 'open'
                ELSE findings.status
            END
        """,
        (
            tenant_id, finding_type_id, client_id,
            subject_type, subject_id, json.dumps(details),
            condition_key, severity, now, now, now,
        ),
    )


def _resolve_absent(cur: Any, finding_type_id: int, keys: list[str], now: datetime) -> None:
    """Close findings of this type whose condition no longer holds."""
    cur.execute(
        """
        UPDATE operations.findings
           SET status = 'resolved', last_seen_at = %s
         WHERE tenant_id = %s AND finding_type_id = %s
           AND status IN ('open', 'acknowledged')
           AND NOT (condition_key = ANY(%s::text[]))
        """,
        (now, TENANT_ID, finding_type_id, keys),
    )


# ── condition queries ────────────────────────────────────────────────────
# Each returns rows shaped for _upsert. Kept as plain SQL so the exact
# predicate is reviewable next to the counts it produced.

_VERDICT_BY_CLIENT = """
SELECT eo.client_id,
       count(*)                                              AS n,
       jsonb_agg(jsonb_build_object(
           'asset_id', eo.entity_key,
           'name',     eo.canonical_data->>'hostname',
           'layout',   eo.canonical_data->>'hudu_layout',
           'url',      eo.canonical_data->>'hudu_url')
         ORDER BY eo.canonical_data->>'hostname')            AS pages
  FROM operations.entity_observation_current eo
 WHERE eo.tenant_id = %s AND eo.platform = %s
   AND eo.entity_type = 'cmdb.asset' AND eo.active
   AND eo.client_id IS NOT NULL
   AND eo.canonical_data->>'link_verdict' = %s
 GROUP BY eo.client_id
"""

# Divergent pages, with the devices they resolve to, split by evidence.
_DIVERGENT = """
WITH div AS (
  SELECT entity_key, client_id,
         canonical_data->>'hostname'    AS page,
         canonical_data->>'hudu_layout' AS layout,
         canonical_data->>'hudu_url'    AS url,
         canonical_data->'relayed'      AS relayed
    FROM operations.entity_observation_current
   WHERE tenant_id = %s AND platform = %s
     AND entity_type = 'cmdb.asset' AND active
     AND canonical_data->>'link_verdict' = 'divergent'
), x AS (
  SELECT d.*, (r->>'resolved_device_id')::uuid AS dev
    FROM div d, jsonb_array_elements(d.relayed) r
   WHERE r->>'resolved_device_id' IS NOT NULL
)
SELECT x.entity_key, x.client_id, x.page, x.layout, x.url,
       count(DISTINCT dv.id)                                   AS devices,
       count(DISTINCT lower(coalesce(dv.canonical_hostname,''))) AS hostnames,
       count(DISTINCT coalesce(dv.canonical_serial,''))          AS serials,
       jsonb_agg(DISTINCT jsonb_build_object(
           'device_id', dv.id,
           'hostname',  dv.canonical_hostname,
           'serial',    dv.canonical_serial))                  AS devs
  FROM x JOIN operations.devices dv ON dv.id = x.dev AND dv.deleted_at IS NULL
 GROUP BY x.entity_key, x.client_id, x.page, x.layout, x.url
HAVING count(DISTINCT dv.id) > 1
"""

# Vendors relayed through an aggregator that Operations does not ingest.
# Scoped per client, not per source binding: the actionable question is which
# clients are running an unintegrated tool, and operators work by client. A
# vendor deployed at five clients therefore raises five findings, which is
# also the signal for how much direct integration would be worth.
_UNINTEGRATED = """
SELECT r->>'source'  AS vendor,
       eo.client_id  AS client_id,
       count(*)      AS n
  FROM operations.entity_observation_current eo,
       jsonb_array_elements(eo.canonical_data->'relayed') r
 WHERE eo.tenant_id = %s AND eo.platform = %s
   AND eo.entity_type = 'cmdb.asset' AND eo.active
   AND eo.client_id IS NOT NULL
   AND (r->>'integrated')::boolean IS FALSE
 GROUP BY 1, 2
"""


def evaluate(*, dry_run: bool = True) -> dict[str, int]:
    """Compute CMDB findings. Writes nothing unless dry_run=False."""
    now = datetime.now(UTC)
    counts: dict[str, int] = {}

    with db.transaction() as cur:
        cur.execute(f"SET LOCAL operations.tenant_id = {TENANT_ID}")

        ft_stale = _finding_type_id(cur, "cmdb_asset_stale")
        ft_wrong = _finding_type_id(cur, "cmdb_link_incorrect")
        ft_dupe = _finding_type_id(cur, "duplicate_device_records")
        ft_unint = _finding_type_id(cur, "unintegrated_source_observed")

        # 1. stale — filed against the client, pages enumerated
        cur.execute(_VERDICT_BY_CLIENT, (TENANT_ID, _PLATFORM, "stale"))
        stale_rows = cur.fetchall()
        stale_keys = []
        for client_id, n, pages in stale_rows:
            key = _condition_key(TENANT_ID, client_id, "cmdb_asset_stale", _PLATFORM)
            stale_keys.append(key)
            if not dry_run:
                _upsert(
                    cur, tenant_id=TENANT_ID, finding_type_id=ft_stale,
                    client_id=client_id, subject_type="client", subject_id=client_id,
                    condition_key=key, severity="low", now=now,
                    details={"page_count": n, "pages": pages[:_MAX_DETAIL_ITEMS]},
                )
        counts["cmdb_asset_stale"] = len(stale_rows)
        counts["cmdb_asset_stale_pages"] = sum(r[1] for r in stale_rows)

        # 2/3. divergent — split on evidence
        cur.execute(_DIVERGENT, (TENANT_ID, _PLATFORM))
        wrong_by_client: dict[Any, list] = {}
        dupes: list[tuple] = []
        for entity_key, client_id, page, layout, url, _devs, hostnames, serials, devlist in cur.fetchall():
            item = {"asset_id": entity_key, "name": page, "layout": layout,
                    "url": url, "devices": devlist}
            if hostnames == 1:
                dupes.append((client_id, item, devlist))
            elif serials > 1:
                wrong_by_client.setdefault(client_id, []).append(item)

        wrong_keys = []
        for client_id, items in wrong_by_client.items():
            key = _condition_key(TENANT_ID, client_id, "cmdb_link_incorrect", _PLATFORM)
            wrong_keys.append(key)
            if not dry_run:
                _upsert(
                    cur, tenant_id=TENANT_ID, finding_type_id=ft_wrong,
                    client_id=client_id, subject_type="client", subject_id=client_id,
                    condition_key=key, severity="medium", now=now,
                    details={"page_count": len(items), "pages": items[:_MAX_DETAIL_ITEMS]},
                )
        counts["cmdb_link_incorrect"] = len(wrong_keys)
        counts["cmdb_link_incorrect_pages"] = sum(len(v) for v in wrong_by_client.values())

        dupe_keys = []
        for client_id, item, devlist in dupes:
            # File against the device carrying a serial — the better-evidenced
            # record of the pair — so the finding has a concrete subject.
            anchor = next((d for d in devlist if d.get("serial")), devlist[0])
            subject = uuid.UUID(anchor["device_id"])
            key = _condition_key(TENANT_ID, client_id, subject, "duplicate_device_records", _PLATFORM)
            dupe_keys.append(key)
            if not dry_run:
                _upsert(
                    cur, tenant_id=TENANT_ID, finding_type_id=ft_dupe,
                    client_id=client_id, subject_type="device", subject_id=subject,
                    condition_key=key, severity="medium", now=now, details=item,
                )
        counts["duplicate_device_records"] = len(dupe_keys)

        # 4. unintegrated vendors seen through the aggregator
        cur.execute(_UNINTEGRATED, (TENANT_ID, _PLATFORM))
        unint_rows = cur.fetchall()
        unint_keys = []
        for vendor, client_id, n in unint_rows:
            key = _condition_key(TENANT_ID, client_id, "unintegrated_source_observed", vendor)
            unint_keys.append(key)
            if not dry_run:
                _upsert(
                    cur, tenant_id=TENANT_ID, finding_type_id=ft_unint,
                    client_id=client_id, subject_type="client", subject_id=client_id,
                    condition_key=key, severity="info", now=now,
                    details={"vendor": vendor, "record_count": n,
                             "relayed_via": _PLATFORM},
                )
        counts["unintegrated_source_observed"] = len(unint_rows)

        if not dry_run:
            _resolve_absent(cur, ft_stale, stale_keys, now)
            _resolve_absent(cur, ft_wrong, wrong_keys, now)
            _resolve_absent(cur, ft_dupe, dupe_keys, now)
            _resolve_absent(cur, ft_unint, unint_keys, now)
        else:
            # Nothing was written, but be explicit rather than relying on it.
            cur.connection.rollback()

    log.info("cmdb_findings: dry_run=%s %s", dry_run, counts)
    return counts
