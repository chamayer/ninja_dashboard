import pytest

from apps.core.views import (
    _dashboard_display_state,
    _dashboard_issue_state,
    _dashboard_priority,
)


@pytest.mark.parametrize(
    ("severity_counts", "expected"),
    [
        ({"critical": 1}, "needs_action"),
        ({"high": 1}, "review"),
        ({"medium": 2}, "monitor"),
        ({"low": 1}, "monitor"),
        ({}, "on_track"),
    ],
)
def test_dashboard_issue_state_uses_highest_operational_severity(severity_counts, expected):
    assert _dashboard_issue_state(severity_counts) == expected


def test_dashboard_delayed_data_never_appears_on_track():
    assert _dashboard_display_state("on_track", data_delayed=True) == "delayed"


def test_dashboard_delay_does_not_hide_known_action():
    assert _dashboard_display_state("needs_action", data_delayed=True) == "needs_action"


def test_dashboard_unavailable_data_is_distinct_from_health():
    assert _dashboard_display_state("on_track", has_data=False) == "unavailable"


def test_dashboard_priority_names_multiple_contributing_domains():
    domains = [
        {"name": "Patching", "issue_state": "needs_action"},
        {"name": "Compliance", "issue_state": "review"},
        {"name": "Software", "issue_state": "monitor"},
        {"name": "Inventory", "issue_state": "on_track"},
    ]

    assert _dashboard_priority(domains) == ("immediate", "Patching + 2 more areas")


def test_dashboard_priority_has_clear_no_concern_state():
    domains = [
        {"name": "Patching", "issue_state": "on_track"},
        {"name": "Compliance", "issue_state": "on_track"},
    ]

    assert _dashboard_priority(domains) == ("none", "")
