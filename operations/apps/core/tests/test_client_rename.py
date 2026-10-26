"""A client renamed at its sources is renamed here; recorded and undoable."""

from __future__ import annotations

import importlib
from pathlib import Path

from django.template.loader import get_template
from django.urls import reverse

migration = importlib.import_module("apps.core.migrations.0347_client_rename")
_ROOT = Path(__file__).resolve().parents[3]


def test_a_rename_is_one_recorded_change_that_keeps_the_old_name_matching():
    sql = " ".join(migration.FORWARD_SQL.split())
    assert "'client.rename', v_reason" in sql
    assert "jsonb_build_object('client_id', p_client_id, 'from', v_old, 'to', v_new)" in sql
    # The old name stays an alias; the slug is not touched.
    assert "INSERT INTO operations.client_name_aliases" in sql
    assert "SET display_name = v_new" in sql and "slug =" not in sql
    assert "another client already uses that name" in sql
    assert "TO ninja_ingest, operations_app" in sql


def test_the_client_page_offers_rename_and_undo():
    get_template("org_index.html")
    page = (_ROOT / "templates" / "org_index.html").read_text(encoding="utf-8")
    assert "{% url 'client_rename' org_slug=current_client.slug %}" in page
    assert 'name="undo" value="1"' in page and "last_rename.automatic" in page
    assert reverse("client_rename", kwargs={"org_slug": "prompt"}) == "/clients/prompt/rename/"
