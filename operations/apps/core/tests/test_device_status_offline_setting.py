"""The Device status page owns the single "offline after" definition."""

from __future__ import annotations

from pathlib import Path

from apps.core import device_status

_ROOT = Path(__file__).resolve().parents[3]


def test_defaults_are_seven_days_offline_and_thirty_to_review_retirement():
    assert device_status.DEFAULTS["active_device_days"] == 7
    assert device_status.DEFAULTS["retire_review_days"] == 30


def test_retirement_review_always_comes_after_offline(monkeypatch):
    class _Values:
        def filter(self, **_kwargs):
            return self

        def values_list(self, *_args, **_kwargs):
            return self

        def first(self):
            return {"active_device_days": 40, "retire_review_days": 30}

    monkeypatch.setattr(device_status.EvaluatorConfig, "objects", _Values())
    policy = device_status.get_device_status_policy()
    assert policy["active_device_days"] == 40
    assert policy["retire_review_days"] == 41


def test_page_offers_both_settings_and_says_patch_staleness_is_not_offline():
    template = (_ROOT / "templates" / "device_status_config.html").read_text(encoding="utf-8")
    views = (_ROOT / "apps" / "core" / "views.py").read_text(encoding="utf-8")
    assert 'name="retire_review_days"' in template
    assert "Offline after" in template and "Review for retirement after" in template
    assert "not about a computer being offline" in template
    assert '"retire_review_days": (2, 365)' in views
