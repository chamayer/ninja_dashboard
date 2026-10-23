"""All repeated finding evaluations must refresh the current evaluation fields."""

from pathlib import Path


ROOT = Path(__file__).parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_evaluator_refreshes_evaluable_fields_but_preserves_episode_state():
    source = _source("evaluator.py")
    start = source.index("def _upsert_finding")
    section = source[start:source.find("\ndef ", start + 4)]

    assert "Severity is immutable" not in section
    for field in ("client_id", "subject_id", "finding_details", "severity", "confidence"):
        assert f"{field}" in section and f"EXCLUDED.{field}" in section
    assert "first_seen_at" not in section.split("DO UPDATE SET", 1)[1]


def test_platform_findings_refresh_severity_and_current_subject_reference():
    source = _source("platform_findings.py")
    section = source[source.index("def _upsert_admin_finding"):source.index("def _record_platform_assessment")]

    assert "subject_ref = EXCLUDED.subject_ref" in section
    assert "severity = EXCLUDED.severity" in section
    assert 'severity="critical"' in source


def test_cmdb_patch_and_identity_producers_refresh_current_evaluation_fields():
    cmdb = _source("cmdb_findings.py")
    patch = _source("patch_findings.py")
    identity = _source("identity/findings.py")
    resolver = _source("identity/resolver.py")

    for source in (cmdb, patch, identity):
        assert "severity         = EXCLUDED.severity" in source
        assert "confidence       = EXCLUDED.confidence" in source
    assert "'unmatched_source_group:'" in resolver
    assert "'critical', 'confirmed', 'open'" in resolver
    # cross_client_serial moved to identity/findings.py as computer_client_conflict (ADR-0040).
    assert resolver.count("severity = EXCLUDED.severity") >= 6
