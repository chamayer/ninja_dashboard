from pathlib import Path

from apps.core import views

_VIEWS = (Path(__file__).resolve().parents[1] / "views.py").read_text(encoding="utf-8")
_TEMPLATE = (
    Path(__file__).resolve().parents[3] / "templates" / "_issues_rows.html"
).read_text(encoding="utf-8")


def test_the_context_line_names_title_publisher_scale_suggestion_and_signals():
    text = views._software_review_context({
        "canonical_name": "Acme Tool", "publisher": "Acme Corp", "fleet_device_count": 14,
        "client_count": 3, "recent": True, "suggestion": "investigate",
        "signals": ["install_path", "junk_publisher"],
    })
    assert text == (
        "Acme Tool · Acme Corp · on 14 machines at 3 clients · first seen recently · "
        "suggested: Investigate · signals: install path, junk publisher"
    )


def test_a_quiet_single_install_has_no_suggestion_or_signals():
    assert views._software_review_context({
        "canonical_name": "Solo", "publisher": "", "fleet_device_count": 1,
        "client_count": 1, "suggestion": "none", "signals": [],
    }) == "Solo · on 1 machine"
    assert views._software_review_context({}) == "undecided software"


def test_the_context_line_counts_only_uncovered_machines():
    """Microsoft Store: decided on 3,916 computers, one install has no publisher."""
    text = views._software_review_context({
        "canonical_name": "Microsoft.WindowsStore", "publisher": "",
        "title_publisher": "Microsoft Corporation", "fleet_device_count": 3917,
        "client_count": 40, "uncovered_device_count": 1, "uncovered_client_count": 1,
        "suggestion": "none", "signals": [],
    })
    assert text == "Microsoft.WindowsStore · on 1 machine (3917 in the fleet)"


def test_rows_link_to_the_grouped_review_page_only_for_undecided_software():
    assert "publisher_review_url" in _TEMPLATE
    assert 'f.finding_type.name in ("rare_recent", "whitelist_suggestion")' in _VIEWS
