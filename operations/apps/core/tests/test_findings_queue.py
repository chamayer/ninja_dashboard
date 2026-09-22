from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs

import pytest
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from django.template.loader import get_template

from apps.core import views
from apps.core.conditions.operator import operator_guidance, operator_state
from apps.core.finding_actions import (
    ARCHIVE_HUDU_ASSETS,
    BULK_RETIRE_COMPUTERS,
    available_finding_actions,
)
from apps.core.templatetags.human_labels import finding_drilldown_query


def test_finding_type_groups_preserve_category_order_and_other_bucket():
    categories = [
        SimpleNamespace(id=2, name="software"),
        SimpleNamespace(id=1, name="lifecycle"),
    ]
    finding_types = [
        SimpleNamespace(category_id=1, name="windows_servicing_eol"),
        SimpleNamespace(category_id=2, name="vulnerable_software"),
        SimpleNamespace(category_id=None, name="legacy_finding"),
    ]

    assert views._finding_type_groups(categories, finding_types) == [
        {
            "label": "software",
            "types": [SimpleNamespace(category_id=2, name="vulnerable_software")],
        },
        {
            "label": "lifecycle",
            "types": [SimpleNamespace(category_id=1, name="windows_servicing_eol")],
        },
        {
            "label": "Other",
            "types": [SimpleNamespace(category_id=None, name="legacy_finding")],
        },
    ]


class _Cursor:
    def __init__(self):
        self.statement = ""
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params):
        self.statement = statement
        self.params = params

    def fetchall(self):
        return [
            (
                "device-1",
                "host-1",
                "Client A",
                "Windows 11 Pro",
                "23H2",
                "22631",
                ["windows_servicing_eol"],
            )
        ]


class _Connection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


class _Compiler:
    def as_sql(self):
        return "SELECT id FROM filtered_findings WHERE status = %s", ("open",)


class _Query:
    def get_compiler(self, *, connection):
        return _Compiler()


class _Findings:
    query = _Query()

    def order_by(self):
        return self

    def values(self, *_fields):
        return self


def test_affected_device_rows_uses_one_filtered_finding_set(monkeypatch):
    cursor = _Cursor()
    monkeypatch.setattr(views, "connection", _Connection(cursor))

    rows = views._affected_device_rows(_Findings())

    assert "WITH matching AS (SELECT id FROM filtered_findings" in cursor.statement
    assert "operations.v_device_software_exposure" in cursor.statement
    assert cursor.params == ("open",)
    assert rows == [
        {
            "device_id": "device-1",
            "hostname": "host-1",
            "client": "Client A",
            "os_name": "Windows 11 Pro",
            "os_release_id": "23H2",
            "os_build_number": "22631",
            "finding_types": ["windows_servicing_eol"],
        }
    ]


def test_findings_queue_template_exposes_device_csv_and_grouped_types():
    template = Path("templates/findings_queue.html").read_text(encoding="utf-8")
    source = Path("apps/core/views.py").read_text(encoding="utf-8")

    assert "fleet_summary_cards" in template
    for label in ("Unresolved", "Needs action", "Blocked", "Pending", "Paused", "Software decisions"):
        assert label in source
    assert "format=devices_csv" in template
    assert "Issues CSV" in template
    assert "Shown issues CSV" not in template
    assert 'value="{{ group.value }}"' in template
    assert "<optgroup" not in template
    assert "Selected actions" in template
    assert "bulk-action" in template
    assert "table_finding" in template
    assert "sort_links.finding" in template
    assert "issues-group-navigation" in template
    assert "Issues summary" in template
    assert "Filtered results" in template
    assert "issues-column-filter" in template
    assert "Clear column filters" in template
    assert "More filters" in template
    assert "issues-results-intro" in template
    assert "current_result_summary" in template
    assert '<select name="issue" id="issues-issue-filter">' in template
    assert "issue_choices" in template
    assert "issues-type-link" in template
    assert "json_script:\"issue-taxonomy-data\"" in template
    assert "card.count }} / {{ card.total" not in template
    assert "card.percentage" not in template
    assert "action.label" in template
    assert "Why take this action?" in template
    assert "action.confirmation" in template
    assert "Archive in Hudu" in template
    assert "Hudu record:" in template
    assert "archiveHuduRow" in template


