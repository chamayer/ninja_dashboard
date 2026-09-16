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
* same hostname      -> Operations may hold two device records for one
  computer. The identity resolver emits the single cross-source
  ``identity_conflict`` Finding; Hudu is evidence for it, not a second queue.

Findings must attach to something clickable in Operations, and `subject_id` is
NOT NULL with a closed `subject_type` list (client / device / client_user /
source_binding / collector_instance). There is no subject type for a CMDB
page, so each page-level condition is filed against its client while the exact
source target remains in `finding_details`.

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
from ingest.condition_evidence import complete_snapshot_available, preserve_operator_episode
from ingest.conditions import record_assessment
from shared.conditions.contracts import (
    Condition,
    EvaluationCoverage,
    Participant,
    Readiness,
    Signal,
)

log = logging.getLogger(__name__)

TENANT_ID = 1
_PLATFORM = "Hudu"

# The incorrect-link finding remains client-scoped, so cap only its embedded
# example list. Archive candidates are one source record per finding and do
# not use this cap.
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
) -> uuid.UUID:
    """Upsert one finding.

    Deliberately not reusing `evaluator._upsert_finding`: that helper hardcodes
    `subject_type='device'`, and three of the four conditions here are not
    device-scoped. Conflict target, status handling and reopen semantics match
    it exactly so the two behave identically where they overlap.
    """
    preserved = preserve_operator_episode(cur, "findings", tenant_id, condition_key, now, details)
    if preserved is not None:
        return uuid.UUID(preserved)
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
            WHERE condition_key > '' AND status IN ('open', 'acknowledged', 'investigating', 'suppressed')
        DO UPDATE SET
            finding_details  = EXCLUDED.finding_details,
            last_seen_at     = EXCLUDED.last_seen_at,
            last_detected_at = EXCLUDED.last_detected_at,
            status           = CASE
                WHEN findings.status = 'resolved' THEN 'open'
                ELSE findings.status
            END
        RETURNING id
        """,
        (
            tenant_id, finding_type_id, client_id,
            subject_type, subject_id, json.dumps(details),
            condition_key, severity, now, now, now,
        ),
    )
    return cur.fetchone()[0]


def _resolve_absent(
    cur: Any,
    finding_type_id: int,
    keys: list[str],
    now: datetime,
    *,
    assessment_required: bool = False,
    empty_result_verified: bool = False,
) -> None:
    """Close absent findings only after a complete result is established."""
    if not keys and not empty_result_verified:
        return
    assessment_clause = ""
    if assessment_required:
        # The producer is deployed before the Operations migration in some
        # restart sequences.  Do not let the compatibility lifecycle query
        # fail while the additive assessment tables are still absent.
        cur.execute("SELECT to_regclass('operations.condition_assessments') IS NOT NULL")
        assessment_required = bool(cur.fetchone()[0])
        if not assessment_required:
            return
    if assessment_required:
        assessment_clause = """
           AND EXISTS (
               SELECT 1
                 FROM operations.condition_assessments assessment
                WHERE assessment.tenant_id = operations.findings.tenant_id
                 AND assessment.row_kind = 'entity'
                 AND assessment.finding_id = operations.findings.id
                 AND (assessment.response ->> 'may_clear')::boolean IS TRUE
                 AND assessment.policy_version = (
                     SELECT version FROM operations.condition_policy_versions
                     WHERE active ORDER BY version DESC LIMIT 1
                 )
                 AND assessment.assessed_at >= now() - (
                     SELECT (policy->>'freshness_hours')::integer * interval '1 hour'
                     FROM operations.condition_policy_versions
                     WHERE active ORDER BY version DESC LIMIT 1
                 )
           )
        """
    cur.execute(
        f"""
        UPDATE operations.findings
           SET status = 'resolved', last_seen_at = %s
         WHERE tenant_id = %s AND finding_type_id = %s
           AND status IN ('open', 'acknowledged')
           AND NOT (condition_key = ANY(%s::text[]))
           {assessment_clause}
        """,
        (now, TENANT_ID, finding_type_id, keys),
    )


def _record_stale_assessment(
    cur: Any,
    *,
    tenant_id: int,
    finding_id: uuid.UUID,
    finding_type_id: int,
    condition_key: str,
    source_instance_id: uuid.UUID,
    source_binding_id: uuid.UUID,
    now: datetime,
) -> None:
    cur.execute("SELECT to_regclass('operations.condition_assessments') IS NOT NULL")
    if not cur.fetchone()[0]:
        return
    cur.execute("SELECT name FROM operations.finding_types WHERE id = %s", (finding_type_id,))
    type_name = cur.fetchone()[0]
    participants = (
        Participant("source_instance", str(source_instance_id), "context", tenant_id),
        Participant("source_binding", str(source_binding_id), "affected", tenant_id),
    )
    measured = complete_snapshot_available(
        cur,
        tenant_id,
        str(source_instance_id),
        source_binding_id=str(source_binding_id),
        now=now,
    )
    condition = Condition(
        tenant_id, "entity", str(finding_id), type_name, condition_key, "open", participants
    )
    record_assessment(
        cur,
        condition,
        (
            Signal(
                "collection",
                participants[1],
                Readiness.READY if measured else Readiness.UNKNOWN,
                "collection:complete_snapshot" if measured else "collection:readiness_not_measured",
            ),
        ),
        EvaluationCoverage(measured, measured, measured, measured),
        now=now,
        reevaluation_key=f"cmdb:{condition_key}",
            participant=participants[1],
    )


# ── condition queries ────────────────────────────────────────────────────
# Each returns rows shaped for _upsert. Kept as plain SQL so the exact
# predicate is reviewable next to the counts it produced.

_STALE_ASSETS = """
SELECT eo.client_id,
       eo.source_instance_id,
       eo.source_binding_id,
       eo.raw_data->>'company_id' AS company_id,
       eo.external_id,
       eo.canonical_data->>'hostname' AS name,
       eo.canonical_data->>'hudu_layout' AS layout,
       eo.canonical_data->>'hudu_url' AS url,
       eo.canonical_data->'relayed' AS relayed
  FROM operations.entity_observation_current eo
 WHERE eo.tenant_id = %s AND eo.platform = %s
   AND eo.entity_type = 'cmdb.asset' AND eo.active
   AND eo.client_id IS NOT NULL
   AND COALESCE((eo.canonical_data->>'archived')::boolean, FALSE) IS FALSE
   AND eo.canonical_data->>'link_verdict' = 'stale'
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

        # 1. stale — one actionable Hudu source record per finding.  A
        # client-scoped aggregate hid targets beyond its detail cap and could
        # not be safely acted on.  The subject remains the client because a
        # Hudu source record is evidence, not an Operations subject type.
        cur.execute(_STALE_ASSETS, (TENANT_ID, _PLATFORM))
        stale_rows = cur.fetchall()
        stale_keys = []
        for (
            client_id, source_instance_id, source_binding_id, parent_external_id, external_id,
            name, layout, url, relayed,
        ) in stale_rows:
            key = _condition_key(
                TENANT_ID, source_instance_id, parent_external_id, external_id,
                "cmdb_asset_stale",
            )
            stale_keys.append(key)
            if not dry_run:
                finding_id = _upsert(
                    cur, tenant_id=TENANT_ID, finding_type_id=ft_stale,
                    client_id=client_id, subject_type="client", subject_id=client_id,
                    condition_key=key, severity="low", now=now,
                    details={
                        "asset_id": external_id,
                        "company_id": parent_external_id,
                        "source_instance_id": str(source_instance_id),
                        "name": name,
                        "layout": layout,
                        "url": url,
                        "linked_records": relayed or [],
                    },
                )
                _record_stale_assessment(
                    cur,
                    tenant_id=TENANT_ID,
                    finding_id=finding_id,
                    finding_type_id=ft_stale,
                    condition_key=key,
                    source_instance_id=source_instance_id,
                    source_binding_id=source_binding_id,
                    now=now,
                )
        counts["cmdb_asset_stale"] = len(stale_rows)
        counts["cmdb_asset_stale_pages"] = len(stale_rows)

        # 2/3. divergent — split on evidence
        cur.execute(_DIVERGENT, (TENANT_ID, _PLATFORM))
        wrong_by_client: dict[Any, list] = {}
        for entity_key, client_id, page, layout, url, _devs, hostnames, serials, devlist in cur.fetchall():
            item = {"asset_id": entity_key, "name": page, "layout": layout,
                    "url": url, "devices": devlist}
            if hostnames != 1 and serials > 1:
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

        # A Hudu page that shares a name with multiple Computers is useful
        # evidence, but not a distinct operational condition.  The identity
        # resolver owns the one client-scoped duplicate-Computer Finding.  An
        # empty key set retires legacy Hudu-only duplicate findings on this
        # evaluator's next normal run.
        dupe_keys: list[str] = []
        counts["duplicate_device_records"] = 0

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
            _resolve_absent(cur, ft_stale, stale_keys, now, assessment_required=True)
            _resolve_absent(cur, ft_wrong, wrong_keys, now, assessment_required=True)
            _resolve_absent(cur, ft_dupe, dupe_keys, now, assessment_required=True)
            _resolve_absent(cur, ft_unint, unint_keys, now, assessment_required=True)
        else:
            # Nothing was written, but be explicit rather than relying on it.
            cur.connection.rollback()

    log.info("cmdb_findings: dry_run=%s %s", dry_run, counts)
    return counts
