"""An operator can split a merge from the Computer page (ADR-0032 undo, ADR-0040 audit)."""

from __future__ import annotations

import inspect
import uuid
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from django.core.exceptions import PermissionDenied
from django.template.loader import get_template
from django.test import RequestFactory
from django.urls import reverse

from apps.core import views

MERGE = uuid.uuid4()
SURVIVOR, ABSORBED = uuid.uuid4(), uuid.uuid4()
_ROOT = Path(__file__).resolve().parents[3]


def _split(data, may=True):
    request = RequestFactory().post(reverse("computer_merge_split", args=[MERGE]), data)
    request.user = SimpleNamespace(pk=7)
    cursor = mock.MagicMock()
    cursor.fetchone.return_value = (SURVIVOR, ABSORBED)
    with (
        mock.patch.object(views, "can_manage_lifecycle", return_value=may),
        mock.patch.object(views.connection, "cursor", return_value=nullcontext(cursor)),
        mock.patch.object(views.transaction, "atomic", return_value=nullcontext()),
        mock.patch.object(views.computer_naming, "name_now") as name_now,
        mock.patch.object(views, "messages") as messages,
    ):
        inspect.unwrap(views.computer_merge_split)(request, str(MERGE))
    return cursor, name_now, messages


def test_split_runs_the_recorded_undo_and_names_both_computers_again():
    cursor, name_now, messages = _split({"reason": "two machines after all"})
    sql, params = cursor.execute.call_args_list[-1].args
    assert "operations.split_computer_merge" in sql and "'operator'" in sql
    assert params == (str(MERGE), "two machines after all", 7)
    name_now.assert_called_once_with(cursor, [SURVIVOR, ABSORBED])
    messages.success.assert_called_once()


def test_split_needs_lifecycle_permission_and_a_reason():
    with pytest.raises(PermissionDenied):
        _split({"reason": "x"}, may=False)
    cursor, _, messages = _split({})
    cursor.execute.assert_not_called()
    messages.error.assert_called_once()


def test_the_computer_page_lists_open_merges_with_a_split_form():
    get_template("device_detail.html")
    page = (_ROOT / "templates" / "device_detail.html").read_text(encoding="utf-8")
    assert 'id="merged-computers"' in page
    assert "{% url 'computer_merge_split' merge.id %}" in page
    assert "{% if can_manage_lifecycle %}" in page
