"""Automatic client mappings are recorded and a source group can be moved (ADR-0040)."""

from __future__ import annotations

import importlib
import inspect
import uuid
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.db import DatabaseError
from django.template.loader import get_template
from django.test import RequestFactory
from django.urls import reverse

from apps.core import views

migration = importlib.import_module("apps.core.migrations.0341_client_source_group_move")
SQL = " ".join(migration.FORWARD_SQL.split())
_ROOT = Path(__file__).resolve().parents[3]
TARGET = str(uuid.UUID(int=9))


def _bulk(data, cursor=None):
    request = RequestFactory().post(reverse("client_mapping_bulk"), data)
    request.user = SimpleNamespace(pk=7)
    cursor = cursor or mock.MagicMock()
    with (
        mock.patch.object(views.connection, "cursor", return_value=nullcontext(cursor)),
        mock.patch.object(views.transaction, "atomic", return_value=nullcontext()),
        mock.patch.object(views, "messages") as messages,
    ):
        response = inspect.unwrap(views.client_mapping_bulk)(request)
    return response, cursor, messages


def test_the_resolver_records_only_where_no_decision_exists():
    assert "'automatic', 'resolver'" in SQL
    assert "AND superseded_at IS NULL) THEN RETURN false;" in SQL
    assert (
        "GRANT EXECUTE ON FUNCTION operations.record_automatic_client_mapping_v1(bigint, uuid, text)"
        " TO ninja_ingest;" in SQL
    )


def test_a_move_takes_the_link_its_history_records_alias_and_computers_with_it():
    for statement in (
        "UPDATE operations.entity_source_links SET entity_id = p_client_id",
        "UPDATE operations.entity_source_link_history SET effective_to",
        "INSERT INTO operations.entity_source_link_history",
        "PERFORM operations.decide_client_source_mapping_v1( p_tenant_id, l.id, 'explicit'",
        "UPDATE operations.client_name_aliases SET client_id = p_client_id",
        "PERFORM operations.move_computer_to_client(v_device, p_client_id",
        "'operator', p_actor_id, 'operations.ui'",
    ):
        assert statement in SQL, statement
    # Device records already on another client are not swept along.
    assert "AND client_id = l.entity_id;" in SQL
    assert (
        "GRANT EXECUTE ON FUNCTION operations.move_client_source_group_v1"
        "(bigint, uuid, uuid, text, bigint) TO operations_app;" in SQL
    )


def test_bulk_confirm_and_ignore_record_one_decision_per_selected_group():
    ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    _, cursor, messages = _bulk({"link_ids": ids, "action": "ignore", "reason": "test org"})
    calls = [c.args for c in cursor.execute.call_args_list[1:]]
    assert [args[1] for args in calls] == [[i, "ignored", "test org", 7] for i in ids]
    assert "decide_client_source_mapping_v1" in calls[0][0]
    messages.success.assert_called_once()


def test_bulk_move_reports_computers_moved_and_left_for_review():
    cursor = mock.MagicMock()
    cursor.fetchone.return_value = (
        {"records": 15, "computers_moved": 2, "computers_mixed": 12, "to_client": "Starfire"},
    )
    _, cursor, messages = _bulk(
        {
            "link_ids": [str(uuid.uuid4())],
            "action": "move",
            "client_id": TARGET,
            "reason": "spinoff",
        },
        cursor,
    )
    assert "move_client_source_group_v1" in cursor.execute.call_args_list[1].args[0]
    note = messages.success.call_args.args[1]
    assert "moved to Starfire; 2 Computers" in note and "12 Computers" in note


def test_bulk_refuses_without_a_reason_or_a_destination_and_reports_a_refused_row():
    _, cursor, messages = _bulk({"link_ids": [str(uuid.uuid4())], "action": "move", "reason": "x"})
    cursor.execute.assert_not_called()
    messages.error.assert_called_once()
    _, cursor, messages = _bulk({"link_ids": [str(uuid.uuid4())], "action": "confirm"})
    cursor.execute.assert_not_called()
    failing = mock.MagicMock()
    failing.execute.side_effect = [None, DatabaseError("move_client_source_group: nope\nCONTEXT")]
    _, _, messages = _bulk(
        {"link_ids": [str(uuid.uuid4())], "action": "move", "client_id": TARGET, "reason": "x"},
        failing,
    )
    assert messages.error.call_args.args[1] == "Nothing was changed: move_client_source_group: nope"


def test_the_client_page_selects_one_several_or_all_source_references():
    get_template("org_index.html")
    page = (_ROOT / "templates" / "org_index.html").read_text(encoding="utf-8")
    assert 'id="mapping-select-all"' in page
    assert 'class="mapping-cb" name="link_ids"' in page and 'form="mapping-bulk"' in page
    assert "{% url 'client_mapping_bulk' %}" in page
    for value in ("confirm", "move", "ignore"):
        assert f'<option value="{value}">' in page
