from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.http import HttpResponse
from django.template.loader import get_template
from django.test import RequestFactory

from apps.core import context_processors, views


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"hostname": "example"}, {"hostname": "example"}),
        ('{"hostname": "example"}', {"hostname": "example"}),
        ("[1, 2]", {}),
        ("not-json", {}),
        (None, {}),
    ],
)
def test_raw_json_object_normalizes_only_json_objects(value, expected):
    assert views._raw_json_object(value) == expected


@pytest.mark.parametrize(
    ("staff", "software_state", "client_error"),
    [
        (True, "current", False),
        (False, "current", False),
        (False, "pending", False),
        (False, "denied", True),
    ],
)
def test_home_keeps_cheap_counts_and_excludes_expensive_readers(
    monkeypatch, staff, software_state, client_error
):
    from django.core.exceptions import PermissionDenied
    from django.db import DatabaseError
    from django.urls import resolve
    from apps.core import software_overview

    resolve("/")  # Load decorated URL handlers before stubbing transactions.
    monkeypatch.setattr(views.issue_selection, "mapping_query", lambda: {"type": "client_mapping"})
    policy = {"active_device_days": 30, "patch_activity_days": 35}
    policy_read = Mock(return_value=policy)
    monkeypatch.setattr(views, "get_device_status_policy", policy_read)
    monkeypatch.setattr(views.transaction, "atomic", lambda: nullcontext())
    monkeypatch.setattr(
        views.client_workspace_reads,
        "home_summary",
        Mock(side_effect=DatabaseError) if client_error else Mock(return_value={"total": 0}),
    )
    computer_read = Mock(return_value={"total": 42, "active": 30, "needs_review": 3, "retired": 2})
    monkeypatch.setattr(views.computer_reads_summary, "home_summary", computer_read)
    monkeypatch.setattr(
        views.coverage_reads,
        "home_summary",
        Mock(return_value={"meeting": 38, "not_meeting": 2, "stale": 1, "neutral": 1, "exempt": 0}),
    )
    patch_read = Mock(
        return_value={
            "included": 30,
            "excluded": 5,
            "unmanaged": 7,
            "unresolved": 0,
            "unspecified": 0,
        }
    )
    monkeypatch.setattr(views.patching_reads, "home_summary", patch_read)
    payload = {
        "overview_publication": {"state": software_state, "message": "Pending refresh"},
        "unique_titles": 20,
        "installations": 99,
        "pending_decisions": 4,
    }
    software_read = (
        Mock(side_effect=PermissionDenied)
        if software_state == "denied"
        else Mock(return_value=payload)
    )
    monkeypatch.setattr(software_overview, "read_overview", software_read)
    sources = Mock(return_value={"available": True, "current": 3, "total": 4})
    jobs = Mock(return_value={"available": True, "running": 1, "waiting": 2, "contained": 0})
    monkeypatch.setattr(views, "_sources_home_summary", sources)
    monkeypatch.setattr(views, "_jobs_home_summary", jobs)
    monkeypatch.setattr(
        views.issue_selection,
        "home_data",
        Mock(side_effect=AssertionError("Expensive Issues read")),
    )
    monkeypatch.setattr(
        views.source_record_summary,
        "home_summary",
        Mock(side_effect=AssertionError("Expensive inventory read")),
    )

    def render_page(request, template_name, context):
        return HttpResponse(get_template(template_name).render({**context, "request": request}))

    monkeypatch.setattr(views, "render", render_page)
    request = RequestFactory().get("/")
    request.user = SimpleNamespace(is_authenticated=True, is_staff=staff)
    response = views.home(request)
    content = response.content.decode()
    assert response.status_code == 200
    policy_read.assert_called_once_with()
    computer_read.assert_called_once_with(active_device_days=30)
    assert patch_read.call_args.kwargs["policy"] is policy
    assert sources.called == staff and jobs.called == staff
    assert "42 <small>current computers" in content
    assert "38 / 2" in content and "30 <small>computers in patching scope" in content
    assert ("0 <small>active clients" in content) != client_error
    assert ("Client count unavailable" in content) == client_error
    assert ("20 <small>installed titles" in content) == (software_state == "current")
    if software_state == "pending":
        assert "Pending refresh" in content
    if software_state == "denied":
        assert "Software summary unavailable in this context" in content
    assert "Review critical mapping issues" in content
    assert "No current Issues need review" not in content
    assert ("Data and processing administration" in content) == staff


def test_home_template_loads():
    assert get_template("home.html")


@pytest.mark.parametrize(
    ("url_name", "loads_client_roster"),
    [("home", False), ("devices_page", True)],
)
def test_home_context_skips_unused_active_client_roster(monkeypatch, url_name, loads_client_roster):
    clients = [object()]
    order_query = Mock(return_value=clients)
    filter_query = Mock(return_value=SimpleNamespace(order_by=order_query))
    monkeypatch.setattr(context_processors.Client.objects, "filter", filter_query)
    monkeypatch.setattr(context_processors, "_nav_issues_count", lambda _tenant_id: 0)
    monkeypatch.setattr(context_processors, "_nav_patching_count", lambda _tenant_id: 0)

    request = RequestFactory().get("/")
    request.user = SimpleNamespace(is_authenticated=True)
    request.resolver_match = SimpleNamespace(url_name=url_name)

    context = context_processors.brand(request)

    if loads_client_roster:
        assert context["clients"] == clients
        filter_query.assert_called_once_with(tenant_id=1, deleted_at__isnull=True)
        order_query.assert_called_once_with("display_name")
    else:
        assert "clients" not in context
        filter_query.assert_not_called()


def test_jobs_home_summary_reads_only_displayed_health_and_runtime_data(monkeypatch):
    now = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
    health = {"running_runs": 1, "waiting_runs": 2, "contained_claims": 0}
    runtimes = [
        {"runtime_kind": "scheduler", "heartbeat_at": now.isoformat()},
        {"runtime_kind": "worker", "heartbeat_at": now.isoformat()},
    ]
    cursor = Mock()
    cursor_context = Mock()
    cursor_context.__enter__ = Mock(return_value=cursor)
    cursor_context.__exit__ = Mock(return_value=False)
    diagnostics = Mock(side_effect=[(1, [health]), (2, runtimes)])

    monkeypatch.setattr(views.transaction, "atomic", lambda: nullcontext())
    monkeypatch.setattr(views.connection, "cursor", lambda: cursor_context)
    monkeypatch.setattr(views, "_jobs_diagnostic_query", diagnostics)

    summary = views._jobs_home_summary(now)

    assert summary == {
        "available": True,
        "label": "Jobs processing normally",
        "running": 1,
        "waiting": 2,
        "contained": 0,
    }
    assert [call.args[0] for call in diagnostics.call_args_list] == ["health", "runtimes"]
    cursor.execute.assert_called_once_with("SET LOCAL operations.tenant_id = 1")
