from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.http import HttpResponse
from django.template.loader import get_template
from django.test import RequestFactory

from apps.core import context_processors, finding_registry, views


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


def test_home_composes_domain_summaries_above_attention_and_keeps_client_detail_on_clients(  # noqa: PLR0915
    monkeypatch,
):
    empty_actions = {"open_actions": 0, "paused_actions": 0, "critical_actions": 0}
    categories = {
        name: dict(empty_actions)
        for name in (
            finding_registry.INVENTORY,
            finding_registry.COLLECTION,
            finding_registry.PATCHING,
        )
    }
    categories[finding_registry.COLLECTION]["open_actions"] = 4
    categories[finding_registry.COLLECTION]["paused_actions"] = 1
    issue_summary = {
        "categories": categories,
        "open_actions": 7,
        "critical_actions": 2,
        "paused_actions": 1,
        "mapping_actions": 0,
        "mapping_clients": 0,
    }

    device_policy = {"active_device_days": 30, "patch_activity_days": 35}
    monkeypatch.setattr(views, "get_device_status_policy", lambda: device_policy)
    monkeypatch.setattr(
        views.client_workspace_reads,
        "home_summary",
        lambda **_kwargs: {"total": 12, "trend_30d": "CLIENTS +1 NET"},
    )
    monkeypatch.setattr(
        views.computer_reads_summary,
        "home_summary",
        lambda **_kwargs: {"total": 42, "active": 30, "needs_review": 3, "retired": 2},
    )
    monkeypatch.setattr(
        views.source_record_summary,
        "home_summary",
        lambda **_kwargs: {"current": 99, "trend_30d": "INVENTORY +3 NET", "latest": None},
    )
    monkeypatch.setattr(views.issue_selection, "home_summary", lambda: issue_summary)
    monkeypatch.setattr(
        views.issue_selection,
        "home_attention_items",
        lambda: [
            {
                "severity": "high",
                "label": "Review finding",
                "affected": "2 affected",
                "href": "/issues",
            }
        ],
    )
    monkeypatch.setattr(views.issue_selection, "mapping_query", lambda: {})
    patching_call = {}

    def patching_summary(**kwargs):
        patching_call.update(kwargs)
        return {
            "current_total": 42,
            "included": 30,
            "excluded": 5,
            "unmanaged": 7,
            "actively_patching": 18,
            "actively_patching_percent": 42.9,
            "installed_30d": 70,
            "failed_30d": 2,
            "latest": None,
        }

    monkeypatch.setattr(views.patching_reads, "home_summary", patching_summary)
    monkeypatch.setattr(
        views.coverage_reads,
        "home_summary",
        lambda: {
            "meeting": 38,
            "not_meeting": 2,
            "stale": 1,
            "neutral": 1,
            "exempt": 0,
            "evaluated_at": None,
        },
    )
    monkeypatch.setattr(
        views.software_review,
        "home_summary",
        lambda: {
            "installed_titles": 20,
            "approval_counts": {"approve": 10, "pending": 4, "reject": 3, "investigate": 3},
            "risk_titles": 5,
        },
    )
    monkeypatch.setattr(
        views,
        "_sources_home_summary",
        lambda _now: {"available": True, "total": 4, "current": 3, "attention": 1, "latest": None},
    )
    monkeypatch.setattr(
        views,
        "_jobs_home_summary",
        lambda _now: {
            "running": 1,
            "waiting": 2,
            "contained": 0,
            "label": "Jobs processing normally",
        },
    )

    def render_without_database_context(request, template_name, context):
        rendered_context = {**context, "request": request}
        return HttpResponse(get_template(template_name).render(rendered_context))

    monkeypatch.setattr(views, "render", render_without_database_context)

    request = RequestFactory().get("/")
    request.user = SimpleNamespace(is_authenticated=True, is_staff=True)
    response = views.home(request)

    assert response.status_code == 200
    assert patching_call["policy"] is device_policy
    content = response.content.decode()
    assert content.index('aria-label="Operational areas"') < content.index("What needs attention")
    assert content.index(">Clients</h2>") < content.index(">Computers</h2>")
    assert content.index(">Computers</h2>") < content.index(">Inventory</h2>")
    assert content.index(">Inventory</h2>") < content.index(">Patching</h2>")
    assert ">Data collection</h2>" in content
    assert "Security &amp; coverage" in content
    assert ">Software</h2>" in content
    assert ">Issues</h2>" in content
    assert "CLIENTS +1 NET" in content
    assert "INVENTORY +3 NET" in content
    assert 'class="area-value area-value-good">38</span>' in content
    assert 'class="area-value area-value-bad">2</span>' in content
    assert "18 of 42 current" in content
    assert "5 titles with at least one active risk finding" in content
    assert ">4</span>" in content
    assert "open collection actions" in content
    assert "2 critical" in content
    assert ">Sources</h2>" in content
    assert ">Jobs</h2>" in content
    assert "View the detailed client portfolio" in content
    assert "client-table" not in content
    assert "Review finding" in content


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
