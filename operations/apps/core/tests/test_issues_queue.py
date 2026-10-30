"""PLAN-003 R3: one Issues selection contract, grouped queue and readiness removal."""

from __future__ import annotations

from pathlib import Path

from django.http import QueryDict

from apps.core import issue_selection, views

_VIEWS = Path("apps/core/views.py").read_text(encoding="utf-8")
_QUEUE = Path("templates/findings_queue.html").read_text(encoding="utf-8")
_ROWS = Path("templates/_issues_rows.html").read_text(encoding="utf-8")

CATEGORIES = [
    {
        "key": "inventory",
        "label": "Inventory",
        "categories": {"inventory", "Inventory"},
        "types": {"unmatched_source_group", "client_unattached_group", "device_offline"},
    },
]
GROUPS = {
    "client_mapping": {
        "value": "client_mapping",
        "label": "Client mapping",
        "category": "inventory",
        "types": {"unmatched_source_group", "client_unattached_group"},
        "issues": (),
    },
    "computers_offline": {
        "value": "computers_offline",
        "label": "Computers offline",
        "category": "inventory",
        "types": {"device_offline"},
        "issues": (),
    },
}


def _parse(query: str, session=None):
    return views._parse_issues_request(QueryDict(query), CATEGORIES, GROUPS, session)


def test_default_is_open_work_in_the_remembered_grouped_view():
    parsed = _parse("")
    assert parsed.base.status == "open"
    assert parsed.view == "severity"
    assert not parsed.explicit_taxonomy
    assert _parse("", {views._ISSUES_SESSION_VIEW: "flat"}).view == "flat"
    for legacy in ("active", "all", "acknowledged"):
        assert _parse(f"status={legacy}").base.status == "open"


def test_readiness_parameters_get_an_explicit_notice_not_an_equivalent():
    for query in ("attention=pending", "response=actionable", "covered=1"):
        parsed = _parse(query)
        assert parsed.notices == [views._RETIRED_READINESS_NOTICE]
        assert not parsed.base.invalid


def test_an_unknown_scope_selects_nothing_instead_of_everything():
    for query in (
        "type=retired_type",
        "category=nowhere",
        "severity=urgent",
        "type=client_mapping&issue=device_offline",
    ):
        parsed = _parse(query)
        assert parsed.base.invalid, query
        assert parsed.notices, query
    sql, _params = issue_selection._filtered_sql(issue_selection.Scope(invalid=True))
    assert "false" in sql


def test_a_finding_type_name_opens_that_issue_in_its_type():
    parsed = _parse("type=device_offline")
    assert (parsed.category, parsed.type, parsed.issue) == (
        "inventory",
        "computers_offline",
        "device_offline",
    )


def test_select_all_reselects_the_exact_group_never_its_parent():
    scope = views._issues_scope_from_query(
        "type=client_mapping&subgroup=critical&client=acme", CATEGORIES, GROUPS
    )
    assert scope.types == ("client_unattached_group", "unmatched_source_group")
    assert scope.severity == "critical"
    assert scope.client == "acme"
    # Without a group there is nothing to select all of.
    assert views._issues_scope_from_query("client=acme", CATEGORIES, GROUPS) is None


def test_filters_never_widen_and_computer_filters_drop_other_kinds():
    sql, _ = issue_selection._filtered_sql(issue_selection.Scope(os="Windows 11"))
    assert "i.subject_type = 'device' AND EXISTS" in sql
    sql, _ = issue_selection._filtered_sql(issue_selection.Scope(computer_type="tablet"))
    assert "false" in sql
    sql, _ = issue_selection._filtered_sql(issue_selection.Scope(subject_id="not-a-uuid"))
    assert "false" in sql
    sql, _ = issue_selection._filtered_sql(
        issue_selection.Scope(detail_key="Bad Key", detail_value="x")
    )
    assert "false" in sql