def test_operator_projection_uses_operator_vocabulary_and_short_reasons():
    now = datetime(2026, 9, 18, tzinfo=UTC)
    assert operator_state(
        status="open",
        snoozed_until=None,
        assessment={"disposition": "complete", "may_execute": True},
        now=now,
    ) == {"status": "active", "attention": "needs_action", "reason": "Ready for action"}
    assert operator_state(
        status="open",
        snoozed_until=None,
        assessment={"disposition": "blocked", "blockers": ["offline:extended_absence"]},
        now=now,
    ) == {"status": "active", "attention": "blocked", "reason": "Computer offline"}
    assert operator_state(
        status="open",
        snoozed_until=now + timedelta(hours=1),
        assessment=None,
        now=now,
    ) == {"status": "paused", "attention": "paused", "reason": "Paused by operator"}
    assert operator_guidance(
        attention="blocked", reason="Identity unresolved"
    ) == {"owner": "Operator", "next_step": "Review identity", "route": "subject"}
    assert operator_guidance(
        attention="pending", reason="Patch data incomplete"
    ) == {"owner": "Integration", "next_step": "Review patch collection", "route": "patch"}


def test_findings_group_summaries_are_computed_before_screen_cap():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    assert source.index("issue_group_headers =") < source.index("paginator = Paginator(findings_with_detail")
    assert "actionable_qs[:500]" not in source


def test_database_page_replaces_raw_findings_with_display_rows():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    assert "database_page.object_list = findings_with_detail" in source


def test_collapsed_queue_skips_affected_device_rollup_until_a_type_is_opened():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")

    assert 'needs_affected_devices = show_finding_rows or request.GET.get("format") == "devices_csv"' in source
    assert "_affected_device_rows(matching_qs) if needs_affected_devices else []" in source


def test_filtered_issue_queue_reuses_the_fleet_operator_state_projection():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")

    assert "fleet_states = _condition_operator_states(fleet_ids)" in source
    assert "if governed_id_keys.issubset(fleet_id_keys)" in source
    assert "{finding_id: fleet_states[finding_id] for finding_id in governed_id_keys}" in source


def test_issue_work_status_uses_one_operator_label_without_a_repeated_reason():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    template = Path("templates/findings_queue.html").read_text(encoding="utf-8")

    assert 'row["work_status_label"]' in source
    assert 'row["operator_status_note"]' in source
    assert '("Work status", "work_status_label")' in source
    assert '>Work status</a>' in template
    assert '{{ row.work_status_label }}' in template
    assert '{{ row.operator_attention|humanize_label }}' not in template


def test_expanded_type_state_links_are_stacked_for_scanning():
    template = Path("templates/findings_queue.html").read_text(encoding="utf-8")

    assert ".issues-type-group { min-width:0; }" in template
    assert ".issues-type-link > span { min-width:0; overflow:hidden; text-overflow:ellipsis; }" in template
    assert ".issues-state-links { display:grid;" in template
    assert ".issues-state-links a { display:block; }" in template


class _FindingActionUser:
    is_authenticated = True

    def __init__(self, *, may_manage_lifecycle: bool, may_manage_sources: bool = False) -> None:
        self.is_superuser = False
        self._may_manage_lifecycle = may_manage_lifecycle
        self._may_manage_sources = may_manage_sources

    def has_perm(self, permission: str) -> bool:
        return (
            permission == "operations.manage_lifecycle" and self._may_manage_lifecycle
        ) or (permission == "operations.manage_sources" and self._may_manage_sources)


def test_registered_retirement_action_requires_lifecycle_permission():
    assert available_finding_actions(_FindingActionUser(may_manage_lifecycle=False)) == ()
    assert available_finding_actions(_FindingActionUser(may_manage_lifecycle=True)) == (
        BULK_RETIRE_COMPUTERS,
    )


def test_hudu_archive_action_requires_source_management_permission():
    assert available_finding_actions(
        _FindingActionUser(may_manage_lifecycle=False, may_manage_sources=True)
    ) == (ARCHIVE_HUDU_ASSETS,)


def test_bulk_retirement_fails_closed_without_lifecycle_permission():
    request = RequestFactory().post(
        "/findings/bulk/",
        {"ids": "7e0ae011-9b4e-4a8b-9a74-7c13f7b61123", "action": "retire_computers"},
    )
    request.user = _FindingActionUser(may_manage_lifecycle=False)

    with pytest.raises(PermissionDenied):
        views.findings_bulk_action(request)


