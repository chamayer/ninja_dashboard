from pathlib import Path

from apps.core import views

_VIEWS = (Path(__file__).resolve().parents[1] / "views.py").read_text(encoding="utf-8")
_TEMPLATE = (
    Path(__file__).resolve().parents[3] / "templates" / "findings_queue.html"
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


def test_sql_and_python_use_the_same_wording():
    """Issues sort and filter on the SQL text but show the Python text."""
    start = _VIEWS.index("WHEN finding_type_id IN (SELECT id FROM operations.finding_types WHERE name IN ('rare_recent', 'whitelist_suggestion'))")
    sql = _VIEWS[start:start + 1800]
    for fragment in ("' machine'", "' at '", "' clients'", "'first seen recently'",
                     "'suggested: '", "'signals: '", "replace(", "'undecided software'"):
        assert fragment in sql, fragment
    label_sql = views._suggestion_label_sql()
    for value, label in views.SoftwareSuggestionRule.Suggestion.choices:
        assert f"WHEN '{value}' THEN '{label}'" in label_sql
    assert "%" not in label_sql  # safe inside RawSQL


def test_rows_link_to_the_grouped_review_page_only_for_undecided_software():
    assert "publisher_review_url" in _TEMPLATE
    assert 'f.finding_type.name in ("rare_recent", "whitelist_suggestion")' in _VIEWS
