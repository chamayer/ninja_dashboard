"""Operator-managed Computer identity matching (ADR-0032).

The policy table selects from a small set of evidence matchers and their order.
The code owns normalization, the live-Computer boundary, hard conflicts and
candidate selection:

* Current names can identify a candidate in the record's client. Withdrawn and
  historical names remain available for review but cannot prove an attachment.
* Serial and VM UUID are compared with what active records report now, not with
  a Computer's stored value (a stale stored serial caused a wrong merge).
* Names are the names the client's source records report (ADR-0034
  section 4), never a Computer's stored name: matched exactly, ignoring
  separators, or as a 15-character cut of a longer name, in tiers (current
  records on active Computers, on other non-retired Computers, withdrawn
  records, record history).
* A different usable serial or VM UUID, a conflicting recent pair of names
  from one agent stream, or an applicable operator separation excludes a
  candidate. A record an operator split off a Computer never matches it again.
* A roaming record (an agent identity moving between clones of one image,
  ``operations.identity_roaming_records``) proves nothing by serial or VM
  UUID, as candidate or as incoming record.
* Multiple Computers with the same identifier can represent one machine. The
  oldest Computer is selected only when their combined evidence has no conflict.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal

from ingest.normalize import is_usable_serial, normalize_mac
from shared.identity_evidence import (
    current_client_scopes,
    assess_identifier_group,
    assess_identity,
    hostname_conflict,
    loose_identity_name,
    operator_separated_pairs,
    usable_serial,
)

log = logging.getLogger(__name__)

# Bump whenever matching, candidate qualification, or source exclusions change.
MATCHER_RULE_REVISION = "plan-015-matcher.11"
_MATCHERS = frozenset(
    {"source_identity", "serial", "vm_uuid", "hostname_mac", "hostname"}
)
_SIGNALS = frozenset({"serial", "vm_uuid", "same_source_live"})
_NETBIOS_LENGTH = 15
_LOOSE_RE = re.compile(r"[^a-z0-9]")

_EXCLUDE_SOURCE_RECORD_SQL = """
AND NOT (eo.platform = %s
         AND (%s::uuid IS NULL OR eo.source_instance_id = %s::uuid)
         AND CASE WHEN %s::text IS NULL THEN eo.entity_key = %s
                  ELSE (eo.external_namespace, eo.parent_external_namespace,
                        eo.parent_external_id, eo.external_id) = (%s, %s, %s, %s) END)
"""

_HOSTNAME_REPORT_SQL = """
eo.platform, eo.entity_type,
CASE WHEN coalesce(lc.record_lifecycle, '') <> 'archived'
     AND coalesce(forms.name_key, '') <> '' THEN forms.name_short END,
eo.last_seen_at
"""
_HOSTNAME_REPORT_JOINS = """
LEFT JOIN operations.v_device_source_record_lifecycle_current lc ON lc.observation_id = eo.observation_id
CROSS JOIN LATERAL operations.record_name_forms(
    eo.platform, eo.entity_type,
    coalesce(nullif(eo.canonical_data ->> 'hostname', ''), eo.canonical_data ->> 'guest_name'),
    eo.canonical_data ->> 'domain'
) forms
"""


def _source_record_parameters(source_name, source_instance_id, external_id, source_identity_key):
    return (
        source_name, source_instance_id, source_instance_id,
        source_identity_key[0] if source_identity_key is not None else None,
        external_id, *(source_identity_key or ("", "", "", "")),
    )


def _identity_mac_sql(column: str) -> str:
    """SQL expression for a usable compact MAC, for trusted query aliases only."""
    if column not in {"m.mac", "mac.value"}:
        raise ValueError("unsupported MAC query column")
    value = f"lower(btrim({column}))"
    compact = f"replace(replace({value}, ':', ''), '-', '')"
    return (
        f"CASE WHEN {value} ~ '^([0-9a-f]{{2}}[:-]){{5}}[0-9a-f]{{2}}$|^[0-9a-f]{{12}}$' "
        f"AND {compact} NOT IN ('000000000000', 'ffffffffffff', '02004c4f4f50') "
        f"AND {compact} NOT LIKE '00155d%%' THEN {compact} END"
    )


@dataclass(frozen=True)
class IdentityMatchPolicy:
    matcher: str
    priority: int
    requires_client_scope: bool
    requires_unique_candidate: bool
    avoid_same_stream_duplicates: bool
    blocking_signal_keys: frozenset[str]
    confidence: Decimal
    requires_independent_corroboration: bool = False


@dataclass(frozen=True)
class MatchResult:
    """The selected Computer and the evidence that selected it."""

    device_id: uuid.UUID
    matcher: str
    compared: dict = field(default_factory=dict)
    candidates: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True)
class MatchAttempt:
    """One policy considered during a counterfactual match."""

    matcher: str
    candidates: tuple[uuid.UUID, ...]
    usable: tuple[uuid.UUID, ...]
    blockers: dict[uuid.UUID, str]
    missing: tuple[str, ...] = ()


@dataclass(frozen=True)
class MatchPreview:
    """The selected match plus every policy attempt made to reach it."""

    result: MatchResult | None
    attempts: tuple[MatchAttempt, ...]
    ownership_deferred: bool = False
    ninja_slot_occupied: bool = False


class OwnershipMatchDeferred(Exception):
    """A machine match cannot be used under the current client scope."""


class SourceRecordSuperseded(OwnershipMatchDeferred):
    """A historical Ninja record is ineligible for an attachment or promotion."""


class NinjaRecordSlotOccupied(OwnershipMatchDeferred):
    """A machine match needs successor selection before attaching this record."""

    def __init__(self, device_id: uuid.UUID) -> None:
        super().__init__("The matched Computer already has a current Ninja record")
        self.device_id = device_id


def _ninja_association_guards_present(cur):
    """Allow ingest to start before the Operations migration is applied."""
    cur.execute(
        "SELECT to_regprocedure("
        "'operations.ninja_record_is_superseded(bigint, uuid, text, text, text, text)') IS NOT NULL"
    )
    return cur.fetchone()[0]


def _is_superseded_ninja_record(cur, tenant_id, source_instance_id, source_identity_key):
    cur.execute(
        "SELECT operations.ninja_record_is_superseded(%s, %s, %s, %s, %s, %s)",
        (tenant_id, source_instance_id, *source_identity_key),
    )
    return cur.fetchone()[0]


def _identity_exclusions(cur, tenant_id: int, records: list[dict]) -> dict[uuid.UUID, tuple]:
    """Collect a source record's observations, including linked companions."""
    subject_ids = [record["id"] for record in records]
    if not subject_ids:
        return {}
    cur.execute(
        """
        SELECT s.id, o.observation_id
          FROM operations.source_record_subjects s
          JOIN operations.entity_observation_current o
            ON o.tenant_id = s.tenant_id
           AND o.source_instance_id = s.source_instance_id
           AND o.external_namespace = s.external_namespace
           AND o.parent_external_namespace = s.parent_external_namespace
           AND o.parent_external_id = s.parent_external_id
           AND o.external_id = s.external_id
         WHERE s.tenant_id = %s AND s.id = ANY(%s::uuid[])
        UNION
        SELECT c.owner_subject_id, c.observation_id
          FROM operations.source_record_companions c
         WHERE c.tenant_id = %s AND c.owner_subject_id = ANY(%s::uuid[])
        """,
        (tenant_id, subject_ids, tenant_id, subject_ids),
    )
    result: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for subject_id, observation_id in cur.fetchall():
        result[subject_id].append(observation_id)
    for record in records:
        if record["observation_id"] not in result[record["id"]]:
            result[record["id"]].append(record["observation_id"])
    return {subject_id: tuple(ids) for subject_id, ids in result.items()}