def test_findings_scope_cards_compare_filtered_counts_with_labeled_baselines():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")

    assert "fleet_governed_qs" in source
    assert "fleet_policy_qs" in source
    assert "current_result_summary" in source
    assert '"total_label": total_label' not in source


def test_software_policy_candidates_are_not_managed_as_incidents():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")

    assert views._SOFTWARE_POLICY_CANDIDATE_TYPES == ("whitelist_suggestion",)
    assert 'qs = qs.exclude(finding_type__name__in=_SOFTWARE_POLICY_CANDIDATE_TYPES)' in source
    assert "actionable_qs" in source
    assert "_policy_candidate_state_action_blocked" in source
    assert "Skipped {policy_count} software policy candidate" in source


def test_findings_queue_csv_includes_windows_servicing_context():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")

    assert '"Operating system"' in source
    assert '"OS release"' in source
    assert '"OS build"' in source
    assert '"Lifecycle cycle"' in source
    assert '"Security support ends"' in source


def test_registered_evidence_group_drilldown_opens_the_full_group():
    finding = SimpleNamespace(
        finding_type=SimpleNamespace(
            name="cross_client_serial", drilldown_evidence_key="serial"
        ),
        finding_details={"serial": "AB 123"},
    )

    assert parse_qs(finding_drilldown_query(finding, "device-1")) == {
        "type": ["cross_client_serial"],
        "status": ["all"],
        "group_key": ["serial"],
        "group_value": ["AB 123"],
    }


def test_unregistered_evidence_group_preserves_device_drilldown():
    finding = SimpleNamespace(
        finding_type=SimpleNamespace(name="device_offline", drilldown_evidence_key=""),
        finding_details={},
    )

    assert parse_qs(finding_drilldown_query(finding, "device-1")) == {
        "type": ["device_offline"],
        "status": ["all"],
        "subject_id": ["device-1"],
    }


def test_finding_group_filter_requires_the_registry_key():
    assert views._finding_group_lookup(
        finding_type_name="cross_client_serial",
        configured_key="serial",
        requested_key="serial",
        requested_value="AB 123",
    ) == {"finding_details__serial__iexact": "AB 123"}
    assert (
        views._finding_group_lookup(
            finding_type_name="cross_client_serial",
            configured_key="serial",
            requested_key="client_ids",
            requested_value="AB 123",
        )
        is None
    )


def test_device_and_issues_templates_explain_the_drilldown_scope():
    device_template = Path("templates/device_detail.html").read_text(encoding="utf-8")
    findings_template = Path("templates/findings_queue.html").read_text(encoding="utf-8")

    assert "{% finding_drilldown_query f device.id %}" in device_template
    assert "Showing every device with this finding type" in findings_template
    assert "Filtered to the selected device." in findings_template


def test_findings_queue_exposes_governed_response_filter():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    template = Path("templates/findings_queue.html").read_text(encoding="utf-8")
    for value in ("actionable", "blocked", "pending", "paused", "all"):
        assert value in source
    assert 'name="attention"' in template
    assert "_condition_operator_states" in source
    assert "condition_participants" in source
    assert '"Work status"' in source
    assert '"Reason"' in source
    assert "Policy:" not in template
    assert "row.assessment" not in template
    assert "finding_reviewed_distinct" in template
    assert "Reviewed distinct" in template
    assert "category_tiles" not in template


def test_findings_queue_canonicalizes_legacy_category_urls():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    assert "requested_category_filter = category_filter" in source
    assert 'params["category"] = category_filter' in source
    assert "reverse('findings_queue')}?{params.urlencode()" in source


def test_findings_queue_retains_offline_evidence_for_explicit_review():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    assert "Retained findings stay discoverable even when their device is offline" in source
    assert "status_scope_qs = status_scope_qs.exclude(coalesced_offline_q)" not in source
    assert "qs = qs.exclude(coalesced_offline_q)" not in source


