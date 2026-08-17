"""Contract for the client context shown beside product authorization scopes."""

from __future__ import annotations

from pathlib import Path


def test_authorization_selector_uses_full_current_installation_counts() -> None:
    """The 500-row device list must not determine authorization scope context."""
    app_root = Path(__file__).resolve().parents[1]
    views_source = (app_root / "views.py").read_text(encoding="utf-8")
    template_source = (app_root.parents[1] / "templates" / "software_detail.html").read_text(
        encoding="utf-8"
    )

    assert "COUNT(DISTINCT sic.device_id)::int AS device_count" in views_source
    assert "COUNT(*)::int AS installation_count" in views_source
    assert "LOWER(sic.canonical_name) = LOWER(%s)" in views_source
    assert "{{ client.device_count }} devices / {{ client.installation_count }} installs" in template_source
