"""The Finding state checks page and the cleanup migration (0303)."""

from __future__ import annotations

import importlib
from pathlib import Path

from django.template.loader import get_template
from django.urls import reverse

_CLEANUP = importlib.import_module("apps.core.migrations.0303_drop_attention_view_and_columns")
_APP = Path(__file__).resolve().parents[1]
_MODELS = (_APP / "models.py").read_text(encoding="utf-8")


def test_the_page_is_routed_and_its_template_compiles():
    assert reverse("finding_state_checks") == "/admin/finding-state-checks/"
    get_template("finding_state_checks.html")


def test_the_settings_page_links_to_it():
    template = (_APP.parents[1] / "templates" / "admin_settings.html").read_text(encoding="utf-8")
    assert "finding_state_checks" in template


def test_the_cleanup_removes_every_old_object_and_nothing_current():
    sql = _CLEANUP.FORWARD_SQL
    for dropped in (
        "DROP VIEW IF EXISTS operations.finding_states",
        "DROP FUNCTION IF EXISTS operations.refresh_finding_attention(uuid[])",
        "DROP FUNCTION IF EXISTS operations.compute_finding_attention(uuid[])",
        "DROP TABLE IF EXISTS operations.finding_attention_drift",
        "DROP COLUMN IF EXISTS attention",
    ):
        assert dropped in sql
    assert "DROP TABLE IF EXISTS operations.finding_state;" not in sql
    assert "refresh_finding_state" not in sql


def test_the_old_models_and_columns_are_gone_from_the_code():
    assert "class FindingState(" not in _MODELS
    assert "class StoredFindingState(" in _MODELS
    finding_class = _MODELS.split("class Finding(")[1].split("\nclass ")[0]
    assert "attention_at" not in finding_class
