from pathlib import Path

_SQL = (Path(__file__).resolve().parents[2] / "sql" / "migrations"
        / "115_drop_retired_software_queues.sql").read_text(encoding="utf-8")


def test_only_the_retired_queues_are_dropped():
    assert "DROP TABLE IF EXISTS ninja_core.software_scheduled_queue;" in _SQL
    assert "DROP TABLE IF EXISTS ninja_core.software_demand_queue;" in _SQL
    assert "software_activity_queue;" not in _SQL
    assert "CASCADE" not in _SQL  # nothing depends on them; fail loudly if that changes
    assert "queue_key IN ('software.scheduled', 'software.demand')" in _SQL


def test_no_code_still_uses_the_retired_queues():
    root = Path(__file__).resolve().parents[2]
    for path in (root / "ingest").rglob("*.py"):
        if "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        assert "software_scheduled_queue" not in text, path
        assert "software_demand_queue" not in text, path
