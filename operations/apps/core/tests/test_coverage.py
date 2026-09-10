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
                    "physical",
                    "workstation",
                    "active",
                    False,
                ),
                (
                    "device-2",
                    "client-2",
                    "beta",
                    "Beta",
                    "host-2",
                    "Ubuntu",
                    "vm",
                    "server",
                    "active",
                    True,
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
            [
                ("device-1", "Ninja", True, None, None),
                ("device-1", "SentinelOne", True, None, None),
                ("device-2", "Ninja", True, None, None),
            ],
            [
                (
                    "source-observation-1",
                    "client-3",
                    "gamma",
                    "Gamma",
                    "source-only-host",
                    "Ninja",
                    True,
                ),
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


def test_coverage_uses_effective_requirements_and_source_specific_filters(monkeypatch):
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
        "/coverage/?client=acme&client=beta&agent_0=Ninja&agent_state_0=Online"
        "&agent_requirement_0=Missing&agent_1=SentinelOne&agent_state_1=Online"
        "&agent_requirement_1=Required&hudu=in_hudu&hudu_links=has_links"
        "&s1_exemption=not_exempt"
        "&os_family=Windows+11&device_type=physical&device_role=workstation"
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
    assert "v_hudu_computer_inventory_evidence_current" in hudu_statement
    assert "platform_aliases" in hudu_statement
    assert "hudu.source_name = 'Hudu'" not in hudu_statement
    assert hudu_params is None
    computer_statement, _ = cursor.queries[3]
    assert "device_operator_decisions" in computer_statement
    assert "AS s1_exempt" in computer_statement

    context = captured["context"]
    assert context["client_filters"] == ["acme", "beta"]
    assert context["agent_filter_conditions"] == [
        {"index": 0, "agent": "Ninja", "states": ["Online"], "requirements": ["Missing"]},
        {"index": 1, "agent": "SentinelOne", "states": ["Online"], "requirements": ["Required"]},
    ]
    assert context["hudu_filters"] == ["in_hudu"]
    assert context["hudu_link_filters"] == ["has_links"]
    assert context["s1_exemption_filters"] == ["not_exempt"]
    assert context["state_filters"] == []
    assert context["os_family_filters"] == ["Windows 11"]
    assert context["device_type_filters"] == ["physical"]
    assert context["device_role_filters"] == ["workstation"]
    assert len(context["device_rows"]) == 1
    assert context["paginator"].count == 1
    assert context["filtered_summary"] == {
        "clients": 1,
        "devices": 1,
        "in_hudu": 1,
        "not_in_hudu": 0,
    }
    row = context["device_rows"][0]
    assert row["hudu_present"] is True
    assert row["hudu_links"] == ["Ninja — host-1", "Auvik #42"]
    assert [
        (cell["platform"], cell["record_status"], cell["rule_label"])
        for cell in row["agent_cells"]
    ] == [
        ("Ninja", "Online", "Required · Missing"),
        ("SentinelOne", "Online", "Required"),
    ]
    assert row["agent_cells"][0]["record_url"] == (
        "?agent_0=Ninja&agent_state_0=Online"
    )
    cards = {card["platform"]: card for card in context["platform_cards"]}
    assert {item["name"]: item["count"] for item in cards["Ninja"]["counts"]} == {
        "Online": 3,
        "Offline": 0,
        "No status reported": 0,
        "Withdrawn": 0,
        "No record": 1,
        "Total": 3,
    }
    assert cards["Ninja"]["requirement_total"] == 2
    assert {item["name"]: item["count"] for item in cards["Ninja"]["requirement_exceptions"]} == {
        "Missing": 1,
    }
    assert cards["SentinelOne"]["requirement_total"] == 1
    assert {item["name"]: item["count"] for item in cards["SentinelOne"]["requirement_exceptions"]} == {
        "Exempt": 1,
    }
    assert {item["name"]: item["count"] for item in context["hudu_card"]["counts"]} == {
        "Current only": 2,
        "Current + archived": 0,
        "Archived only": 0,
        "No record": 2,
        "Total": 2,
    }


def _render_coverage_context(monkeypatch, query: str) -> dict:
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
    request = RequestFactory().get(f"/inventory/computers/?{query}")
    request.user = SimpleNamespace(is_authenticated=True)
    views.fleet_coverage(request)
    return captured["context"]


def test_computer_shortcuts_distinguish_other_records_from_hudu(monkeypatch):
    no_four = _render_coverage_context(monkeypatch, "computer_scope=no_product_records")
    assert no_four["paginator"].count == 1
    assert no_four["device_rows"][0]["inventory_key"] == "hudu:hudu-observation-2"

    no_current = _render_coverage_context(monkeypatch, "computer_scope=no_current_records")
    assert no_current["paginator"].count == 0


def test_required_filter_includes_missing_and_sentinelone_exempt_is_independent(monkeypatch):
    required = _render_coverage_context(monkeypatch, "rule_status=Ninja%7CRequired")
    assert required["paginator"].count == 2

    exempt = _render_coverage_context(monkeypatch, "rule_status=SentinelOne%7CExempt")
    assert exempt["paginator"].count == 1
    assert exempt["device_rows"][0]["device_id"] == "device-2"


def test_role_filter_is_distinct_from_hardware_type(monkeypatch):
    context = _render_coverage_context(monkeypatch, "device_role=server")

    assert context["device_role_filters"] == ["server"]
    assert context["paginator"].count == 1
    assert context["device_rows"][0]["device_id"] == "device-2"
    assert context["device_rows"][0]["device_type"] == "vm"
    assert context["device_rows"][0]["device_role"] == "server"


def test_agents_condition_builder_shows_its_exact_and_or_logic(monkeypatch):
    context = _render_coverage_context(
        monkeypatch,
        "agent_0=Ninja&agent_state_0=Online&agent_state_0=Offline"
        "&agent_requirement_0=Required&agent_1=SentinelOne"
        "&agent_requirement_1=Required",
    )

    assert context["paginator"].count == 1
    assert context["filter_logic"] == (
        "((Ninja state is Online OR Ninja state is Offline) AND Ninja requirement is Required)"
        " AND (SentinelOne requirement is Required)"
    )


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

    hudu_only = next(
        row for row in captured["context"]["device_rows"]
        if row["inventory_key"] == "hudu:hudu-observation-2"
    )
    assert hudu_only["hostname"] == "host-2"
    assert hudu_only["hudu_present"] is True
    assert hudu_only["hudu_links"] == []
    assert hudu_only["possible_match"]["device_id"] == "device-2"
    assert hudu_only["agent_cells"][0]["possible_match"]["device_id"] == "device-2"
    source_only = next(
        row for row in captured["context"]["device_rows"]
        if row["inventory_key"] == "source:source-observation-1"
    )
    assert source_only["device_id"] is None
    assert source_only["source_states"] == {"Ninja": "Online"}


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
        "Role",
        "Lifecycle",
        "Hudu",
        "Hudu links",
        "Agents",
    ]
    assert [
        "Acme",
        "host-1",
        "Windows 11",
        "physical",
        "workstation",
        "active",
        "In Hudu",
        "Ninja — host-1, Auvik #42",
        "Ninja: Online; Required · Missing | SentinelOne: Online; Required",
    ] in rows
    assert [
        "Beta",
        "host-2",
        "",
        "",
        "",
        "",
        "In Hudu",
        "",
        "Ninja: No record; possible match: host-2; N/A | SentinelOne: No record; N/A",
    ] in rows


def test_coverage_template_has_clear_statuses_hudu_and_multiselect_filters():
    template = (Path(__file__).parents[3] / "templates/coverage.html").read_text(encoding="utf-8")

    for label in (
        "Links",
        "Agents",
        "OS family",
        "Device type",
        "Role",
    ):
        assert label in template
    assert "Show Computers where every condition below is true." in template
    assert "Required platform" not in template
    assert "Hudu" in template
    assert template.count('type="checkbox"') >= 12
    assert template.count('<details class="coverage-filter">') == 6
    assert template.count('class="coverage-filter-search"') >= 7
    assert "coverage-filterbar" in template
    assert "const filterMenus" in template
    assert "event.target.closest('details.coverage-filter, details.coverage-column-filter')" in template
    assert "coverage-result-summary" in template
    assert "Filtered results" in template
    assert "{{ filter_logic }}" in template
    assert "No links" in template
    assert 'name="hudu_record_filter"' in template
    assert "Has current record" in template
    assert "Has archived record" in template
    assert "Current records only" in template
    assert "Archived records only" in template
    assert 'name="show_archived_hudu"' not in template
    assert "row.hudu_records" in template
    assert "Every Computer known to Operations" in template
    assert "Agents" in template
    assert "Add condition" in template
    assert 'name="agent_{{ condition.index }}"' in template
    assert 'name="agent_requirement_{{ condition.index }}"' in template
    for label in ("Clients", "Computers", "In Hudu", "Not in Hudu"):
        assert label in template
    assert "Agent checks" not in template
    assert "_pagination.html" in template
    assert "In Hudu" in template
    assert "Not in Hudu" in template
    assert "agent_filter_states" in template
    assert "agent_filter_requirements" in template
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
