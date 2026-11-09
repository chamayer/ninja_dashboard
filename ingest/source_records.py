"""Managed source-record assessment and publication (PLAN-004 R4, ADR-0049).

Migration 0370 admits every received record as a ``source_record`` subject and
queues it. This worker drains that queue in small batches. Each batch is one
short transaction that:

1. takes the exclusive tenant guard (findings contract), then a share lock on
   the tenant generation row, so no input commit can land until it commits
   (amendment R4-1, design §7.2);
2. claims pending queue rows and reads their current inputs under those locks;
3. evaluates the code-defined rules, writes ``source_record_assessment_current``
   and opens or resolves the matching native findings;
4. acknowledges only the dirty revision it read, so a newer enqueue survives.

Rules (revision ``RULE_REVISION``) evaluate their own inputs only. A missing
input of one rule is ``unknown`` for that rule, never a clean result:

* ``record.role``: the record has a role, or ``unknown`` with ``record_role``.
* ``record.presence``: present or withdrawn, as the source reports it.
* ``record.reference`` (dimension ``hudu_device_reference``): linked,
  stale/conflicting, or unknown from Hudu's typed integrated-card evidence.
* ``identifier.validity`` (dimensions ``serial`` and ``mac``): reported
  identifiers are usable for identity, malformed/placeholder (``contradicted``),
  or missing (``unknown``).
* ``identity.association``: an attached record is ``supported`` by its
  confirmed link. An unattached present record whose keys reach two or more
  live Computers is ``contradicted`` (competing possibilities); one or none is
  ``unknown``. Names count only within the record's mapped client; recency
  never breaks a tie.
* ``case.duplicate`` (Stage C, ``ingest.source_record_cases``).

Work ownership (§9.1): attached records' invalid serials and known junk MACs
belong to their existing Computer findings. An unattached record with a pending
identity candidate belongs to that candidate. The assessment records the owner
instead of opening duplicate work. New native findings are never alertable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Iterator

import psycopg

from ingest import db
from ingest import software_capabilities
from ingest.identity import identity_entity_types
from ingest.identity.matching import (
    load_identity_match_policies,
    preview_match,
    record_name_short,
)
from ingest.conditions import record_assessment
from ingest.normalize import (
    is_junk_mac,
    is_usable_serial,
    load_identity_value_rejections,
    normalize_mac,
)
from shared import software_coverage, software_settings
from shared.conditions.contracts import Condition, EvaluationCoverage, Participant
from shared.findings_contract import guard_findings_writes

log = logging.getLogger(__name__)

TENANT_ID = 1
RULE_REVISION = 8
BATCH_SIZE = 200
MAX_ATTEMPTS = 5
_IDENTITY_ROLES = frozenset({"endpoint_agent", "virtual_machine", "virtual_host"})
_ACTIVE = ("open", "acknowledged", "investigating", "suppressed")


class GuardBusy(Exception):
    """The tenant guard or generation row could not be locked within the timeout."""


@contextmanager
def publication_transaction(tenant_id: int) -> Iterator[tuple[Any, int]]:
    """One bounded publication transaction holding both locks (design §7.2).

    Yields the cursor and the tenant input generation, which is current for the
    whole transaction because input commits wait on the share lock.
    """
    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '5s'")
            cur.execute("SET LOCAL statement_timeout = '60s'")
            try:
                guard_findings_writes(cur, tenant_id)
                cur.execute(
                    "SELECT input_generation FROM operations.source_record_tenant_state"
                    " WHERE tenant_id = %s FOR SHARE",
                    (tenant_id,),
                )
            except psycopg.errors.LockNotAvailable as exc:
                raise GuardBusy(str(exc)) from exc
            row = cur.fetchone()
            yield cur, (row[0] if row else 0)


def assess(*, max_seconds: float = 240.0, tenant_id: int = TENANT_ID) -> int:
    """Drain the assessment queue in bounded batches until empty or out of time."""
    from ingest import source_record_cases

    deadline = time.monotonic() + max_seconds
    total = 0
    while time.monotonic() < deadline:
        try:
            with publication_transaction(tenant_id) as (cur, generation):
                load_identity_value_rejections(cur)
                processed = _assess_batch(
                    cur, tenant_id, generation, source_record_cases
                )
        except GuardBusy:
            log.info(
                "source records: tenant guard busy; leaving the queue for the next run"
            )
            break
        total += processed
        if processed == 0:
            break
    return total


def _claim(cur: Any, tenant_id: int) -> list[tuple[str, uuid.UUID, dict, int]]:
    cur.execute(
        """
        SELECT target_kind, target_id, target_key, dirty_revision
          FROM operations.source_record_assessment_queue
         WHERE tenant_id = %s AND status = 'pending'
         ORDER BY queued_at, target_id
         LIMIT %s
           FOR UPDATE SKIP LOCKED
        """,
        (tenant_id, BATCH_SIZE),
    )
    return cur.fetchall()


def _assess_batch(cur: Any, tenant_id: int, generation: int, cases_module: Any) -> int:
    claimed = _claim(cur, tenant_id)
    if not claimed:
        return 0
    now = datetime.now(UTC)
    records = [row for row in claimed if row[0] == "source_record"]
    keys = [row for row in claimed if row[0] == "case_key"]
    failures: dict[tuple[str, uuid.UUID], str] = {}
    if records:
        cur.execute("SAVEPOINT source_record_rules")
        try:
            assess_records(cur, tenant_id, generation, [row[1] for row in records], now)
            cur.execute("RELEASE SAVEPOINT source_record_rules")
        except psycopg.errors.QueryCanceled:
            raise
        except Exception as exc:  # recorded per row below; the batch retries
            cur.execute("ROLLBACK TO SAVEPOINT source_record_rules")
            log.exception(
                "source records: record rules failed for %d targets", len(records)
            )
            failures.update(
                {("source_record", row[1]): str(exc)[:500] for row in records}
            )
    if keys:
        cur.execute("SAVEPOINT source_record_cases")
        try:
            cases_module.assess_case_keys(
                cur, tenant_id, generation, [(row[1], row[2]) for row in keys], now
            )
            cur.execute("RELEASE SAVEPOINT source_record_cases")
        except psycopg.errors.QueryCanceled:
            raise
        except Exception as exc:
            cur.execute("ROLLBACK TO SAVEPOINT source_record_cases")
            log.exception("source records: case rules failed for %d keys", len(keys))
            failures.update({("case_key", row[1]): str(exc)[:500] for row in keys})
    _acknowledge(cur, tenant_id, claimed, failures)
    return len(claimed)


def _acknowledge(
    cur: Any,
    tenant_id: int,
    claimed: list[tuple[str, uuid.UUID, dict, int]],
    failures: dict[tuple[str, uuid.UUID], str],
) -> None:
    done = [
        (kind, target, rev)
        for kind, target, _key, rev in claimed
        if (kind, target) not in failures
    ]
    if done:
        cur.execute(
            """
            UPDATE operations.source_record_assessment_queue q
               SET processed_revision = d.rev, processed_at = now(), attempts = 0,
                   last_error = '',
                   status = CASE WHEN q.dirty_revision > d.rev THEN 'pending' ELSE 'done' END
              FROM unnest(%s::text[], %s::uuid[], %s::bigint[]) AS d(kind, target, rev)
             WHERE q.tenant_id = %s AND q.target_kind = d.kind AND q.target_id = d.target
            """,
            (
                [d[0] for d in done],
                [d[1] for d in done],
                [d[2] for d in done],
                tenant_id,
            ),
        )
    for (kind, target), error in failures.items():
        cur.execute(
            """
            UPDATE operations.source_record_assessment_queue
               SET attempts = attempts + 1, last_error = %s,
                   status = CASE WHEN attempts + 1 >= %s THEN 'failed' ELSE 'pending' END
             WHERE tenant_id = %s AND target_kind = %s AND target_id = %s
            """,
            (error, MAX_ATTEMPTS, tenant_id, kind, target),
        )


# --- record rules -----------------------------------------------------------------


def _load_records(cur: Any, tenant_id: int, subject_ids: list[uuid.UUID]) -> list[dict]:
    # The legacy CMDB owners are read once per batch, not once per record.
    cur.execute(
        """
        WITH legacy_stale AS (
            SELECT DISTINCT f.finding_details->>'asset_id' AS asset_id,
                   f.finding_details->>'source_instance_id' AS source_instance_id
              FROM operations.findings f
              JOIN operations.finding_types ft ON ft.id = f.finding_type_id
             WHERE f.tenant_id = %s AND f.condition_namespace = 'entity'
               AND f.status IN ('open', 'acknowledged', 'investigating', 'suppressed')
               AND ft.name = 'cmdb_asset_stale'
        ), legacy_divergent AS (
            SELECT DISTINCT f.client_id, ref->>'asset_id' AS asset_id,
                   ref->>'source_instance_id' AS source_instance_id
              FROM operations.findings f
              JOIN operations.finding_types ft ON ft.id = f.finding_type_id
              CROSS JOIN LATERAL jsonb_array_elements(
                  CASE WHEN jsonb_typeof(f.finding_details->'source_refs') = 'array'
                       THEN f.finding_details->'source_refs' ELSE '[]'::jsonb END) ref
             WHERE f.tenant_id = %s AND f.condition_namespace = 'entity'
               AND f.status IN ('open', 'acknowledged', 'investigating', 'suppressed')
               AND ft.name = 'cmdb_link_incorrect'
        )
        SELECT s.id, s.input_version, s.association_version, s.record_role, s.presence,
               s.platform, s.entity_type, s.source_instance_id, s.external_id,
               o.observation_id,
               operations.computer_client_independent_evidence(s.tenant_id, o.observation_id) AS client_id,
               o.canonical_data,
               (
                    SELECT CASE
                             WHEN count(DISTINCT group_link.entity_id) = 1
                             THEN min(group_link.entity_id::text)::uuid
                           END
                      FROM operations.entity_source_links group_link
                     WHERE group_link.tenant_id = s.tenant_id
                       AND group_link.source_instance_id = s.source_instance_id
                       AND group_link.entity_class_id = 'client'
                       AND (group_link.external_id = o.canonical_data ->> 'platform_group_id'
                            OR EXISTS (SELECT 1 FROM operations.entity_observation_current org
                                 WHERE org.tenant_id = group_link.tenant_id
                                   AND org.source_instance_id = group_link.source_instance_id
                                   AND org.entity_type = 'org' AND org.active
                                   AND org.entity_key = o.canonical_data ->> 'platform_group_id'
                                   AND org.external_id = group_link.external_id
                                   AND org.external_namespace = group_link.external_namespace
                                   AND org.parent_external_namespace = group_link.parent_external_namespace
                                   AND org.parent_external_id = group_link.parent_external_id))
                       AND group_link.entity_id = operations.computer_client_independent_evidence(
                           s.tenant_id, o.observation_id)
                       AND group_link.missing_since IS NULL
                ) AS source_group_client_id,
               link.entity_id AS device_id,
               owner.effective_client_id AS device_client_id,
               link.match_method,
               d.id IS NOT NULL AS device_live,
               EXISTS (SELECT 1 FROM operations.entity_candidates c
                        WHERE c.tenant_id = s.tenant_id
                          AND c.source_instance_id = s.source_instance_id
                          AND c.external_namespace = s.external_namespace
                          AND c.parent_external_namespace = s.parent_external_namespace
                          AND c.parent_external_id = s.parent_external_id
                          AND c.external_id = s.external_id
                          AND c.status = 'pending') AS candidate_pending,
               stale_ref.asset_id IS NOT NULL AS legacy_stale_reference,
               divergent_ref.asset_id IS NOT NULL AS legacy_divergent_reference
          FROM operations.source_record_subjects s
          LEFT JOIN operations.entity_observation_current o
            ON o.tenant_id = s.tenant_id AND o.observation_id = s.observation_id
          LEFT JOIN operations.entity_source_links link
            ON link.tenant_id = s.tenant_id AND link.source_instance_id = s.source_instance_id
           AND link.external_namespace = s.external_namespace
           AND link.parent_external_namespace = s.parent_external_namespace
           AND link.parent_external_id = s.parent_external_id
           AND link.external_id = s.external_id
           AND link.entity_class_id = 'device'
          LEFT JOIN operations.devices d
            ON d.tenant_id = link.tenant_id AND d.id = link.entity_id AND d.deleted_at IS NULL
          LEFT JOIN operations.computer_client_ownership owner
            ON owner.tenant_id = d.tenant_id AND owner.device_id = d.id
           AND owner.state IN ('resolved', 'decision_protected')
          LEFT JOIN legacy_stale stale_ref
            ON stale_ref.asset_id = s.external_id
           AND stale_ref.source_instance_id = s.source_instance_id::text
          LEFT JOIN legacy_divergent divergent_ref
            ON divergent_ref.asset_id = s.external_id
           AND divergent_ref.source_instance_id = s.source_instance_id::text
           AND divergent_ref.client_id IS NOT DISTINCT FROM
               operations.computer_client_independent_evidence(s.tenant_id, o.observation_id)
         WHERE s.tenant_id = %s AND s.id = ANY(%s::uuid[]) AND s.subject_kind = 'record'
        """,
        (tenant_id, tenant_id, tenant_id, subject_ids),
    )
    columns = [c.name for c in cur.description]
    records = [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]
    # Restricted-safe values come from the safe view, filtered by the batch's
    # observation IDs: a constant filter reaches the view's base table, while a
    # join to the view made it evaluate every observation.
    cur.execute(
        """
        SELECT observation_id, reported_online, reported_last_contact_at, restricted
          FROM operations.v_entity_observation_admin_metadata
         WHERE tenant_id = %s AND observation_id = ANY(%s::uuid[])
        """,
        (tenant_id, [r["observation_id"] for r in records if r["observation_id"]]),
    )
    safe = {row[0]: row[1:] for row in cur.fetchall()}
    for record in records:
        online, contact, restricted = safe.get(
            record["observation_id"], (None, None, False)
        )
        record["reported_online"] = online
        record["reported_last_contact_at"] = contact
        record["restricted"] = bool(restricted)
    return records


def _candidate_computers(
    cur: Any, tenant_id: int, subject_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[uuid.UUID, set[str]]]:
    """Live Computers reachable through each subject's keys, with the key families.

    Hardware keys (serial, VM UUID, MAC) compare across clients and sources;
    names only within the subject's mapped client. Operator exclusions of the
    record from a Computer remove that Computer.
    """
    if not subject_ids:
        return {}
    cur.execute(
        """
        SELECT mine.subject_id, d.id, mine.key_family
          FROM operations.source_record_lookup_keys mine
          JOIN operations.source_record_subjects ms
            ON ms.tenant_id = mine.tenant_id AND ms.id = mine.subject_id
          LEFT JOIN operations.entity_observation_current mo
            ON mo.tenant_id = ms.tenant_id AND mo.observation_id = ms.observation_id
          JOIN operations.source_record_lookup_keys other
            ON other.tenant_id = mine.tenant_id AND other.key_family = mine.key_family
           AND other.normalized_value = mine.normalized_value
           AND other.subject_id <> mine.subject_id
          JOIN operations.source_record_subjects os
            ON os.tenant_id = other.tenant_id AND os.id = other.subject_id
          JOIN operations.entity_source_links link
            ON link.tenant_id = os.tenant_id AND link.source_instance_id = os.source_instance_id
           AND link.external_namespace = os.external_namespace
           AND link.parent_external_namespace = os.parent_external_namespace
           AND link.parent_external_id = os.parent_external_id
           AND link.external_id = os.external_id
           AND link.entity_class_id = 'device'
          JOIN operations.devices d
            ON d.tenant_id = link.tenant_id AND d.id = link.entity_id AND d.deleted_at IS NULL
         WHERE mine.tenant_id = %s AND mine.subject_id = ANY(%s::uuid[])
           AND (mine.key_family <> 'name'
                OR (operations.computer_client_independent_evidence(ms.tenant_id, ms.observation_id) IS NOT NULL AND EXISTS (
                    SELECT 1 FROM operations.computer_client_ownership owner
                     WHERE owner.tenant_id = d.tenant_id AND owner.device_id = d.id
                       AND owner.effective_client_id = operations.computer_client_independent_evidence(ms.tenant_id, ms.observation_id)
                       AND owner.state IN ('resolved', 'decision_protected'))))
           AND NOT EXISTS (
               SELECT 1 FROM operations.device_operator_decisions x
                WHERE x.tenant_id = d.tenant_id AND x.device_id = d.id
                  AND x.dimension = 'identity_excluded_records'
                  AND x.value ? (ms.platform || '|' || ms.external_id))
        """,
        (tenant_id, subject_ids),
    )
    found: dict[uuid.UUID, dict[uuid.UUID, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for subject_id, device_id, family in cur.fetchall():
        found[subject_id][device_id].add(family)
    return found


def _result(
    rule: str,
    result: str,
    *,
    dimension: str = "",
    evidence: dict | None = None,
    missing: list[str] | None = None,
    owner: str = "",
    finding: dict | None = None,
) -> dict:
    return {
        "rule": rule,
        "dimension": dimension,
        "result": result,
        "evidence": evidence or {},
        "missing": missing or [],
        "owner": owner,
        "finding": finding,
    }


def evaluate_record(
    record: dict,
    candidates: dict[uuid.UUID, set[str]],
    software_risks: list[dict] | None = None,
    software_risk_enabled: bool = True,
    software_severity_kev: str = "critical",
    software_severity_high: str = "high",
    rejected_software: list[dict] | None = None,
    rejected_software_enabled: bool = True,
    rejected_software_severity: str = "high",
    software_policy_known: bool = True,
    suspicious_software: list[dict] | None = None,
    suspicious_software_enabled: bool = True,
    malicious_software_hints: list[dict] | None = None,
    malicious_software_enabled: bool = True,
    unauthorized_tools: list[dict] | None = None,
    capability_policy_known: bool = True,
    identity_conflicts: dict[uuid.UUID, set[str]] | None = None,
    attached_contradiction: dict | None = None,
    identity_ownership_deferred: bool = False,
    stale_after_days: int | None = None,
    computer_alive: bool = False,
    now: datetime | None = None,
) -> list[dict]:
    """The rule results for one record. Pure: inputs in, results out."""
    data = record.get("canonical_data") or {}
    role = record["record_role"]
    present = record["presence"] == "present"
    results = [
        _result(
            "record.presence",
            "supported",
            evidence={"presence": record["presence"]},
        )
    ]
    # Group/site attribution is retained as a source claim. Check the explicit
    # source-group link, not observation.client_id: intake can fill that column
    # from the attached Computer when no group mapping exists. The resolver owns
    # group-level correction; keep missing mappings unknown without creating
    # one actionable finding per member. Computer ownership conflicts stay a
    # separate entity-level concern.
    group_id = str(data.get("platform_group_id") or "").strip()
    if not group_id:
        results.append(_result("record.source_attribution", "not_applicable"))
    elif record.get("source_group_client_id") is None:
        results.append(
            _result(
                "record.source_attribution",
                "unknown",
                evidence={"platform_group_id": group_id},
                missing=["source_group_mapping"],
                owner="source_group_mapping",
            )
        )
    else:
        device_client_id = record.get("device_client_id")
        group_client_id = record["source_group_client_id"]
        if (
            record.get("device_live")
            and device_client_id is not None
            and device_client_id != group_client_id
        ):
            results.append(
                _result(
                    "record.source_attribution",
                    "contradicted",
                    evidence={"platform_group_id": group_id},
                    owner="legacy:computer_client_conflict",
                )
            )
        else:
            results.append(
                _result(
                    "record.source_attribution",
                    "supported",
                    evidence={"platform_group_id": group_id},
                    owner="source_group_mapping",
                )
            )
    if role == "endpoint_agent" and present:
        reported_online = record.get("reported_online")
        results.append(
            _result(
                "record.reported_status",
                "unknown" if reported_online is None else "supported",
                dimension="connectivity",
                evidence=(
                    {}
                    if reported_online is None
                    else {"reported_online": reported_online}
                ),
                missing=([] if reported_online is not None else ["reported_online"]),
            )
        )
        last_contact = record.get("reported_last_contact_at")
        results.append(
            _result(
                "record.reported_contact",
                "unknown" if last_contact is None else "supported",
                dimension="last_contact",
                evidence=(
                    {}
                    if last_contact is None
                    else {"reported_last_contact_at": last_contact.isoformat()}
                ),
                missing=(
                    [] if last_contact is not None else ["reported_last_contact_at"]
                ),
            )
        )
        results.append(
            _staleness_result(
                record, last_contact, stale_after_days, computer_alive, now
            )
        )
    else:
        results.extend(
            [
                _result(
                    "record.reported_status",
                    "not_applicable",
                    dimension="connectivity",
                    evidence={"role": role, "presence": record["presence"]},
                ),
                _result(
                    "record.reported_contact",
                    "not_applicable",
                    dimension="last_contact",
                    evidence={"role": role, "presence": record["presence"]},
                ),
            ]
        )
    if role == "unclassified":
        results.append(
            _result(
                "record.role",
                "unknown",
                missing=["record_role"],
                evidence={"entity_type": record["entity_type"]},
            )
        )
    else:
        results.append(_result("record.role", "supported", evidence={"role": role}))

    if record["platform"] != "Hudu" or record["entity_type"] != "cmdb.asset":
        results.append(
            _result("record.reference", "not_applicable", evidence={"role": role})
        )
    else:
        verdict = data.get("link_verdict")
        if not present:
            results.append(
                _result(
                    "record.reference",
                    "not_applicable",
                    evidence={"presence": "withdrawn"},
                )
            )
        elif verdict == "linked":
            results.append(
                _result(
                    "record.reference",
                    "supported",
                    dimension="hudu_device_reference",
                    evidence={"verdict": verdict},
                )
            )
        elif verdict == "unlinked":
            results.append(
                _result(
                    "record.reference",
                    "unknown",
                    dimension="hudu_device_reference",
                    missing=["integrated_device_card"],
                    evidence={"verdict": verdict},
                )
            )
        elif verdict == "stale" and bool(data.get("archived")):
            results.append(
                _result(
                    "record.reference",
                    "not_applicable",
                    dimension="hudu_device_reference",
                    evidence={"verdict": verdict, "archived": True},
                )
            )
        elif verdict in {"stale", "divergent"}:
            legacy_owner = (
                "legacy:cmdb_asset_stale"
                if verdict == "stale" and record.get("legacy_stale_reference")
                else "legacy:cmdb_link_incorrect"
                if verdict == "divergent" and record.get("legacy_divergent_reference")
                else ""
            )
            results.append(
                _result(
                    "record.reference",
                    "contradicted",
                    dimension="hudu_device_reference",
                    evidence={"verdict": verdict},
                    owner=legacy_owner,
                    finding=(
                        None
                        if legacy_owner
                        else {
                            "type": "source_record_reference_review",
                            "severity": "medium",
                        }
                    ),
                )
            )
        else:
            results.append(
                _result(
                    "record.reference",
                    "unknown",
                    dimension="hudu_device_reference",
                    missing=["hudu_link_verdict"],
                )
            )

    risks = software_risks or []
    if not software_risk_enabled:
        results.append(
            _result(
                "software.vulnerability",
                "unknown",
                missing=["vulnerable_software_enabled"],
            )
        )
    elif risks:
        actionable = [risk for risk in risks if not risk.get("owned_by_computer")]
        if actionable:
            severity = (
                software_severity_kev
                if any(risk["kev"] for risk in actionable)
                else software_severity_high
            )
            results.append(
                _result(
                    "software.vulnerability",
                    "contradicted",
                    evidence={
                        "installations": actionable[:20],
                        "count": len(actionable),
                    },
                    finding={
                        "type": "source_record_vulnerable_software",
                        "severity": severity,
                    },
                )
            )
        else:
            results.append(
                _result(
                    "software.vulnerability",
                    "contradicted",
                    evidence={"installations": risks[:20], "count": len(risks)},
                    owner="computer_software_finding",
                )
            )
    else:
        results.append(_result("software.vulnerability", "supported"))

    rejected = rejected_software or []
    if not rejected_software_enabled or not software_policy_known:
        missing = (
            ["rejected_installed_enabled"]
            if not rejected_software_enabled
            else ["client_software_policy"]
        )
        results.append(_result("software.decision", "unknown", missing=missing))
    elif rejected:
        results.append(
            _result(
                "software.decision",
                "contradicted",
                evidence={"installations": rejected[:20], "count": len(rejected)},
                finding={
                    "type": "source_record_rejected_software",
                    "severity": rejected_software_severity,
                },
            )
        )
    else:
        results.append(_result("software.decision", "supported"))

    suspicious = suspicious_software or []
    if not suspicious_software_enabled:
        results.append(
            _result(
                "software.suspicious_name",
                "unknown",
                missing=["suspicious_name_enabled"],
            )
        )
    elif suspicious:
        results.append(
            _result(
                "software.suspicious_name",
                "contradicted",
                evidence={"installations": suspicious[:20], "count": len(suspicious)},
                finding={
                    "type": "source_record_suspicious_software",
                    "severity": suspicious[0]["severity"],
                },
            )
        )
    else:
        results.append(_result("software.suspicious_name", "supported"))

    malicious = malicious_software_hints or []
    if not malicious_software_enabled:
        results.append(
            _result(
                "software.threat_intel",
                "unknown",
                missing=["known_malicious_hint_enabled"],
            )
        )
    elif malicious:
        results.append(
            _result(
                "software.threat_intel",
                "contradicted",
                evidence={"installations": malicious[:20], "count": len(malicious)},
                finding={
                    "type": "source_record_malicious_software_hint",
                    "severity": malicious[0]["severity"],
                },
            )
        )
    else:
        results.append(_result("software.threat_intel", "supported"))

    tools = unauthorized_tools or []
    if not capability_policy_known:
        results.append(
            _result(
                "software.capability",
                "unknown",
                missing=["capability_policy_or_product_link"],
            )
        )
    elif tools:
        results.append(
            _result(
                "software.capability",
                "contradicted",
                evidence={"installations": tools[:20], "count": len(tools)},
                finding={"type": "source_record_unauthorized_tool", "severity": "high"},
            )
        )
    else:
        results.append(_result("software.capability", "supported"))

    compares = role in _IDENTITY_ROLES
    attached = record["device_id"] is not None and record["device_live"]

    # identifier.validity / serial
    if not compares:
        results.append(
            _result(
                "identifier.validity",
                "not_applicable",
                dimension="serial",
                evidence={"role": role},
            )
        )
    else:
        serial = (data.get("serial_number") or "").strip()
        if not serial:
            results.append(
                _result(
                    "identifier.validity",
                    "unknown",
                    dimension="serial",
                    missing=["serial_number"],
                )
            )
        elif is_usable_serial(serial):
            results.append(
                _result("identifier.validity", "supported", dimension="serial")
            )
        else:
            evidence = {} if record["restricted"] else {"serial": serial}
            owner = "legacy:placeholder_serial" if attached else ""
            finding = None
            if present and not attached:
                finding = {
                    "type": "source_record_identifier_invalid",
                    "severity": "high",
                }
            results.append(
                _result(
                    "identifier.validity",
                    "contradicted",
                    dimension="serial",
                    evidence=evidence,
                    owner=owner,
                    finding=finding,
                )
            )

    # identifier.validity / MAC
    if not compares:
        results.append(
            _result(
                "identifier.validity",
                "not_applicable",
                dimension="mac",
                evidence={"role": role},
            )
        )
    else:
        mac_claims = data.get("macs")
        if mac_claims in (None, []):
            results.append(
                _result(
                    "identifier.validity",
                    "unknown",
                    dimension="mac",
                    missing=["macs"],
                )
            )
        else:
            valid_shape = isinstance(mac_claims, list)
            values = mac_claims if valid_shape else [mac_claims]
            invalid = [
                value
                for value in values
                if not valid_shape
                or not isinstance(value, str)
                or not normalize_mac(value)
            ]
            if not invalid:
                results.append(
                    _result(
                        "identifier.validity",
                        "supported",
                        dimension="mac",
                        evidence={"count": len(values)},
                    )
                )
            else:
                legacy_owned = attached and all(
                    isinstance(value, str) and is_junk_mac(value) for value in invalid
                )
                evidence = {"invalid_count": len(invalid)}
                if not valid_shape:
                    evidence["invalid_shape"] = True
                if not record["restricted"]:
                    evidence["invalid_values"] = invalid[:20]
                finding = (
                    None
                    if legacy_owned or not present
                    else {
                        "type": "source_record_identifier_invalid",
                        "severity": "medium"
                        if all(
                            isinstance(value, str) and is_junk_mac(value)
                            for value in invalid
                        )
                        else "high",
                    }
                )
                results.append(
                    _result(
                        "identifier.validity",
                        "contradicted",
                        dimension="mac",
                        evidence=evidence,
                        owner="legacy:placeholder_mac" if legacy_owned else "",
                        finding=finding,
                    )
                )

    # record.purpose: no purpose policy is authored, so presence is allowed by
    # default (user decision 2026-11-01); a future restriction would contradict it.
    results.append(
        _result(
            "record.purpose", "supported", evidence={"policy": "allowed_by_default"}
        )
    )

    # identity.association
    if not compares:
        results.append(
            _result("identity.association", "not_applicable", evidence={"role": role})
        )
    elif identity_ownership_deferred:
        results.append(
            _result("identity.association", "unknown", missing=["computer_client_ownership"])
        )
    elif attached and attached_contradiction:
        # A corroborated serial/VM UUID match points to exactly one other
        # Computer: the attachment needs a decision (standing rule, 2026-11-01).
        owner = attached_contradiction.get("owner") or ""
        results.append(
            _result(
                "identity.association",
                "contradicted",
                evidence={
                    "device_id": str(record["device_id"]),
                    "proposed_device_id": str(attached_contradiction["target"]),
                    "matcher": attached_contradiction["matcher"],
                },
                owner=owner,
                finding=None
                if owner
                else {"type": "source_record_identity_review", "severity": "critical"},
            )
        )
    elif attached:
        results.append(
            _result(
                "identity.association",
                "supported",
                evidence={
                    "device_id": str(record["device_id"]),
                    "method": record["match_method"] or "",
                },
            )
        )
    elif not present:
        results.append(
            _result(
                "identity.association",
                "not_applicable",
                evidence={"presence": "withdrawn"},
            )
        )
    else:
        review = identity_conflicts or {}
        listed = {
            str(device_id): sorted(families) for device_id, families in review.items()
        }
        if review:
            owner = "entity_candidate" if record["candidate_pending"] else ""
            finding = (
                None
                if owner
                else {
                    "type": "source_record_identity_review",
                    "severity": "critical",
                }
            )
            results.append(
                _result(
                    "identity.association",
                    "contradicted",
                    evidence={"candidates": listed},
                    owner=owner,
                    finding=finding,
                )
            )
        else:
            results.append(
                _result(
                    "identity.association",
                    "unknown",
                    evidence={
                        "candidates": {
                            str(device_id): sorted(families)
                            for device_id, families in candidates.items()
                        }
                    },
                    missing=[
                        "unique_qualified_match" if candidates else "candidate_computer"
                    ],
                    owner="entity_candidate" if record["candidate_pending"] else "",
                )
            )
    return results


def condition_key(
    target_kind: str, target_id: uuid.UUID, rule: str, dimension: str
) -> str:
    raw = f"{target_kind}:{target_id}:{rule}:{dimension}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def _rejected_software_by_record(
    cur: Any, tenant_id: int, records: list[dict], subject_ids: list[uuid.UUID]
) -> tuple[dict[uuid.UUID, list[dict]], dict[uuid.UUID, bool]]:
    """Read exact effective title/publisher decisions for source installations."""
    if not subject_ids:
        return {}, {}
    cur.execute(
        f"""
        WITH installs AS (
            SELECT i.source_record_id, i.canonical_name, i.publisher, i.version,
                   CASE WHEN d.id IS NULL
                        THEN operations.computer_client_independent_evidence(s.tenant_id, s.observation_id)
                        ELSE owner.effective_client_id END AS client_id,
                   CASE WHEN d.id IS NOT NULL AND owner.effective_client_id IS NOT NULL
                        THEN d.id END AS device_id
              FROM operations.source_record_software_current i
              JOIN operations.source_record_subjects s
                ON s.tenant_id = i.tenant_id AND s.id = i.source_record_id
              LEFT JOIN operations.entity_observation_current o
                ON o.tenant_id = s.tenant_id AND o.observation_id = s.observation_id
              LEFT JOIN operations.entity_source_links link
                ON link.tenant_id = s.tenant_id AND link.source_instance_id = s.source_instance_id
               AND link.external_namespace = s.external_namespace
               AND link.parent_external_namespace = s.parent_external_namespace
               AND link.parent_external_id = s.parent_external_id
               AND link.external_id = s.external_id AND link.entity_class_id = 'device'
              LEFT JOIN operations.devices d
                ON d.tenant_id = link.tenant_id AND d.id = link.entity_id AND d.deleted_at IS NULL
              LEFT JOIN operations.computer_client_ownership owner
                ON owner.tenant_id = d.tenant_id AND owner.device_id = d.id
               AND owner.state IN ('resolved', 'decision_protected')
             WHERE i.tenant_id = %s AND i.source_record_id = ANY(%s::uuid[])
               AND i.stale_since IS NULL
        )
        SELECT i.source_record_id, i.canonical_name, i.publisher, i.version,
               {software_coverage.TITLE_DECISION} AS title_decision,
               {software_coverage.PUBLISHER_DECISION} AS publisher_decision
          FROM installs i
          LEFT JOIN operations.v_software_decision_keys title_device
            ON title_device.tenant_id = %s AND title_device.match_kind = 'title'
           AND title_device.scope = 'device' AND title_device.device_id = i.device_id
           AND title_device.match_key = lower(i.canonical_name)
          LEFT JOIN operations.v_software_decision_keys title_client
            ON title_client.tenant_id = %s AND title_client.match_kind = 'title'
           AND title_client.scope = 'client' AND title_client.client_id = i.client_id
           AND title_client.match_key = lower(i.canonical_name)
          LEFT JOIN operations.v_software_decision_keys title_global
            ON title_global.tenant_id = %s AND title_global.match_kind = 'title'
           AND title_global.scope = 'global' AND title_global.match_key = lower(i.canonical_name)
          LEFT JOIN operations.v_software_decision_keys publisher_device
            ON publisher_device.tenant_id = %s AND publisher_device.match_kind = 'publisher'
           AND publisher_device.scope = 'device' AND publisher_device.device_id = i.device_id
           AND publisher_device.match_key = lower(i.publisher)
          LEFT JOIN operations.v_software_decision_keys publisher_client
            ON publisher_client.tenant_id = %s AND publisher_client.match_kind = 'publisher'
           AND publisher_client.scope = 'client' AND publisher_client.client_id = i.client_id
           AND publisher_client.match_key = lower(i.publisher)
          LEFT JOIN operations.v_software_decision_keys publisher_global
            ON publisher_global.tenant_id = %s AND publisher_global.match_kind = 'publisher'
           AND publisher_global.scope = 'global' AND publisher_global.match_key = lower(i.publisher)
        """,
        (tenant_id, subject_ids, *((tenant_id,) * 6)),
    )
    rejected: dict[uuid.UUID, list[dict]] = defaultdict(list)
    policy_known = {
        record["id"]: record.get("client_id") is not None
        and (not record.get("device_live") or record.get("device_client_id") is not None)
        for record in records
    }
    for (
        subject_id,
        name,
        publisher,
        version,
        title,
        publisher_decision,
    ) in cur.fetchall():
        if title is not None or publisher_decision is not None:
            policy_known[subject_id] = True
        if title == "reject" or publisher_decision == "reject":
            rejected[subject_id].append(
                {
                    "canonical_name": name,
                    "publisher": publisher,
                    "version": version,
                    "decision": "reject",
                }
            )
    return rejected, policy_known


def _staleness_result(
    record: dict,
    last_contact: datetime | None,
    stale_after_days: int | None,
    computer_alive: bool,
    now: datetime | None,
) -> dict:
    """An agent record no longer contacting its source (one default threshold).

    The threshold is the tenant's retire-review setting for every source (user
    decision 2026-11-01). When the whole Computer has gone quiet, its lifecycle
    review owns the work; a native cleanup issue opens only for an unattached
    record or one whose Computer still reports through other sources.
    """
    if stale_after_days is None or now is None:
        return _result("record.staleness", "unknown", missing=["stale_after_days"])
    if last_contact is None:
        return _result(
            "record.staleness", "unknown", missing=["reported_last_contact_at"]
        )
    age_days = (now - last_contact).total_seconds() / 86400
    evidence = {"days_since_contact": int(age_days), "threshold_days": stale_after_days}
    if age_days <= stale_after_days:
        return _result("record.staleness", "supported", evidence=evidence)
    attached = record["device_id"] is not None and record["device_live"]
    if attached and not computer_alive:
        return _result(
            "record.staleness",
            "contradicted",
            evidence=evidence,
            owner="legacy:computer_lifecycle",
        )
    return _result(
        "record.staleness",
        "contradicted",
        evidence=evidence,
        finding={"type": "source_record_cleanup", "severity": "medium"},
    )


_LEGACY_IDENTITY_OWNERS = (
    "shared_serial",
    "two_machines_on_one_computer",
    "duplicate_device_records",
)


def _attached_contradictions(
    cur: Any, tenant_id: int, records: list[dict], deferred_subjects: set[uuid.UUID] | None = None
) -> dict[uuid.UUID, dict]:
    """Attached records whose corroborated serial/VM UUID points to another Computer.

    A cheap key pre-filter keeps the full matcher to records that share a strong
    key with a record on a different Computer. An open legacy identity finding
    on either Computer owns the correction.
    """
    attached = {
        r["id"]: r
        for r in records
        if r["record_role"] in _IDENTITY_ROLES
        and r["presence"] == "present"
        and r["device_id"] is not None
        and r["device_live"]
        and r["observation_id"] is not None
    }
    if not attached:
        return {}
    cur.execute(
        """
        SELECT DISTINCT mine.subject_id
          FROM operations.source_record_lookup_keys mine
          JOIN operations.source_record_lookup_keys other
            ON other.tenant_id = mine.tenant_id AND other.key_family = mine.key_family
           AND other.normalized_value = mine.normalized_value
           AND other.subject_id <> mine.subject_id
          JOIN operations.entity_source_links mine_link
            ON mine_link.tenant_id = mine.tenant_id AND mine_link.source_subject_id = mine.subject_id
           AND mine_link.entity_class_id = 'device'
          JOIN operations.entity_source_links other_link
            ON other_link.tenant_id = other.tenant_id
           AND other_link.source_subject_id = other.subject_id
           AND other_link.entity_class_id = 'device'
           AND other_link.entity_id <> mine_link.entity_id
         WHERE mine.tenant_id = %s AND mine.subject_id = ANY(%s::uuid[])
           AND mine.key_family IN ('serial', 'vm_uuid')
        """,
        (tenant_id, list(attached)),
    )
    suspects = [attached[row[0]] for row in cur.fetchall()]
    if not suspects:
        return {}
    policies = load_identity_match_policies(cur, tenant_id)
    identity_types = sorted(identity_entity_types(cur))
    found: dict[uuid.UUID, dict] = {}
    for record in suspects:
        data = record.get("canonical_data") or {}
        preview = preview_match(
            cur,
            tenant_id=tenant_id,
            source_name=record["platform"],
            external_id=record["external_id"],
            entity_type=record["entity_type"],
            serial=data.get("serial_number"),
            vm_uuid=data.get("vm_uuid"),
            hostname=record_name_short(
                cur,
                record["platform"],
                record["entity_type"],
                data.get("hostname") or data.get("guest_name"),
                data.get("domain"),
            )
            or None,
            macs=data.get("macs") or [],
            client_id=record["client_id"],
            source_instance_id=record["source_instance_id"],
            policies=policies,
            is_online=data.get("is_online"),
            identity_types=identity_types,
            excluded_observation_ids=(record["observation_id"],),
        )
        if getattr(preview, "ownership_deferred", False):
            if deferred_subjects is not None:
                deferred_subjects.add(record["id"])
            continue
        result = preview.result
        if (
            result is not None
            and result.matcher in ("serial", "vm_uuid")
            and result.device_id != record["device_id"]
        ):
            found[record["id"]] = {
                "target": result.device_id,
                "matcher": result.matcher,
            }
    if not found:
        return {}
    devices = {attached[sid]["device_id"] for sid in found} | {
        v["target"] for v in found.values()
    }
    cur.execute(
        """
        SELECT DISTINCT f.subject_id
          FROM operations.findings f
          JOIN operations.finding_types ft ON ft.id = f.finding_type_id
         WHERE f.tenant_id = %s AND f.subject_type = 'device'
           AND f.subject_id = ANY(%s::uuid[])
           AND ft.name = ANY(%s)
           AND f.status IN ('open', 'acknowledged', 'investigating', 'suppressed')
        """,
        (tenant_id, list(devices), list(_LEGACY_IDENTITY_OWNERS)),
    )
    owned = {row[0] for row in cur.fetchall()}
    for subject_id, item in found.items():
        if attached[subject_id]["device_id"] in owned or item["target"] in owned:
            item["owner"] = "legacy:computer_identity"
    return found


def _computers_alive(
    cur: Any, tenant_id: int, records: list[dict], stale_after_days: int, now: datetime
) -> dict[uuid.UUID, bool]:
    """Per record: does its Computer still report through another record?"""
    devices = {
        r["device_id"]
        for r in records
        if r["device_id"] is not None and r["device_live"]
    }
    if not devices:
        return {}
    cur.execute(
        """
        SELECT link.entity_id, s.id, s.observation_id
          FROM operations.entity_source_links link
          JOIN operations.source_record_subjects s
            ON s.tenant_id = link.tenant_id AND s.id = link.source_subject_id
         WHERE link.tenant_id = %s AND link.entity_class_id = 'device'
           AND link.entity_id = ANY(%s::uuid[]) AND s.presence = 'present'
        """,
        (tenant_id, list(devices)),
    )
    members = cur.fetchall()
    cur.execute(
        """
        SELECT observation_id, reported_last_contact_at
          FROM operations.v_entity_observation_admin_metadata
         WHERE tenant_id = %s AND observation_id = ANY(%s::uuid[])
        """,
        (tenant_id, [m[2] for m in members if m[2] is not None]),
    )
    contact = dict(cur.fetchall())
    alive: dict[uuid.UUID, bool] = {}
    for record in records:
        if record["device_id"] is None or not record["device_live"]:
            continue
        alive[record["id"]] = any(
            device == record["device_id"]
            and subject != record["id"]
            and contact.get(observation) is not None
            and (now - contact[observation]).total_seconds() / 86400 <= stale_after_days
            for device, subject, observation in members
        )
    return alive


def _qualified_identity_conflicts(
    cur: Any, tenant_id: int, records: list[dict], deferred_subjects: set[uuid.UUID] | None = None
) -> dict[uuid.UUID, dict[uuid.UUID, set[str]]]:
    """Return only competing strong matches or established identity conflicts.

    Weak hostname/MAC similarity remains visible as unknown evidence. It does
    not open a critical identity correction by itself.
    """
    subjects = [
        record
        for record in records
        if record["record_role"] in _IDENTITY_ROLES
        and record["presence"] == "present"
        and not (record["device_id"] is not None and record["device_live"])
        and record["observation_id"] is not None
    ]
    if not subjects:
        return {}
    policies = load_identity_match_policies(cur, tenant_id)
    identity_types = sorted(identity_entity_types(cur))
    conflicts: dict[uuid.UUID, dict[uuid.UUID, set[str]]] = {}
    for record in subjects:
        data = record.get("canonical_data") or {}
        preview = preview_match(
            cur,
            tenant_id=tenant_id,
            source_name=record["platform"],
            external_id=record["external_id"],
            entity_type=record["entity_type"],
            serial=data.get("serial_number"),
            vm_uuid=data.get("vm_uuid"),
            hostname=record_name_short(
                cur,
                record["platform"],
                record["entity_type"],
                data.get("hostname") or data.get("guest_name"),
                data.get("domain"),
            )
            or None,
            macs=data.get("macs") or [],
            client_id=record["client_id"],
            source_instance_id=record["source_instance_id"],
            policies=policies,
            is_online=data.get("is_online"),
            identity_types=identity_types,
            excluded_observation_ids=(record["observation_id"],),
        )
        if getattr(preview, "ownership_deferred", False):
            if deferred_subjects is not None:
                deferred_subjects.add(record["id"])
            continue
        for attempt in preview.attempts:
            established_conflict = any(
                reason != "operator_exclusion" for reason in attempt.blockers.values()
            )
            strong_ambiguity = (
                attempt.matcher in {"serial", "vm_uuid", "hostname_mac"}
                and len(attempt.usable) > 1
            )
            if not established_conflict and not strong_ambiguity:
                continue
            conflicts[record["id"]] = defaultdict(set)
            for device_id in attempt.candidates:
                conflicts[record["id"]][device_id].add(attempt.matcher)
                if device_id in attempt.blockers:
                    conflicts[record["id"]][device_id].add(
                        f"conflict:{attempt.blockers[device_id]}"
                    )
            break
    return conflicts


def _unauthorized_tools_by_record(
    cur: Any, tenant_id: int, subject_ids: list[uuid.UUID]
) -> tuple[dict[uuid.UUID, list[dict]], dict[uuid.UUID, bool]]:
    """Evaluate alertable catalog capabilities with the Computer policy contract."""
    from ingest.config import settings

    if not subject_ids:
        return {}, {}
    if not settings.CAPABILITY_ENFORCEMENT_ENABLED:
        return {}, {subject_id: False for subject_id in subject_ids}
    if not software_capabilities.capability_schema_ready(cur):
        return {}, {subject_id: False for subject_id in subject_ids}

    capabilities = software_capabilities.load_effective_capabilities(cur)
    authorizations = software_capabilities.load_authorizations(cur, tenant_id)
    sanctioned = software_capabilities.load_sanctioned_product_identities(
        cur, tenant_id
    )
    cur.execute(
        f"""
        WITH installs AS (
            SELECT i.source_record_id, i.canonical_name, i.publisher, i.version,
                   CASE WHEN d.id IS NULL
                        THEN operations.computer_client_independent_evidence(s.tenant_id, s.observation_id)
                        ELSE owner.effective_client_id END AS client_id,
                   CASE WHEN d.id IS NOT NULL AND owner.effective_client_id IS NOT NULL
                        THEN d.id END AS device_id
              FROM operations.source_record_software_current i
              JOIN operations.source_record_subjects s
                ON s.tenant_id = i.tenant_id AND s.id = i.source_record_id
              LEFT JOIN operations.entity_observation_current o
                ON o.tenant_id = s.tenant_id AND o.observation_id = s.observation_id
              LEFT JOIN operations.entity_source_links link
                ON link.tenant_id = s.tenant_id AND link.source_instance_id = s.source_instance_id
               AND link.external_namespace = s.external_namespace
               AND link.parent_external_namespace = s.parent_external_namespace
               AND link.parent_external_id = s.parent_external_id
               AND link.external_id = s.external_id AND link.entity_class_id = 'device'
              LEFT JOIN operations.devices d
                ON d.tenant_id = link.tenant_id AND d.id = link.entity_id AND d.deleted_at IS NULL
              LEFT JOIN operations.computer_client_ownership owner
                ON owner.tenant_id = d.tenant_id AND owner.device_id = d.id
               AND owner.state IN ('resolved', 'decision_protected')
             WHERE i.tenant_id = %s AND i.source_record_id = ANY(%s::uuid[])
               AND i.stale_since IS NULL
        ), resolved AS (
            SELECT i.*, product.product_uuid,
                   {software_coverage.TITLE_DECISION} AS title_decision,
                   {software_coverage.PUBLISHER_DECISION} AS publisher_decision
              FROM installs i
              LEFT JOIN LATERAL (
                  SELECT alias.canonical_publisher
                    FROM operations.publisher_aliases alias
                   WHERE alias.enabled AND COALESCE(i.publisher, '') <> ''
                     AND i.publisher ILIKE alias.raw_pattern
                   LIMIT 1
              ) resolved_publisher ON TRUE
              LEFT JOIN catalog.publishers publisher
                ON publisher.canonical_name =
                   COALESCE(resolved_publisher.canonical_publisher, NULLIF(i.publisher, ''))
              LEFT JOIN catalog.products product
                ON product.canonical_name = i.canonical_name
               AND product.publisher_id IS NOT DISTINCT FROM publisher.id
              LEFT JOIN operations.v_software_decision_keys title_device
                ON title_device.tenant_id = %s AND title_device.match_kind = 'title'
               AND title_device.scope = 'device' AND title_device.device_id = i.device_id
               AND title_device.match_key = lower(i.canonical_name)
              LEFT JOIN operations.v_software_decision_keys title_client
                ON title_client.tenant_id = %s AND title_client.match_kind = 'title'
               AND title_client.scope = 'client' AND title_client.client_id = i.client_id
               AND title_client.match_key = lower(i.canonical_name)
              LEFT JOIN operations.v_software_decision_keys title_global
                ON title_global.tenant_id = %s AND title_global.match_kind = 'title'
               AND title_global.scope = 'global' AND title_global.match_key = lower(i.canonical_name)
              LEFT JOIN operations.v_software_decision_keys publisher_device
                ON publisher_device.tenant_id = %s AND publisher_device.match_kind = 'publisher'
               AND publisher_device.scope = 'device' AND publisher_device.device_id = i.device_id
               AND publisher_device.match_key = lower(i.publisher)
              LEFT JOIN operations.v_software_decision_keys publisher_client
                ON publisher_client.tenant_id = %s AND publisher_client.match_kind = 'publisher'
               AND publisher_client.scope = 'client' AND publisher_client.client_id = i.client_id
               AND publisher_client.match_key = lower(i.publisher)
              LEFT JOIN operations.v_software_decision_keys publisher_global
                ON publisher_global.tenant_id = %s AND publisher_global.match_kind = 'publisher'
               AND publisher_global.scope = 'global' AND publisher_global.match_key = lower(i.publisher)
        ), concerns AS (
            -- One pass per batch over open concern findings for these titles.
            SELECT DISTINCT lower(f.finding_details->>'canonical_name') AS title_key
              FROM operations.findings f
              JOIN operations.finding_types other_type ON other_type.id = f.finding_type_id
             WHERE f.tenant_id = %s
               AND f.status IN ('open', 'acknowledged', 'investigating', 'suppressed')
               AND other_type.concern_signal
               AND lower(f.finding_details->>'canonical_name')
                   IN (SELECT lower(canonical_name) FROM installs)
        )
        SELECT r.source_record_id, r.client_id, r.canonical_name, r.publisher, r.version,
               r.product_uuid, e.capability, e.alertable, e.evidence_sources,
               c.unauthorized_finding_type, ft.suppressed_by_approval,
               r.title_decision, r.publisher_decision,
               concern.title_key IS NOT NULL AS other_concern
          FROM resolved r
          LEFT JOIN concerns concern ON concern.title_key = lower(r.canonical_name)
          LEFT JOIN catalog.v_product_capability_effective e
            ON e.product_uuid = r.product_uuid AND e.alertable
          LEFT JOIN catalog.capability c ON c.key = e.capability
          LEFT JOIN operations.finding_types ft ON ft.name = c.unauthorized_finding_type
        """,
        (tenant_id, subject_ids, *((tenant_id,) * 7)),
    )
    risks: dict[uuid.UUID, list[dict]] = defaultdict(list)
    known = {subject_id: False for subject_id in subject_ids}
    saw_install: set[uuid.UUID] = set()
    unlinked_products: set[uuid.UUID] = set()
    for (
        subject_id,
        client_id,
        name,
        publisher,
        version,
        product_uuid,
        capability,
        alertable,
        evidence_sources,
        finding_name,
        suppressed_by_approval,
        title_decision,
        publisher_decision,
        other_concern,
    ) in cur.fetchall():
        saw_install.add(subject_id)
        if client_id is None:
            # Neither a missing source mapping nor an unresolved attached
            # Computer authorizes a client-scoped capability conclusion.
            unlinked_products.add(subject_id)
            continue
        if product_uuid is None:
            unlinked_products.add(subject_id)
            continue
        known[subject_id] = True
        if not capability or not alertable or not finding_name:
            continue
        if not any(
            item["capability"] == capability
            and item["alertable"]
            and item["finding_type"] == finding_name
            for item in capabilities.get(product_uuid, [])
        ):
            continue
        allowed, basis = software_capabilities.permitted(
            authorizations,
            sanctioned,
            client_id,
            capability,
            product_uuid,
        )
        if allowed or software_capabilities.silenced_by_approval(
            bool(suppressed_by_approval),
            title_decision,
            publisher_decision,
            bool(other_concern),
        ):
            continue
        risks[subject_id].append(
            {
                "canonical_name": name,
                "publisher": publisher,
                "version": version,
                "capability": capability,
                "not_permitted_basis": basis,
                "evidence_sources": evidence_sources,
            }
        )
    for subject_id in subject_ids:
        known[subject_id] = (
            subject_id in saw_install and subject_id not in unlinked_products
        )
    return risks, known


def _software_signal_findings_by_record(
    cur: Any,
    tenant_id: int,
    subject_ids: list[uuid.UUID],
    config: dict[str, Any],
    unauthorized_tools: dict[uuid.UUID, list[dict]],
) -> tuple[dict[uuid.UUID, dict[str, list[dict]]], dict[str, bool]]:
    """Evaluate title signals with the catalog rules and approval contract."""
    from ingest.software_rules import compile_rules

    enabled = {
        "suspicious": bool(config["suspicious_name_enabled"]),
        "threat": bool(config["known_malicious_hint_enabled"]),
    }
    if not subject_ids:
        return {}, enabled

    cur.execute(
        "SELECT rule_type, pattern, is_regex FROM operations.software_classifier_rules "
        "WHERE enabled AND rule_type IN ('suspicious_name', 'install_path_suspicious')"
    )
    rules = compile_rules(cur.fetchall())
    suspicious_name = rules.get("suspicious_name", lambda _value: False)
    suspicious_path = rules.get("install_path_suspicious", lambda _value: False)
    cur.execute(
        "SELECT name, default_severity, suppressed_by_approval "
        "FROM operations.finding_types "
        "WHERE name IN ('source_record_suspicious_software', "
        "'source_record_malicious_software_hint')"
    )
    type_policy = {
        name: (severity, bool(suppressed))
        for name, severity, suppressed in cur.fetchall()
    }
    cur.execute(
        f"""
        WITH installs AS (
            SELECT i.tenant_id, i.source_record_id, i.canonical_name, i.publisher,
                   i.version, i.install_location,
                   CASE WHEN d.id IS NULL
                        THEN operations.computer_client_independent_evidence(s.tenant_id, s.observation_id)
                        ELSE owner.effective_client_id END AS client_id,
                   CASE WHEN d.id IS NOT NULL AND owner.effective_client_id IS NOT NULL
                        THEN d.id END AS device_id
              FROM operations.source_record_software_current i
              JOIN operations.source_record_subjects s
                ON s.tenant_id = i.tenant_id AND s.id = i.source_record_id
              LEFT JOIN operations.entity_observation_current o
                ON o.tenant_id = s.tenant_id AND o.observation_id = s.observation_id
              LEFT JOIN operations.entity_source_links link
                ON link.tenant_id = s.tenant_id AND link.source_instance_id = s.source_instance_id
               AND link.external_namespace = s.external_namespace
               AND link.parent_external_namespace = s.parent_external_namespace
               AND link.parent_external_id = s.parent_external_id
               AND link.external_id = s.external_id AND link.entity_class_id = 'device'
              LEFT JOIN operations.devices d
                ON d.tenant_id = link.tenant_id AND d.id = link.entity_id
               AND d.deleted_at IS NULL
              LEFT JOIN operations.computer_client_ownership owner
                ON owner.tenant_id = d.tenant_id AND owner.device_id = d.id
               AND owner.state IN ('resolved', 'decision_protected')
             WHERE i.tenant_id = %s AND i.source_record_id = ANY(%s::uuid[])
               AND i.stale_since IS NULL
        ), threat_titles AS (
            SELECT lower(canonical_name) AS title_key, count(*) AS hits
              FROM operations.safety_signal
             WHERE tenant_id = %s AND signal_type = 'threat_hit'
               AND lower(canonical_name) IN (SELECT lower(canonical_name) FROM installs)
             GROUP BY 1
        ), threat_publishers AS (
            SELECT lower(publisher) AS publisher_key, count(*) AS hits
              FROM operations.safety_signal
             WHERE tenant_id = %s AND signal_type = 'threat_hit'
               AND lower(publisher) IN (SELECT lower(publisher) FROM installs)
             GROUP BY 1
        ), concerns AS (
            SELECT DISTINCT lower(f.finding_details->>'canonical_name') AS title_key
              FROM operations.findings f
              JOIN operations.finding_types ft ON ft.id = f.finding_type_id
             WHERE f.tenant_id = %s
               AND f.status IN ('open', 'acknowledged', 'investigating', 'suppressed')
               AND ft.concern_signal
               AND ft.name NOT IN ('suspicious_name', 'source_record_suspicious_software')
               AND lower(f.finding_details->>'canonical_name')
                   IN (SELECT lower(canonical_name) FROM installs)
        ), resolved AS (
            SELECT i.*,
                   {software_coverage.TITLE_DECISION} AS title_decision,
                   {software_coverage.PUBLISHER_DECISION} AS publisher_decision,
                   COALESCE(title_hits.hits, 0) + COALESCE(publisher_hits.hits, 0) AS threat_hits,
                   concern.title_key IS NOT NULL AS existing_concern
              FROM installs i
              {software_coverage.EFFECTIVE_DECISION_JOINS}
              LEFT JOIN threat_titles title_hits ON title_hits.title_key = lower(i.canonical_name)
              LEFT JOIN threat_publishers publisher_hits
                ON publisher_hits.publisher_key = lower(i.publisher)
              LEFT JOIN concerns concern ON concern.title_key = lower(i.canonical_name)
        )
        SELECT source_record_id, canonical_name, publisher, version, install_location,
               title_decision, publisher_decision, threat_hits, existing_concern
          FROM resolved
        """,
        (tenant_id, subject_ids, tenant_id, tenant_id, tenant_id),
    )
    findings: dict[uuid.UUID, dict[str, list[dict]]] = defaultdict(
        lambda: {"suspicious": [], "threat": []}
    )
    minimum_hits = int(config["known_malicious_hint_min_hits"])
    threat_severity = str(config["known_malicious_hint_severity"])
    for (
        subject_id,
        name,
        publisher,
        version,
        location,
        title_decision,
        publisher_decision,
        threat_hits,
        existing_concern,
    ) in cur.fetchall():
        threat_hits = int(threat_hits or 0)
        other_concern = bool(existing_concern or threat_hits > 0)
        other_concern = other_concern or any(
            item.get("canonical_name", "").lower() == (name or "").lower()
            for item in unauthorized_tools.get(subject_id, [])
        )
        other_concern = other_concern or suspicious_path(location or "")
        if enabled["suspicious"] and suspicious_name(name or ""):
            severity, suppressed = type_policy.get(
                "source_record_suspicious_software", ("medium", True)
            )
            if not software_capabilities.silenced_by_approval(
                suppressed, title_decision, publisher_decision, other_concern
            ):
                findings[subject_id]["suspicious"].append(
                    {
                        "canonical_name": name,
                        "publisher": publisher,
                        "version": version,
                        "signal": "suspicious_name",
                        "severity": severity,
                    }
                )
        if enabled["threat"] and threat_hits >= minimum_hits:
            findings[subject_id]["threat"].append(
                {
                    "canonical_name": name,
                    "publisher": publisher,
                    "version": version,
                    "signal": "threat_hit",
                    "threat_hit_count": threat_hits,
                    "severity": threat_severity,
                }
            )
    return findings, enabled


_TITLE_CVE_TTL = 300.0
_title_cve_cache: dict[tuple[int, float], tuple[float, dict]] = {}


def _title_cve_summaries(
    cur: Any, tenant_id: int, cvss_cutoff: float
) -> dict[str, tuple[bool, int, str, float | None]]:
    """Per title: (any KEV, qualifying CVE count, worst CVE, worst CVSS).

    Covers every title present in source-record inventory. CVE intelligence
    changes only when the intel Jobs run, so one computation serves a whole
    assessment run (cached for ``_TITLE_CVE_TTL`` seconds).
    """
    key = (tenant_id, cvss_cutoff)
    cached = _title_cve_cache.get(key)
    now = time.monotonic()
    if cached and now - cached[0] < _TITLE_CVE_TTL:
        return cached[1]
    cur.execute(
        """
        SELECT lower(match.canonical_name),
               bool_or(cve.kev_flag), count(*),
               (array_agg(cve.cve_id ORDER BY cve.kev_flag DESC, cve.cvss_v3 DESC NULLS LAST))[1],
               max(cve.cvss_v3)
          FROM operations.cve_match match
          JOIN intel.cves cve ON cve.cve_id = match.cve_id
         WHERE match.tenant_id = %s
           AND lower(match.canonical_name) IN (
               SELECT DISTINCT lower(canonical_name)
                 FROM operations.source_record_software_current
                WHERE tenant_id = %s AND stale_since IS NULL)
           AND (cve.kev_flag OR cve.cvss_v3 >= %s)
         GROUP BY 1
        """,
        (tenant_id, tenant_id, cvss_cutoff),
    )
    summaries = {
        title: (bool(kev), int(count), worst, float(cvss) if cvss is not None else None)
        for title, kev, count, worst, cvss in cur.fetchall()
    }
    _title_cve_cache[key] = (now, summaries)
    return summaries


def assess_records(
    cur: Any,
    tenant_id: int,
    generation: int,
    subject_ids: list[uuid.UUID],
    now: datetime,
) -> None:
    records = _load_records(cur, tenant_id, subject_ids)
    cur.execute(
        "SELECT config FROM operations.evaluator_config "
        "WHERE tenant_id = %s AND evaluator_name = 'software_classifier'",
        (tenant_id,),
    )
    config_row = cur.fetchone()
    software_config = software_settings.effective(
        config_row[0] if config_row and isinstance(config_row[0], dict) else {}
    )
    cvss_cutoff = float(software_config["vulnerable_software_cvss_cutoff"])
    vulnerable_enabled = bool(software_config["vulnerable_software_enabled"])
    rejected_enabled = bool(software_config["rejected_installed_enabled"])
    # Title-level CVE summaries (cve_match is title-level, like the Computer
    # finding) are computed once per run and cached; each batch reads only its
    # installations and whether a Computer finding already owns the title.
    title_cves = _title_cve_summaries(cur, tenant_id, cvss_cutoff)
    cur.execute(
        """
        WITH installs AS (
            SELECT i.source_record_id, i.canonical_name, i.version,
                   lower(i.canonical_name) AS title_key
              FROM operations.source_record_software_current i
             WHERE i.tenant_id = %s AND i.source_record_id = ANY(%s::uuid[])
               AND i.stale_since IS NULL
        ), owned AS (
            SELECT DISTINCT s.id AS source_record_id,
                   lower(f.finding_details->>'canonical_name') AS title_key
              FROM operations.source_record_subjects s
              JOIN operations.entity_source_links link
                ON link.tenant_id = s.tenant_id AND link.source_subject_id = s.id
               AND link.entity_class_id = 'device'
              JOIN operations.v_device_software_exposure exposure
                ON exposure.tenant_id = link.tenant_id AND exposure.device_id = link.entity_id
              JOIN operations.findings f
                ON f.tenant_id = exposure.tenant_id AND f.id = exposure.finding_id
              JOIN operations.finding_types ft ON ft.id = f.finding_type_id
             WHERE s.tenant_id = %s AND s.id = ANY(%s::uuid[])
               AND ft.name = 'vulnerable_software'
               AND f.status IN ('open', 'acknowledged', 'investigating', 'suppressed')
        )
        SELECT i.source_record_id, i.canonical_name, i.version, i.title_key,
               owned.source_record_id IS NOT NULL AS owned_by_computer
          FROM installs i
          LEFT JOIN owned
            ON owned.source_record_id = i.source_record_id AND owned.title_key = i.title_key
        """,
        (tenant_id, subject_ids, tenant_id, subject_ids),
    )
    software_risks: dict[uuid.UUID, list[dict]] = defaultdict(list)
    for subject_id, name, version, title_key, owned_by_computer in cur.fetchall():
        summary = title_cves.get(title_key)
        if summary is None:
            continue
        kev, cve_count, worst_cve, worst_cvss = summary
        software_risks[subject_id].append(
            {
                "canonical_name": name,
                "version": version,
                "cve": worst_cve,
                "cvss": worst_cvss,
                "kev": kev,
                "cve_count": cve_count,
                "owned_by_computer": bool(owned_by_computer),
            }
        )
    for risks in software_risks.values():
        risks.sort(key=lambda risk: (not risk["kev"], -(risk["cvss"] or 0)))
    rejected_software, software_policy_known = _rejected_software_by_record(
        cur, tenant_id, records, subject_ids
    )
    unauthorized_tools, capability_policy_known = _unauthorized_tools_by_record(
        cur, tenant_id, subject_ids
    )
    software_signals, software_signal_enabled = _software_signal_findings_by_record(
        cur, tenant_id, subject_ids, software_config, unauthorized_tools
    )
    deferred_identities: set[uuid.UUID] = set()
    identity_conflicts = _qualified_identity_conflicts(cur, tenant_id, records, deferred_identities)
    attached_contradictions = _attached_contradictions(cur, tenant_id, records, deferred_identities)
    from ingest import device_status_settings

    _offline_days, stale_after_days = device_status_settings.load(cur, tenant_id)
    computers_alive = _computers_alive(cur, tenant_id, records, stale_after_days, now)
    candidates = _candidate_computers(
        cur,
        tenant_id,
        [
            r["id"]
            for r in records
            if r["record_role"] in _IDENTITY_ROLES
            and r["presence"] == "present"
            and not (r["device_id"] is not None and r["device_live"])
        ],
    )
    type_ids = finding_type_ids(cur)
    # Unknown or resolved assessments can retain operator-managed findings.
    # Refresh their recorded association independently of each rule result.
    if records:
        cur.execute(
            """
            UPDATE operations.findings f
               SET client_id = attribution.client_id
              FROM unnest(%s::uuid[], %s::uuid[]) AS attribution(subject_id, client_id)
             WHERE f.tenant_id = %s AND f.condition_namespace = 'entity'
               AND f.subject_type = 'source_record' AND f.subject_id = attribution.subject_id
               AND f.finding_type_id = ANY(%s)
               AND f.status IN ('open', 'acknowledged', 'investigating', 'suppressed')
               AND f.client_id IS DISTINCT FROM attribution.client_id
            """,
            ([r["id"] for r in records], [r["client_id"] for r in records],
             tenant_id, list(type_ids.values())),
        )
    active_keys = active_native_keys(
        cur, tenant_id, "source_record", [r["id"] for r in records]
    )
    assessments: list[tuple] = []
    for record in records:
        results = evaluate_record(
            record,
            candidates.get(record["id"], {}),
            software_risks.get(record["id"], []),
            vulnerable_enabled,
            str(software_config["vulnerable_software_severity_kev"]),
            str(software_config["vulnerable_software_severity_high"]),
            rejected_software.get(record["id"], []),
            rejected_enabled,
            str(software_config["rejected_installed_severity"]),
            software_policy_known.get(record["id"], record["client_id"] is not None),
            software_signals.get(record["id"], {}).get("suspicious", []),
            software_signal_enabled["suspicious"],
            software_signals.get(record["id"], {}).get("threat", []),
            software_signal_enabled["threat"],
            unauthorized_tools.get(record["id"], []),
            capability_policy_known.get(record["id"], False),
            identity_conflicts=identity_conflicts.get(record["id"]),
            attached_contradiction=attached_contradictions.get(record["id"]),
            identity_ownership_deferred=record["id"] in deferred_identities,
            stale_after_days=stale_after_days,
            computer_alive=computers_alive.get(record["id"], False),
            now=now,
        )
        for result in results:
            finding_id = publish_finding(
                cur,
                tenant_id,
                type_ids,
                "source_record",
                record["id"],
                result,
                now,
                client_id=record["client_id"],
                context_participants=(
                    (("device", record["device_id"]),) if record["device_live"] else ()
                ),
                context={
                    "platform": record["platform"],
                    "entity_type": record["entity_type"],
                    "name": None
                    if record["restricted"]
                    else ((record.get("canonical_data") or {}).get("hostname")),
                },
                active_keys=active_keys,
            )
            write_assessment(
                cur,
                tenant_id,
                "source_record",
                record["id"],
                result,
                target_version=record["input_version"] * 1_000_000
                + record["association_version"],
                generation=generation,
                finding_id=finding_id,
                now=now,
                buffer=assessments,
            )
    flush_assessments(cur, assessments)


# --- shared publication helpers -----------------------------------------------------

_TYPE_NAMES = (
    "source_record_identity_review",
    "source_record_identifier_invalid",
    "source_record_duplicate_review",
    "source_record_reference_review",
    "source_record_vulnerable_software",
    "source_record_rejected_software",
    "source_record_suspicious_software",
    "source_record_malicious_software_hint",
    "source_record_unauthorized_tool",
    "source_record_cleanup",
)
_RULE_TYPES = {
    ("identity.association", ""): "source_record_identity_review",
    ("identifier.validity", "serial"): "source_record_identifier_invalid",
    ("identifier.validity", "mac"): "source_record_identifier_invalid",
    ("record.reference", "hudu_device_reference"): "source_record_reference_review",
    ("case.duplicate", ""): "source_record_duplicate_review",
    ("software.vulnerability", ""): "source_record_vulnerable_software",
    ("software.decision", ""): "source_record_rejected_software",
    ("software.suspicious_name", ""): "source_record_suspicious_software",
    ("software.threat_intel", ""): "source_record_malicious_software_hint",
    ("software.capability", ""): "source_record_unauthorized_tool",
    ("record.staleness", ""): "source_record_cleanup",
}


def finding_type_ids(cur: Any) -> dict[str, int]:
    cur.execute(
        "SELECT name, id FROM operations.finding_types WHERE name = ANY(%s)",
        (list(_TYPE_NAMES),),
    )
    return dict(cur.fetchall())


def publish_finding(
    cur: Any,
    tenant_id: int,
    type_ids: dict[str, int],
    target_kind: str,
    target_id: uuid.UUID,
    result: dict,
    now: datetime,
    *,
    client_id: Any,
    context: dict[str, Any],
    context_participants: tuple[tuple[str, Any], ...] = (),
    active_keys: set[str] | None = None,
) -> uuid.UUID | None:
    """Open, refresh or resolve the native finding one rule result implies.

    ``active_keys`` (from ``active_native_keys``) lets a batch skip the resolve
    statement for the many results that have no open finding.

    The rule's own result is the closure test: a current non-contradicted
    result (or ownership by legacy work) resolves an open native finding.
    """
    type_name = _RULE_TYPES.get((result["rule"], result["dimension"]))
    if type_name is None or type_name not in type_ids:
        return None
    key = condition_key(target_kind, target_id, result["rule"], result["dimension"])
    spec = result["finding"]
    if spec is None:
        if result["result"] == "unknown" and (
            result["rule"].startswith("software.")
            or result["rule"] == "identifier.validity"
            or result["rule"] == "record.reference"
            or (result["rule"] == "identity.association"
                and "computer_client_ownership" in result["missing"])
            or (result["rule"] == "case.duplicate"
                and "computer_client_ownership" in result["missing"])
        ):
            return None
        if active_keys is not None and key not in active_keys:
            return None
        cur.execute(
            """
            UPDATE operations.findings
               SET status = 'resolved', closed_at = %s, last_seen_at = %s
             WHERE tenant_id = %s AND condition_namespace = 'entity' AND condition_key = %s
               AND finding_type_id = %s AND status IN ('open', 'acknowledged')
            """,
            (now, now, tenant_id, key, type_ids[type_name]),
        )
        return None
    details = {
        "rule": result["rule"],
        "dimension": result["dimension"],
        "rule_revision": RULE_REVISION,
        "evidence": result["evidence"],
        **{k: v for k, v in context.items() if v is not None},
    }
    cur.execute(
        """
        UPDATE operations.findings
           SET client_id = %s, finding_details = %s::jsonb, last_seen_at = %s, last_detected_at = %s
         WHERE tenant_id = %s AND condition_namespace = 'entity' AND condition_key = %s
           AND status IN ('investigating', 'suppressed')
        RETURNING id
        """,
        (client_id, json.dumps(details), now, now, tenant_id, key),
    )
    row = cur.fetchone()
    if row:
        _record_condition(
            cur,
            tenant_id,
            row[0],
            type_name,
            key,
            target_kind,
            target_id,
            context_participants,
            now,
        )
        return row[0]
    cur.execute(
        """
        INSERT INTO operations.findings (
            id, version, tenant_id, finding_type_id, client_id,
            subject_type, subject_id, subject_layer, finding_details,
            condition_key, episode_key, severity, confidence, status,
            first_seen_at, last_seen_at, last_detected_at
        ) VALUES (
            gen_random_uuid(), 1, %s, %s, %s, %s, %s, '', %s::jsonb,
            %s, NULL, %s, 'confirmed', 'open', %s, %s, %s
        )
        ON CONFLICT (tenant_id, condition_namespace, condition_key)
            WHERE condition_key > '' AND status IN ('open', 'acknowledged', 'investigating', 'suppressed')
        DO UPDATE SET
            client_id = EXCLUDED.client_id,
            finding_details = EXCLUDED.finding_details,
            severity = EXCLUDED.severity,
            last_seen_at = EXCLUDED.last_seen_at,
            last_detected_at = EXCLUDED.last_detected_at
        RETURNING id
        """,
        (
            tenant_id,
            type_ids[type_name],
            client_id,
            target_kind,
            target_id,
            json.dumps(details),
            key,
            spec["severity"],
            now,
            now,
            now,
        ),
    )
    finding_id = cur.fetchone()[0]
    _record_condition(
        cur,
        tenant_id,
        finding_id,
        type_name,
        key,
        target_kind,
        target_id,
        context_participants,
        now,
    )
    return finding_id


def _record_condition(
    cur: Any,
    tenant_id: int,
    finding_id: uuid.UUID,
    type_name: str,
    key: str,
    target_kind: str,
    target_id: uuid.UUID,
    context_participants: tuple[tuple[str, Any], ...],
    now: datetime,
) -> None:
    """Write the shared condition assessment and participants of a native finding.

    The native subject is the affected participant. An attached Computer, or a
    case's member records, are context participants, so participant-based
    readers (the Computer page, client rollups) find the finding while the link
    holds. The rule ran on current facts under the publication locks, so its
    coverage is complete and fresh.
    """
    affected = Participant(target_kind, str(target_id), "affected", tenant_id)
    participants = (affected,) + tuple(
        Participant(kind, str(reference), "context", tenant_id)
        for kind, reference in context_participants
        if reference is not None
    )
    record_assessment(
        cur,
        Condition(
            tenant_id, "entity", str(finding_id), type_name, key, "open", participants
        ),
        (),
        EvaluationCoverage(True, True, True, True),
        now=now,
        reevaluation_key=f"source_record:{key}",
        participant=affected,
    )


def write_assessment(
    cur: Any,
    tenant_id: int,
    target_kind: str,
    target_id: uuid.UUID,
    result: dict,
    *,
    target_version: int,
    generation: int,
    finding_id: uuid.UUID | None,
    now: datetime,
    buffer: list[tuple] | None = None,
) -> None:
    """Upsert one current assessment, or append it to ``buffer`` for one flush."""
    row = (
        tenant_id,
        target_kind,
        target_id,
        result["rule"],
        result["dimension"],
        RULE_REVISION,
        target_version,
        generation,
        result["result"],
        json.dumps(result["evidence"]),
        json.dumps(list(result["missing"])),
        result["owner"],
        finding_id,
        now,
    )
    if buffer is not None:
        buffer.append(row)
        return
    flush_assessments(cur, [row])


def active_native_keys(
    cur: Any, tenant_id: int, target_kind: str, target_ids: list[uuid.UUID]
) -> set[str]:
    """Condition keys of the open native findings of these targets (one query)."""
    if not target_ids:
        return set()
    cur.execute(
        """
        SELECT condition_key FROM operations.findings
         WHERE tenant_id = %s AND condition_namespace = 'entity'
           AND subject_type = %s AND subject_id = ANY(%s::uuid[])
           AND status IN ('open', 'acknowledged')
        """,
        (tenant_id, target_kind, target_ids),
    )
    return {row[0] for row in cur.fetchall()}


def flush_assessments(cur: Any, rows: list[tuple]) -> None:
    """Upsert buffered current assessments in one set-based statement."""
    if not rows:
        return
    columns = [list(column) for column in zip(*rows, strict=True)]
    cur.execute(
        """
        INSERT INTO operations.source_record_assessment_current AS a (
            tenant_id, target_kind, target_id, rule_key, dimension, rule_revision,
            target_version, input_generation, result, evidence, missing_facts,
            work_owner, finding_id, assessed_at
        )
        SELECT r.tenant_id, r.target_kind, r.target_id, r.rule_key, r.dimension,
               r.rule_revision, r.target_version, r.input_generation, r.result,
               r.evidence::jsonb,
               ARRAY(SELECT jsonb_array_elements_text(r.missing::jsonb)),
               r.work_owner, r.finding_id, r.assessed_at
          FROM unnest(%s::bigint[], %s::text[], %s::uuid[], %s::text[], %s::text[],
                      %s::integer[], %s::bigint[], %s::bigint[], %s::text[], %s::text[],
                      %s::text[], %s::text[], %s::uuid[], %s::timestamptz[])
               AS r(tenant_id, target_kind, target_id, rule_key, dimension, rule_revision,
                    target_version, input_generation, result, evidence, missing,
                    work_owner, finding_id, assessed_at)
        ON CONFLICT (tenant_id, target_kind, target_id, rule_key, dimension) DO UPDATE
           SET rule_revision = EXCLUDED.rule_revision,
               target_version = EXCLUDED.target_version,
               input_generation = EXCLUDED.input_generation,
               result = EXCLUDED.result,
               evidence = EXCLUDED.evidence,
               missing_facts = EXCLUDED.missing_facts,
               work_owner = EXCLUDED.work_owner,
               finding_id = EXCLUDED.finding_id,
               assessed_at = EXCLUDED.assessed_at
        """,
        columns,
    )