def test_findings_queue_summary_cards_use_fleet_wide_operator_counts():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    template = Path("templates/findings_queue.html").read_text(encoding="utf-8")
    assert "fleet_governed_qs = Finding.objects.filter" in source
    assert "fleet_id_keys = {str(finding_id) for finding_id in fleet_ids}" in source
    assert "fleet_states = _condition_operator_states(fleet_ids)" in source
    assert "if governed_id_keys.issubset(fleet_id_keys)" in source
    assert '"label": "Pending"' in source
    assert "Review by state" in template
    assert "operator_owner" in source
    assert "operator_next_step" in source


def test_issue_categories_are_collapsed_until_a_drilldown_is_selected():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    template = Path("templates/findings_queue.html").read_text(encoding="utf-8")
    assert '"expanded": bool(' in source
    assert ".issues-type-link" in template
    assert "white-space:nowrap" in template
    assert '<details class="issues-category-group"{% if category.expanded %} open{% endif %}>' in template


def test_findings_queue_csv_projects_labels_before_export_and_has_one_owner_column():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    queue = source[source.index("def findings_queue"):source.index("def _policy_candidate_state_action_blocked")]
    assert queue.index('row["issue_label"]') < queue.index('if request.GET.get("format") == "csv"')
    csv_section = queue[queue.index("def _findings_csv_response"):queue.index("# Keep these getters", queue.index("def _findings_csv_response"))]
    assert csv_section.count('(\"Owner\"') == 1
    assert queue.index("return _findings_csv_response()") > queue.index("findings_with_detail = [")
    assert queue.index('if request.GET.get("format") == "csv"') < queue.index(
        "affected_devices = _affected_device_rows"
    )


def test_database_queue_projection_covers_rendered_evidence_context_and_subject_overrides():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    queue = source[source.index("def findings_queue"):source.index("def _policy_candidate_state_action_blocked")]

    # Every special Evidence renderer needs a matching database expression so
    # column filters and sorting operate on what the operator actually sees.
    for finding_type in (
        "device_source_record_withdrawn",
        "device_missing_from_source",
        "device_offline",
        "identity_conflict",
        "cmdb_asset_stale",
        "cross_client_serial",
        "windows_servicing_%",
        "vulnerable_software",
        "known_malicious_hint",
    ):
        assert finding_type in queue

    assert "operations.device_windows_servicing_current" in queue
    assert "operations.device_session_current" in queue
    assert "COALESCE(\n                       finding_details->>'hostname'," in queue
    assert "database_qs = actionable_qs" in queue
    assert '**{f"rendered_{key}": database_annotations[f"rendered_{key}"]}' in queue
    assert 'f"rendered_{key}__icontains"' in queue


def test_database_evidence_projection_escapes_psycopg_percent_literals():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    queue = source[source.index("def findings_queue"):source.index("def _policy_candidate_state_action_blocked")]
    assert "LIKE 'windows_servicing_%%'" in queue
    assert "LIKE 'windows_servicing_%%_eol'" in queue
    assert "LIKE 'windows_servicing_%'" not in queue


def test_database_evidence_projection_parenthesizes_json_text_before_concatenation():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    queue = source[source.index("def findings_queue"):source.index("def _policy_candidate_state_action_blocked")]
    assert "|| finding_details->>" not in queue


def test_admin_health_is_admin_only():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    assert "@require_admin" in source[source.rfind("@login_required", 0, source.index("def findings_admin_health")):source.index("def findings_admin_health")]
    assert "condition_participants" in source[source.index("def _condition_coverage_summary"):source.index("def admin_finding_acknowledge")]


def test_findings_queue_does_not_substitute_packaged_taxonomy():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    taxonomy_section = source[source.index("def _issue_taxonomy"):source.index("def _condition_assessment_display")]
    assert "load_profile" not in taxonomy_section
    assert "issue_taxonomy" in taxonomy_section


def test_condition_reasons_are_humanized_in_evidence_surfaces():
    queue = Path("templates/findings_queue.html").read_text(encoding="utf-8")
    admin = Path("templates/findings_admin_health.html").read_text(encoding="utf-8")
    device = Path("templates/device_detail.html").read_text(encoding="utf-8")
    assert queue.count("|humanize_label") >= 1
    assert admin.count("|humanize_label") >= 2
    assert "blocker|humanize_label" in device


def test_human_label_filter_formats_scoped_condition_reasons():
    source = Path("apps/core/templatetags/human_labels.py").read_text(encoding="utf-8")
    assert 'key.split(":", 1)' in source
    assert "suffix.replace('_', ' ')" in source


