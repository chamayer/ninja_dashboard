"""Response eligibility, separate from observed truth and operator handling."""

from __future__ import annotations

from datetime import datetime

from .contracts import Condition, Decision, Participant, Readiness, Signal
from .policy import Profile


def _expanded_rules(definition, profile):
    applicable = set(definition["rules"])
    pending = list(applicable)
    while pending:
        for parent in profile.rules[pending.pop()].get("requires", []):
            if parent not in applicable:
                applicable.add(parent)
                pending.append(parent)
    return sorted(applicable)


def _applicable_signals(condition, definition, profile, signals, participant):
    for rule_name in _expanded_rules(definition, profile):
        rule = profile.rules[rule_name]
        independent = condition.has_independent_software_subject
        if rule.get("participant_kind") and (
            participant is None or participant.kind != rule["participant_kind"]
        ):
            if not independent:
                yield rule, None, f"{rule_name}:participant_scope_unmeasured"
            continue
        matches = [
            s
            for s in signals
            if s.prerequisite == rule_name and (participant is None or s.participant == participant)
        ]
        if not matches:
            yield rule, None, f"{rule_name}:unmeasured"
        for signal in matches:
            yield rule, signal, signal.reason


def assess(
    condition: Condition,
    profile: Profile,
    signals: tuple[Signal, ...],
    now: datetime,
    participant: Participant | None = None,
) -> Decision:
    """Assess one participant scope; no writes, notifications or permissions.

    No critical-hides-medium rule exists. Global software facts and individual
    exposure relationships can receive different decisions for the same finding.
    Unknown prerequisites cannot imply ready. Identity-resolution definitions
    explicitly omit the identity prerequisite, preventing self-blocking.
    """
    if participant is not None and participant not in condition.participant_set:
        raise ValueError("Participant is not a member of this condition")
    if now.tzinfo is None:
        raise ValueError("Evaluation time must be timezone-aware")
    if any(s.participant not in condition.participant_set for s in signals):
        raise ValueError("Dependency signal is not for a condition participant")
    reasons, blockers = set(), set()
    gated = unknown = suppressed = False
    definition = profile.definitions.get(condition.type_name)
    if definition is None or definition["lifecycle"] != "active":
        unknown = True
        reasons.add("definition_unverified_or_inactive")
    else:
        for rule, signal, reason in _applicable_signals(
            condition, definition, profile, signals, participant
        ):
            if signal is None or signal.readiness == Readiness.UNKNOWN:
                unknown = True
                reasons.add(reason)
            elif signal.readiness == Readiness.BLOCKED:
                blockers.update(signal.blocker_references)
                reasons.add(reason)
                if rule["effect"] == "gate":
                    gated = True
                else:
                    suppressed = True
    if condition.status in {"suppressed", "wontfix"} or (
        condition.snoozed_until is not None and condition.snoozed_until > now
    ):
        suppressed = True
        reasons.add("existing_operator_suppression")
    if condition.status == "resolved":
        unknown = True
        reasons.add("historical_resolution_not_reinterpreted")
    disposition = (
        "blocked" if gated else "unknown" if unknown else "suppressed" if suppressed else "eligible"
    )
    return Decision(
        condition.identity,
        participant,
        disposition,
        not (gated or unknown),
        not (gated or unknown or suppressed),
        not (gated or unknown or suppressed),
        tuple(sorted(reasons)),
        tuple(sorted(blockers)),
    )