class _StaleNameEvidence(Exception):
    """A name candidate is supported only by withdrawn or historical records."""

    def __init__(self, candidates: list[uuid.UUID]) -> None:
        self.candidates = tuple(candidates)


class _AmbiguousNameEvidence(Exception):
    """A truncated name matches more than one distinct longer name."""

    def __init__(self, candidates: list[uuid.UUID]) -> None:
        self.candidates = tuple(candidates)


def _scope_candidates(cur, tenant_id, client_id, candidates, *, lock):
    """Keep only current-client candidates; defer unresolved ownership."""
    scopes = current_client_scopes(cur, tenant_id, candidates, lock=lock)
    if scopes is None:
        raise OwnershipMatchDeferred()
    return [device_id for device_id, effective in scopes.items() if effective == client_id]


def load_identity_match_policies(
    cur, tenant_id: int
) -> tuple[IdentityMatchPolicy, ...]:
    """Load validated enabled policies, failing closed on bad configuration."""
    cur.execute(
        """
        SELECT matcher, priority, requires_client_scope,
               requires_unique_candidate, avoid_same_stream_duplicates,
               blocking_signal_keys, confidence, requires_independent_corroboration
          FROM operations.identity_match_policies
         WHERE tenant_id = %s AND enabled = TRUE
         ORDER BY priority, matcher
        """,
        (tenant_id,),
    )
    policies: list[IdentityMatchPolicy] = []
    seen: set[str] = set()
    for (
        matcher,
        priority,
        client_scope,
        unique,
        avoid_same_stream,
        blockers,
        confidence,
        corroboration,
    ) in cur.fetchall():
        blocker_set = frozenset(blockers or [])
        if (
            matcher not in _MATCHERS
            or matcher in seen
            or not blocker_set <= _SIGNALS
            or not unique
            or (matcher in {"hostname", "hostname_mac"} and not client_scope)
        ):
            raise RuntimeError("invalid enabled Computer identity-match policy")
        seen.add(matcher)
        policies.append(
            IdentityMatchPolicy(
                matcher=matcher,
                priority=priority,
                requires_client_scope=client_scope,
                requires_unique_candidate=unique,
                avoid_same_stream_duplicates=avoid_same_stream,
                blocking_signal_keys=blocker_set,
                confidence=confidence,
                requires_independent_corroboration=corroboration,
            )
        )
    if not policies:
        raise RuntimeError("no enabled Computer identity-match policy")
    return tuple(policies)


def loose_name(name: str | None) -> str:
    """The name with separators removed (dash, space, apostrophe, dot...)."""
    return loose_identity_name(name)


def resolve_device_by_policy(cur, **kwargs) -> uuid.UUID | None:
    """Return one Computer selected by the configured policy, or None."""
    result = resolve_match(cur, **kwargs)
    return result.device_id if result else None


def resolve_match(
    cur,
    *,
    tenant_id: int,
    source_name: str,
    external_id: str,
    entity_type: str,
    serial: str | None,
    vm_uuid: str | None,
    hostname: str | None,
    macs: list[str] | None,
    client_id: uuid.UUID | None,
    policies: tuple[IdentityMatchPolicy, ...],
    is_online: bool | None = None,
    source_instance_id: uuid.UUID | None = None,
    skip_source_identity: bool = False,
    identity_types: list[str] | None = None,
    source_identity_key: tuple[str, str, str, str] | None = None,
    excluded_observation_ids: tuple[uuid.UUID, ...] = (),
    source_seen_at: datetime | None = None,
) -> MatchResult | None:
    """Select a Computer for one source record, or None when nothing matches.

    ``skip_source_identity`` is the re-check: an attached record whose serial
    or VM UUID arrived or changed is matched again without its current link.
    """
    return _resolve_match(
        cur,
        tenant_id=tenant_id,
        source_name=source_name,
        external_id=external_id,
        entity_type=entity_type,
        serial=serial,
        vm_uuid=vm_uuid,
        hostname=hostname,
        macs=macs,
        client_id=client_id,
        policies=policies,
        is_online=is_online,
        source_instance_id=source_instance_id,
        skip_source_identity=skip_source_identity,
        identity_types=identity_types,
        excluded_observation_ids=excluded_observation_ids,
        trace=False,
        source_identity_key=source_identity_key,
        source_seen_at=source_seen_at,
    ).result


def preview_match(
    cur,
    *,
    tenant_id: int,
    source_name: str,
    external_id: str,
    entity_type: str,
    serial: str | None,
    vm_uuid: str | None,
    hostname: str | None,
    macs: list[str] | None,
    client_id: uuid.UUID | None,
    policies: tuple[IdentityMatchPolicy, ...],
    is_online: bool | None = None,
    source_instance_id: uuid.UUID | None = None,
    identity_types: list[str] | None = None,
    excluded_observation_ids: tuple[uuid.UUID, ...] = (),
    source_identity_key: tuple[str, str, str, str] | None = None,
    rejected_serials: frozenset[str] | None = None,
    universal: bool = False,
    assess_globally: bool = False,
) -> MatchPreview:
    """Counterfactually match a record without its existing evidence.

    Universal mode assesses serial and VM UUID matches across clients; it is
    read-only machine evidence, not an authorization to change an association.
    The normal resolver retains its configured client scope.
    """
    if not excluded_observation_ids:
        raise ValueError("counterfactual matching requires excluded observations")
    return _resolve_match(
        cur,
        tenant_id=tenant_id,
        source_name=source_name,
        external_id=external_id,
        entity_type=entity_type,
        serial=serial,
        vm_uuid=vm_uuid,
        hostname=hostname,
        macs=macs,
        client_id=client_id,
        policies=policies,
        is_online=is_online,
        source_instance_id=source_instance_id,
        skip_source_identity=True,
        identity_types=identity_types,
        excluded_observation_ids=excluded_observation_ids,
        trace=True,
        source_identity_key=source_identity_key,
        rejected_serials=rejected_serials,
        universal=universal,
        assess_globally=assess_globally,
    )


