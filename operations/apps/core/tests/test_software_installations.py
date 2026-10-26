"""Software > Installations: one row per installation, filtered on the server."""

from __future__ import annotations

from pathlib import Path

from django.template.loader import get_template
from django.test import RequestFactory
from django.urls import reverse

from apps.core import views

_ROOT = Path(__file__).resolve().parents[3]


def _filters(**query):
    return views._installation_filters(RequestFactory().get("/software/installations/", query))


def test_filters_read_current_computers_and_the_shared_decision():
    filters, clauses, params = _filters(client="uta", q="chrome", decision="none")
    assert filters["client"] == "uta" and params == ["uta", "%chrome%", "%chrome%"]
    assert "lifecycle_status <> 'retired'" in " ".join(clauses)
    assert "COALESCE(COALESCE(title_device.decision" in clauses[-1]
    assert clauses[-1].endswith("IS NULL")
    assert "operations.v_device d" in views._INSTALLATION_FROM


def test_an_unknown_decision_filter_is_ignored():
    filters, clauses, _ = _filters(decision="drop table")
    assert filters["decision"] == "" and not any("decision" in c for c in clauses)


def test_the_decision_names_where_it_comes_from():
    assert views._installation_decision_label("approve", "reject") == "Approve"
    assert views._installation_decision_label(None, "approve_publisher") == (
        "Approve publisher (publisher)"
    )
    assert views._installation_decision_label(None, None) == ""


def test_page_navigation_and_product_links_open_installations():
    for name in ("software_installations.html", "org_software.html", "software_clients.html"):
        get_template(name)
    assert reverse("software_installations") == "/software/installations/"
    page = (_ROOT / "templates" / "software_installations.html").read_text(encoding="utf-8")
    assert "data-server-table" in page and "?{{ csv_query }}" in page
    for template in ("base.html", "org_software.html", "software_clients.html"):
        text = (_ROOT / "templates" / template).read_text(encoding="utf-8")
        assert "{% url 'software_installations' %}" in text, template
