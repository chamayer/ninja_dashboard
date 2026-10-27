"""Cross-domain evidence boundaries required before sharing offline decisions."""

from datetime import timedelta
import uuid

import pytest

from ingest.computer_listing import Listing
from ingest.evaluator import _device_lifecycle_target, _select_lifecycle_evidence
from ingest.tests.test_evaluator_lifecycle import NOW, _row


def test_recent_collection_with_no_contact_does_not_establish_device_liveness():
    evidence, conflict = _select_lifecycle_evidence([
        _row(mode="direct_contact", contact_at=None, observed_at=NOW),
    ])
    assert evidence is None and conflict is False


def test_a_recent_explicit_offline_report_has_different_meaning_from_a_recent_fetch():
    evidence, conflict = _select_lifecycle_evidence([
        _row(mode="reported_state", reported_online=False,
             has_reported_online_state=True, observed_at=NOW),
    ])
    assert conflict is False
    assert evidence["status"] == "offline_aging"
    assert evidence["kind"] == "reported_state"


@pytest.mark.parametrize("flags,reason", [
    ({"documentation": True}, "documentation_only"),
    ({"stopped": True}, "stopped_vm_only"),
    ({"archived": True, "stopped": True}, "archived_still_listed"),
    ({}, "nothing_listed"),
    ({"in_use_confirmed": True}, "confirmed_in_use"),
])
def test_pending_cleanup_alone_does_not_identify_an_offline_contact_condition(flags, reason):
    values = dict(device_id=uuid.uuid4(), client_id=uuid.uuid4(),
                  lifecycle_status="pending_cleanup", evidence=False, reporting=False,
                  documentation=False, archived=False, stopped=False,
                  last_seen_at=NOW - timedelta(days=1), last_source=None)
    values.update(flags)
    listing = Listing(**values)
    assert listing.state(NOW, 30) == reason


@pytest.mark.parametrize("age,expected", [(7, "active"), (8, "active"), (11, "offline_aging")])
def test_client_offline_override_is_part_of_the_authoritative_decision(age, expected):
    client = uuid.uuid4()
    assert _device_lifecycle_target(
        {"client_id": client},
        {"status": "active", "at": NOW - timedelta(days=age)},
        NOW, 7, 30, {str(client): 10},
    ) == expected


def test_conflicting_current_reports_cannot_validate_an_old_lifecycle_label():
    evidence, conflict = _select_lifecycle_evidence([
        _row(mode="reported_state", reported_online=True, has_reported_online_state=True),
        _row(mode="reported_state", reported_online=False, has_reported_online_state=True),
    ])
    assert evidence is None and conflict is True