def _resolve_match(
    cur,
    *,
    tenant_id: int,
    source_name: str,
    external_id: str,
    entity_type: str,
    serial: str | None,
    vm_uuid: str | None,
    hostname: str | None,
    macs: list[str] | None,
    client_id: uuid.UUID | None,
    policies: tuple[IdentityMatchPolicy, ...],
    is_online: bool | None,
    source_instance_id: uuid.UUID | None = None,
    skip_source_identity: bool,
    identity_types: list[str] | None,
    excluded_observation_ids: tuple[uuid.UUID, ...],
    trace: bool,
    source_identity_key: tuple[str, str, str, str] | None = None,
    record_attempts: bool = False,
    rejected_serials: frozenset[str] | None = None,
    universal: bool = False,
    assess_globally: bool = False,
    source_seen_at: datetime | None = None,
) -> MatchPreview:
    """Shared matching path for normal resolution and read-only preview."""
    has_ninja_guards = (
        source_name == "Ninja" and source_instance_id is not None and source_identity_key is not None
        and _ninja_association_guards_present(cur)
    )
    if has_ninja_guards and _is_superseded_ninja_record(cur, tenant_id, source_instance_id, source_identity_key):
        if not trace:
            raise SourceRecordSuperseded()
        return MatchPreview(
            None, (MatchAttempt("source_identity", (), (), {}, ("superseded_source_record",)),)
        )
    if identity_types is None:
        identity_types = _identity_types(cur)
    normalized_macs = sorted({
        normalized for mac in (macs if isinstance(macs, (list, tuple)) else ())
        if isinstance(mac, str) and (normalized := normalize_mac(mac))
    })
    serial_usable = (is_usable_serial(serial) if rejected_serials is None
                     else usable_serial(serial, rejected_serials))
    record_serial = serial.strip().lower() if serial_usable else None
    record_vm_uuid = (vm_uuid or "").strip().lower() or None
    roaming_external_id = source_identity_key[3] if source_identity_key is not None else external_id
    source_roaming = bool(record_serial or record_vm_uuid or hostname) and _is_roaming(
        cur, tenant_id, source_name, source_instance_id, roaming_external_id
    )
    if source_roaming:
        # The record moves between clones of one image (migration 0317): its
        # serial and VM UUID prove nothing about this machine.
        record_serial = record_vm_uuid = None
    attempts: list[MatchAttempt] = []
    source_report = ()
    source_report_loaded = False
    for policy in policies:
        machine_scope = (universal or assess_globally or not trace) and policy.matcher in {"serial", "vm_uuid"}
        if skip_source_identity and policy.matcher == "source_identity":
            continue
        if policy.requires_client_scope and not machine_scope and client_id is None:
            continue
        try:
            candidates = _candidates(
                cur,
                tenant_id=tenant_id,
                source_name=source_name,
                source_instance_id=source_instance_id,
                external_id=external_id,
                entity_type=entity_type,
                serial=record_serial,
                vm_uuid=record_vm_uuid,
                hostname=hostname,
                macs=normalized_macs,
                client_id=client_id if policy.requires_client_scope and not machine_scope else None,
                matcher=policy.matcher,
                identity_types=identity_types,
                excluded_observation_ids=excluded_observation_ids,
                lock_candidates=not trace,
                source_identity_key=source_identity_key,
            )
        except OwnershipMatchDeferred:
            if trace:
                return MatchPreview(None, tuple(attempts), ownership_deferred=True)
            raise
        except (_StaleNameEvidence, _AmbiguousNameEvidence) as exc:
            if trace or record_attempts:
                reason = (
                    "stale_name_evidence"
                    if isinstance(exc, _StaleNameEvidence)
                    else "ambiguous_name_evidence"
                )
                attempts.append(
                    MatchAttempt(
                        policy.matcher, exc.candidates, (),
                        {device_id: reason for device_id in exc.candidates},
                    )
                )
            return MatchPreview(None, tuple(attempts))
        if not candidates:
            if trace or record_attempts:
                attempts.append(MatchAttempt(policy.matcher, (), (), {}))
            continue
        if not machine_scope and policy.requires_client_scope:
            try:
                candidates = _scope_candidates(
                    cur, tenant_id, client_id, candidates, lock=not trace
                )
            except OwnershipMatchDeferred:
                if trace:
                    return MatchPreview(None, tuple(attempts), ownership_deferred=True)
                raise
            if not candidates:
                continue
        elif not machine_scope and current_client_scopes(cur, tenant_id, candidates, lock=not trace) is None:
            # A source-identity or other unscoped proof must not bypass the
            # ownership transition fence when the association is written.
            if trace:
                return MatchPreview(None, tuple(attempts), ownership_deferred=True)
            raise OwnershipMatchDeferred()
        if not source_report_loaded:
            source_report_loaded = True
            if hostname and entity_type.startswith("agent.") and not source_roaming:
                if source_seen_at is None and source_instance_id is not None and source_identity_key is not None:
                    cur.execute(
                        """
                        SELECT eo.last_seen_at
                          FROM operations.entity_observation_current eo
                          LEFT JOIN operations.v_device_source_record_lifecycle_current lc
                            ON lc.observation_id = eo.observation_id
                         WHERE eo.tenant_id = %s AND eo.source_instance_id = %s AND eo.active
                           AND (eo.external_namespace, eo.parent_external_namespace,
                                eo.parent_external_id, eo.external_id) = (%s, %s, %s, %s)
                           AND coalesce(lc.record_lifecycle, '') <> 'archived'
                        """,
                        (tenant_id, source_instance_id, *source_identity_key),
                    )
                    row = cur.fetchone()
                    source_seen_at = row[0] if row else None
                if source_seen_at is not None:
                    source_report = ((source_name, entity_type, hostname,
                                      record_serial, record_vm_uuid, source_seen_at),)
        blockers = {
            device_id: blocker
            for device_id in candidates
            if (
                blocker := _hard_conflict_reason(
                    cur,
                    tenant_id,
                    device_id,
                    policy.blocking_signal_keys | {"serial", "vm_uuid"},
                    source_name=source_name,
                    source_instance_id=source_instance_id,
                    entity_type=entity_type,
                    external_id=external_id,
                    serial=record_serial,
                    vm_uuid=record_vm_uuid,
                    is_online=is_online,
                    excluded_observation_ids=excluded_observation_ids,
                    identity_types=identity_types,
                    source_identity_key=source_identity_key,
                    rejected_serials=rejected_serials,
                    source_report=source_report,
                )
            )
            is not None
        }
        usable = [device_id for device_id in candidates if device_id not in blockers]
        if trace or record_attempts:
            attempts.append(
                MatchAttempt(policy.matcher, tuple(candidates), tuple(usable), blockers)
            )
        if not usable:
            # Do not bypass a contradiction by falling through to a weaker key.
            if blockers:
                return MatchPreview(None, tuple(attempts))
            continue
        if machine_scope and not universal:
            # Machine evidence is tenant-wide; the existing association policy
            # still decides whether the result can be used.
            try:
                if policy.requires_client_scope:
                    scoped = _scope_candidates(cur, tenant_id, client_id, usable, lock=not trace)
                    if len(scoped) != len(usable):
                        raise OwnershipMatchDeferred()
                elif current_client_scopes(cur, tenant_id, usable, lock=not trace) is None:
                    raise OwnershipMatchDeferred()
            except OwnershipMatchDeferred:
                if trace:
                    return MatchPreview(None, (), ownership_deferred=True)
                raise
        duplicates = ()
        if len(usable) == 1:
            chosen = usable[0]
        elif policy.matcher in {"serial", "vm_uuid"}:
            chosen = _duplicate_candidate_survivor(
                cur, tenant_id, usable, identity_types, excluded_observation_ids,
                source_name, source_instance_id, external_id, source_identity_key,
                rejected_serials, matcher=policy.matcher, universal=universal, source_report=source_report,
            )
            if chosen is None:
                if trace or record_attempts:
                    attempts[-1] = replace(attempts[-1], missing=("unresolved_identifier_group",))
                return MatchPreview(None, tuple(attempts))
            duplicates = tuple(usable)
        else:
            return MatchPreview(None, tuple(attempts))
        assessment = assess_identity(proof=policy.matcher)
        if assessment.outcome != "same":
            if trace or record_attempts:
                attempts[-1] = replace(attempts[-1], missing=(assessment.reason,))
            # An unsupported proof does not bind a record; a later policy
            # may still select a candidate.
            continue
        compared = _compared(
            policy.matcher, record_serial, record_vm_uuid, hostname,
            source_name, source_instance_id,
        )
        if duplicates:
            compared["duplicate_candidates"] = [str(device_id) for device_id in duplicates]
        if policy.matcher in {"serial", "vm_uuid"}:
            report = _identifier_report(
                cur, tenant_id, chosen, policy.matcher,
                record_serial if policy.matcher == "serial" else record_vm_uuid,
                identity_types, excluded_observation_ids, source_name, source_instance_id,
                external_id, source_identity_key,
            )
            if report is None:
                if trace or record_attempts:
                    attempts[-1] = replace(attempts[-1], missing=("identifier_report_changed",))
                return MatchPreview(None, tuple(attempts))
            compared["matched_report"] = report
        ninja_slot_occupied = False
        if has_ninja_guards:
            cur.execute(
                "SELECT operations.ninja_computer_slot_occupied(%s, %s, %s, %s, %s, %s, %s)",
                (tenant_id, chosen, source_instance_id, *source_identity_key),
            )
            ninja_slot_occupied = cur.fetchone()[0]
            if ninja_slot_occupied and not trace:
                raise NinjaRecordSlotOccupied(chosen)
        return MatchPreview(
            MatchResult(
                device_id=chosen,
                matcher=policy.matcher,
                compared=compared,
                candidates=(chosen,),
            ),
            tuple(attempts),
            ninja_slot_occupied=ninja_slot_occupied,
        )
    return MatchPreview(None, tuple(attempts))


