from pathlib import Path


def test_routine_incremental_classification_uses_complete_device_slices():
    source = Path("ingest/software_findings.py").read_text(encoding="utf-8")

    assert "_INCREMENTAL_DEVICE_BATCH_SIZE = 25" in source
    assert "def _incremental_selection" in source
    assert "target.cursor_device_id" in source
    assert "SELECT device_id FROM candidate_devices ORDER BY device_id LIMIT %s" in source
