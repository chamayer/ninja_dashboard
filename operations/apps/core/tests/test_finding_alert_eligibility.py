"""Alert eligibility: the registry flag, its admin editor and notifier wiring."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from apps.core import finding_alerts
from apps.core.models import FindingType

_ROOT = Path(__file__).resolve().parents[3]
_INGEST = _ROOT.parent / "ingest"
_SOURCE = (_ROOT / "apps" / "core" / "finding_alerts.py").read_text(encoding="utf-8")


def test_alertable_defaults_off():
    assert FindingType._meta.get_field("alertable").default is False


def test_change_is_staff_only_and_audited():
    assert "if not request.user.is_staff:" in _SOURCE
    assert "HttpResponseForbidden" in _SOURCE
    assert '"finding_type.alertable_update"' in _SOURCE


def test_save_changes_only_differing_types_and_audits_each(monkeypatch):
    saved, audited = [], []

    class Row:
        def __init__(self, id_, alertable):
            self.id, self.name, self.alertable = id_, f"t{id_}", alertable

        def save(self, update_fields):
            saved.append((self.id, self.alertable, update_fields))

    rows = [Row(1, False), Row(2, True), Row(3, True)]
    manager = SimpleNamespace(
        select_for_update=lambda: SimpleNamespace(all=lambda: rows)
    )
    monkeypatch.setattr(finding_alerts.FindingType, "objects", manager)
    monkeypatch.setattr(finding_alerts, "_audit", lambda r, ft, b, a: audited.append((ft.id, b, a)))
    request = SimpleNamespace(POST=SimpleNamespace(getlist=lambda k: ["1", "3", "x"]))
    assert finding_alerts._save_alertable(request) == 2
    assert saved == [(1, True, ["alertable"]), (2, False, ["alertable"])]
    assert audited == [(1, False, True), (2, True, False)]


def test_every_notifier_query_filters_on_alertable():
    notifications = (_INGEST / "notifications.py").read_text(encoding="utf-8")
    digest = (_INGEST / "notifications_digest.py").read_text(encoding="utf-8")
    # still-notifyable entity + admin, candidate selection entity + admin.
    assert notifications.count("{alertable_clause(") == 4
    assert digest.count("{alertable_clause(") == 1


def test_page_is_reachable_from_settings_and_routed():
    urls = (_ROOT / "config" / "urls.py").read_text(encoding="utf-8")
    assert 'name="finding_alert_eligibility"' in urls
    settings_page = (_ROOT / "templates" / "admin_settings.html").read_text(encoding="utf-8")
    assert "{% url 'finding_alert_eligibility' %}" in settings_page
