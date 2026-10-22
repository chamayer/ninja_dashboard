from __future__ import annotations

from pathlib import Path

from apps.core import software_review as review

_VIEWS = (Path(__file__).resolve().parents[1] / "views.py").read_text(encoding="utf-8")


def _row(fid, type_name, title, publisher, *, devices=5, signals=(), suggestion="approve_title",
         severity="low"):
    details = {
        "canonical_name": title, "publisher": publisher, "fleet_device_count": devices,
        "client_count": 1, "signals": list(signals), "suggestion": suggestion,
    }
    scope = "device" if type_name == "rare_recent" else "global"
    return (fid, type_name, severity, details, None, scope)


def test_titles_keep_their_own_rows_inside_publisher_groups():
    groups = review.build_groups([
        _row("1", "whitelist_suggestion", "Acme Paint", "Acme"),
        _row("2", "rare_recent", "Acme Tool", "Acme", devices=1),
        _row("3", "whitelist_suggestion", "Solo", "Other"),
    ])
    assert [g["publisher"] for g in groups] == ["Acme", "Other"]  # most titles first
    assert {t["title"] for t in groups[0]["titles"]} == {"Acme Paint", "Acme Tool"}
    assert {t["type_label"] for t in groups[0]["titles"]} == {"Non-approved", "Rare"}


def test_a_concern_on_any_title_asks_for_title_review_before_the_publisher():
    groups = review.build_groups([
        _row("1", "whitelist_suggestion", "Clean", "Acme", suggestion="approve_publisher"),
        _row("2", "whitelist_suggestion", "Shady", "Acme", signals=["install_path"],
             suggestion="investigate"),
    ])
    assert groups[0]["suggestion"] == "review_titles"
    assert groups[0]["suggestion_label"] == "Review titles first (1 with concerns)"


def test_established_publisher_without_concerns_suggests_approving_it():
    groups = review.build_groups([
        _row("1", "whitelist_suggestion", "A", "Acme", suggestion="approve_publisher"),
        _row("2", "whitelist_suggestion", "B", "Acme", suggestion="approve_title"),
    ])
    assert groups[0]["suggestion"] == "approve_publisher"


def test_titles_without_a_publisher_cannot_be_approved_by_publisher():
    groups = review.build_groups([_row("1", "rare_recent", "Thing", "", devices=1)])
    assert groups[0]["suggestion"] == "decide_titles"


def test_filters_narrow_by_type_suggestion_and_text():
    rows = [
        _row("1", "whitelist_suggestion", "Alpha", "Acme"),
        _row("2", "rare_recent", "Beta", "Acme", devices=1, suggestion="investigate"),
    ]
    assert [t["title"] for g in review.build_groups(rows, kind="rare_recent") for t in g["titles"]] == ["Beta"]
    assert [t["title"] for g in review.build_groups(rows, suggestion="approve_title") for t in g["titles"]] == ["Alpha"]
    assert [t["title"] for g in review.build_groups(rows, query="alp") for t in g["titles"]] == ["Alpha"]


def test_pages_hold_whole_publisher_groups():
    items, page, pages = review.paginate(list(range(85)), 3, per_page=40)
    assert (items, page, pages) == ([80, 81, 82, 83, 84], 3, 3)
    assert review.paginate([], 5)[1:] == (1, 1)


class _Cursor:
    def __init__(self):
        self.calls = []
        self.rowcount = 2

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))


def test_a_title_decision_closes_its_prompts_and_a_publisher_decision_spares_concerns():
    cur = _Cursor()
    closed = review.resolve_decided_prompts(
        cur, tenant_id=1, canonical_names=["Acme Paint"], publishers=["Acme"],
        decision="approve_publisher", actor="admin", decided_at="2026-10-13T00:00:00Z",
    )
    assert closed == 4
    title_sql, title_params = cur.calls[0]
    assert "finding_type.name IN ('whitelist_suggestion', 'rare_recent')" in title_sql
    assert title_params["names"] == ["acme paint"]
    publisher_sql, publisher_params = cur.calls[1]
    assert "finding_type.name = 'rare_recent' AND COALESCE(jsonb_array_length(" in publisher_sql
    assert publisher_params["pubs"] == ["acme"]
    assert '"reason": "decision_recorded"' in publisher_params["resolution"]


def test_queue_and_decisions_use_the_review_module():
    body = _VIEWS[_VIEWS.index("def software_decisions_queue(") :]
    body = body[: body.index("\ndef ", 1)]
    assert "software_review.PROMPTS_SQL" in body
    assert "software_review.build_groups(" in body
    assert _VIEWS.count("software_review.resolve_decided_prompts(") == 2


