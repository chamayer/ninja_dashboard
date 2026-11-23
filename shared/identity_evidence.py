"""Source-independent checks for contradictory Computer identity evidence."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from dataclasses import dataclass
from typing import Any, TypeVar

_Stream = TypeVar("_Stream")

# Bump when the shared contradiction-check semantics change.
CONFLICT_RULE_REVISION = "plan-015-conflict.6"


def loose_identity_name(name: str | None) -> str:
    """Normalize separators for identity comparisons."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def two_names_in_one_source(records: list[dict[str, Any]], now: datetime) -> bool:
    """Recognize recent same-source agents that report different machines."""
    agents = [
        record for record in records
        if record["entity_type"].startswith("agent.")
        and not record.get("roaming") and record["hostname"] and record["last_seen_at"]
        and record["last_seen_at"] > now - timedelta(days=30)
    ]
    return any(
        left["stream"] == right["stream"]
        and loose_identity_name(left["hostname"]) != loose_identity_name(right["hostname"])
        and abs(left["last_seen_at"] - right["last_seen_at"]) < timedelta(days=1)
        and not (left["serial"] and left["serial"] == right["serial"])
        and not (left["vm_uuid"] and left["vm_uuid"] == right["vm_uuid"])
        for index, left in enumerate(agents) for right in agents[index + 1:]
    )


def hostname_conflict(reports, *, now: datetime | None = None) -> bool:
    """Check normalized active reports using the split review's hostname rule."""
    records = [
        {"entity_type": entity_type, "stream": (platform, entity_type),
         "hostname": hostname, "serial": serial, "vm_uuid": vm_uuid,
         "last_seen_at": datetime.fromisoformat(seen) if isinstance(seen, str) else seen}
        for platform, entity_type, hostname, serial, vm_uuid, seen in reports
    ]
    return two_names_in_one_source(records, now or datetime.now(UTC))


def split_assessment(name: str, records: list[dict[str, Any]], now: datetime) -> dict | None:
    """Describe a split only when current records contain a machine contradiction."""
    assessment = assess_identifier_group(
        serial_groups=[(record["serial"],) if record["serial"] else () for record in records],
        vm_uuid_groups=[(record["vm_uuid"],) if record["vm_uuid"] else () for record in records],
    )
    if assessment.reason == "serial_conflict":
        kind = "serial"
    elif assessment.reason == "vm_uuid_conflict":
        kind = "vm_uuid"
    elif two_names_in_one_source(records, now):
        kind = "hostname"
    else:
        return None
    groups: dict[str, list[dict[str, Any]]] = {}
    unplaced = []
    for record in records:
        value = record[kind]
        (groups.setdefault(value, []) if value else unplaced).append(record)
    for record in unplaced:
        homes = [value for value, members in groups.items() if record["hostname"]
                 and any(member["hostname"] == record["hostname"] for member in members)]
        if len(homes) == 1:
            groups[homes[0]].append(record)
    own = loose_identity_name(name)

    def rank(item):
        value, members = item
        named = any(loose_identity_name(member["hostname"]) == own for member in members)
        seen = max((member["last_seen_at"] for member in members if member["last_seen_at"]), default=None)
        return named, len(members), seen.timestamp() if seen else 0, value

    keep = max(groups.items(), key=rank)[0]
    machines = []
    for value, members in sorted(groups.items(), key=lambda item: (item[0] != keep, item[0])):
        details = [{
            "observation_id": str(member["observation_id"]), "platform": member["platform"],
            "entity_type": member["entity_type"], "hostname": member["hostname"],
            "serial": member["serial"], "vm_uuid": member["vm_uuid"], "online": member["online"],
            "last_seen_at": member["last_seen_at"].isoformat() if member["last_seen_at"] else None,
        } for member in members]
        machines.append({kind: value, "keep": value == keep,
                         "hostnames": sorted({member["hostname"] for member in members if member["hostname"]}),
                         "records": details})
    return {
        "hostname": name, "divided_by": kind, "machine_count": len(machines), "machines": machines,
        "proposed_split_observation_ids": [
            str(member["observation_id"]) for value, members in groups.items() if value != keep
            for member in members
        ],
    }


