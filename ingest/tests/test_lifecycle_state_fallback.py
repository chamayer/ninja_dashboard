"""Explicit state fallback never displaces contact or invents absence duration."""

from datetime import timedelta

import pytest

from ingest.evaluator import _lifecycle_target, _select_lifecycle_evidence
from ingest.tests.test_evaluator_lifecycle import NOW, _row

MODE = "direct_contact_state_fallback"


@pytest.mark.parametrize(
    "online,expected", [(True, "active"), (False, "offline_aging")]
)
def test_explicit_state_is_used_only_under_the_opted_in_mode(online, expected):
    row = _row(mode=MODE, reported_online=online, has_reported_online_state=True)
    evidence, conflict = _select_lifecycle_evidence([row])
    assert not conflict and evidence["status"] == expected
    assert evidence["kind"] == "reported_state"
    row["mode"] = "direct_contact"
    assert _select_lifecycle_evidence([row]) == (None, False)


@pytest.mark.parametrize("contact_mode", [MODE, "direct_contact"])
def test_new_report_cannot_displace_aged_contact_from_any_source(contact_mode):
    direct = _row(mode=contact_mode, contact_at=NOW - timedelta(days=45))
    report = _row(
        mode=MODE,
        platform="ScreenConnect",
        reported_online=True,
        has_reported_online_state=True,
    )
    evidence, conflict = _select_lifecycle_evidence([direct, report])
    assert not conflict and evidence["kind"] == "direct_contact"
    assert _lifecycle_target(evidence, NOW, 7, 30) == "pending_cleanup"


def test_contactless_poll_without_explicit_state_has_no_authority():
    assert _select_lifecycle_evidence([_row(mode=MODE)]) == (None, False)


def test_unknown_and_equal_time_conflicting_reports_remain_uncertain():
    unknown = _row(mode=MODE, power_state="unknown", has_power_state=True)
    assert _select_lifecycle_evidence([unknown]) == (None, False)
    online = _row(mode=MODE, reported_online=True, has_reported_online_state=True)
    offline = _row(mode=MODE, reported_online=False, has_reported_online_state=True)
    assert _select_lifecycle_evidence([online, offline]) == (None, True)


def test_even_an_aged_negative_report_does_not_measure_offline_duration():
    evidence, _ = _select_lifecycle_evidence(
        [
            _row(
                mode=MODE,
                observed_at=NOW - timedelta(days=60),
                reported_online=False,
                has_reported_online_state=True,
            ),
        ]
    )
    assert evidence["duration_unknown"] is True
    assert _lifecycle_target(evidence, NOW, 7, 30) == "offline_aging"


def test_existing_hybrid_mode_keeps_newest_evidence_semantics():
    evidence, _ = _select_lifecycle_evidence(
        [
            _row(
                mode="direct_then_reported_state",
                contact_at=NOW - timedelta(days=45),
                reported_online=True,
                has_reported_online_state=True,
            ),
        ]
    )
    assert evidence["kind"] == "reported_state" and evidence["status"] == "active"
