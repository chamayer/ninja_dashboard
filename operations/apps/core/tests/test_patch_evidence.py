from pathlib import Path

from apps.core import views


def test_patch_evidence_choices_match_ninja_stored_values():
    assert all(value == value.upper() for value, _label in views._PATCH_STATUS_CHOICES)
    assert views._PATCH_SEVERITY_VALUES["optional"] == ("OPTIONAL", "optional")


def test_patch_evidence_uses_device_context_filters_and_recent_default():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    template = Path("templates/patch_evidence.html").read_text(encoding="utf-8")

    assert "operations.device_session_current" in source
    assert "patch_state_source" in source
    assert "LIMIT 1000" in source
    assert 'name="online"' in template
    assert 'name="role"' in template
    assert 'name="os_group"' in template
    assert "recent sample" in template
