"""Coverage page request and template regression coverage."""

from __future__ import annotations

import csv as csv_module
from contextlib import nullcontext
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from django.http import HttpResponse
from django.test import RequestFactory

from apps.core import views


class _Cursor:
    def __init__(self):
        self.queries: list[tuple[str, dict | None]] = []
        self._results = [
            [
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
                    False,
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
                    False,
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
                ),
            ],
            [
                (
                    "hudu-observation-1",
                    "device-1",
                    "client-1",
                    "host-1",
                    "Computer Assets",
                    "https://hudu.example/assets/1",
                    "SERIAL-1",
                    "linked",
                    "ninja",
                    "296",
                    "device-1",
                    False,
                    "Ninja",
                ),
                (
                    "hudu-observation-1",
                    "device-1",
                    "client-1",
                    "host-1",
                    "Computer Assets",
                    "https://hudu.example/assets/1",
                    "SERIAL-1",
                    "linked",
                    "auvik",
                    "42",
                    None,
                    False,
                    "Auvik",
                ),
                (
                    "hudu-observation-2",
                    None,
                    "client-2",
                    "host-2",
                    "Computer Assets",
                    "https://hudu.example/assets/2",
                    "SERIAL-2",
                    "unlinked",
                    None,
                    None,
                    False,
                    None,
                    None,
                ),
            ],
            [
                (
                    "device-1",
                    "client-1",
                    "acme",
                    "Acme",
                    "host-1",
                    "Windows 11",
                    "workstation",
                ),
                (
                    "device-2",
                    "client-2",
                    "beta",
                    "Beta",
                    "host-2",
                    "Ubuntu",
                    "server",
                ),
            ],
            [
                ("client-1", "acme", "Acme"),
                ("client-2", "beta", "Beta"),
            ],
            [
                ("device-1", "Ninja", True),
                ("device-1", "SentinelOne", True),
                ("device-2", "Ninja", True),
            ],
        ]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=None):
        self.queries.append((statement, params))

    def fetchall(self):
        return self._results.pop(0)


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
    assert "missing_required_platform" in statement
    assert "stale_required_platform" in statement
    assert params is None
    hudu_statement, hudu_params = cursor.queries[2]
    assert "v_cmdb_inventory_evidence_current" in hudu_statement
    assert "platform_aliases" in hudu_statement
    assert "hudu.source_name = 'Hudu'" in hudu_statement
    assert "hudu.source_layout = ANY(%s)" in hudu_statement
    assert hudu_params == (False, ["Computer Assets", "Servers"])

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
    assert context["paginator"].count == 1
    assert context["filtered_summary"] == {
        "clients": 1,
        "devices": 1,
        "agent_checks": 2,
        "online_devices": 1,
    }
    row = context["device_rows"][0]
    assert row["hudu_present"] is True
    assert row["hudu_links"] == ["Ninja — host-1", "Auvik #42"]
    assert [(cell["platform"], cell["status"]) for cell in row["platform_cells"]] == [
        ("Ninja", "Missing"),
        ("SentinelOne", "Online"),
    ]
    assert row["platform_cells"][0]["url"] == "?platform=Ninja&state=Missing"


def test_coverage_includes_an_unattached_hudu_computer_as_its_own_row(monkeypatch):
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
    request = RequestFactory().get("/inventory/computers/")
    request.user = SimpleNamespace(is_authenticated=True)

    views.fleet_coverage(request)

    hudu_only = next(row for row in captured["context"]["device_rows"] if row["device_id"] is None)
    assert hudu_only["hostname"] == "host-2"
    assert hudu_only["hudu_present"] is True
    assert hudu_only["hudu_links"] == []
    assert hudu_only["possible_match"]["device_id"] == "device-2"
    assert hudu_only["platform_cells"][0]["possible_match"]["device_id"] == "device-2"