def usable_serial(serial: str | None, rejected: set[str] | frozenset[str] | None) -> bool:
    """Apply the shared placeholder and configured serial-rejection rules."""
    if not serial or rejected is None:
        return False
    value = serial.strip().lower()
    return len(value) >= 4 and len(set(value)) > 1 and value not in rejected


def current_client_scopes(
    cur, tenant_id: int, device_ids: list[uuid.UUID], *, lock: bool, batch: bool = True,
):
    """Return stable effective clients, or None when a scope cannot be trusted."""
    cur.execute(
        """
        SELECT d.id, owner.state, owner.effective_client_id, d.client_id
          FROM operations.devices d
          LEFT JOIN operations.computer_client_ownership owner
            ON owner.tenant_id = d.tenant_id AND owner.device_id = d.id
         WHERE d.tenant_id = %s AND d.deleted_at IS NULL AND d.id = ANY(%s::uuid[])
        """,
        (tenant_id, device_ids),
    )
    rows = cur.fetchall()
    if len(rows) != len(set(device_ids)) or any(
        state not in {"resolved", "decision_protected"}
        or effective is None or effective != stored
        for _, state, effective, stored in rows
    ):
        return None
    captured = sorted(((device_id, effective) for device_id, _, effective, _ in rows), key=lambda x: str(x[0]))
    if lock and captured and batch:
        cur.execute(
            "SELECT device_id FROM operations.lock_computer_client_scopes(%s, %s::uuid[], %s::uuid[])",
            (tenant_id, [item[0] for item in captured], [item[1] for item in captured]),
        )
        if {row[0] for row in cur.fetchall()} != {item[0] for item in captured}:
            return None
    elif lock:
        for device_id, client_id in captured:
            cur.execute(
                "SELECT operations.lock_computer_client_scope(%s, %s, %s)",
                (tenant_id, device_id, client_id),
            )
            row = cur.fetchone()
            if not row or not row[0]:
                return None
    return dict(captured)


def operator_separated_pairs(
    cur, tenant_id: int, device_ids=None, *, observation_metadata: bool = False,
) -> set[tuple]:
    """Return both directions of current operator separations and split history."""
    relation = (
        "operations.v_entity_observation_admin_metadata" if observation_metadata
        else "operations.entity_observation_current"
    )
    cur.execute(
        """
        SELECT dec.device_id, k.value::uuid
          FROM operations.device_operator_decisions dec,
               jsonb_array_elements_text(dec.value) k
         WHERE dec.tenant_id = %s AND dec.dimension = 'identity_separate'
           AND (%s::uuid[] IS NULL OR dec.device_id = ANY(%s::uuid[]))
        UNION
        SELECT dec.device_id, eo.device_id
          FROM operations.device_operator_decisions dec,
               jsonb_array_elements_text(dec.value) k
          JOIN {observation_relation} eo
            ON eo.tenant_id = %s AND eo.platform = split_part(k.value, '|', 1)
           AND eo.entity_key = substr(k.value, length(split_part(k.value, '|', 1)) + 2)
         WHERE dec.tenant_id = %s AND dec.dimension = 'identity_excluded_records'
           AND eo.device_id IS NOT NULL
           AND (%s::uuid[] IS NULL OR dec.device_id = ANY(%s::uuid[]))
        UNION
        SELECT survivor_id, absorbed_id FROM operations.computer_merges
         WHERE tenant_id = %s AND split_at IS NOT NULL
           AND (%s::uuid[] IS NULL OR survivor_id = ANY(%s::uuid[])
                OR absorbed_id = ANY(%s::uuid[]))
        """.replace("{observation_relation}", relation),
        (tenant_id, device_ids, device_ids, tenant_id, tenant_id,
         device_ids, device_ids, tenant_id, device_ids, device_ids, device_ids),
    )
    pairs = set()
    for a, b in cur.fetchall():
        pairs.add((a, b))
        pairs.add((b, a))
    return pairs


