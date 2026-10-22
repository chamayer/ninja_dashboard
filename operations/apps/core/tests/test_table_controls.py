import re
from pathlib import Path

from django.template.loader import get_template

TEMPLATES = Path(__file__).parents[3] / "templates"

# Pages whose primary table is server-paginated. Browser-side filtering there
# would only see one page, so the table must be marked data-server-table.
PAGINATED_TABLES = {
    "admin_job_detail.html": 1,
    "coverage.html": 1,
    "entity_admin_list.html": 1,
    "entity_candidates_queue.html": 1,
    "findings_queue.html": 1,
    "org_devices.html": 1,
    "org_software.html": 1,
    "patching_queue.html": 1,
    "software_decisions.html": 2,
    "software_products.html": 1,
    # Paginated card list, no table: nothing for browser-side controls to mislead.
    "software_tech_checklist.html": 0,
}


def test_shared_script_makes_every_table_sortable_and_filterable():
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    assert "document.querySelectorAll('table').forEach(enhanceTable)" in base
    assert "table-filter-row" in base
    assert "data-no-sort" in base
    assert "data-server-table" in base


def test_paginated_tables_are_marked_for_server_side_controls():
    for name, expected in PAGINATED_TABLES.items():
        source = (TEMPLATES / name).read_text(encoding="utf-8")
        marked = len(re.findall(r"<table[^>]*data-server-table", source))
        assert marked == expected, name


def test_every_template_with_pagination_is_accounted_for():
    paginated = {
        path.name
        for path in TEMPLATES.glob("*.html")
        if '_pagination.html"' in path.read_text(encoding="utf-8")
    }
    assert paginated <= set(PAGINATED_TABLES)


def test_pages_with_their_own_table_scripts_opt_out():
    home = (TEMPLATES / "home.html").read_text(encoding="utf-8")
    org_index = (TEMPLATES / "org_index.html").read_text(encoding="utf-8")
    assert 'id="client-table" data-no-sort' in home
    assert 'id="attention-table" data-no-sort' in org_index
    assert 'id="directory-table" data-no-sort' in org_index


def test_changed_templates_compile():
    for name in [*PAGINATED_TABLES, "base.html", "home.html", "org_index.html"]:
        get_template(name)


def test_jobs_table_sorts_within_groups_and_shows_default_order():
    jobs = (TEMPLATES / "admin_jobs.html").read_text(encoding="utf-8")
    assert '<table class="jobs-table" data-sortable>' in jobs
    assert '<th data-sort="asc">Status</th>' in jobs
    assert 'data-sort-value="{{ job.status_rank }}"' in jobs
    # One tbody per group keeps sorted rows under their group heading.
    assert jobs.index("{% for group in job_groups %}") < jobs.index("<tbody>")
    get_template("admin_jobs.html")
