"""Automatic client promotion: recorded, listed for verification, adjustable (ADR-0041)."""

from __future__ import annotations

import importlib
import inspect
import uuid
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.template.loader import get_template
from django.test import RequestFactory
from django.urls import reverse

from apps.core import views

migration = importlib.import_module("apps.core.migrations.0342_automatic_client_promotion")
SQL = " ".join(migration.FORWARD_SQL.split())
_ROOT = Path(__file__).resolve().parents[3]


def _post(view, url_name, data, promotions=()):
    request = RequestFactory().post(reverse(url_name), data)
    request.user = SimpleNamespace(pk=7, get_username=lambda: "operator")
    cursor = mock.MagicMock()
    with (
        mock.patch.object(views.connection, "cursor", return_value=nullcontext(cursor)),
        mock.patch.object(views.transaction, "atomic", return_value=nullcontext()),
        mock.patch.object(views, "_automatic_promotions", return_value=list(promotions)),
        mock.patch.object(views, "messages") as messages,
    ):
        inspect.unwrap(view)(request)
    return cursor, messages


def _promotion(created=True, groups=(), may_retire=False):
    client = SimpleNamespace(save=mock.Mock(), entity_id=uuid.uuid4(), verified_at=None)
    return {
        "candidate": SimpleNamespace(id=uuid.uuid4()),
        "client": client,
        "created": created,
        "groups": list(groups),
        "unconfirmed": list(groups),
        "may_retire": may_retire,
    }


def test_promotion_is_one_recorded_change_that_creates_a_provisional_client_or_maps():
    assert "PERFORM operations.begin_change( 'client.promote'" in SQL
    assert "INSERT INTO operations.entities (" in SQL and "'client', 'tenant'" in SQL
    assert "provisional_since, provisional_reason, verified_at, verified_by)" in SQL
    assert "c.normalized_name, 'source', true, now(), 'resolver', v_reason" in SQL
    assert "THEN 'accepted' ELSE 'mapped' END" in SQL and "resolved_by = 'resolver'" in SQL
    # The required source lives in admin settings, not code.
    assert '"create_required_source": "Ninja"' in SQL
    assert "TO ninja_ingest;" in SQL


def test_verify_confirms_each_unconfirmed_group_and_marks_a_created_client_verified():
    group = {"source_link_id": uuid.uuid4()}
    promotion = _promotion(groups=[group])
    cursor, messages = _post(
        views.client_promotions_decide,
        "client_promotions_decide",
        {"candidate_ids": [str(promotion["candidate"].id)], "action": "verify", "reason": "ok"},
        [promotion],
    )
    sql = [call.args[0] for call in cursor.execute.call_args_list]
    assert any("decide_client_source_mapping_v1(1, %s, 'explicit'" in q for q in sql)
    assert promotion["client"].verified_by == "operator"
    messages.success.assert_called_once()


def test_retire_is_refused_while_a_client_still_has_groups_or_computers():
    promotion = _promotion(groups=[{"source_link_id": uuid.uuid4()}])
    cursor, messages = _post(
        views.client_promotions_decide,
        "client_promotions_decide",
        {"candidate_ids": [str(promotion["candidate"].id)], "action": "retire", "reason": "x"},
        [promotion],
    )
    cursor.execute.assert_not_called()
    messages.error.assert_called_once()


def test_settings_are_saved_as_admin_managed_config():
    row = SimpleNamespace(config={}, save=mock.Mock())
    with mock.patch.object(views.EvaluatorConfig, "objects") as configs:
        configs.get_or_create.return_value = (row, False)
        _post(
            views.client_promotion_settings,
            "client_promotion_settings",
            {
                "map_enabled": "on",
                "map_min_names": "3",
                "create_min_sources": "2",
                "create_required_source": "Ninja",
                "min_seen_runs": "2",
            },
        )
    assert row.config == {
        "map_enabled": True,
        "map_min_names": 3,
        "create_enabled": False,
        "create_min_sources": 2,
        "create_required_source": "Ninja",
        "min_seen_runs": 2,
    }


def test_inventory_lists_promotions_and_the_settings_live_under_admin_settings():
    get_template("inventory_clients.html")
    get_template("client_promotion_settings.html")
    page = (_ROOT / "templates" / "inventory_clients.html").read_text(encoding="utf-8")
    assert 'id="promoted-clients"' in page and 'id="promotion-select-all"' in page
    assert "{% url 'client_promotions_decide' %}" in page
    assert "client_promotion_settings" not in page
    settings_page = (_ROOT / "templates" / "admin_settings.html").read_text(encoding="utf-8")
    assert "{% url 'client_promotion_settings' %}" in settings_page
    assert reverse("client_promotion_settings") == "/admin/client-matching/"
