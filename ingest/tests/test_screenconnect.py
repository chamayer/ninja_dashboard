"""ScreenConnect client isolation and source identity contracts."""

from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID

import httpx
import pytest

from ingest.connectors import screenconnect
from ingest.sources import SourceConfig


def _source(**changes):
    source = SourceConfig(
        platform="ScreenConnect",
        source_key="sc-test",
        source_name="ScreenConnect",
        is_shared=False,
        enabled=True,
        base_url="https://remote.example",
        token_url=None,
        api_token=None,
        client_id_value=None,
        client_secret=None,
        ext_guid="test-extension",
        secret_key="test-only",
        company_id=None,
        psk=None,
        ops_source_id=3,
        source_instance_id=UUID(int=1),
        source_binding_id=UUID(int=2),
        entity_type="agent.remote_access",
        client_id=UUID(int=3),
        client_name="Acme",
    )
    return replace(source, **changes)


def _fetch(monkeypatch, source, sessions):
    real_client = httpx.Client

    def respond(request):
        assert request.url.path.endswith("/GetSessionsByFilter")
        return httpx.Response(200, json=sessions)

    monkeypatch.setattr(
        screenconnect.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    return screenconnect.fetch(source, datetime(2026, 10, 27, tzinfo=timezone.utc))


def _session(session_id, group=None, **changes):
    return {
        "SessionID": session_id,
        "Name": "PC-01",
        "CustomProperties": {"CustomProperty1": group},
        "GuestInfo": {"OperatingSystemName": "Windows 11"},
        **changes,
    }


def test_scoped_source_preserves_instance_identity_and_duplicate_sessions(monkeypatch):
    source = _source()
    rows = _fetch(
        monkeypatch, source, [_session("1", "Other"), _session("2", "Elsewhere")]
    )
    assert len(rows) == 2
    for row in rows:
        assert row["container_external_namespace"] == "source-instance"
        assert row["container_external_id"] == "self"
        assert row["platform_group_id"] == str(source.client_id)
        assert row["platform_group_name"] == "Acme"
        assert row["raw_data"].obj["IsDup"] is True


def test_shared_groups_keep_customer_boundaries_and_unassigned_evidence(monkeypatch):
    source = _source(
        is_shared=True,
        client_id=None,
        client_name=None,
        screenconnect_group_field="CustomProperty1",
    )
    rows = _fetch(
        monkeypatch,
        source,
        [
            _session("1", " Acme "),
            _session("2", "Beta"),
            _session("3", "Acme"),
            _session("4"),
            _session("5", "Acme", IsDeleted=True),
            _session("6", "Acme", IsEnded=True),
        ],
    )
    assert [row["platform_device_id"] for row in rows] == ["1", "2", "3", "4"]
    assert [row["platform_group_id"] for row in rows] == ["Acme", "Beta", "Acme", ""]
    assert [row["raw_data"].obj["IsDup"] for row in rows] == [True, False, True, False]
    assert all(row["source_client_name"] is None for row in rows)
    assert all(row["container_external_namespace"] == "customproperty1" for row in rows)
    assert all(row["container_external_id"] == row["platform_group_id"] for row in rows)
    assert all(row["external_namespace"] == "access-session" for row in rows)


def test_shared_source_uses_selected_property_and_array_fallback(monkeypatch):
    source = _source(
        is_shared=True,
        client_id=None,
        client_name=None,
        screenconnect_group_field="CustomProperty2",
    )
    rows = _fetch(
        monkeypatch,
        source,
        [
            _session("1", "Wrong", CustomPropertyValues=["Wrong", "Acme"]),
            _session("2", CustomProperties={"CustomProperty2": "Beta"}),
            _session(
                "3",
                CustomProperties={"CustomProperty2": ""},
                CustomPropertyValues=["Wrong", "Stale value"],
            ),
        ],
    )
    assert [row["platform_group_name"] for row in rows] == ["Acme", "Beta", ""]
    assert all(row["container_external_namespace"] == "customproperty2" for row in rows)


@pytest.mark.parametrize(
    "changes",
    [
        {"is_shared": True},
        {"is_shared": True, "client_id": None},
        {"is_shared": True, "client_id": None, "screenconnect_group_field": "Company"},
        {"client_name": None},
    ],
)
def test_invalid_scope_fails_before_contacting_source(monkeypatch, changes):
    def unexpected_request(**kwargs):
        pytest.fail("Invalid source scope must fail before HTTP access")

    monkeypatch.setattr(screenconnect.httpx, "Client", unexpected_request)
    with pytest.raises(RuntimeError):
        screenconnect.fetch(_source(**changes), datetime.now(timezone.utc))


def test_malformed_response_is_not_accepted_as_a_snapshot(monkeypatch):
    with pytest.raises(RuntimeError, match="list of session objects"):
        _fetch(monkeypatch, _source(), {"error": "not a session list"})
