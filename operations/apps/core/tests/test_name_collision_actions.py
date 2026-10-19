"""A name collision is review-only: Merge and Confirm separate never apply to it (ADR-0034 5a)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from apps.core import identity_actions
from apps.core.finding_actions import (
    CONFIRM_COMPUTERS_SEPARATE,
    FINDING_ACTIONS,
    MERGE_COMPUTERS,
)

COLLISION = "computer_name_collision"


def _finding(type_name):
    return SimpleNamespace(
        id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
        finding_type=SimpleNamespace(name=type_name),
        finding_details={"computers": [{"device_id": str(uuid.uuid4())}]},
    )


def test_no_issue_action_offers_itself_for_a_name_collision():
    assert [
        key for key, action in FINDING_ACTIONS.items() if COLLISION in action.finding_types
    ] == []


def test_merge_and_confirm_separate_are_refused_for_a_name_collision():
    finding = _finding(COLLISION)
    for action in (MERGE_COMPUTERS, CONFIRM_COMPUTERS_SEPARATE):
        refusal = identity_actions._refusal([finding], [str(finding.id)], action, "checked")
        assert refusal == f"“{action.label}” does not apply to every selected issue."


def test_merge_is_still_offered_for_a_real_duplicate():
    finding = _finding("duplicate_device_records")
    assert identity_actions._refusal([finding], [str(finding.id)], MERGE_COMPUTERS, "checked") == ""