def test_computers_csv_has_the_current_table_platform_columns(monkeypatch):
    cursor = _Cursor()
    monkeypatch.setattr(views, "connection", _Connection(cursor))
    monkeypatch.setattr(views.transaction, "atomic", nullcontext)
    request = RequestFactory().get("/inventory/computers/?format=csv")
    request.user = SimpleNamespace(is_authenticated=True)

    response = views.fleet_coverage(request)

    csv = response.content.decode("utf-8-sig")
    rows = list(csv_module.reader(StringIO(csv)))
    assert "Platform statuses" not in csv
    assert rows[0] == [
        "Client",
        "Device",
        "OS family",
        "Device type",
        "Hudu",
        "Hudu links",
        "Ninja",
        "SentinelOne",
    ]
    assert [
        "Acme",
        "host-1",
        "Windows 11",
        "workstation",
        "In Hudu",
        "Ninja — host-1, Auvik #42",
        "Missing",
        "Online",
    ] in rows
    assert [
        "Beta",
        "host-2",
        "",
        "",
        "In Hudu",
        "",
        "Possible: host-2",
        "Not applicable",
    ] in rows


def test_coverage_template_has_clear_statuses_hudu_and_multiselect_filters():
    template = (Path(__file__).parents[3] / "templates/coverage.html").read_text(encoding="utf-8")

    for label in (
        "Online in",
        "Hudu links",
        "SentinelOne",
        "Required platform",
        "Status",
        "OS family",
        "Device type",
    ):
        assert label in template
    assert "Hudu" in template
    assert template.count('type="checkbox"') >= 12
    assert template.count('<details class="coverage-filter">') == 9
    assert template.count('class="coverage-filter-search"') == 9
    assert "coverage-filterbar" in template
    assert "details.coverage-filter[open]" in template
    assert "event.target.closest('details.coverage-filter')" in template
    assert "coverage-result-summary" in template
    assert "Filtered results" in template
    assert "Counts reflect the current filter selections." in template
    assert "No linked cards" in template
    assert "Show archived Hudu records" in template
    assert "row.hudu_status" in template
    assert "Computer inventory from all sources" in template
    for label in ("Clients", "Devices", "Agent checks", "Online devices"):
        assert label in template
    assert "_pagination.html" in template
    assert "In Hudu" in template
    assert "Not in Hudu" in template
    assert "Online" in template
    assert "Offline" in template
    assert "Stale" in template
    assert "Missing" in template
    assert "device_missing_from_source" not in template


def test_inventory_computers_navigation_uses_the_coverage_reader():
    base = (Path(__file__).parents[3] / "templates/base.html").read_text(encoding="utf-8")
    urls = (Path(__file__).parents[3] / "config/urls.py").read_text(encoding="utf-8")

    assert "Inventory" in base
    assert 'aria-label="Inventory navigation"' in base
    assert "inventory_computers" in base
    assert 'path("inventory/computers/", fleet_coverage, name="inventory_computers")' in urls


def test_hudu_device_link_read_model_is_tenant_scoped_and_read_only():
    migration = (
        Path(__file__).parents[1] / "migrations/0146_hudu_device_links_read_model.py"
    ).read_text(encoding="utf-8")

    assert "v_device_hudu_link_current" in migration
    assert "observation.tenant_id = operations.current_tenant_id()" in migration
    assert "observation.device_id IS NOT NULL" in migration
    assert "card_resolved_device_id" in migration
    assert "OWNER TO operations_view_owner" in migration
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE" in migration
    assert "GRANT SELECT" in migration


def test_cmdb_inventory_evidence_read_model_includes_unattached_assets():
    migration = (
        Path(__file__).parents[1] / "migrations/0147_cmdb_inventory_evidence_read_model.py"
    ).read_text(encoding="utf-8")

    assert "v_cmdb_inventory_evidence_current" in migration
    assert "observation.device_id" in migration
    assert "observation.platform AS source_name" in migration
    assert "observation.entity_type = 'cmdb.asset'" in migration
    assert "observation.platform = 'Hudu'" not in migration
    assert "observation.device_id IS NOT NULL" not in migration
    assert "security_barrier" in migration
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE" in migration


def test_cmdb_inventory_archive_state_is_read_only():
    migration = (
        Path(__file__).parents[1] / "migrations/0148_cmdb_inventory_evidence_archive_state.py"
    ).read_text(encoding="utf-8")

    assert "CREATE OR REPLACE VIEW operations.v_cmdb_inventory_evidence_current" in migration
    assert "END AS is_archived" in migration
    assert "OWNER TO operations_view_owner" in migration
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE" in migration