def test_condition_response_reads_are_batched():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    assert "for offset in range(0, len(candidate_ids), 1000)" in source
    assert "candidate_ids = [finding_id for finding_id in ids if finding_id in assessed_ids]" in source
    assert "batch = candidate_ids[offset:offset + 1000]" in source
    assert "finding_id for finding_id in ids if finding_id not in assessed_ids" in source
    assert "[batch, batch]" in source


def test_operator_state_uses_an_id_index_for_critical_priority():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    section = source[source.index("def _condition_operator_states"):source.index("def _operator_issue_type_groups")]
    assert 'row_by_id = {str(row["id"]): row for row in rows}' in section
    assert 'row_by_id[key]["severity"]' in section
    assert 'next((row["severity"] for row in rows' not in section


def test_findings_queue_template_compiles():
    get_template("findings_queue.html")


def test_device_surface_exposes_governed_response_state():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    template = Path("templates/device_detail.html").read_text(encoding="utf-8")
    assert "_condition_response_ids(finding.id for finding in active_findings)" in source
    assert "condition_response" in template
    assert "condition_assessment" in source
    assert "policy_digest" in source
    assert "condition_policy_available" in source
    assert "Condition policy unavailable" in template


def test_admin_health_exposes_unavailable_policy_state():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    template = Path("templates/findings_admin_health.html").read_text(encoding="utf-8")
    assert '"condition_policy_available": condition_policy_available' in source
    assert "Condition policy is unavailable" in template


def test_admin_coverage_tracks_condition_keys_and_links_to_issues():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    template = Path("templates/findings_admin_health.html").read_text(encoding="utf-8")
    assert "f.condition_key AS name" in source
    assert "condition_coverage = _condition_coverage_summary(condition_profile)" in source
    assert "findings_queue" in template
    assert "row.category_key" in template
    assert "row.type_key" in template
    assert "row.name|urlencode" in template


def test_device_issue_card_links_to_all_retained_responses():
    template = Path("templates/device_detail.html").read_text(encoding="utf-8")
    assert "status=all&amp;response=all&amp;subject_id={{ device.id }}" in template


def test_client_workspace_drilldowns_match_retained_issue_counts():
    source = Path("apps/core/client_workspace.py").read_text(encoding="utf-8")
    assert 'f"&response=all&type={row[\'finding_type__name\']}"' in source


def test_source_action_enqueue_requires_current_actionable_response():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    assert '_condition_operator_states([finding.id])' in source


def test_source_action_actionability_excludes_operator_managed_findings():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    section = source[source.index("def _condition_response_ids"):source.index("def _operator_issue_type_groups")]
    assert "f.status IN ('open', 'acknowledged', 'investigating')" in section
    assert "f.snoozed_until IS NULL OR f.snoozed_until <= now()" in section
    assert "may_execute" in section
    assert "may_clear" not in section


def test_operator_resolution_and_retirement_preserve_explicit_reasons():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    assert '"reason": "operator_resolved"' in source
    assert '"reason": "retired"' in source
    assert "finding_details" in source[source.index("def finding_resolve"):source.index("def finding_snooze")]


def test_device_merge_preserves_finding_merge_provenance():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    section = source[source.index("def _merge_devices"):source.index("def merge_candidate_group_review")]
    assert "'merge'" in section
    assert "from_device_id" in section
    assert "into_device_id" in section


def test_device_merge_reconciles_condition_scopes_before_downstream_use():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    section = source[source.index("def _merge_devices"):source.index("def merge_candidate_group_review")]
    assert "condition_participants_reconciled" in section
    assert "condition_participants" in section
    assert "condition_assessments" in section
    assert "ON CONFLICT DO NOTHING" in section
    assert "source_action_requests" not in section
    assert "UPDATE operations.findings SET id" not in section
def test_client_attachment_resolution_requires_current_clear_assessment():
    source = (Path(__file__).parents[1] / "views.py").read_text(encoding="utf-8")
    section = source[source.index("def _attach_group_to_client"):source.index("@login_required", source.index("def _resolve_finding_for_group"))]
    assert section.count("condition_assessments") >= 2
    assert section.count("may_clear") >= 2
    assert "policy.active" in section
