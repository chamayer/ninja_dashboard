from __future__ import annotations

from pathlib import Path

from shared import software_settings as ss

_ROOT = Path(__file__).resolve().parents[2]


def test_defaults_cover_every_field_and_mirror_legacy_names():
    values = ss.effective({})
    for field in ss.FIELDS:
        assert values[field.key] == field.default
    assert values["rare_max_devices"] == 2
    assert values["rare_recent_max_devices"] == 2  # read by the previous classifier
    assert values["recent_days"] == values["rare_recent_max_age_days"] == 7


def test_stored_legacy_value_is_honoured_until_the_canonical_key_is_saved():
    assert ss.effective({"rare_recent_max_devices": 5})["rare_max_devices"] == 5
    both = ss.effective({"rare_recent_max_devices": 5, "rare_max_devices": 3})
    assert both["rare_max_devices"] == 3
    assert both["rare_recent_max_devices"] == 3


def test_unknown_stored_keys_pass_through():
    assert ss.effective({"some_future_key": "x"})["some_future_key"] == "x"


def test_saving_merges_and_never_drops_keys_the_form_does_not_show():
    stored = {"whitelist_suggestion_min_devices": 10, "rare_max_devices": 2}
    merged = ss.merge(stored, {"rare_max_devices": 4})
    assert merged == {"whitelist_suggestion_min_devices": 10, "rare_max_devices": 4}
    assert stored == {"whitelist_suggestion_min_devices": 10, "rare_max_devices": 2}


def test_form_values_are_validated_and_clamped():
    values = ss.parse_form(
        {
            "rare_max_devices": "500",
            "recent_days": "not a number",
            "vulnerable_software_cvss_cutoff": "-3",
            "rare_recent_severity": "catastrophic",
            "non_approved_severity": "high",
            "rare_enabled": "on",
        }
    )
    assert values["rare_max_devices"] == 100
    assert values["recent_days"] == 7
    assert values["vulnerable_software_cvss_cutoff"] == 0.0
    assert values["rare_recent_severity"] == "medium"
    assert values["non_approved_severity"] == "high"
    assert values["rare_enabled"] is True
    assert values["non_approved_enabled"] is False  # unchecked box


def test_every_section_has_fields_and_numeric_fields_have_ranges():
    sections = ss.sections()
    assert sections and all(fields for _, fields in sections)
    for field in ss.FIELDS:
        if field.kind in {"int", "float"}:
            assert field.minimum is not None and field.maximum is not None
        if field.kind == "severity":
            assert field.default in ss.SEVERITIES


def test_admin_page_merges_validates_and_audits():
    views = (_ROOT / "operations" / "apps" / "core" / "views.py").read_text(encoding="utf-8")
    body = views[views.index("def classifier_config(") :]
    body = body[: body.index("\ndef ", 1)]
    assert "software_settings.merge(stored, software_settings.parse_form(request.POST))" in body
    assert '"evaluator_config.update"' in body
    assert "row.config = new_cfg" not in body


def test_the_findings_run_and_inventory_read_the_shared_settings():
    for name in ("software_reconcile.py", "inventory/software.py"):
        source = (_ROOT / "ingest" / name).read_text(encoding="utf-8")
        assert "software_settings.effective(" in source, name
