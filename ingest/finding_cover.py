"""The ``parent_open`` rule is satisfied for every assessment: cover is not evidence.

Whether a finding is covered by another open finding is a relation between two findings, decided
by ``operations.compute_finding_state`` (migration 0304) from the open findings on the same
computer. It is no longer recorded in the child's assessment, so a parent opening or closing
changes the child's state immediately without a reassessment.

The policy still carries the ``parent_open`` rule (added in migration 0296) and the engine reads a
missing signal as unknown, so each participant is given a ready signal until the rule is removed
at the next policy version.
"""

from __future__ import annotations

from shared.conditions.contracts import Condition, Readiness, Signal

RULE = "parent_open"


def ready_signals(condition: Condition) -> tuple[Signal, ...]:
    """One ready ``parent_open`` signal per participant."""
    return tuple(
        Signal(RULE, participant, Readiness.READY, "parent_open:not_evidence")
        for participant in condition.participants
    )
