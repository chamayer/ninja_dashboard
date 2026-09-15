from __future__ import annotations

import json
from contextlib import nullcontext
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.conditions import reader
from apps.core.conditions.policy import load_profile


def test_catalog_command_never_accesses_database(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("catalog-only must not access database")

    from apps.core.management.commands import compare_conditions

    monkeypatch.setattr(compare_conditions, "read_snapshot", fail)
    output = StringIO()
    call_command("compare_conditions", tenant_id=1, catalog_only=True, stdout=output)
    result = json.loads(output.getvalue())
    assert result["mode"] == "catalog_only"
    assert len(result["definitions"]) == 53


def test_command_has_no_apply_mode():
    with pytest.raises((CommandError, TypeError)):
        call_command("compare_conditions", tenant_id=1, apply=True)


def test_command_rejects_invalid_tenant():
    with pytest.raises(CommandError):
        call_command("compare_conditions", tenant_id=0, catalog_only=True)


def test_reader_refuses_sqlite_and_existing_transactions():
    for vendor, atomic in [("sqlite", False), ("postgresql", True)]:
        with pytest.raises(ValueError, match="PostgreSQL"):
            reader.read_snapshot(
                SimpleNamespace(vendor=vendor, in_atomic_block=atomic), 1, load_profile()
            )


def test_reader_sets_read_only_and_tenant_before_data_and_rolls_back(monkeypatch):
    conn = MagicMock(vendor="postgresql", in_atomic_block=False, alias="default")
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.side_effect = [(1,), ("time",)]
    calls = []
    monkeypatch.setattr(reader.transaction, "atomic", lambda **kwargs: nullcontext())
    rollback = MagicMock()
    monkeypatch.setattr(reader.transaction, "set_rollback", rollback)

    def rows(cursor, statement, params, limit):
        calls.append((statement, params))
        return []

    monkeypatch.setattr(reader, "_rows", rows)
    reader.read_snapshot(conn, 7, load_profile())
    assert cur.execute.call_args_list[0].args == (
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
    )
    assert cur.execute.call_args_list[1].args[1] == ("7",)
    assert len(calls) == 7
    for statement, params in calls:
        if statement != reader.REGISTRY_SQL:
            assert 7 in params
    rollback.assert_called_once_with(True, using="default")


def test_row_limit_fails_instead_of_reporting_partial_success():
    cur = MagicMock()
    cur.description = [("name",)]
    cur.fetchmany.return_value = [("a",), ("b",)]
    with pytest.raises(ValueError, match="no partial report"):
        reader._rows(cur, "SELECT name", (), 1)


def test_database_error_does_not_print_connection_or_payload(monkeypatch):
    from django.db import DatabaseError

    from apps.core.management.commands import compare_conditions

    def fail(*args, **kwargs):
        raise DatabaseError("private connection secret")

    monkeypatch.setattr(compare_conditions, "read_snapshot", fail)
    with pytest.raises(CommandError) as caught:
        call_command("compare_conditions", tenant_id=1)
    assert "private" not in str(caught.value)


def test_dockerfile_copies_profile_and_command():
    from pathlib import Path

    root = Path(__file__).resolve().parents[4]
    assert "COPY operations/apps/" in (root / "operations.Dockerfile").read_text()
    assert (root / "operations/apps/core/conditions/profile.json").is_file()
