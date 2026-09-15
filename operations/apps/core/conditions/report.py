"""Aggregate shadow comparison. Never emit names, payloads, URLs or raw IDs."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import timedelta
from uuid import UUID

from .contracts import Condition, Participant, Readiness, Signal
from .engine import assess
from .policy import Profile
from .reader import Snapshot

MIN_IDENTITY_MEMBERS = 2


def _uuid(value) -> str | None:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def _identity_groups(snapshot: Snapshot, profile: Profile, devices: dict) -> tuple[dict, int]:
    groups = defaultdict(set)
    invalid = 0
    for row in snapshot.findings:
        if row["type_name"] != profile.identity_group_type or row["status"] == "resolved":
            continue
        # A snooze, suppression or Won't fix is not proof of settled identity.
        raw_members = row.get("candidate_ids")
        # Django's psycopg adapter may return raw JSON text for cursor results;
        # unlike JSONField ORM reads, it does not guarantee decoded arrays.
        if isinstance(raw_members, str):
            try:
                raw_members = json.loads(raw_members)
            except (ValueError, TypeError):
                raw_members = None
        if not isinstance(raw_members, list):
            invalid += 1
            continue
        members = {_uuid(value) for value in raw_members}
        valid = {value for value in members if value in devices}
        invalid += len(members - valid)
        if len(valid) < MIN_IDENTITY_MEMBERS:
            invalid += 1
            continue
        for value in valid:
            groups[value].add(f"{row['row_kind']}:{row['row_id']}")
    return groups, invalid


def _collection_signal(row, participant, collections, now, profile):
    key = (_uuid(row.get("source_instance_id")), row.get("snapshot_scope"))
    record = collections.get(key)
    state, reason = Readiness.UNKNOWN, "collection:scope_unmapped"
    if record:
        complete = record["status"] == "complete" and record["is_complete_snapshot"] is True
        counts_ok = (
            record["failed_rows"] == 0
            and record["written_rows"] is not None
            and record["expected_rows"] is not None
            and record["written_rows"] >= record["expected_rows"]
        )
        completed = record["completed_at"]
        fresh = (
            completed is not None
            and now - timedelta(hours=profile.freshness_hours) <= completed <= now
        )
        if complete and counts_ok and fresh:
            # A mapped single scope is measurable, but legacy findings do not
            # declare whether that is ALL the input scopes needed for absence.
            state, reason = Readiness.UNKNOWN, "collection:required_scope_set_unverified"
        else:
            state, reason = Readiness.BLOCKED, "collection:incomplete_or_stale"
    return Signal("collection", participant, state, reason)


def _signals(row, participant, groups, presence, collections, snapshot, profile):
    signals = [_collection_signal(row, participant, collections, snapshot.now, profile)]
    if participant.kind != "device":
        return tuple(signals)
    blockers = groups.get(participant.reference, set())
    signals.append(
        Signal(
            "identity",
            participant,
            Readiness.BLOCKED if blockers else Readiness.UNKNOWN,
            "identity:unsettled_group" if blockers else "identity:readiness_not_established",
            tuple(sorted(blockers)),
        )
    )
    current = presence.get(participant.reference)
    state, reason = Readiness.UNKNOWN, "offline:contact_unavailable"
    if current and current["last_contact"] is not None:
        contact = current["last_contact"]
        if contact > snapshot.now:
            reason = "offline:future_contact"
        elif contact < snapshot.now - timedelta(days=profile.offline_days):
            if current["any_reported_online"]:
                # Contradictory signals must not be silently resolved by picking
                # a convenient field. Count separately for the review.
                reason = "offline:conflicting_online_evidence"
            else:
                state, reason = Readiness.BLOCKED, "offline:extended_absence"
        else:
            state, reason = Readiness.READY, "offline:within_window"
    signals.append(Signal("offline", participant, state, reason))
    return tuple(signals)


def _condition(row, snapshot, profile, devices, associations, groups):
    participants = set()
    subject_id = row.get("subject_id")
    missing_subject = row["subject_type"] == "device" and subject_id not in devices
    if subject_id and not missing_subject:
        participants.add(
            Participant(row["subject_type"], subject_id, "affected", snapshot.tenant_id)
        )
    # The legacy tables have independent ID namespaces.
    if row["row_kind"] == "entity":
        for device_id, kind in associations.get(row["row_id"], ()):
            participants.add(Participant("device", device_id, kind, snapshot.tenant_id))
    if row["type_name"] == profile.identity_group_type:
        for device_id, references in groups.items():
            if f"{row['row_kind']}:{row['row_id']}" in references:
                participants.add(
                    Participant("device", device_id, "conflicting", snapshot.tenant_id)
                )
    if row.get("client_id"):
        participants.add(Participant("client", row["client_id"], "context", snapshot.tenant_id))
    value = Condition(
        snapshot.tenant_id,
        row["row_kind"],
        row["row_id"],
        row["type_name"],
        row["condition_key"],
        row["status"],
        tuple(sorted(participants)),
        row.get("snoozed_until"),
    )
    return value, missing_subject


def build_report(snapshot: Snapshot, profile: Profile) -> dict:
    """Count condition rows separately from proposed participant dispositions.

    This is NOT a simulation of configured delivery, permissions or every
    legacy predicate. Subscriber limitations are part of the returned contract.
    """
    devices = {row["device_id"]: row for row in snapshot.devices}
    presence = {
        row["device_id"]: row
        for row in snapshot.presence
        if row["device_id"] in devices
        and devices[row["device_id"]]["lifecycle_status"] != "retired"
    }
    collections = {
        (row["source_instance_id"], row["snapshot_scope"]): row for row in snapshot.collections
    }
    groups, invalid_members = _identity_groups(snapshot, profile, devices)
    associations = defaultdict(set)
    for row in snapshot.associations:
        if row["device_id"] in devices:
            associations[row["row_id"]].add((row["device_id"], row["association_kind"]))
    active_statuses = {"open", "acknowledged", "investigating"}
    by_type = defaultdict(
        lambda: {
            "rows": 0,
            "active_rows": 0,
            "participant_scopes": 0,
            "dispositions": Counter(),
            "reasons": Counter(),
        }
    )
    baseline = Counter()
    identities = Counter()
    affected_rows, affected_devices = set(), set()
    candidate_exposures, installation_impacts = set(), set()
    offline_rows, incomplete_rows = set(), set()
    mixed_rows, missing_subjects = 0, 0
    for row in snapshot.findings:
        condition, missing = _condition(row, snapshot, profile, devices, associations, groups)
        missing_subjects += missing
        info = by_type[condition.type_name]
        info["rows"] += 1
        active = condition.status in active_statuses
        if active:
            identities[condition.identity] += 1
            info["active_rows"] += 1
            baseline[condition.row_kind] += 1
        targets = [p for p in condition.participants if p.role != "context"]
        dispositions = set()
        reasons = set()
        for participant in targets or [None]:
            signals = (
                ()
                if participant is None
                else _signals(row, participant, groups, presence, collections, snapshot, profile)
            )
            decision = assess(condition, profile, signals, snapshot.now, participant)
            dispositions.add(decision.disposition)
            reasons.update(decision.reasons)
            info["participant_scopes"] += 1
            info["dispositions"][decision.disposition] += 1
            if active and "identity:unsettled_group" in decision.reasons:
                affected_rows.add((condition.row_kind, condition.row_id))
                affected_devices.add(participant.reference)
                if participant.role == "candidate_software_exposure":
                    candidate_exposures.add((condition.row_id, participant.reference))
                elif participant.role == "installation_subject":
                    installation_impacts.add(condition.row_id)
            if active and "offline:extended_absence" in decision.reasons:
                offline_rows.add((condition.row_kind, condition.row_id))
            if active and "collection:incomplete_or_stale" in decision.reasons:
                incomplete_rows.add((condition.row_kind, condition.row_id))
        mixed_rows += len(dispositions) > 1
        info["reasons"].update(reasons)
    comparison = {
        "identity_group_devices": len(groups),
        "active_rows_with_identity_blocked_participants": len(affected_rows),
        "identity_blocked_devices": len(affected_devices),
        "identity_blocked_installation_rows": len(installation_impacts),
        "identity_blocked_candidate_exposure_pairs": len(candidate_exposures),
        "active_rows_with_offline_suppression_reason": len(offline_rows),
        "active_rows_with_collection_block_reason": len(incomplete_rows),
        "rows_with_mixed_participant_dispositions": mixed_rows,
        "duplicate_active_identity_groups": sum(n > 1 for n in identities.values()),
        "invalid_or_unavailable_identity_members": invalid_members,
        "unavailable_direct_device_subjects": missing_subjects,
    }
    return _format_report(snapshot, profile, comparison, by_type, baseline)


def _format_report(snapshot, profile, comparison, by_type, baseline):
    registry_names = {row["name"] for row in snapshot.registry}
    for name in registry_names | profile.definitions.keys():
        info = by_type[name]
        definition = profile.definitions.get(name, {})
        info.update(
            {
                key: definition.get(key, "unmapped")
                for key in ("category", "type", "label", "lifecycle")
            }
        )
    return {
        "mode": "shadow_only",
        "tenant_id": snapshot.tenant_id,
        "evaluated_at": snapshot.now.isoformat(),
        "profile_version": profile.version,
        "profile_sha256": profile.digest,
        "thresholds": {
            "offline_days": profile.offline_days,
            "freshness_hours": profile.freshness_hours,
        },
        "registry": {
            "registered": len(registry_names),
            "profile_definitions": len(profile.definitions),
            "unmapped_live_types": sorted(registry_names - profile.definitions.keys()),
            "profile_types_not_registered": sorted(profile.definitions.keys() - registry_names),
        },
        "baseline_active_rows": dict(baseline),
        "comparison": comparison,
        "by_type": {
            name: {
                **data,
                "dispositions": dict(data["dispositions"]),
                "reasons": dict(data["reasons"]),
            }
            for name, data in sorted(by_type.items())
        },
        "consumer_state": {row["name"]: row["count"] for row in snapshot.consumers},
        "subscriber_coverage": {
            name: "candidate dependency impact only; unchanged" for name in profile.consumers
        },
        "limitations": [
            "No writes, notifications, actions, or live consumer changes.",
            "Identity groups are provisional blockers; absence of a group does not establish readiness.",
            "Candidate software exposure joins do not reproduce every current exposure predicate.",
            "Legacy findings do not declare their complete required source-scope set; unmapped scope stays unknown.",
            "Client aggregates without member contracts remain unmeasured, not suppressed as a whole.",
            "Subscriber routing, authorization, historical health metrics and external consumers are not simulated.",
            "Condition counts and participant counts overlap; do not sum them.",
        ],
    }
