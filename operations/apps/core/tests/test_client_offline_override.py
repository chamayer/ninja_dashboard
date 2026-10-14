"""A client may set its own "offline after" days on its Configuration tab."""

from __future__ import annotations

import importlib
from pathlib import Path

from apps.core.models import Client

_ROOT = Path(__file__).resolve().parents[3]
_VIEWS = (_ROOT / "apps" / "core" / "views.py").read_text(encoding="utf-8")
_TEMPLATE = (_ROOT / "templates" / "client_requirements_config.html").read_text(encoding="utf-8")


def test_the_field_is_optional_so_the_default_applies_until_it_is_set():
    field = Client._meta.get_field("offline_after_days")
    assert field.null and field.blank


def test_migration_only_adds_a_nullable_column_after_the_previous_migration():
    migration = importlib.import_module("apps.core.migrations.0294_client_offline_after_days")
    assert migration.Migration.dependencies == [("operations", "0293_software_title_main_publisher")]
    (operation,) = migration.Migration.operations
    assert operation.__class__.__name__ == "AddField"
    assert operation.field.null is True


def test_the_page_validates_audits_and_caps_the_override_below_retirement_review():
    assert 'action == "offline_after"' in _VIEWS or 'elif action == "offline_after"' in _VIEWS
    assert 'policy["retire_review_days"] - 1' in _VIEWS
    assert '"client.offline_after_days.update"' in _VIEWS
    assert 'name="offline_after_days"' in _TEMPLATE
    assert "device_policy.retire_review_days|add:-1" in _TEMPLATE
    assert "Leave empty to use the default" in _TEMPLATE
