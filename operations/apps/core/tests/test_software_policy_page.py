from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.core import software_policy

_ROOT = Path(__file__).resolve().parents[3]
_SOURCE = (_ROOT / "apps" / "core" / "software_policy.py").read_text(encoding="utf-8")
_TEMPLATE = (_ROOT / "templates" / "software_policy_config.html").read_text(encoding="utf-8")


def test_every_change_is_staff_only_and_audited():
    assert 'if not request.user.is_staff:' in _SOURCE
    assert "HttpResponseForbidden" in _SOURCE
    for action in ("finding_type.policy_update", "software_rule.add", "software_rule.toggle",
                   "software_suggestion_rule.update", "software_inventory.release_hold"):
        assert f'"{action}"' in _SOURCE


@pytest.mark.parametrize("pattern", ["(unclosed", "[a-"])
def test_invalid_regex_rules_are_refused(monkeypatch, pattern):
    created = []
    monkeypatch.setattr(
        software_policy.SoftwareClassifierRule.objects, "get_or_create",
        lambda **kw: created.append(kw) or (None, True),
    )
    request = SimpleNamespace(POST={"rule_type": "suspicious_name", "pattern": pattern, "is_regex": "on"})
    error = software_policy._add_rule(request)
    assert "not a valid regular expression" in error
    assert not created


def test_table_rows_bind_controls_with_form_attributes_not_nested_forms():
    assert "<tr>\n            <form" not in _TEMPLATE
    assert _TEMPLATE.count('form="type-{{ ft.id }}"') == 5
    assert _TEMPLATE.count('form="suggestion-{{ rule.id }}"') == 5


def test_held_computers_are_listed_with_a_release_action():
    assert "Computers with held removals" in _TEMPLATE
    assert 'name="action" value="release_hold"' in _TEMPLATE
    assert "WHERE s.tenant_id = 1 AND s.held_at IS NOT NULL" in software_policy.HELD_SQL
    # The refresh runs only after the release is committed, so the worker sees it.
    assert "transaction.on_commit(_refresh_now)" in _SOURCE


def test_page_is_reachable_from_settings_and_admin_tabs():
    urls = (_ROOT / "config" / "urls.py").read_text(encoding="utf-8")
    assert 'path("admin/software-policy/", software_policy_config, name="software_policy_config")' in urls
    settings_page = (_ROOT / "templates" / "admin_settings.html").read_text(encoding="utf-8")
    tabs = (_ROOT / "templates" / "_admin_tabs.html").read_text(encoding="utf-8")
    assert "{% url 'software_policy_config' %}" in settings_page
    assert "{% url 'software_policy_config' %}" in tabs
