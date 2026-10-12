"""R-U-ON overview parser and observation shaping (synthetic markup, no network)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ingest.connectors import ruon
from ingest.sources import SourceConfig


def _row(
    agent_id: str, name: str, state: str, last: str = "", kind: str = "ServerOn"
) -> str:
    title = f' title="Last contact at {last}"' if last else ""
    return (
        f'<tr><td><a href="/ctrl?action=agentdetail&amp;agent={agent_id}">{name}</a></td>'
        f"<td>{kind}</td><td>10.0.0.5</td><td>203.0.113.9</td>"
        f"<td{title}>{state}</td></tr>"
    )


def _page(*rows: str) -> str:
    return (
        '<a href="/ctrl?action=logout">Logout</a>'
        "<table><tr><th>Name</th><th>Type</th><th>IP</th><th>Public</th>"
        "<th>State</th></tr>" + "".join(rows) + "</table>"
    )


GROUP_ACME = '<tr><td class="group"><span>Acme  Corp</span></td></tr>'
OVERVIEW = _page(
    GROUP_ACME,
    _row("101", "SRV-APP01", "ON"),
    _row("102", "SRV-OLD&amp;1", "OFF", "Tue, Oct 06 2026, 03:15PM"),
    '<tr><td class="group"><span>Beta</span></td></tr>',
    _row("201", "BETA-DC", "Degraded"),
    _row("301", "BETA-DC-PROC", "ON", kind="ProcessOn"),
)


def _source() -> SourceConfig:
    return SourceConfig(
        platform="R-U-ON",
        source_key="ruon",
        source_name="R-U-ON",
        is_shared=True,
        enabled=True,
        base_url=None,
        token_url=None,
        api_token=None,
        client_id_value="user",
        client_secret="pw",
        ext_guid=None,
        secret_key=None,
        company_id=None,
        psk=None,
        ops_source_id=1,
        source_instance_id=None,
        source_binding_id=None,
        entity_type="agent.monitoring",
        client_id=None,
        client_name=None,
    )


def test_parse_overview_reads_agents_groups_and_decodes_entities():
    agents = ruon.parse_overview(OVERVIEW)
    assert [(a["agent_id"], a["name"], a["group"]) for a in agents] == [
        ("101", "SRV-APP01", "Acme  Corp"),
        ("102", "SRV-OLD&1", "Acme  Corp"),
        ("201", "BETA-DC", "Beta"),
        ("301", "BETA-DC-PROC", "Beta"),
    ]
    assert agents[1]["last_contact_text"] == "Tue, Oct 06 2026, 03:15PM"
    assert agents[0]["last_contact_text"] == ""


@pytest.mark.parametrize(
    "page, message",
    [
        ("<html>login form</html>", "authenticated"),
        (
            '<a href="/ctrl?action=logout">x</a><table></table>',
            "unrecognized agent list",
        ),
    ],
)
def test_parse_overview_refuses_unrecognized_pages(page, message):
    with pytest.raises(RuntimeError, match=message):
        ruon.parse_overview(page)


def test_parse_overview_refuses_malformed_agent_row():
    bad = _page(
        '<tr><td><a href="/ctrl?action=agentdetail&agent=9">X</a></td><td>t</td></tr>'
    )
    with pytest.raises(RuntimeError, match="agent row"):
        ruon.parse_overview(bad)


def test_state_is_never_guessed():
    assert ruon.parse_state("ON") is True
    assert ruon.parse_state(" off ") is False
    assert ruon.parse_state("Degraded") is None


def test_group_id_is_normalized_name():
    assert ruon.group_id_for("  Acme   Corp ") == "acme corp"
    assert ruon.group_id_for(None) == ""


class _FakeClient:
    def __init__(self, *_a, **_k):
        self.cookies = type(
            "J", (), {"jar": [type("C", (), {"name": "JSESSIONID"})()]}
        )()

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def get(self, url, params=None):
        text = OVERVIEW if params else ""
        return type("R", (), {"text": text, "raise_for_status": lambda self: None})()

    def post(self, url, data=None):
        text = "<meta http-equiv='refresh' content='0;url=/ctrl?action=overview'>"
        return type("R", (), {"text": text, "raise_for_status": lambda self: None})()


def test_fetch_shapes_observations_without_guessing(monkeypatch):
    monkeypatch.setattr(ruon.httpx, "Client", _FakeClient)
    rows = ruon.fetch(_source(), datetime(2026, 10, 12, tzinfo=timezone.utc))
    agents = [r for r in rows if not r.get("_org_only")]
    groups = [r for r in rows if r.get("_org_only")]
    assert [r["platform_device_id"] for r in agents] == ["101", "102", "201"]
    assert [r["is_online"] for r in agents] == [True, False, None]
    assert all(r["last_seen_at"] is None for r in agents)
    assert agents[1]["raw_data"].obj["last_contact_text"] == "Tue, Oct 06 2026, 03:15PM"
    assert all(r["device_type"] is None and r["os_name"] is None for r in agents)
    assert {g["platform_group_id"] for g in groups} == {"acme corp", "beta"}
    assert agents[1]["hostname"] == "SRV-OLD&1"


def test_fetch_requires_credentials():
    source = _source()
    object.__setattr__(source, "client_secret", None)
    with pytest.raises(RuntimeError, match="requires"):
        ruon.fetch(source, datetime(2026, 10, 12, tzinfo=timezone.utc))


def test_non_machine_agent_types_are_not_observed(monkeypatch, caplog):
    monkeypatch.setattr(ruon.httpx, "Client", _FakeClient)
    with caplog.at_level("WARNING"):
        rows = ruon.fetch(_source(), datetime(2026, 10, 12, tzinfo=timezone.utc))
    ids = [r["platform_device_id"] for r in rows if not r.get("_org_only")]
    assert "301" not in ids
    assert "ProcessOn" in caplog.text
