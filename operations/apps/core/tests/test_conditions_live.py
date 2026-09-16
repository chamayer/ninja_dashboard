"""The Operations policy reader accepts both PostgreSQL JSONB result shapes."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from apps.core.conditions import live


@pytest.mark.parametrize("as_text", [False, True])
def test_active_policy_raw_sql_result_is_parsed(monkeypatch, as_text):
    profile_path = Path(__file__).resolve().parents[4] / "shared" / "conditions" / "profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))

    class Cursor:
        def execute(self, query):
            assert "condition_policy_versions" in query

        def fetchone(self):
            digest = hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()
            return (profile["version"], digest, json.dumps(profile) if as_text else profile)

    @contextmanager
    def cursor():
        yield Cursor()

    monkeypatch.setattr(live.connection, "cursor", cursor)
    assert live.load_active_profile().version == profile["version"]


def test_active_policy_reader_requires_current_active_policy_and_digest(monkeypatch):
    class Cursor:
        def __init__(self):
            self.query = ""

        def execute(self, query):
            self.query = query

        def fetchone(self):
            digest = hashlib.sha256(b"{}").hexdigest()
            return ("v1", digest, "{}")

    cursor_instance = Cursor()

    @contextmanager
    def cursor():
        yield cursor_instance

    monkeypatch.setattr(live.connection, "cursor", cursor)
    with pytest.raises(ValueError):
        live.load_active_profile()
    assert "WHERE active" in cursor_instance.query
    assert "SELECT version, digest, policy" in cursor_instance.query
