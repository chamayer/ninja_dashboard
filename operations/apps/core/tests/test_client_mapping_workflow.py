"""Client mapping work: Issues is the queue, client pages decide (2026-10-07 single inbox)."""

from pathlib import Path

from django.template.loader import get_template

_ROOT = Path(__file__).resolve().parents[3]
_VIEWS = (_ROOT / "apps" / "core" / "views.py").read_text(encoding="utf-8")
_WORKSPACE = (_ROOT / "apps" / "core" / "client_workspace.py").read_text(encoding="utf-8")


def _template(name: str) -> str:
    get_template(name)
    return (_ROOT / "templates" / name).read_text(encoding="utf-8")


def test_name_difference_links_use_the_registry_issue_group():
    # Issue groups are slugs of finding_types.issue_group ("Client mapping").
    inventory = _template("inventory_clients.html")
    assert "type=client_mapping&amp;issue=client_name_conflict" in inventory
    assert "'type': 'client_mapping', 'issue': 'client_name_conflict'" in _WORKSPACE
    assert "client_name_differences" not in inventory + _WORKSPACE
    assert "type=computer_identity_matching" not in _template("org_index.html")


def test_the_client_page_decides_its_source_mappings_in_place():
    page = _template("org_index.html")
    assert "{% url 'client_mapping_decide' reference.source_link_id %}" in page
    assert 'name="next" value="{{ request.path }}#source-references"' in page
    # Only users the decide action admits see the form.
    assert "{% if user.is_superuser or perms.operations.manage_catalog %}" in page
    assert "{% url 'client_mappings' %}?source_link_id" not in page
    detail = _template("client_source_reference_detail.html")
    assert "{% url 'org_index' org_slug=reference.client_slug %}#source-references" in detail


def test_issues_send_a_known_clients_mapping_to_its_page():
    assert "kwargs={'org_slug': client.slug})}#source-references" in _VIEWS
    assert 'resolution_label = "Decide on the client page"' in _VIEWS


def test_inventory_clients_lists_new_clients_from_the_same_records_as_issues():
    page = _template("inventory_clients.html")
    assert 'id="new-clients"' in page and "New / discovered clients" in page
    assert '<a class="badge badge-high" href="#new-clients"' in page
    assert '"issue": "client_unattached_group"' in _VIEWS
    assert '"type": "client_mapping"' in _VIEWS
    home = _template("home.html")
    assert "{% url 'inventory_clients' %}#new-clients" in home
    assert "{% url 'client_mappings' %}?state=unattached" not in home


def test_inventory_client_coverage_shows_each_source_name_as_evidence():
    page = _template("inventory_clients.html")

    assert "ic-cov-line" in page
    assert "item.reported_names|join" in page
    assert "no current source name" in page
    assert '"reported_names": sorted(' in _VIEWS


def test_client_mapping_conflicts_are_prominent_on_client_and_fleet_dashboards():
    inventory = _template("inventory_clients.html")
    client_dashboard = _template("org_index.html")
    dashboard = _template("home.html")

    assert "Client mapping conflicts" in inventory
    assert "critical</a>" in inventory
    assert "Critical client mapping conflict" in client_dashboard
    assert "client_mapping_conflict_url" in client_dashboard
    assert "Critical mapping issues" in dashboard
    assert "client_mapping_conflict_clients" in _VIEWS
