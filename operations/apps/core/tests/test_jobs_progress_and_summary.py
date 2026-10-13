import importlib
from pathlib import Path

from apps.core import views

_TEMPLATES = Path(__file__).resolve().parents[3] / "templates"


def test_progress_with_a_total_is_a_percentage():
    progress = views._run_progress(700, 3674, "computers")
    assert progress["percent"] == 19
    assert progress["label"] == "700 of 3,674 computers (19%)"


def test_progress_without_a_total_is_a_running_count():
    assert views._run_progress(350000, None, "software rows from Ninja")["label"] == (
        "350,000 software rows from Ninja so far"
    )
    assert views._run_progress(None, None, "") is None


def test_a_finished_run_shows_its_own_summary_before_a_bare_count():
    assert views._run_summary({"summary": "Full check: 4,629 computers refreshed."}, 4629) == (
        "Full check: 4,629 computers refreshed."
    )
    assert views._run_summary('{"summary": "From JSON text."}', 1) == "From JSON text."
    assert views._run_summary({}, 12) == "12 updated."
    assert views._run_summary(None, None) == ""


def test_the_placeholder_sentence_is_never_shown():
    assert views._running_detail("Collecting", views._NO_MEASURABLE_TOTAL) == "Collecting"
    assert views._running_detail("Collecting", "") == "Collecting"
    assert views._running_detail("Collecting", "batch 3 of 9") == "batch 3 of 9"


def test_jobs_pages_render_a_progress_bar():
    jobs = (_TEMPLATES / "admin_jobs.html").read_text(encoding="utf-8")
    detail = (_TEMPLATES / "admin_job_detail.html").read_text(encoding="utf-8")
    assert '<progress max="{{ job.progress.total }}"' in jobs
    assert '<progress max="{{ latest_run.progress.total }}"' in detail


def test_migration_0287_adds_fenced_progress_counts():
    migration = importlib.import_module("apps.core.migrations.0287_jobs_progress_counts")
    sql = migration.FORWARD_SQL
    assert "ADD COLUMN progress_done BIGINT" in sql
    assert "claim_token = p_claim_token" in sql  # only the claiming worker records
    assert "LEAST(p_done, p_total)" in sql
    assert "TO ninja_ingest;" in sql
    assert migration.Migration.dependencies == [("operations", "0286_software_inventory_policy")]


def test_the_computer_page_lists_only_installed_software_and_shows_removals_apart():
    source = (Path(__file__).resolve().parents[1] / "views.py").read_text(encoding="utf-8")
    template = (_TEMPLATES / "device_detail.html").read_text(encoding="utf-8")
    assert "AND installation.stale_since IS NULL" in source
    assert "FROM operations.software_inventory_devices" in source
    assert "Removed software (" in template
    assert "Ninja collected this list" in template
    assert views._software_removal_reason("ninja.inventory.not_listed") == "No longer listed by Ninja"
