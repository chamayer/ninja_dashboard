"""One-key source-record cases (PLAN-004 R4 Stage C, design §6.1).

Called by ``ingest.source_records`` inside its publication transaction (exclusive
tenant guard plus the generation share lock). One queue target is one key scope:
a source instance, a hardware key family (serial, VM UUID, MAC) and a value.

* Two or more present Computer-role records of that source instance share the
  key: the scope qualifies. Its one case is opened or kept; memberships join and
  release with provenance.
* Fewer than two: the rule's closure test passes; an open case closes and its
  finding resolves.
* A shared MAC alone keeps the case for investigation but opens no issue (§5).
* All members attached to the same live Computer: the legacy
  ``duplicate_platform_record`` work owns the correction; the case is kept but
  opens no native finding.
* A valid duplicate disposition keeps its scope reserved while the member set it
  was decided on and its target case are unchanged. Otherwise the reservation
  ends, the case reopens and a new finding episode starts.

Similarity is not proof of shared identity: a case says only that these records
report the same key.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Any

from ingest import source_records

_FAMILY_LABELS = {"serial": "serial number", "vm_uuid": "VM UUID", "mac": "MAC address"}
# Keys whose sharing within one source establishes a possible duplicate entry.
_DEFECT_FAMILIES = frozenset({"serial", "vm_uuid"})


def _members(cur: Any, tenant_id: int, key: dict) -> list[dict]:
    cur.execute(
        """
        SELECT s.id, s.platform, s.input_version, s.association_version,
               link.entity_id AS device_id, d.id IS NOT NULL AS device_live
          FROM operations.source_record_lookup_keys k
          JOIN operations.source_record_subjects s
            ON s.tenant_id = k.tenant_id AND s.id = k.subject_id
          LEFT JOIN operations.entity_source_links link
            ON link.tenant_id = s.tenant_id AND link.source_instance_id = s.source_instance_id
           AND link.external_namespace = s.external_namespace
           AND link.parent_external_namespace = s.parent_external_namespace
           AND link.parent_external_id = s.parent_external_id
           AND link.external_id = s.external_id AND link.entity_class_id = 'device'
          LEFT JOIN operations.devices d
            ON d.tenant_id = link.tenant_id AND d.id = link.entity_id AND d.deleted_at IS NULL
         WHERE k.tenant_id = %s AND k.source_instance_id = %s
           AND k.key_family = %s AND k.normalized_value = %s
           AND s.presence = 'present'
           AND operations.source_record_role_compares_identity(s.record_role)
         ORDER BY s.id
        """,
        (
            tenant_id,
            key["source_instance_id"],
            key["key_family"],
            key["normalized_value"],
        ),
    )
    columns = [c.name for c in cur.description]
    return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]


def fingerprint(member_ids: list[uuid.UUID]) -> str:
    return hashlib.sha256(",".join(sorted(map(str, member_ids))).encode()).hexdigest()


def _current_case(cur: Any, tenant_id: int, scope_key: uuid.UUID) -> dict | None:
    cur.execute(
        """
        SELECT c.id, c.state, c.version, c.member_fingerprint, c.disposition_valid,
               c.disposition_fingerprint, c.duplicate_of_id, target.state AS target_state
          FROM operations.source_record_cases c
          LEFT JOIN operations.source_record_cases target
            ON target.tenant_id = c.tenant_id AND target.id = c.duplicate_of_id
         WHERE c.tenant_id = %s AND c.scope_key = %s
           AND (c.state = 'open' OR (c.state = 'duplicate' AND c.disposition_valid))
           FOR UPDATE OF c
        """,
        (tenant_id, scope_key),
    )
    row = cur.fetchone()
    if row is None:
        return None
    columns = [c.name for c in cur.description]
    return dict(zip(columns, row, strict=True))


def _sync_members(
    cur: Any, tenant_id: int, case_id: uuid.UUID, member_ids: list[uuid.UUID]
) -> None:
    cur.execute(
        """
        UPDATE operations.source_record_case_members
           SET released_at = now(), release_reason = 'no_longer_shares_key'
         WHERE tenant_id = %s AND case_id = %s AND released_at IS NULL
           AND NOT (subject_id = ANY(%s::uuid[]))
        """,
        (tenant_id, case_id, member_ids),
    )
    cur.execute(
        """
        INSERT INTO operations.source_record_case_members (tenant_id, case_id, subject_id)
        SELECT %s, %s, m FROM unnest(%s::uuid[]) AS m
        ON CONFLICT (tenant_id, case_id, subject_id) WHERE released_at IS NULL DO NOTHING
        """,
        (tenant_id, case_id, member_ids),
    )


def assess_case_keys(
    cur: Any,
    tenant_id: int,
    generation: int,
    keys: list[tuple[uuid.UUID, dict]],
    now: datetime,
) -> None:
    type_ids = source_records.finding_type_ids(cur)
    for scope_key, key in keys:
        if not key or key.get("key_family") not in _FAMILY_LABELS:
            continue
        members = _members(cur, tenant_id, key)
        member_ids = [m["id"] for m in members]
        current = _current_case(cur, tenant_id, scope_key)
        print_ = fingerprint(member_ids)

        if len(members) < 2:
            if current is not None:
                _sync_members(cur, tenant_id, current["id"], [])
                cur.execute(
                    """
                    UPDATE operations.source_record_cases
                       SET state = 'closed', closed_at = now(), member_count = %s,
                           member_fingerprint = %s, disposition_valid = false,
                           closure_reason = 'fewer_than_two_records', version = version + 1
                     WHERE tenant_id = %s AND id = %s
                    """,
                    (len(members), print_, tenant_id, current["id"]),
                )
                result = source_records._result(
                    "case.duplicate",
                    "supported",
                    evidence={"member_count": len(members)},
                )
                source_records.publish_finding(
                    cur,
                    tenant_id,
                    type_ids,
                    "source_record_case",
                    current["id"],
                    result,
                    now,
                    client_id=None,
                    context={},
                )
                source_records.write_assessment(
                    cur,
                    tenant_id,
                    "source_record_case",
                    current["id"],
                    result,
                    target_version=current["version"] + 1,
                    generation=generation,
                    finding_id=None,
                    now=now,
                )
            continue

        if current is None:
            cur.execute(
                """
                INSERT INTO operations.source_record_cases (
                    tenant_id, scope_key, source_instance_id, key_family, key_value,
                    member_count, member_fingerprint)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, state, version, member_fingerprint, disposition_valid,
                          disposition_fingerprint, duplicate_of_id, NULL::text
                """,
                (
                    tenant_id,
                    scope_key,
                    key["source_instance_id"],
                    key["key_family"],
                    key["normalized_value"],
                    len(members),
                    print_,
                ),
            )
            columns = [c.name for c in cur.description]
            current = dict(zip(columns, cur.fetchone(), strict=True))
            current["target_state"] = None

        reserved = current["state"] == "duplicate"
        if reserved and (
            current["disposition_fingerprint"] != print_
            or current["target_state"] not in ("open", "duplicate")
        ):
            # The decision no longer describes this case: end the reservation.
            cur.execute(
                """
                UPDATE operations.source_record_cases
                   SET state = 'open', disposition_valid = false, version = version + 1
                 WHERE tenant_id = %s AND id = %s
                """,
                (tenant_id, current["id"]),
            )
            current["state"] = "open"
            current["version"] += 1
            reserved = False

        _sync_members(cur, tenant_id, current["id"], member_ids)
        if current["member_fingerprint"] != print_:
            cur.execute(
                """
                UPDATE operations.source_record_cases
                   SET member_count = %s, member_fingerprint = %s, version = version + 1
                 WHERE tenant_id = %s AND id = %s
                """,
                (len(members), print_, tenant_id, current["id"]),
            )
            current["version"] += 1

        attached = {m["device_id"] for m in members if m["device_live"]}
        same_computer = len(attached) == 1 and all(m["device_live"] for m in members)
        evidence = {
            "member_count": len(members),
            "attached_computers": len(attached),
            "unattached_records": sum(1 for m in members if not m["device_live"]),
        }
        if reserved:
            result = source_records._result(
                "case.duplicate",
                "contradicted",
                evidence=evidence,
                owner="duplicate_disposition",
            )
            finding_id = None  # resolved by the disposition; nothing to reopen
        elif key["key_family"] not in _DEFECT_FAMILIES:
            # A shared MAC (docks, adapters, VPNs) starts an investigation; it
            # does not establish a duplicate entry (§5). The case stays visible.
            result = source_records._result(
                "case.duplicate",
                "unknown",
                evidence=evidence,
                missing=["corroborating_hardware_identifier"],
            )
            finding_id = source_records.publish_finding(
                cur,
                tenant_id,
                type_ids,
                "source_record_case",
                current["id"],
                result,
                now,
                client_id=None,
                context={},
            )
        else:
            owner = "legacy:duplicate_platform_record" if same_computer else ""
            result = source_records._result(
                "case.duplicate",
                "contradicted",
                evidence=evidence,
                owner=owner,
                finding=None
                if owner
                else {
                    "type": "source_record_duplicate_review",
                    "severity": "high",
                },
            )
            finding_id = source_records.publish_finding(
                cur,
                tenant_id,
                type_ids,
                "source_record_case",
                current["id"],
                result,
                now,
                client_id=None,
                context_participants=tuple(("source_record", m["id"]) for m in members),
                context={
                    "case_label": f"Shared {_FAMILY_LABELS[key['key_family']]}",
                    "key_family": _FAMILY_LABELS[key["key_family"]],
                    "platform": members[0]["platform"],
                },
            )
        source_records.write_assessment(
            cur,
            tenant_id,
            "source_record_case",
            current["id"],
            result,
            target_version=current["version"],
            generation=generation,
            finding_id=finding_id,
            now=now,
        )
