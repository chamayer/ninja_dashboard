"""Computer identity actions from the Issues queue (ADR-0032)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from apps.core.finding_actions import (
    CONFIRM_COMPUTERS_SEPARATE,
    FINDING_ACTIONS,
    IDENTITY_ACTIONS,
    MERGE_COMPUTERS,
    SPLIT_COMPUTER_RECORDS,
)
from apps.core.identity_actions import named_computers


def _finding(subject, **details):
    return SimpleNamespace(subject_id=subject, finding_details=details)


def test_named_computers_puts_the_subject_first_for_every_identity_type():
    subject, other, third = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    duplicate = _finding(
        subject,
        computers=[{"device_id": str(other)}, {"device_id": str(subject)}, {"device_id": "x"}],
    )
    assert named_computers(duplicate) == [subject, other]
    conflict = _finding(subject, candidate_device_ids=[str(third), str(subject)])
    assert named_computers(conflict) == [subject, third]
    shared = _finding(subject, device_ids=[str(other), str(third)])
    assert named_computers(shared) == [subject, other, third]


def test_identity_actions_are_registered_with_the_lifecycle_permission_and_a_reason():
    for action in (MERGE_COMPUTERS, CONFIRM_COMPUTERS_SEPARATE, SPLIT_COMPUTER_RECORDS):
        assert FINDING_ACTIONS[action.key] is action
        assert action.key in IDENTITY_ACTIONS
        assert action.permission == "operations.manage_lifecycle"
        assert action.requires_reason
    assert SPLIT_COMPUTER_RECORDS.finding_types == {"two_machines_on_one_computer"}
    # A shared serial left after automatic merges is a clone or two machines:
    # never offered as a merge from the queue.
    assert "shared_serial" not in MERGE_COMPUTERS.finding_types