def test_decision_writes_refresh_risk_view_only_after_commit():
    """A best-effort refresh must not abort the durable decision transaction."""
    bulk = _VIEWS[_VIEWS.index("def software_decision_bulk(") :]
    bulk = bulk[: bulk.index("\ndef ", 1)]
    create = _VIEWS[_VIEWS.index("def software_decision_create(") :]
    create = create[: create.index("\ndef ", 1)]

    for body in (bulk, create):
        assert "transaction.on_commit(_refresh_software_risk_matview)" in body
        assert "\n    _refresh_software_risk_matview()" not in body


def test_rare_limit_preview_splits_every_title_into_exactly_one_type():
    distribution = {1: 6000, 2: 3883, 3: 1800, 5: 1200, 10: 300}
    now = review.rare_limit_preview(distribution, 2, 2)
    assert (now["rare"], now["non_approved"], now["moves"]) == (9883, 3300, 0)
    raised = review.rare_limit_preview(distribution, 3, 2)
    assert (raised["rare"], raised["non_approved"]) == (11683, 1500)
    assert raised["moves"] == 1800 and raised["rare"] + raised["non_approved"] == raised["total"]
    lowered = review.rare_limit_preview(distribution, 1, 2)
    assert lowered["moves"] == 3883


def test_classifier_settings_page_embeds_the_preview():
    template = (Path(__file__).resolve().parents[3] / "templates" / "classifier_config.html").read_text(
        encoding="utf-8")
    assert 'id="rare-preview"' in template and 'json_script:"rare-distribution"' in template
    assert "Nothing changes until you save." in template
    assert "rare_distribution" in _VIEWS and "DEVICE_COUNTS_SQL" in _VIEWS


class _HoldCursor(_Cursor):
    def __init__(self, rows):
        super().__init__()
        self.rows = rows

    def fetchall(self):
        return self.rows


def test_an_approved_publisher_shows_its_status_and_why_each_title_is_still_open(monkeypatch):
    monkeypatch.setattr(review, "publisher_decisions", lambda tenant_id, keys: {
        "adobe inc.": {"global": {"decision": "approve_publisher", "label": "Approved",
                                  "approved": True, "decided_at": None, "decided_by": "op",
                                  "reason": "vendor"}, "narrower": 1},
    })
    groups = review.build_groups([
        _row("1", "whitelist_suggestion", "Bridge", "Adobe Inc.", suggestion="approve_publisher"),
        _row("2", "rare_recent", "Helper", "Adobe Inc.", devices=1, signals=["install_path"]),
        _row("3", "whitelist_suggestion", "Solo", "Other"),
    ])
    cur = _HoldCursor([
        ("bridge", 10, 1, 3, ["Adobe Systems Incorporated"]),
        ("helper", 1, 0, 0, None),
    ])
    review.attach_publisher_status(cur, 1, groups)
    adobe = next(g for g in groups if g["publisher"] == "Adobe Inc.")
    assert adobe["decision"]["label"] == "Approved" and adobe["narrower_decisions"] == 1
    assert sorted(adobe["open_title_names"]) == ["Bridge", "Helper"]
    assert adobe["suggestion"] == "decide_titles"
    titles = {t["title"]: t["hold_reasons"] for t in adobe["titles"]}
    assert titles["Bridge"] == [
        "publisher name differs on 3 of 10 installs (Adobe Systems Incorporated)",
        "no publisher on 1 of 10 installs",
    ]
    assert titles["Helper"] == ["rare with a concern, so the publisher approval does not cover it"]
    other = next(g for g in groups if g["publisher"] == "Other")
    assert "decision" not in other and "hold_reasons" not in other["titles"][0]
    assert cur.calls[0][1][0] == ["bridge", "helper"]


def test_a_title_with_no_remaining_cause_waits_for_the_next_check():
    title = {"type_name": "whitelist_suggestion", "signals": []}
    assert review.hold_reasons(title, 4, 0, 0, []) == [
        "covered now; closes on the next software check"
    ]


