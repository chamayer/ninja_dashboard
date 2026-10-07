from pathlib import Path


def test_routine_incremental_classification_uses_complete_device_slices():
    source = Path("ingest/software_findings.py").read_text(encoding="utf-8")

    assert "_INCREMENTAL_DEVICE_BATCH_SIZE = 250" in source
    assert "def _bounded_incremental_scope" in source
    assert "_bounded_incremental_scope(incremental_scope), targeted_scope" in source
    assert "a slice never separates installations from the same device" in source
