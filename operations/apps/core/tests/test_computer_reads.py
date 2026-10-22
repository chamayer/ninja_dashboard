from pathlib import Path

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


def test_source_status_counts_have_an_observation_grain_destination():
    views = Path(__file__).parents[1].joinpath("views.py").read_text(encoding="utf-8")
    sources_template = Path(__file__).parents[3].joinpath("templates", "sources.html").read_text(
        encoding="utf-8"
    )
    assert "def source_records(" in views
    assert "operations.entity_observation_current observation" in views
    assert "source_records" in sources_template


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
