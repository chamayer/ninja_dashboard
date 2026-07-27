import pytest

from apps.core.client_workspace import _display_state, _issue_state


@pytest.mark.parametrize(
    ("severities", "expected"),
    [
        ({"critical": 1}, "needs_action"),
        ({"high": 1}, "review"),
        ({"medium": 1}, "monitor"),
        ({}, "on_track"),
    ],
)
def test_client_domain_state_uses_highest_issue_severity(severities, expected):
    assert _issue_state({"severities": severities}) == expected


def test_client_domain_never_hides_unavailable_data():
    assert _display_state({"severities": {}}, has_data=False) == (
        "unavailable",
        "Data unavailable",
    )


def test_client_domain_never_calls_delayed_data_on_track():
    assert _display_state({"severities": {}}, data_delayed=True) == (
        "delayed",
        "Data delayed",
    )


def test_known_problem_remains_visible_when_data_is_delayed():
    state = _display_state({"severities": {"critical": 1}}, data_delayed=True)
    assert state == ("needs_action", "Attention")


def test_known_problem_remains_visible_when_current_data_is_unavailable():
    state = _display_state({"severities": {"high": 1}}, has_data=False)
    assert state == ("review", "Watch")
