"""Decision helper display and the editable required signals."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from apps.core import software_policy, software_review
from apps.core.models import SoftwareSuggestionRule

_ROOT = Path(__file__).resolve().parents[3]
_MIGRATION = (_ROOT / "apps" / "core" / "migrations" / "0292_software_routine_helper.py").read_text(
    encoding="utf-8"
)


def test_evidence_is_shown_in_plain_words_and_unknown_codes_are_readable():
    details = {"evidence": ["known_vendor", "established_publisher", "new_thing", 7]}
    assert software_review.evidence_labels(details) == [
        "known vendor",
        "established publisher",
        "new thing",
    ]
    assert software_review.evidence_labels({}) == []


def test_a_group_of_routine_titles_is_labeled_routine():
    row = (
        "f1",
        "whitelist_suggestion",
        "low",
        {
            "canonical_name": "Foo",
            "publisher": "Acme",
            "fleet_device_count": 9,
            "suggestion": "supports_approval",
            "evidence": ["known_vendor"],
        },
        None,
        "global",
    )
    (group,) = software_review.build_groups([row])
    assert group["suggestion"] == "supports_approval"
    assert group["titles"][0]["evidence"] == ["known vendor"]


def test_choices_include_the_new_signals_and_suggestion():
    assert "known_vendor" in SoftwareSuggestionRule.Signal.values
    assert "publisher_approved" in SoftwareSuggestionRule.Signal.values
    assert "supports_approval" in SoftwareSuggestionRule.Suggestion.values


def _rule(signal="known_vendor"):
    saved = []
    rule = SimpleNamespace(
        id=1, priority=55, signal=signal, adverse=False, suggestion="supports_approval",
        enabled=True, requires=[], save=lambda update_fields: saved.append(update_fields),
    )
    return rule, saved


def _update(monkeypatch, rule, post):
    monkeypatch.setattr(software_policy, "get_object_or_404", lambda *_a, **_k: rule)
    monkeypatch.setattr(software_policy, "_audit", lambda *_a, **_k: None)
    request = SimpleNamespace(POST={"rule_id": "1", "priority": "55", **post})
    return software_policy._update_suggestion(request)


def test_required_signals_are_validated_and_saved(monkeypatch):
    rule, saved = _rule()
    assert _update(monkeypatch, rule, {"suggestion": "supports_approval", "requires": "established_publisher, prevalent"}) == ""
    assert rule.requires == ["established_publisher", "prevalent"]
    assert "requires" in saved[0]


def test_unknown_or_self_required_signal_is_refused(monkeypatch):
    rule, _ = _rule()
    assert "Unknown required signal" in _update(
        monkeypatch, rule, {"suggestion": "supports_approval", "requires": "made_up"}
    )
    assert "cannot require its own" in _update(
        monkeypatch, rule, {"suggestion": "supports_approval", "requires": "known_vendor"}
    )


def test_migration_adds_the_helper_rules_and_disables_popularity_rules():
    assert "'supports_approval'" in _MIGRATION
    assert '"established_publisher"' in _MIGRATION
    assert "SET enabled = FALSE" in _MIGRATION
    assert "'established_publisher', 'prevalent'" in _MIGRATION
    assert "0291_finding_type_alertable" in _MIGRATION


def test_review_page_survives_a_finding_with_no_title():
    template = (_ROOT / "templates" / "_software_review_row.html").read_text(encoding="utf-8")
    assert "{% if t.title %}<a href=\"{% url 'software_detail' name=t.title %}\">" in template
    assert "(no title recorded)" in template


def test_review_groups_read_details_that_arrive_as_json_text():
    # Django's raw cursor returns jsonb as text; this is what production sends.
    details = (
        '{"canonical_name": "Foo", "publisher": "Acme", "fleet_device_count": 9, '
        '"suggestion": "supports_approval", "evidence": ["known_vendor"]}'
    )
    (group,) = software_review.build_groups(
        [("f1", "whitelist_suggestion", "low", details, None, "global")]
    )
    assert group["titles"][0]["title"] == "Foo"
    assert group["titles"][0]["devices"] == 9
    assert group["titles"][0]["evidence"] == ["known vendor"]
    assert software_review._details("not json") == {}
    assert software_review._details("[1]") == {}


def _t(title, publisher="", devices=1, clients=1, signals=(), label="Rare", severity="low", suggestion="None"):
    return {
        "title": title, "publisher": publisher, "devices": devices, "clients": clients,
        "signals": list(signals), "type_label": label, "severity": severity,
        "suggestion_label": suggestion,
    }


def test_every_column_sorts_the_whole_table_in_both_directions():
    rows = [
        _t("b", "Zed", 5, 2, ["x"], "Rare", "high", "Investigate"),
        _t("a", "", 9, 1, [], "Non-approved", "low", "No suggestion"),
        _t("c", "Acme", 1, 7, ["x", "y"], "Rare", "low", "Supports approval"),
    ]
    first = lambda key, d: [t["title"] for t in software_review.sort_titles(rows, key, d)]  # noqa: E731
    assert first("title", "asc") == ["a", "b", "c"]
    assert first("title", "desc") == ["c", "b", "a"]
    assert first("devices", "desc") == ["a", "b", "c"]
    assert first("clients", "desc") == ["c", "b", "a"]
    assert first("publisher", "asc") == ["c", "b", "a"]  # blank publisher last
    assert first("signals", "desc") == ["c", "b", "a"]
    assert first("suggestion", "asc") == ["b", "a", "c"]
    assert first("type", "asc")[0] == "a"  # Non-approved before Rare
    assert first("not_a_column", "asc") == first("devices", "desc")


def test_flat_table_has_sortable_headers_and_a_toggle_to_group_by_publisher():
    template = (_ROOT / "templates" / "software_decisions.html").read_text(encoding="utf-8")
    row = (_ROOT / "templates" / "_software_review_row.html").read_text(encoding="utf-8")
    assert '<a href="{{ col.href }}">{{ col.label }}{{ col.mark }}</a>' in template
    assert "Group by publisher" in template and "Show as one sortable table" in template
    assert '{% include "_software_review_row.html"' in template
    # An included template does not inherit the parent's {% load %}.
    assert row.lstrip().startswith("{% load human_labels %}")


def _g(publisher, titles, devices, clients, concerns, suggestion="No suggestion"):
    return {
        "publisher": publisher, "titles": [{"title": f"t{i}"} for i in range(titles)],
        "devices": devices, "clients": clients, "concerns": concerns,
        "suggestion_label": suggestion,
    }


def test_publisher_rows_sort_by_every_total():
    groups = [_g("Zed", 3, 10, 5, 0), _g("Acme", 9, 4, 2, 3, "Investigate"), _g("", 1, 50, 9, 1)]
    order = lambda k, d: [g["publisher"] for g in software_review.sort_groups(groups, k, d)]  # noqa: E731
    assert order("titles", "desc") == ["Acme", "Zed", ""]
    assert order("installs", "desc") == ["", "Zed", "Acme"]
    assert order("clients", "desc") == ["", "Zed", "Acme"]
    assert order("flagged", "desc") == ["Acme", "", "Zed"]
    assert order("publisher", "asc") == ["Acme", "Zed", ""]  # no publisher last
    assert order("suggestion", "asc")[0] == "Acme"  # Investigate sorts before No suggestion
    assert order("nope", "asc") == order("titles", "desc")


def test_group_clients_total_is_the_widest_title():
    rows = [
        ("a", "whitelist_suggestion", "low", {"canonical_name": "A", "publisher": "P", "fleet_device_count": 3, "client_count": 2}, None, "global"),
        ("b", "whitelist_suggestion", "low", {"canonical_name": "B", "publisher": "P", "fleet_device_count": 4, "client_count": 7}, None, "global"),
    ]
    (group,) = software_review.build_groups(rows)
    assert group["clients"] == 7 and group["devices"] == 7 and len(group["titles"]) == 2


def test_titles_under_a_publisher_are_capped_but_counted():
    big = _g("Big", software_review.GROUP_TITLES_SHOWN + 20, 1, 1, 0)
    (trimmed,) = software_review.trim_group_titles([big])
    assert len(trimmed["titles"]) == software_review.GROUP_TITLES_SHOWN
    assert trimmed["title_count"] == software_review.GROUP_TITLES_SHOWN + 20
    template = (_ROOT / "templates" / "software_decisions.html").read_text(encoding="utf-8")
    assert "See every title of this publisher as a table" in template
    assert 'id="sw-review-publishers"' in template


def test_titles_under_each_publisher_are_sortable_and_keep_their_publisher_open():
    template = (_ROOT / "templates" / "software_decisions.html").read_text(encoding="utf-8")
    views = (_ROOT / "apps" / "core" / "views.py").read_text(encoding="utf-8")
    # Sub-table headers are links that carry the publisher anchor ...
    assert '{% for col in title_columns %}' in template
    assert '<a href="{{ col.href }}#pub-{{ group.publisher|slugify }}">' in template
    # ... the page reopens that publisher after the reload ...
    assert 'id="pub-{{ group.publisher|slugify }}"' in template
    assert "location.hash.indexOf('#pub-') === 0" in template
    # ... and the sort is applied before the 50-title cap, so the shown titles are
    # the first in the chosen order.
    sort_at = views.index("title_sort, title_dir")
    trim_at = views.index("page_groups = software_review.trim_group_titles(page_groups)")
    assert sort_at < trim_at