def test_counts_are_corrective_actions_with_covered_and_duplicate_records_excluded():
    sql, _ = issue_selection._filtered_sql(issue_selection.Scope())
    assert "WHEN 'unmatched_source_group' THEN 'source_group:'" in sql
    assert "WHEN 'client_unattached_group' THEN 'source_group:'" in sql
    assert "PARTITION BY action_key, status" in sql
    assert "action_rank = 1 AND NOT covered" in sql
    # Open and Paused are disjoint; candidates are only open work.
    items, _ = issue_selection._items_sql(issue_selection.Scope(status="paused"))
    assert "f.snoozed_until > now()" in items
    assert "entity_candidates" not in items
    items, _ = issue_selection._items_sql(issue_selection.Scope())
    assert "c.status = 'pending'" in items


def test_queue_has_no_readiness_controls_and_uses_open_paused_resolved():
    for removed in (
        'name="attention"',
        "Needs action",
        "Review by state",
        "Pending current",
        "fleet_summary_cards",
        "issues-column-filter",
    ):
        assert removed not in _QUEUE, removed
        assert removed not in _ROWS, removed
    assert "status_links" in _QUEUE
    assert "All clients, no filters:" in _QUEUE
    assert "Category → Type → Severity" in issue_selection.VIEW_LABELS.values()


def test_rows_render_beneath_the_open_header_with_review_and_related_issues():
    assert _QUEUE.count('{% include "_issues_rows.html" %}') == 4  # related, flat, type, severity
    assert "Related issues ({{ row.covered_count|add:row.other_records }})" in _ROWS
    assert '{{ row.review_label|default:"Review" }}' in _ROWS
    assert "Select all {{ total }} in this group" in _ROWS
    assert "data-server-table" in _ROWS
    for kept in (
        "finding_snooze",
        "finding_refresh",
        "openExcludeDialog",
        "Keep separate",
        "Archive in Hudu",
        "Hudu record:",
        "publisher_review_url",
    ):
        assert kept in _ROWS, kept
    for alert_action in ("finding_acknowledge", "finding_resolve"):
        assert alert_action not in _ROWS


def test_drilldown_scopes_are_explained():
    assert "Showing every device with this finding type" in _QUEUE
    assert "Filtered to the selected device." in _QUEUE


def test_bulk_pause_spans_kinds_after_permission_checks_and_remediation_needs_one_kind():
    bulk = _VIEWS[
        _VIEWS.index("def findings_bulk_action") : _VIEWS.index("def _retire_selected_computers")
    ]
    assert bulk.index("raise PermissionDenied") < bulk.index('if action in ("snooze", "resume")')
    assert "applies to one kind of issue at a time" in bulk
    assert "Finding.all_namespaces.filter(" in bulk
    assert "_issues_scope_from_query(scope_query" in bulk
    assert "_ISSUES_SELECT_ALL_LIMIT" in bulk


def test_home_mapping_count_and_link_share_one_selection():
    assert "client_mapping_conflict_count = issue_selection.count(mapping_scope)" in _VIEWS
    assert "issue_selection.mapping_query()" in _VIEWS
    query = issue_selection.mapping_query.__code__.co_consts
    assert "critical" in query and "open" in query
    home = Path("templates/home.html").read_text(encoding="utf-8")
    assert "Critical mapping issues ({{ client_mapping_conflict_count }})" in home
    assert "View all mapping issues" in home


def test_csv_shares_the_selection_and_keeps_lifecycle_context():
    queue = _VIEWS[
        _VIEWS.index("def findings_queue") : _VIEWS.index(
            "def _policy_candidate_state_action_blocked"
        )
    ]
    assert "issue_selection.items(export_scope" in queue
    for column in (
        '"Operating system"',
        '"OS release"',
        '"OS build"',
        '"Lifecycle cycle"',
        '"Security support ends"',
        '"Status"',
        '"Details"',
    ):
        assert column in _VIEWS
    assert '("Owner"' not in _VIEWS
