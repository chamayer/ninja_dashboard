"""Coverage page request and template regression coverage."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

from django.http import HttpResponse
from django.test import RequestFactory

from apps.core import views


class _Cursor:
    def __init__(self):
        self.queries: list[tuple[str, dict | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=None):
        self.queries.append((statement, params))

    def fetchall(self):
        return [
            (
                "acme",
                "Acme",
                "device-1",
                "host-1",
                "Windows 11",
                "workstation",
                "Ninja",
                False,
                "Missing",
                True,
                "https://hudu.example/assets/1",
                ["Ninja #296", "Auvik #42"],
            ),
            (
                "acme",
                "Acme",
                "device-1",
                "host-1",
                "Windows 11",
                "workstation",
                "SentinelOne",
                False,
                "Online",
                True,
                "https://hudu.example/assets/1",
                ["Ninja #296", "Auvik #42"],
            ),
            (
                "beta",
                "Beta",
                "device-2",
                "host-2",
                "Ubuntu",
                "server",
                "Ninja",
                True,
                "Online",
                False,
                None,
                [],
            ),
        ]


class _Connection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def test_coverage_uses_effective_requirements_and_multiselect_filters(monkeypatch):
    cursor = _Cursor()
    captured = {}
    monkeypatch.setattr(views, "connection", _Connection(cursor))
    monkeypatch.setattr(views.transaction, "atomic", nullcontext)
    monkeypatch.setattr(
        views,
        "render",
        lambda _request, _template, context: captured.setdefault("context", context)
        or HttpResponse(),
    )
    request = RequestFactory().get(
        "/coverage/?client=acme&client=beta&platform=Ninja&platform=SentinelOne"
        "&online_in=SentinelOne&hudu=in_hudu&hudu_links=has_links"
        "&s1_exemption=not_exempt&state=Online&state=Missing"
        "&os_family=Windows+11&device_type=workstation"
    )
    request.user = SimpleNamespace(is_authenticated=True)

    views.fleet_coverage(request)

    statement, params = cursor.queries[1]
    assert "requirement_profile_items" in statement
    assert "coverage_requirements" in statement
    assert "device_operator_decisions" in statement
    assert "v_device_hudu_link_current" in statement
    assert "platform_aliases" in statement
    assert "Ninja — " in statement
    assert "missing_required_platform" in statement
    assert "stale_required_platform" in statement
    assert params is None

    context = captured["context"]
    assert context["client_filters"] == ["acme", "beta"]
    assert context["platform_filters"] == ["Ninja", "SentinelOne"]
    assert context["online_filters"] == ["SentinelOne"]
    assert context["hudu_filters"] == ["in_hudu"]
    assert context["hudu_link_filters"] == ["has_links"]
    assert context["s1_exemption_filters"] == ["not_exempt"]
    assert context["state_filters"] == ["Online", "Missing"]
    assert context["os_family_filters"] == ["Windows 11"]
    assert context["device_type_filters"] == ["workstation"]
    assert len(context["device_rows"]) == 1
    row = context["device_rows"][0]
    assert row["hudu_present"] is True
    assert row["hudu_links"] == ["Ninja #296", "Auvik #42"]
    assert [(cell["platform"], cell["status"]) for cell in row["platform_cells"]] == [
        ("Ninja", "Missing"),
        ("SentinelOne", "Online"),
    ]
    assert row["platform_cells"][0]["url"] == "?platform=Ninja&state=Missing"


def test_coverage_template_has_clear_statuses_hudu_and_multiselect_filters():
    template = (Path(__file__).parents[3] / "templates/coverage.html").read_text(encoding="utf-8")

    for label in ("Online in", "Hudu links", "SentinelOne", "Required platform", "Status", "OS family", "Device type"):
        assert label in template
    assert "Hudu" in template
    assert template.count('type="checkbox"') >= 12
    assert template.count('<details class="coverage-filter">') == 9
    assert template.count('class="coverage-filter-search"') == 9
    assert "In Hudu" in template
    assert "Not in Hudu" in template
    assert "Online" in template
    assert "Offline" in template
    assert "Stale" in template
    assert "Missing" in template
    assert "device_missing_from_source" not in template


def test_hudu_device_link_read_model_is_tenant_scoped_and_read_only():
    migration = (
        Path(__file__).parents[1]
        / "migrations/0146_hudu_device_links_read_model.py"
    ).read_text(encoding="utf-8")

    assert "v_device_hudu_link_current" in migration
    assert "observation.tenant_id = operations.current_tenant_id()" in migration
    assert "observation.device_id IS NOT NULL" in migration
    assert "card_resolved_device_id" in migration
    assert "OWNER TO operations_view_owner" in migration
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE" in migration
    assert "GRANT SELECT" in migration