def identifier_group_conflict(values: set[str], proposed: str | None = None) -> bool:
    """Reject contradictory identifiers in a group or against a proposed record."""
    return len(values) > 1 or bool(proposed and values - {proposed})


def live_stream_conflict(
    streams_a: set[_Stream] | frozenset[_Stream],
    streams_b: set[_Stream] | frozenset[_Stream],
) -> bool:
    """Recognize simultaneous records from the same source and record type."""
    return bool(streams_a & streams_b)


def different_identity_evidence(
    serials_a: set[str], serials_b: set[str],
    vm_uuids_a: set[str], vm_uuids_b: set[str],
    streams_a: set[str] | frozenset[str], streams_b: set[str] | frozenset[str],
) -> bool:
    """Identify conflicting hardware evidence for two Computers."""
    return assess_identifier_group(
        serial_groups=(serials_a, serials_b),
        vm_uuid_groups=(vm_uuids_a, vm_uuids_b),
    ).outcome == "different"


def identity_conflict_reason(
    *, serial_groups=(), vm_uuid_groups=(), stream_groups=(), separated=False,
) -> str | None:
    """Assess current identity contradictions using the same rules for every caller."""
    if separated:
        return "operator_exclusion"
    serial_groups = [{value for value in group if value} for group in serial_groups]
    vm_uuid_groups = [{value for value in group if value} for group in vm_uuid_groups]
    if identifier_group_conflict({value for group in serial_groups for value in group if value}):
        return "serial_conflict"
    if identifier_group_conflict({value for group in vm_uuid_groups for value in group if value}):
        return "vm_uuid_conflict"
    # Simultaneous reports from one source are not, by themselves, evidence
    # that two records represent different machines (PLAN-015 clarification).
    return None


@dataclass(frozen=True)
class IdentityAssessment:
    """Machine conclusion from qualified proof and current contradictions."""

    outcome: str
    reason: str


def assess_identity(
    *, serial_groups=(), vm_uuid_groups=(), stream_groups=(), separated=False,
    proof: str | None = None, proof_origin: str = "unknown",
) -> IdentityAssessment:
    """Return one machine conclusion; callers must qualify their proof first."""
    conflict = identity_conflict_reason(
        serial_groups=serial_groups, vm_uuid_groups=vm_uuid_groups,
        stream_groups=stream_groups, separated=separated,
    )
    if conflict:
        return IdentityAssessment("different", conflict)
    if proof in {"serial", "vm_uuid", "serial_corroborated", "vm_uuid_corroborated"}:
        return IdentityAssessment("same", proof)
    if proof in {"source_identity", "hostname", "hostname_mac"}:
        return IdentityAssessment("same", proof)
    return IdentityAssessment("unresolved", "no_qualified_proof")


def assess_identifier_group(
    *, serial_groups, vm_uuid_groups, separated=False, required_proof: str | None = None,
) -> IdentityAssessment:
    """Require one qualified identifier shared by every member of the group."""
    serials = [{value for value in group if value} for group in serial_groups]
    vm_uuids = [{value for value in group if value} for group in vm_uuid_groups]
    proof = None
    if required_proof in (None, "serial") and len(serials) > 1 and set.intersection(*serials):
        proof = "serial"
    elif required_proof in (None, "vm_uuid") and len(vm_uuids) > 1 and set.intersection(*vm_uuids):
        proof = "vm_uuid"
    return assess_identity(
        serial_groups=serials, vm_uuid_groups=vm_uuids, separated=separated, proof=proof
    )


def group_has_conflict(
    *, identifiers: list[tuple[str, ...]], streams: list[frozenset[str]],
    device_ids: list[uuid.UUID], separated: set[tuple],
    vm_identifiers: list[tuple[str, ...]] | None = None,
) -> bool:
    """Check identifier contradictions and separations across a group."""
    return assess_identifier_group(
        serial_groups=identifiers,
        vm_uuid_groups=vm_identifiers or (),
        separated=any((a, b) in separated for a in device_ids for b in device_ids if a != b),
    ).outcome == "different"
