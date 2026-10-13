from pathlib import Path

from apps.core import views

_TEMPLATE = (
    Path(__file__).resolve().parents[3] / "templates" / "software_publishers.html"
).read_text(encoding="utf-8")


def test_actions_and_states_use_one_vocabulary():
    vocabulary = views._publisher_decision_vocabulary()
    assert [verb for _value, verb, _state, _key in vocabulary] == ["Approve", "Reject", "Investigate"]
    assert [state for _value, _verb, state, _key in vocabulary] == [
        "Approved", "Rejected", "Investigating",
    ]
    # A title-level approve is not a publisher action.
    assert "approve" not in [value for value, *_rest in vocabulary]


def test_row_buttons_match_the_bulk_and_filter_wording():
    for verb in ("Approve</button>", "Reject</button>", "Investigate</button>"):
        assert verb in _TEMPLATE
    for retired in (">Allow<", ">Block<", ">Review<", "No decision yet"):
        assert retired not in _TEMPLATE
    assert "{{ p.decision_label }}" in _TEMPLATE
    assert "{% for key, label in decision_filters %}" in _TEMPLATE


def test_the_publishers_page_still_requires_login():
    from django.contrib.auth.models import AnonymousUser
    from django.test import RequestFactory

    request = RequestFactory().get("/software/publishers/")
    request.user = AnonymousUser()
    response = views.software_publishers(request)
    assert response.status_code == 302