def _duplicate_candidate_survivor(
    cur, tenant_id, candidates, identity_types, excluded, source_name,
    source_instance_id, external_id, source_identity_key, rejected_serials, *,
    matcher, universal=False, source_report=(),
):
    """Select the existing merge planner's oldest survivor for one machine."""
    cur.execute(
        f"""
        SELECT d.id, d.created_at, d.client_id,
               lower(trim(eo.canonical_data ->> 'serial_number')),
               lower(nullif(trim(eo.canonical_data ->> 'vm_uuid'), '')),
               {_HOSTNAME_REPORT_SQL}
          FROM operations.devices d
          JOIN operations.entity_observation_current eo
            ON eo.tenant_id = d.tenant_id AND eo.device_id = d.id AND eo.active
          {_HOSTNAME_REPORT_JOINS}
         WHERE d.tenant_id = %s AND d.id = ANY(%s::uuid[]) AND d.deleted_at IS NULL
           AND eo.entity_type = ANY(%s::text[])
           {_EXCLUDE_SOURCE_RECORD_SQL}
           AND NOT (eo.observation_id = ANY(%s::uuid[]))
           AND NOT EXISTS (
               SELECT 1 FROM operations.identity_roaming_records rr
                WHERE rr.tenant_id = eo.tenant_id AND rr.source_instance_id = eo.source_instance_id
                  AND rr.external_id = eo.external_id
           )
        """,
        (tenant_id, candidates, identity_types,
         *_source_record_parameters(source_name, source_instance_id, external_id, source_identity_key),
         list(excluded)),
    )
    evidence = {}
    reports = list(source_report)
    for device_id, created_at, client_id, serial, vm_uuid, platform, entity_type, hostname, seen in cur.fetchall():
        group = evidence.setdefault(device_id, {"created_at": created_at, "client_id": client_id,
                                                 "serials": set(), "vm_uuids": set()})
        serial_is_usable = (is_usable_serial(serial) if rejected_serials is None
                            else usable_serial(serial, rejected_serials))
        if serial_is_usable:
            group["serials"].add(serial)
        else:
            serial = None
        if vm_uuid:
            group["vm_uuids"].add(vm_uuid)
        reports.append((platform, entity_type, hostname, serial, vm_uuid, seen))
    if set(evidence) != set(candidates) or (
        not universal and len({item["client_id"] for item in evidence.values()}) != 1
    ):
        return None
    separated = operator_separated_pairs(cur, tenant_id, candidates)
    assessment = assess_identifier_group(
        serial_groups=[item["serials"] for item in evidence.values()],
        vm_uuid_groups=[item["vm_uuids"] for item in evidence.values()],
        separated=any((a, b) in separated for a in candidates for b in candidates if a != b),
        required_proof=matcher,
    )
    if assessment.outcome != "same" or hostname_conflict(reports):
        return None
    return min(candidates, key=lambda device_id: (evidence[device_id]["created_at"], str(device_id)))


