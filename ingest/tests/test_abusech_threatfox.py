"""ThreatFox reads the authenticated community API, not the retired export.

The `threatfox.abuse.ch/export/json/recent/` export began returning
`410 Gone` on 2026-10-21 (PLAN-037 Step 2). The API returns a list of IOC
records under `data`, so the matcher must iterate that list directly.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from pydantic import SecretStr

for _name, _value in {
    "NINJA_BASE_URL": "https://example.invalid",
    "NINJA_TOKEN_URL": "https://example.invalid/token",
    "NINJA_CLIENT_ID": "test",
    "NINJA_CLIENT_SECRET": "test",
    "POSTGRES_USER": "test",
    "POSTGRES_PASSWORD": "test",
}.items():
    os.environ.setdefault(_name, _value)

from ingest.intel import abusech  # noqa: E402


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _Client:
    calls: list[dict[str, Any]] = []
    payload: dict[str, Any] = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> "_Client":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def post(self, url: str, headers: dict[str, str], json: dict[str, Any]) -> _Response:
        _Client.calls.append({"url": url, "headers": headers, "json": json})
        return _Response(_Client.payload)


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> type[_Client]:
    _Client.calls = []
    monkeypatch.setattr(abusech.httpx, "Client", _Client)
    monkeypatch.setattr(abusech.settings, "ABUSECH_AUTH_KEY", SecretStr("test-key"))
    return _Client


def test_threatfox_uses_the_authenticated_api(api: type[_Client]) -> None:
    api.payload = {"query_status": "ok", "data": [{"ioc": "evil.example"}]}

    assert abusech._fetch_threatfox() == [{"ioc": "evil.example"}]
    assert "export" not in abusech._TF_API
    (call,) = api.calls
    assert call["url"] == abusech._TF_API
    assert call["headers"] == {"Auth-Key": "test-key"}
    assert call["json"] == {"query": "get_iocs", "days": 7}


def test_threatfox_without_a_key_fails_visibly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(abusech.settings, "ABUSECH_AUTH_KEY", SecretStr(""))

    with pytest.raises(RuntimeError, match="ABUSECH_AUTH_KEY"):
        abusech._fetch_threatfox()


def test_threatfox_no_result_is_empty_and_errors_raise(api: type[_Client]) -> None:
    api.payload = {"query_status": "no_result"}
    assert abusech._fetch_threatfox() == []

    api.payload = {"query_status": "unknown_auth_key"}
    with pytest.raises(RuntimeError):
        abusech._fetch_threatfox()


def test_threatfox_matches_api_records(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        abusech,
        "_fetch_threatfox",
        lambda: [
            {"ioc": "http://anydesk-update.example/x", "malware_printable": "x", "tags": ["t"]},
            {"ioc": "1.2.3.4:443", "malware_printable": "Contoso Loader", "tags": None},
        ],
    )
    monkeypatch.setattr(abusech, "_tracked_names", lambda: (["anydesk"], ["contoso"]))
    captured: list[list[tuple]] = []
    monkeypatch.setattr(abusech, "_upsert_rows", lambda rows: captured.append(rows) or len(rows))

    result = abusech._pull_threatfox()

    (rows,) = captured
    assert [(row[1], row[2]) for row in rows] == [("anydesk", ""), ("", "contoso")]
    assert int(result) == 2
