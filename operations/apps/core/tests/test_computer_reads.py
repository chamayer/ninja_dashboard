from pathlib import Path

from django.template.loader import get_template

from apps.core.computer_reads import current_computer_sql


def test_current_computer_sql_excludes_only_retired_computers():
    assert current_computer_sql() == "lifecycle_status <> 'retired'"
    assert current_computer_sql("device") == "device.lifecycle_status <> 'retired'"


def test_inventory_consumers_use_the_shared_current_computer_selector():
    views = Path(__file__).parents[1].joinpath("views.py").read_text(encoding="utf-8")

    for consumer in (
        "org_index",
        "org_devices",
        "patching_queue",
        "inventory_clients",
        "software_detail",
        "software_publisher_detail",
        "software_clients",
        "org_software",
        "org_software_devices",
    ):
        start = views.index(f"def {consumer}(")
        next_view = views.find("\n@login_required\ndef ", start + 1)
        section = views[start : next_view if next_view >= 0 else len(views)]
        assert "current_computer" in section


def test_software_count_destinations_are_not_silently_capped():
    views = Path(__file__).parents[1].joinpath("views.py").read_text(encoding="utf-8")
    for consumer, limit in (
        ("software_detail", "LIMIT %s OFFSET %s"),
        ("software_publisher_detail", "LIMIT %s OFFSET %s"),
    ):
        start = views.index(f"def {consumer}(")
        next_view = views.find("\n@login_required\ndef ", start + 1)
        section = views[start : next_view if next_view >= 0 else len(views)]
        assert limit in section


def test_software_status_counts_are_parameterized_by_current_computer_scope():
    review = Path(__file__).parents[1].joinpath("software_review.py").read_text(encoding="utf-8")
    assert "def title_status_counts_sql(computer_selector: str)" in review
    assert "JOIN operations.devices d" in review
    assert "AND {computer_selector}" in review


def test_source_records_is_a_generic_observation_reader_with_explicit_relationships():
    views = Path(__file__).parents[1].joinpath("views.py").read_text(encoding="utf-8")
    sources_template = Path(__file__).parents[3].joinpath("templates", "sources.html").read_text(
        encoding="utf-8"
    )
    source_records_template = Path(__file__).parents[3].joinpath(
        "templates", "source_records.html"
    ).read_text(encoding="utf-8")
    urls = Path(__file__).parents[3].joinpath("config", "urls.py").read_text(encoding="utf-8")

    assert "def source_records(" in views
    start = views.index("def source_records(")
    next_view = views.find("\n@login_required\ndef ", start + 1)
    section = views[start : next_view if next_view >= 0 else len(views)]
    assert "operations.v_entity_observation_admin_metadata observation" in section
    assert "operations.entity_observation_current observation" not in section
    assert "source_instance_id: uuid.UUID | None = None" in views
    assert "observation.device_id IS NOT NULL" in views
    assert "observation.client_id IS NOT NULL" in views
    assert "observation.parent_external_id" in views
    assert "_source_record_type_label" in views
    assert 'path("inventory/source-records/", source_records, name="inventory_source_records")' in urls
    assert "source_records" in sources_template
    assert "current record" in sources_template
    assert "Record type" in source_records_template
    assert "No resolved relationship" in source_records_template


def test_global_search_keeps_source_records_as_a_separate_result_population():
    views = Path(__file__).parents[1].joinpath("views.py").read_text(encoding="utf-8")
    get_template("search_results.html")
    template = Path(__file__).parents[3].joinpath("templates", "search_results.html").read_text(
        encoding="utf-8"
    )

    assert "def _search_source_records(" in views
    start = views.index("def _search_source_records(")
    end = views.find("\n\n@login_required", start)
    section = views[start : end if end >= 0 else len(views)]
    assert "operations.v_entity_observation_admin_metadata observation" in section
    assert "operations.entity_observation_current observation" not in section
    assert "source_records = _search_source_records(q)" in views
    assert "Source records (" in template
    assert "inventory_source_records" in template


def test_computer_inventory_does_not_render_unlinked_source_records_as_computers():
    views = Path(__file__).parents[1].joinpath("views.py").read_text(encoding="utf-8")
    template = Path(__file__).parents[3].joinpath("templates", "coverage.html").read_text(
        encoding="utf-8"
    )
    start = views.index("def fleet_coverage(")
    end = views.index("def sources_status(", start)
    section = views[start:end]

    assert "v_computer_inventory_source_record_current" not in section
    assert '"source_record": platform' not in section
    assert "All current Computers" in template
    assert "Review source records" in template


def test_computer_overview_pages_html_and_exports_the_full_filtered_scope():
    views = Path(__file__).parents[1].joinpath("views.py").read_text(encoding="utf-8")
    start = views.index("def devices_page(")
    next_view = views.find("\n@login_required\ndef ", start + 1)
    section = views[start : next_view if next_view >= 0 else len(views)]
    assert 'is_csv = wants_csv(request)' in section
    assert 'LIMIT %s OFFSET %s' in section
    assert '"filtered_total": filtered_total' in section


def test_computer_overview_issue_chips_name_their_governed_issue_populations():
    views = Path(__file__).parents[1].joinpath("views.py").read_text(encoding="utf-8")
    template = Path(__file__).parents[3].joinpath("templates", "devices_page.html").read_text(
        encoding="utf-8"
    )
    assert "agent_reporting_issues, inventory_issues = cur.fetchone()" in views
    assert "agent or reporting issue" in template
    assert "with an inventory issue" in template
    assert "identity conflict" not in template