def _identifier_report(
    cur, tenant_id, device_id, matcher, value, identity_types, excluded,
    source_name, source_instance_id, external_id, source_identity_key,
):
    """Identify the current source report used for an identifier match."""
    field = "serial_number" if matcher == "serial" else "vm_uuid"
    cur.execute(
        """
        SELECT eo.observation_id, eo.platform, eo.source_instance_id
          FROM operations.entity_observation_current eo
         WHERE eo.tenant_id = %s AND eo.device_id = %s AND eo.active
           AND eo.entity_type = ANY(%s::text[])
           AND lower(trim(eo.canonical_data ->> %s)) = %s
           {exclude_source_record}
           AND NOT (eo.observation_id = ANY(%s::uuid[]))
           AND NOT EXISTS (
               SELECT 1 FROM operations.identity_roaming_records rr
                WHERE rr.tenant_id = eo.tenant_id AND rr.source_instance_id = eo.source_instance_id
                  AND rr.external_id = eo.external_id
           )
         ORDER BY eo.observation_id LIMIT 1
        """.replace("{exclude_source_record}", _EXCLUDE_SOURCE_RECORD_SQL),
        (tenant_id, device_id, identity_types, field, value,
         *_source_record_parameters(source_name, source_instance_id, external_id, source_identity_key),
         list(excluded)),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "observation_id": str(row[0]), "reporting_source": row[1],
        "reporting_source_instance_id": str(row[2]) if row[2] else None,
        "field_origin": "unknown",
    }


def _identity_types(cur) -> list[str]:
    from ingest.identity import identity_entity_types

    return sorted(identity_entity_types(cur))


def _is_roaming(
    cur,
    tenant_id: int,
    source_name: str,
    source_instance_id: uuid.UUID | None,
    external_id: str,
) -> bool:
    if source_instance_id is None:
        return True
    cur.execute(
        """
        SELECT 1 FROM operations.identity_roaming_records rr
         WHERE rr.tenant_id = %s AND rr.source_instance_id = %s
           AND rr.platform = %s AND rr.external_id = %s
         LIMIT 1
        """,
        (tenant_id, source_instance_id, source_name, external_id),
    )
    return cur.fetchone() is not None


def _compared(matcher: str, serial, vm_uuid, hostname, source_name, source_instance_id) -> dict:
    source = {
        "reporting_source": source_name,
        "reporting_source_instance_id": str(source_instance_id) if source_instance_id else None,
        "field_origin": "unknown",
    }
    if matcher == "serial":
        return {**source, "serial": serial}
    if matcher == "vm_uuid":
        return {**source, "vm_uuid": vm_uuid}
    if matcher in ("hostname", "hostname_mac"):
        return {**source, "hostname": hostname}
    return source


def _candidates(
    cur,
    *,
    tenant_id: int,
    source_name: str,
    source_instance_id: uuid.UUID | None,
    external_id: str,
    entity_type: str,
    serial: str | None,
    vm_uuid: str | None,
    hostname: str | None,
    macs: list[str],
    client_id: uuid.UUID | None,
    matcher: str,
    identity_types: list[str],
    excluded_observation_ids: tuple[uuid.UUID, ...],
    lock_candidates: bool,
    source_identity_key: tuple[str, str, str, str] | None = None,
) -> list[uuid.UUID]:
    if matcher == "source_identity":
        if source_instance_id is None or source_identity_key is None:
            return []
        cur.execute(
            """
            SELECT DISTINCT d.id
              FROM operations.entity_observation_current eo
              JOIN operations.devices d
                ON d.tenant_id = eo.tenant_id AND d.id = eo.device_id
             WHERE eo.tenant_id = %s AND eo.active AND eo.platform = %s AND eo.source_instance_id = %s
               AND eo.external_namespace = %s AND eo.parent_external_namespace = %s
               AND eo.parent_external_id = %s AND eo.external_id = %s
               AND eo.entity_type = %s AND d.deleted_at IS NULL
               AND NOT (eo.observation_id = ANY(%s::uuid[]))
            """,
            (
                tenant_id,
                source_name,
                source_instance_id,
                *source_identity_key,
                entity_type,
                list(excluded_observation_ids),
            ),
        )
        return [row[0] for row in cur.fetchall()]
    if matcher == "serial" and serial:
        cur.execute(
            """
            SELECT DISTINCT d.id
              FROM operations.entity_observation_current eo
              JOIN operations.devices d
                ON d.tenant_id = eo.tenant_id AND d.id = eo.device_id
             WHERE eo.tenant_id = %s AND eo.active
               AND eo.entity_type = ANY(%s::text[])
               AND lower(trim(eo.canonical_data ->> 'serial_number')) = %s
               {exclude_source_record}
               AND NOT (eo.observation_id = ANY(%s::uuid[]))
               AND NOT EXISTS (SELECT 1 FROM operations.identity_roaming_records rr
                                WHERE rr.tenant_id = eo.tenant_id
                                  AND rr.source_instance_id = eo.source_instance_id
                                  AND rr.external_id = eo.external_id)
               AND d.deleted_at IS NULL
            """.replace("{exclude_source_record}", _EXCLUDE_SOURCE_RECORD_SQL),
            (
                tenant_id,
                identity_types,
                serial,
                *_source_record_parameters(source_name, source_instance_id, external_id, source_identity_key),
                list(excluded_observation_ids),
            ),
        )
        return [row[0] for row in cur.fetchall()]
    if matcher == "vm_uuid" and vm_uuid:
        cur.execute(
            """
            SELECT DISTINCT d.id
              FROM operations.entity_observation_current eo
              JOIN operations.devices d
                ON d.tenant_id = eo.tenant_id AND d.id = eo.device_id
             WHERE eo.tenant_id = %s AND eo.active
               AND eo.entity_type = ANY(%s::text[])
               AND lower(nullif(trim(eo.canonical_data ->> 'vm_uuid'), '')) = %s
               {exclude_source_record}
               AND NOT (eo.observation_id = ANY(%s::uuid[]))
               AND NOT EXISTS (SELECT 1 FROM operations.identity_roaming_records rr
                                WHERE rr.tenant_id = eo.tenant_id
                                  AND rr.source_instance_id = eo.source_instance_id
                                  AND rr.external_id = eo.external_id)
               AND d.deleted_at IS NULL
            """.replace("{exclude_source_record}", _EXCLUDE_SOURCE_RECORD_SQL),
            (
                tenant_id,
                identity_types,
                vm_uuid,
                *_source_record_parameters(source_name, source_instance_id, external_id, source_identity_key),
                list(excluded_observation_ids),
            ),
        )
        return [row[0] for row in cur.fetchall()]
    if matcher in ("hostname", "hostname_mac") and hostname:
        if matcher == "hostname_mac" and not macs:
            return []
        return _name_candidates(
            cur,
            tenant_id=tenant_id,
            hostname=hostname,
            client_id=client_id,
            macs=macs if matcher == "hostname_mac" else None,
            source_name=source_name,
            source_instance_id=source_instance_id,
            external_id=external_id,
            identity_types=identity_types,
            excluded_observation_ids=excluded_observation_ids,
            lock_candidates=lock_candidates,
            source_identity_key=source_identity_key,
        )
    return []


