"""The Requirements page edits the default and override profiles."""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

from django.template.loader import get_template

from apps.core import requirement_baselines as rb

_ROOT = Path(__file__).resolve().parents[3]
_VIEWS = (_ROOT / "apps" / "core" / "views.py").read_text(encoding="utf-8")
_PAGE = (_ROOT / "templates" / "requirement_profiles.html").read_text(encoding="utf-8")
_TABLE = (_ROOT / "templates" / "_requirement_baseline_table.html").read_text(encoding="utf-8")
_CLIENTS = (_ROOT / "templates" / "_requirement_profile_clients.html").read_text(
    encoding="utf-8"
)

NINJA = SimpleNamespace(
    id=1,
    name="Ninja",
    entity_type="rmm.agent",
    default_severity="high",
    default_gap_after_hours=24,
    default_confidence_probable=48,
    default_confidence_confirmed=168,
)
HUDU = SimpleNamespace(
    id=2,
    name="Hudu",
    entity_type="cmdb.asset",
    default_severity="medium",
    default_gap_after_hours=720,
    default_confidence_probable=1440,
    default_confidence_confirmed=2160,
)


def _item(agent_id, entity_type, platform, scope="all"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        agent_id=agent_id,
        entity_type=entity_type,
        platform=platform,
        device_scope=scope,
        severity="high",
        gap_after_hours=24,
        confidence_probable=48,
        confidence_confirmed=168,
    )


def test_every_service_is_offered_for_all_devices_and_marks_what_is_required():
    rows = rb.baseline_rows([NINJA, HUDU], [_item(1, "rmm.agent", "Ninja")])
    assert [(r["name"], r["scope"], r["required"]) for r in rows] == [
        ("Hudu", "all", False),
        ("Ninja", "all", True),
    ]


def test_existing_scoped_and_legacy_items_are_listed_so_they_can_be_removed():
    rows = rb.baseline_rows(
        [NINJA],
        [_item(1, "rmm.agent", "Ninja", "server"), _item(None, "edr.agent", "Old EDR")],
    )
    assert [(r["name"], r["scope"], r["required"], r["agent"]) for r in rows] == [
        ("Ninja", "all", False, NINJA),
        ("Ninja", "server", True, NINJA),
        ("Old EDR", "all", True, None),
    ]


def test_a_row_written_before_agents_existed_matches_by_type_and_name():
    assert rb.matches_agent(_item(None, "rmm.agent", "Ninja"), NINJA)
    assert not rb.matches_agent(_item(None, "rmm.agent", "Other"), NINJA)
    assert not rb.matches_agent(_item(2, "rmm.agent", "Ninja"), NINJA)


def test_a_new_requirement_takes_the_services_default_thresholds():
    values = rb.new_item_values(HUDU)
    assert values == {
        "agent_id": 2,
        "entity_type": "cmdb.asset",
        "platform": "Hudu",
        "device_scope": "all",
        "severity": "medium",
        "gap_after_hours": 720,
        "confidence_probable": 1440,
        "confidence_confirmed": 2160,
    }


def test_valid_scopes_keep_role_specific_baselines_explicit():
    assert rb.VALID_SCOPES == ("all", "server", "workstation")
    assert rb.ROLE_SCOPES == ("server", "workstation")


def test_writes_are_audited_and_guarded():
    for action in (
        "requirement_profile.create",
        "requirement_profile.update",
        "requirement_profile.delete",
        "requirement_baseline.require",
        "requirement_baseline.remove",
        "requirement_baseline.add",
        "client.requirement_profile.assign",
    ):
        assert f'"{action}"' in _VIEWS
    # A profile still assigned to any client cannot be deleted.
    assert "Client.objects.filter(tenant_id=1, requirement_profile=profile).count()" in _VIEWS
    # Legacy Global rows cannot be edited from the profile UI.
    assert "row.enabled = False" in _VIEWS
    assert "Global requirements are retired" in _VIEWS
    assert "Edit items via" not in _PAGE
    assert '"copy_all", "replace_role"' in _VIEWS
    assert "_copy_all_baseline_to_role" in _VIEWS


def test_the_page_and_table_render():
    get_template("requirement_profiles.html")
    html = get_template("_requirement_baseline_table.html").render(
        {
            "target": "global",
            "service_rows": rb.baseline_rows(
                [NINJA, HUDU],
                [_item(1, "rmm.agent", "Ninja"), _item(None, "edr.agent", "Old EDR", "server")],
            ),
        }
    )
    assert 'name="agent_id" value="2"' in html
    assert "Servers only" in html
    assert ">Remove</button>" in html


def test_scoped_add_and_collapsed_assignment_controls_render():
    get_template("_requirement_profile_clients.html")
    assert 'name="action" value="add_requirement"' in _TABLE
    assert 'name="device_scope"' in _TABLE
    assert "Copy All rules, then add" in _TABLE
    assert 'name="action" value="assign_clients"' in _CLIENTS
    assert 'name="client_id"' in _CLIENTS
    assert "Use {{ default_profile.name|default:\"Standard\" }} (default)" in _CLIENTS
    assert "Global requirements" not in _PAGE
