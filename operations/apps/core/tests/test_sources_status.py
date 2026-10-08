from datetime import datetime, timedelta, timezone

from apps.core.views import _source_is_stale


def test_source_staleness_respects_each_configured_cadence():
    now = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)

    assert not _source_is_stale(now - timedelta(hours=47), 24 * 60, now)
    assert _source_is_stale(now - timedelta(hours=49), 24 * 60, now)
    assert not _source_is_stale(now - timedelta(hours=7, minutes=59), 60, now)
    assert _source_is_stale(now - timedelta(hours=8, minutes=1), 60, now)


def test_sources_template_labels_transition_history_clearly():
    from django.template.loader import get_template

    template = get_template("sources.html")
    assert "previous schedule" in template.template.source
    assert "Current schedule" in template.template.source