# Every named identity record of the client's Computers, normalized by the one
# SQL function (ADR-0034 section 1). Roaming records carry no name. Read once
# per client and matched in Python: one query per record cost about a second
# on a large client and made the resolver and source runs several times slower.
_CLIENT_NAMES = """
SELECT eo.device_id, d.lifecycle_status, f.name_short, f.name_key,
       eo.active AND coalesce(lc.record_lifecycle, '') <> 'archived' AS is_current,
       eo.platform, eo.entity_key, eo.entity_type, eo.source_instance_id,
       eo.external_namespace, eo.parent_external_namespace, eo.parent_external_id, eo.external_id
  FROM operations.entity_observation_current eo
  JOIN operations.devices d
    ON d.tenant_id = eo.tenant_id AND d.id = eo.device_id AND d.deleted_at IS NULL
  LEFT JOIN operations.v_device_source_record_lifecycle_current lc
    ON lc.observation_id = eo.observation_id
 CROSS JOIN LATERAL operations.record_name_forms(
      eo.platform, eo.entity_type,
      coalesce(nullif(eo.canonical_data ->> 'hostname', ''), eo.canonical_data ->> 'guest_name'),
      eo.canonical_data ->> 'domain') f
 WHERE eo.tenant_id = %(tenant)s
   AND (%(all_clients)s OR %(client)s::uuid IS NULL OR d.client_id = %(client)s::uuid OR NOT EXISTS (
       SELECT 1 FROM operations.computer_client_ownership owner
        WHERE owner.tenant_id = d.tenant_id AND owner.device_id = d.id
          AND owner.effective_client_id = d.client_id
          AND owner.state IN ('resolved', 'decision_protected')))
   AND NOT (eo.observation_id = ANY(%(excluded_observation_ids)s::uuid[]))
   AND eo.entity_key NOT LIKE 'device-health:%%'
   AND f.name_short IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM operations.identity_roaming_records rr
                    WHERE rr.tenant_id = eo.tenant_id
                      AND rr.source_instance_id = eo.source_instance_id
                      AND rr.external_id = eo.external_id)
"""
# Kept briefly and dropped for a client as soon as a record attaches to one of
# its Computers (invalidate_client_names), so a run sees its own attachments.
_NAMES_TTL = 120.0
_names_cache: dict[tuple, tuple[float, list[tuple]]] = {}


def invalidate_client_names(client_id=None) -> None:
    """Forget cached record names for a client (all clients when ``None``)."""
    if client_id is None:
        _names_cache.clear()
        return
    for cache_key in [k for k in _names_cache if k[1] in (client_id, None)]:
        _names_cache.pop(cache_key, None)


def client_record_names(
    cur, tenant_id: int, client_id, excluded_observation_ids: tuple[uuid.UUID, ...] = (),
    *, match_name: str | None = None,
) -> list[tuple]:
    """(device_id, lifecycle, name_short, name_key, is_current, platform, entity_key,
    entity_type, source_instance_id, and the four-part source key) for each named record."""
    if match_name is not None:
        # Ownership can change in another process while a client cache is
        # warm. Query only names that can match this record so a newly owned
        # or unresolved Computer cannot be omitted from the decision.
        cur.execute(
            _CLIENT_NAMES + """
   AND (f.name_key = %(match_key)s
        OR (length(%(match_name)s) = 15 AND length(f.name_short) > 15
            AND left(f.name_short, 15) = %(match_name)s)
        OR (length(f.name_short) = 15 AND length(%(match_name)s) > 15
            AND left(%(match_name)s, 15) = f.name_short))
            """,
            {
                "tenant": tenant_id, "client": client_id, "all_clients": True,
                "excluded_observation_ids": list(excluded_observation_ids),
                "match_name": match_name, "match_key": _LOOSE_RE.sub("", match_name),
            },
        )
        return cur.fetchall()
    cache_key = (
        tenant_id,
        client_id,
        tuple(sorted(map(str, excluded_observation_ids))),
    )
    # Counterfactual reads must use the caller's snapshot, not a cache entry
    # created by an earlier transaction.
    cached = _names_cache.get(cache_key) if not excluded_observation_ids else None
    now = time.monotonic()
    if cached and now - cached[0] < _NAMES_TTL:
        return cached[1]
    cur.execute(
        _CLIENT_NAMES,
        {
            "tenant": tenant_id,
            "client": client_id,
            "all_clients": False,
            "excluded_observation_ids": list(excluded_observation_ids),
        },
    )
    rows = cur.fetchall()
    if not excluded_observation_ids:
        _names_cache[cache_key] = (now, rows)
    return rows


def _tier(lifecycle: str, is_current: bool) -> int:
    if is_current and lifecycle == "active":
        return 1
    if is_current and lifecycle != "retired":
        return 2
    return 3


def _names_match(short: str, key: str, name_short: str, name_key: str) -> bool:
    if not key or not name_key:
        return False
    return (
        name_key == key
        or (len(short) == 15 and len(name_short) > 15 and name_short[:15] == short)
        or (len(name_short) == 15 and len(short) > 15 and short[:15] == name_short)
    )


# Names the client's records reported earlier (tier 4), distinct per record.
# Reading the history of every record of a large client takes seconds, so it
# is computed once per client and kept briefly (_HISTORY_TTL).
_HISTORY_NAMES = """
SELECT DISTINCT eo.device_id, eo.platform, eo.entity_key, eo.source_instance_id,
       f.name_short, f.name_key, eo.external_namespace, eo.parent_external_namespace,
       eo.parent_external_id, eo.external_id
  FROM (
    SELECT DISTINCT eo.device_id, eo.platform, eo.entity_key, eo.source_instance_id,
           eo.external_namespace, eo.parent_external_namespace, eo.parent_external_id, eo.external_id,
           h.platform AS h_platform,
           h.entity_type AS h_type,
           coalesce(nullif(h.material_data ->> 'hostname', ''), h.material_data ->> 'guest_name') AS raw,
           h.material_data ->> 'domain' AS domain
      FROM operations.entity_observation_current eo
      JOIN operations.devices d
        ON d.tenant_id = eo.tenant_id AND d.id = eo.device_id AND d.deleted_at IS NULL
      JOIN operations.entity_observation_history h
        ON h.tenant_id = eo.tenant_id AND h.source_instance_id = eo.source_instance_id
       AND h.external_namespace = eo.external_namespace
       AND h.parent_external_namespace = eo.parent_external_namespace
       AND h.parent_external_id = eo.parent_external_id
       AND h.external_id = eo.external_id AND h.entity_type = eo.entity_type
     WHERE eo.tenant_id = %(tenant)s
       AND (%(all_clients)s OR %(client)s::uuid IS NULL OR d.client_id = %(client)s::uuid OR NOT EXISTS (
           SELECT 1 FROM operations.computer_client_ownership owner
            WHERE owner.tenant_id = d.tenant_id AND owner.device_id = d.id
              AND owner.effective_client_id = d.client_id
              AND owner.state IN ('resolved', 'decision_protected')))
       AND eo.entity_type = ANY(%(types)s::text[])
       AND NOT (eo.observation_id = ANY(%(excluded_observation_ids)s::uuid[]))
       AND NOT EXISTS (SELECT 1 FROM operations.identity_roaming_records rr
                        WHERE rr.tenant_id = eo.tenant_id
                          AND rr.source_instance_id = eo.source_instance_id
                          AND rr.external_id = eo.external_id)
  ) eo
 CROSS JOIN LATERAL operations.record_name_forms(eo.h_platform, eo.h_type, eo.raw, eo.domain) f
 WHERE f.name_key IS NOT NULL
"""
_HISTORY_TTL = 600.0
_history_cache: dict[tuple, tuple[float, list[tuple]]] = {}


