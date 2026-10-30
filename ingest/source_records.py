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
* ``identifier.validity`` (dimension ``serial``): the reported serial is usable
  for identity, a placeholder (``contradicted``), or missing (``unknown``).
* ``identity.association``: an attached record is ``supported`` by its
  confirmed link. An unattached present record whose keys reach two or more
  live Computers is ``contradicted`` (competing possibilities); one or none is
  ``unknown``. Names count only within the record's mapped client; recency
  never breaks a tie.
* ``case.duplicate`` (Stage C, ``ingest.source_record_cases``).

Work ownership (§9.1): attached records' invalid serials belong to the
Computer's ``placeholder_serial`` finding, and an unattached record with a pending
identity candidate belongs to that candidate. The assessment records the owner
instead of opening a second task. New native findings are never alertable.
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
from ingest.normalize import is_usable_serial, load_identity_value_rejections
from shared.findings_contract import guard_findings_writes

log = logging.getLogger(__name__)

TENANT_ID = 1
RULE_REVISION = 1
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
    cur.execute(
        """
        SELECT s.id, s.input_version, s.association_version, s.record_role, s.presence,
               s.platform, s.entity_type, s.source_instance_id, s.external_id,
               o.observation_id, o.client_id, o.canonical_data,
               link.entity_id AS device_id,
               link.match_method,
               d.id IS NOT NULL AS device_live,
               coalesce(meta.restricted, false) AS restricted,
               EXISTS (SELECT 1 FROM operations.entity_candidates c
                        WHERE c.tenant_id = s.tenant_id
                          AND c.source_instance_id = s.source_instance_id
                          AND c.external_namespace = s.external_namespace
                          AND c.parent_external_namespace = s.parent_external_namespace
                          AND c.parent_external_id = s.parent_external_id
                          AND c.external_id = s.external_id
                          AND c.status = 'pending') AS candidate_pending
          FROM operations.source_record_subjects s
          LEFT JOIN operations.entity_observation_current o
            ON o.tenant_id = s.tenant_id AND o.observation_id = s.observation_id
          LEFT JOIN operations.v_entity_observation_admin_metadata meta
            ON meta.tenant_id = s.tenant_id AND meta.observation_id = s.observation_id
          LEFT JOIN operations.entity_source_links link
            ON link.tenant_id = s.tenant_id AND link.source_instance_id = s.source_instance_id
           AND link.external_namespace = s.external_namespace
           AND link.parent_external_namespace = s.parent_external_namespace
           AND link.parent_external_id = s.parent_external_id
           AND link.external_id = s.external_id
           AND link.entity_class_id = 'device'
          LEFT JOIN operations.devices d
            ON d.tenant_id = link.tenant_id AND d.id = link.entity_id AND d.deleted_at IS NULL
         WHERE s.tenant_id = %s AND s.id = ANY(%s::uuid[]) AND s.subject_kind = 'record'
        """,
        (tenant_id, subject_ids),
    )
    columns = [c.name for c in cur.description]
    return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]


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
                OR (mo.client_id IS NOT NULL AND d.client_id = mo.client_id))
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


def evaluate_record(record: dict, candidates: dict[uuid.UUID, set[str]]) -> list[dict]:
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

    # identity.association
    if not compares:
        results.append(
            _result("identity.association", "not_applicable", evidence={"role": role})
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
        listed = {
            str(device_id): sorted(families)
            for device_id, families in candidates.items()
        }
        if len(candidates) >= 2:
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
                    evidence={"candidates": listed},
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


def assess_records(
    cur: Any,
    tenant_id: int,
    generation: int,
    subject_ids: list[uuid.UUID],
    now: datetime,
) -> None:
    records = _load_records(cur, tenant_id, subject_ids)
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
    for record in records:
        results = evaluate_record(record, candidates.get(record["id"], {}))
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
                context={
                    "platform": record["platform"],
                    "entity_type": record["entity_type"],
                    "name": None
                    if record["restricted"]
                    else ((record.get("canonical_data") or {}).get("hostname")),
                },
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
            )


# --- shared publication helpers -----------------------------------------------------

_TYPE_NAMES = (
    "source_record_identity_review",
    "source_record_identifier_invalid",
    "source_record_duplicate_review",
    "source_record_policy_incomplete",
)
_RULE_TYPES = {
    ("identity.association", ""): "source_record_identity_review",
    ("identifier.validity", "serial"): "source_record_identifier_invalid",
    ("case.duplicate", ""): "source_record_duplicate_review",
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
) -> uuid.UUID | None:
    """Open, refresh or resolve the native finding one rule result implies.

    The rule's own result is the closure test: a current non-contradicted
    result (or ownership by legacy work) resolves an open native finding.
    """
    type_name = _RULE_TYPES.get((result["rule"], result["dimension"]))
    if type_name is None:
        return None
    key = condition_key(target_kind, target_id, result["rule"], result["dimension"])
    spec = result["finding"]
    if spec is None:
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
           SET finding_details = %s::jsonb, last_seen_at = %s, last_detected_at = %s
         WHERE tenant_id = %s AND condition_namespace = 'entity' AND condition_key = %s
           AND status IN ('investigating', 'suppressed')
        RETURNING id
        """,
        (json.dumps(details), now, now, tenant_id, key),
    )
    row = cur.fetchone()
    if row:
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
    return cur.fetchone()[0]


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
) -> None:
    cur.execute(
        """
        INSERT INTO operations.source_record_assessment_current AS a (
            tenant_id, target_kind, target_id, rule_key, dimension, rule_revision,
            target_version, input_generation, result, evidence, missing_facts,
            work_owner, finding_id, assessed_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
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
        (
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
            result["missing"],
            result["owner"],
            finding_id,
            now,
        ),
    )