def test_publisher_status_filter_uses_the_publisher_wide_decision(monkeypatch):
    decisions = {
        "acme": {"global": {"decision": "approve_publisher"}, "narrower": 0},
        "beta": {"global": {"decision": "investigate"}, "narrower": 0},
        "gamma": {"global": None, "narrower": 2},
    }
    monkeypatch.setattr(review, "publisher_decisions", lambda tenant_id, keys: decisions)
    groups = review.build_groups(
        [
            _row("1", "whitelist_suggestion", "Acme Paint", "Acme"),
            _row("2", "whitelist_suggestion", "Beta Tool", "Beta"),
            _row("3", "whitelist_suggestion", "Gamma App", "Gamma"),
            _row("4", "whitelist_suggestion", "Loose", ""),
        ]
    )

    review.stamp_publisher_status(1, groups)

    def publishers(status):
        return [g["publisher"] for g in review.filter_by_publisher_status(groups, status)]

    assert publishers("approved") == ["Acme"]
    assert publishers("investigating") == ["Beta"]
    assert publishers("rejected") == []
    # Client or computer decisions are not publisher-wide; no publisher is "none".
    assert sorted(publishers("none")) == ["", "Gamma"]
    # Titles carry their publisher's status for the table view and export.
    acme = next(g for g in groups if g["publisher"] == "Acme")
    assert acme["titles"][0]["publisher_status_label"] == "Approved"
    # The column sorts across every group: approved first, no decision last.
    ordered = review.sort_groups(groups, "publisher_status", "asc")
    assert [g["publisher_status"] for g in ordered] == [
        "approved",
        "investigating",
        "none",
        "none",
    ]
    titles = review.sort_titles([t for g in groups for t in g["titles"]], "publisher_status", "asc")
    assert titles[0]["title"] == "Acme Paint"


def test_publisher_status_filter_runs_before_sorting_and_paging():
    section = _VIEWS[_VIEWS.index("def software_decisions_queue") :]
    for step in ("stamp_publisher_status", "filter_by_publisher_status"):
        assert section.index(step) < section.index("software_review.sort_groups(")
        assert section.index(step) < section.index("software_review.paginate(")
        assert section.index(step) < section.index("wants_csv(request)")


def test_publisher_status_is_its_own_sortable_filterable_column():
    template = (
        Path(__file__).resolve().parents[3] / "templates" / "software_decisions.html"
    ).read_text(encoding="utf-8")
    assert ("publisher_status", "Publisher status", False) in review.GROUP_COLUMNS
    assert ("publisher_status", "Publisher status", False) in review.SORT_COLUMNS
    assert 'class="status-pill {{ group.publisher_status }}"' in template
    assert template.count('{% include "_software_review_filter_cell.html" %}') == 2
    # Header labels are plain text (selectable); the header itself sorts.
    assert '<th data-sort-href="{{ col.href }}"' in template
    assert '<a href="{{ col.href }}">{{ col.label }}' not in template


def test_rows_count_only_the_uncovered_computers():
    details = {
        "canonical_name": "Microsoft.WindowsStore",
        "publisher": "",
        "title_publisher": "Microsoft Corporation",
        "fleet_device_count": 3917,
        "client_count": 40,
        "uncovered_device_count": 1,
        "uncovered_client_count": 1,
        "uncovered_publishers": [""],
        "uncovered_publisher_count": 1,
        "coverage_scope": "undecided",
        "suggestion": "none",
        "signals": [],
    }
    [group] = review.build_groups([("1", "rare_recent", "low", details, None, "device")])
    [title] = group["titles"]
    assert (title["devices"], title["clients"]) == (1, 1)
    assert (title["fleet_devices"], title["covered_devices"]) == (3917, 3916)
    assert title["uncovered_publishers"] == [""]
    # Grouped under the publisher the uncovered installation reports.
    assert group["publisher"] == ""


def test_prompts_written_before_coverage_counts_fall_back_to_fleet_counts():
    [group] = review.build_groups([_row("1", "whitelist_suggestion", "Old", "Acme", devices=7)])
    [title] = group["titles"]
    assert title["devices"] == 7 and title["covered_devices"] == 0


def test_rare_targets_list_only_computers_the_prompt_is_about():
    class Cursor:
        def execute(self, sql, params):
            assert "v_software_decision_keys" in sql

        def fetchall(self):
            return [
                ("store", "d1", "PC-1", "acme", "Acme", True, True),
                ("store", "d2", "PC-2", "acme", "Acme", False, True),
                ("store", "d3", "PC-3", "acme", "Acme", False, False),
            ]

    undecided = {"title": "Store", "devices": 1, "coverage_scope": "undecided"}
    title_open = {"title": "Store", "devices": 2, "coverage_scope": "title_open"}
    groups = [{"titles": [undecided, title_open]}]
    review.attach_device_targets(Cursor(), 1, groups, rare_limit=2)
    assert [t["hostname"] for t in undecided["device_targets"]] == ["PC-1"]
    assert [t["hostname"] for t in title_open["device_targets"]] == ["PC-1", "PC-2"]