def _history_names(
    cur,
    tenant_id: int,
    client_id,
    identity_types: list[str],
    excluded_observation_ids: tuple[uuid.UUID, ...] = (),
    *, match_key: str | None = None,
) -> list[tuple]:
    if match_key is not None:
        cur.execute(
            _HISTORY_NAMES + " AND f.name_key = %(match_key)s",
            {"tenant": tenant_id, "client": client_id, "all_clients": True, "types": identity_types,
             "excluded_observation_ids": list(excluded_observation_ids), "match_key": match_key},
        )
        return cur.fetchall()
    cache_key = (
        tenant_id,
        client_id,
        tuple(sorted(identity_types)),
        tuple(sorted(map(str, excluded_observation_ids))),
    )
    cached = _history_cache.get(cache_key) if not excluded_observation_ids else None
    now = time.monotonic()
    if cached and now - cached[0] < _HISTORY_TTL:
        return cached[1]
    started = time.monotonic()
    cur.execute(
        _HISTORY_NAMES,
        {
            "tenant": tenant_id,
            "client": client_id,
            "all_clients": False,
            "types": identity_types,
            "excluded_observation_ids": list(excluded_observation_ids),
        },
    )
    rows = cur.fetchall()
    log.info(
        "identity matching: query=history_names elapsed_seconds=%.3f rows=%d",
        time.monotonic() - started, len(rows),
    )
    if not excluded_observation_ids:
        _history_cache[cache_key] = (now, rows)
    return rows


def _name_candidates(
    cur,
    *,
    tenant_id: int,
    hostname: str,
    client_id: uuid.UUID | None,
    macs: list[str] | None,
    source_name: str,
    source_instance_id: uuid.UUID | None,
    external_id: str,
    identity_types: list[str],
    excluded_observation_ids: tuple[uuid.UUID, ...],
    lock_candidates: bool,
    source_identity_key: tuple[str, str, str, str] | None = None,
) -> list[uuid.UUID]:
    """Computers whose records report the name (ADR-0034 section 4).

    ``hostname`` is the incoming record's strict name form from
    ``operations.record_name_forms``. Tiers, the first with a candidate
    deciding: current records on active Computers, on other non-retired
    Computers, withdrawn records, record history. The last two tiers require
    review rather than an automatic attachment. A strict match may name
    several Computers; the caller leaves that decision unresolved. A loose
    match decides only when it identifies
    exactly one Computer; a 15-character match only when exactly one distinct
    longer name starts with it.
    """
    key = _LOOSE_RE.sub("", hostname)
    if not key:
        return []
    types = set(identity_types)
    rows = [
        (device_id, _tier(lifecycle, is_current), name_short, name_key)
        for device_id, lifecycle, name_short, name_key, is_current, platform, entity_key, entity_type, row_source_instance, *row_key in client_record_names(
            cur, tenant_id, client_id, excluded_observation_ids,
            match_name=hostname if client_id is not None else None
        )
        # The record's own row is skipped by its complete source identity.
        if entity_type in types
        and not (
            platform == source_name
            and (tuple(row_key) == source_identity_key if source_identity_key is not None
                 else entity_key == external_id)
            and (
                source_instance_id is None or row_source_instance == source_instance_id
            )
        )
        and _names_match(hostname, key, name_short, name_key or "")
    ]
    if rows and client_id is not None:
        scoped = set(_scope_candidates(
            cur, tenant_id, client_id, list({row[0] for row in rows}), lock=lock_candidates
        ))
        rows = [row for row in rows if row[0] in scoped]
    if not rows:
        # Tier 4 only decides when no current or withdrawn record holds the name.
        rows = [
            (device_id, 4, short, name_key)
            for device_id, platform, entity_key, row_source_instance, short, name_key, *row_key in _history_names(
                cur, tenant_id, client_id, identity_types, excluded_observation_ids,
                match_key=key if client_id is not None else None,
            )
            if name_key == key
            and not (
                platform == source_name
                and (tuple(row_key) == source_identity_key if source_identity_key is not None
                     else entity_key == external_id)
                and (
                    source_instance_id is None
                    or row_source_instance == source_instance_id
                )
            )
        ]
        if rows and client_id is not None:
            scoped = set(_scope_candidates(
                cur, tenant_id, client_id, list({row[0] for row in rows}), lock=lock_candidates
            ))
            rows = [row for row in rows if row[0] in scoped]
    chosen: list[uuid.UUID] = []
    for tier in (1, 2, 3, 4):
        in_tier = [row for row in rows if row[1] == tier]
        if not in_tier:
            continue
        strict = sorted({row[0] for row in in_tier if row[2] == hostname}, key=str)
        loose = sorted({row[0] for row in in_tier if row[3] == key}, key=str)
        cut_names = {row[2] for row in in_tier if row[3] != key}
        if strict:
            chosen = strict
        elif loose:
            # Preserve all candidates so the shared decision path reports an
            # ambiguity instead of treating it as no evidence and falling
            # through to a weaker policy.
            chosen = loose
        elif len(cut_names) == 1:
            chosen = sorted({row[0] for row in in_tier if row[2] in cut_names}, key=str)
        elif cut_names:
            raise _AmbiguousNameEvidence(
                sorted({row[0] for row in in_tier if row[2] in cut_names}, key=str)
            )
        # The highest tier holding the name decides, even when it is ambiguous.
        if chosen and tier >= 3:
            raise _StaleNameEvidence(chosen)
        break
    # An unverified MAC cannot turn an ambiguous hostname into the unique
    # same-client hostname match approved for automatic attachment.
    if len(chosen) > 1:
        return chosen
    if chosen and macs is not None:
        cur.execute(
            """
            SELECT DISTINCT eo.device_id
              FROM operations.entity_observation_current eo
             WHERE eo.tenant_id = %s AND eo.device_id = ANY(%s::uuid[]) AND eo.active
               AND eo.entity_type = ANY(%s::text[])
               AND NOT (eo.observation_id = ANY(%s::uuid[]))
               AND NOT EXISTS (
                   SELECT 1 FROM operations.identity_roaming_records rr
                    WHERE rr.tenant_id = eo.tenant_id
                      AND rr.source_instance_id = eo.source_instance_id
                      AND rr.external_id = eo.external_id
               )
               AND EXISTS (SELECT 1
                             FROM jsonb_array_elements_text(
                                  CASE WHEN jsonb_typeof(eo.canonical_data -> 'macs') = 'array'
                                       THEN eo.canonical_data -> 'macs' ELSE '[]'::jsonb END) m(mac)
                            WHERE {identity_mac} = ANY(%s::text[]))
            """.replace("{identity_mac}", _identity_mac_sql("m.mac")),
            (tenant_id, chosen, identity_types, list(excluded_observation_ids),
             [mac.replace(':', '') for mac in macs]),
        )
        with_mac = {row[0] for row in cur.fetchall()}
        chosen = [device_id for device_id in chosen if device_id in with_mac]
    return chosen


def record_name_short(
    cur, platform: str, entity_type: str, name: str | None, domain=None
) -> str:
    """The strict name form of one reported name (``operations.record_name_forms``)."""
    if not name:
        return ""
    cur.execute(
        "SELECT name_short FROM operations.record_name_forms(%s, %s, %s, %s)",
        (platform, entity_type, name, domain),
    )
    row = cur.fetchone()
    return (row[0] or "") if row else ""


def _hard_conflict(
    cur,
    tenant_id: int,
    device_id: uuid.UUID,
    blockers: frozenset[str],
    *,
    source_name: str,
    source_instance_id: uuid.UUID | None = None,
    entity_type: str,
    external_id: str,
    serial: str | None,
    vm_uuid: str | None,
    is_online: bool | None,
) -> bool:
    return (
        _hard_conflict_reason(
            cur,
            tenant_id,
            device_id,
            blockers,
            source_name=source_name,
            source_instance_id=source_instance_id,
            entity_type=entity_type,
            external_id=external_id,
            serial=serial,
            vm_uuid=vm_uuid,
            is_online=is_online,
            excluded_observation_ids=(),
        )
        is not None
    )


def _hard_conflict_reason(
    cur,
    tenant_id: int,
    device_id: uuid.UUID,
    blockers: frozenset[str],
    *,
    source_name: str,
    source_instance_id: uuid.UUID | None = None,
    entity_type: str,
    external_id: str,
    serial: str | None,
    vm_uuid: str | None,
    is_online: bool | None,
    excluded_observation_ids: tuple[uuid.UUID, ...],
    identity_types: list[str] | None = None,
    source_identity_key: tuple[str, str, str, str] | None = None,
    rejected_serials: frozenset[str] | None = None,
    source_report: tuple = (),
) -> str | None:
    """True when the candidate is proven to be a different machine."""
    if identity_types is None:
        identity_types = _identity_types(cur)
    # An operator split this record off the candidate (migration 0309).
    cur.execute(
        """
        SELECT 1 FROM operations.device_operator_decisions
         WHERE tenant_id = %s AND device_id = %s AND dimension = 'identity_excluded_records'
           AND value ? %s
        """,
        (tenant_id, device_id, f"{source_name}|{external_id}"),
    )
    if cur.fetchone() is not None:
        return "operator_exclusion"
    if excluded_observation_ids:
        cur.execute(
            "SELECT DISTINCT device_id FROM operations.entity_observation_current "
            "WHERE tenant_id = %s AND observation_id = ANY(%s::uuid[]) AND device_id IS NOT NULL",
            (tenant_id, list(excluded_observation_ids)),
        )
        source_devices = {row[0] for row in cur.fetchall()} - {device_id}
        if source_devices:
            separated = operator_separated_pairs(cur, tenant_id, [device_id, *source_devices])
            if any((device_id, source_device) in separated for source_device in source_devices):
                return "operator_exclusion"
    cur.execute(
        f"""
        SELECT eo.active, lower(trim(eo.canonical_data ->> 'serial_number')),
               lower(nullif(trim(eo.canonical_data ->> 'vm_uuid'), '')),
               EXISTS (SELECT 1 FROM operations.identity_roaming_records rr
                        WHERE rr.tenant_id = eo.tenant_id
                          AND rr.source_instance_id = eo.source_instance_id
                          AND rr.external_id = eo.external_id) AS roaming,
               {_HOSTNAME_REPORT_SQL}
          FROM operations.entity_observation_current eo
          {_HOSTNAME_REPORT_JOINS}
         WHERE eo.tenant_id = %s AND eo.device_id = %s
           AND eo.entity_type = ANY(%s::text[])
           {_EXCLUDE_SOURCE_RECORD_SQL}
           AND NOT (eo.observation_id = ANY(%s::uuid[]))
        """,
        (
            tenant_id,
            device_id,
            identity_types,
            *_source_record_parameters(source_name, source_instance_id, external_id, source_identity_key),
            list(excluded_observation_ids),
        ),
    )
    rows = cur.fetchall()
    live_rows = [row for row in rows if row[0]]
    # Withdrawn and roaming records cannot establish a current contradiction.
    judged = [row for row in live_rows if not row[3]]
    serial_groups = [
        {row[1]} if "serial" in blockers and row[1] and
        (is_usable_serial(row[1]) if rejected_serials is None
         else usable_serial(row[1], rejected_serials)) else set()
        for row in judged
    ]
    vm_groups = [
        {row[2]} if "vm_uuid" in blockers and row[2] else set() for row in judged
    ]
    assessment = assess_identity(
        serial_groups=[*serial_groups, {serial} if serial and "serial" in blockers else set()],
        vm_uuid_groups=[*vm_groups, {vm_uuid} if vm_uuid and "vm_uuid" in blockers else set()],
    )
    if assessment.outcome == "different":
        return assessment.reason
    reports = [
        (platform, entity_type, name, next(iter(serial_group), None), vm_uuid, seen)
        for (_, _, vm_uuid, _, platform, entity_type, name, seen), serial_group
        in zip(judged, serial_groups, strict=True)
    ]
    if hostname_conflict([*source_report, *reports]):
        return "hostname_conflict"
    return None
