"""Migration 0322 on a real PostgreSQL: record names, name kinds, shadow naming (ADR-0034).

Builds on the 0318 chain (change history foundation, merges, links, roaming
records) and adds the tables the naming function reads, with production
column types (2026-10-19). Every statement of the migration runs, the
RunPython step included.
"""

from __future__ import annotations

import importlib
import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from apps.core.tests.test_migration_0306_postgres import FINDING_TYPES_SCHEMA, _SchemaEditor
from apps.core.tests.test_migration_0306_postgres import SCHEMA as FOUNDATION_SCHEMA
from apps.core.tests.test_migration_0308_postgres import TABLES, _computer
from apps.core.tests.test_migration_0315_postgres import LINKS
from apps.core.tests.test_migration_0318_postgres import HISTORY, _versions

CHAIN = (
    "0306_change_history_foundation",
    "0308_computer_merge_and_split",
    "0315_merge_moves_source_links",
    "0317_close_moved_link_history",
    "0318_roaming_agent_records",
)

MODULE = "apps.core.migrations.0322_record_names_and_shadow_naming"
NOW = datetime.now(UTC)
SOURCE = uuid.UUID("00000000-0000-4000-8000-000000000020")

EXTRA = """
ALTER TABLE operations.entity_observation_history ADD COLUMN effective_to timestamptz NULL;
CREATE TABLE operations.identity_value_rejections (
    id smallint NOT NULL, value_kind text NOT NULL, normalized_value text NOT NULL,
    reason text NOT NULL, enabled boolean NOT NULL, provenance text NOT NULL,
    created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL
);
INSERT INTO operations.identity_value_rejections VALUES
    (1, 'serial', 'default string', 'placeholder', true, 'test', now(), now()),
    (2, 'serial', 'none', 'placeholder', true, 'test', now(), now());
CREATE TABLE operations.device_operator_decisions (
    version integer NOT NULL, id uuid NOT NULL, dimension varchar(80) NOT NULL,
    value jsonb NOT NULL, reason text NOT NULL, set_by varchar(120) NOT NULL,
    set_at timestamptz NOT NULL, tenant_id bigint NOT NULL, device_id uuid NOT NULL
);
-- A view in production (record lifecycle mappings); only these columns are read.
CREATE TABLE operations.v_device_source_record_lifecycle_current (
    observation_id uuid NOT NULL, record_lifecycle varchar(24) NOT NULL
);
"""


@pytest.fixture(scope="module")
def conn():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION_TESTS=1 for PostgreSQL coverage")
    postgres = pytest.importorskip("testcontainers.postgres")
    container = postgres.PostgresContainer("postgres:16-alpine")
    with container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        with psycopg.connect(dsn, autocommit=True) as connection:
            for ddl in (FOUNDATION_SCHEMA, TABLES, LINKS, HISTORY, EXTRA, FINDING_TYPES_SCHEMA):
                connection.execute(ddl)
            # The 0318 image agent: four serials under four names.
            _versions(
                connection,
                "s1-image",
                [
                    ("CitrixAppMCS", "VMW-1"),
                    ("CitrixApp29", "VMW-2"),
                    ("CitrixApp33", "VMW-3"),
                    ("CitrixApp27", "VMW-4"),
                ],
            )
            for name in (*CHAIN, MODULE.rsplit(".", 1)[1]):
                module = importlib.import_module(f"apps.core.migrations.{name}")
                with connection.transaction():
                    connection.execute("SET LOCAL ROLE operations_migrate")
                    connection.execute(
                        getattr(module, "FOUNDATION_SQL", None) or module.FORWARD_SQL
                    )
            module.register_finding_type(None, _SchemaEditor(connection))
            module.register_finding_type(None, _SchemaEditor(connection))
            connection.execute("SELECT set_config('operations.tenant_id', '1', false)")
            yield connection


def _record(
    conn,
    device,
    platform,
    entity_type,
    name,
    *,
    active=True,
    seen=NOW,
    online=None,
    contact=None,
    domain=None,
    key=None,
):
    observation = uuid.uuid4()
    data = {"hostname": name}
    if online is not None:
        data["is_online"] = online
    if contact is not None:
        data["last_seen_at"] = contact.isoformat()
    if domain is not None:
        data["domain"] = domain
    key = key or str(observation)
    conn.execute(
        """INSERT INTO operations.entity_observation_current
               (observation_id, tenant_id, device_id, platform, entity_key, active, canonical_data,
                source_instance_id, external_id, entity_type, last_seen_at)
           VALUES (%s, 1, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)""",
        (
            observation,
            device,
            platform,
            key,
            active,
            json.dumps(data),
            SOURCE,
            key,
            entity_type,
            seen,
        ),
    )
    return observation, key


def _history(
    conn, key, platform, entity_type, names, *, serial=None, vm_uuid=None, start=None, until=None
):
    """One closed interval per name, a day each from start; ``until`` closes the last."""
    start = start or NOW - timedelta(days=20)
    for i, name in enumerate(names):
        data = {"hostname": name}
        if serial:
            data["serial_number"] = serial
        if vm_uuid:
            data["vm_uuid"] = vm_uuid
        last = i == len(names) - 1
        conn.execute(
            """INSERT INTO operations.entity_observation_history
                   (id, entity_type, entity_key, effective_from, effective_to, material_data,
                    tenant_id, platform, source_instance_id, external_id)
               VALUES (%s, %s, %s, %s, %s, %s::jsonb, 1, %s, %s, %s)""",
            (
                uuid.uuid4(),
                entity_type,
                key,
                start + timedelta(days=i),
                until if last else start + timedelta(days=i + 1),
                json.dumps(data),
                platform,
                SOURCE,
                key,
            ),
        )


def _name(conn, device):
    return conn.execute(
        "SELECT name, name_rule, observation_id FROM operations.computer_names(1, %s)",
        ([device],),
    ).fetchone()


@pytest.mark.parametrize(
    ("platform", "record_type", "name", "domain", "expected"),
    [
        (
            "LogMeIn",
            "agent.remote_access",
            "CTXDesktop065.utaw.org",
            None,
            ("ctxdesktop065", "ctxdesktop065", "utaw.org"),
        ),
        ("Ninja", "agent.rmm", "DEV-SQL2", "UTAW", ("dev-sql2", "devsql2", "utaw")),
        ("R-U-ON", "agent.monitoring", "CP-AMT-VMH (temp)", None, ("cp-amt-vmh", "cpamtvmh", None)),
        # No strip pattern for agents: the annotation stays part of the name.
        (
            "SentinelOne",
            "agent.edr",
            "CP-AMT-VMH (temp)",
            None,
            ("cp-amt-vmh (temp)", "cpamtvmhtemp", None),
        ),
        # macOS names carry a typographic apostrophe (U+2019); it is kept in the name.
        (
            "SentinelOne",
            "agent.edr",
            "Brenda\u2019s MacBook Air",
            None,
            ("brenda\u2019s macbook air", "brendasmacbookair", None),
        ),
        (
            "Ninja",
            "vm.guest",
            "adh-bk-sql5 (retired #110503)",
            None,
            ("adh-bk-sql5", "adhbksql5", None),
        ),
        ("Hudu", "cmdb.asset", "10.1.2.3", None, (None, None, None)),
        ("NewTool", "agent.thing", "  ", "corp", (None, None, None)),
        # Whitespace runs, a non-breaking space included, become one space.
        (
            "Ninja",
            "vm.guest",
            "FINGERTECH\u00a0 ",
            None,
            ("fingertech", "fingertech", None),
        ),
        (
            "Hudu",
            "cmdb.asset",
            "kuppy retired  ticket #93629",
            None,
            ("kuppy retired ticket #93629", "kuppyretiredticket93629", None),
        ),
    ],
)
def test_record_name_forms(conn, platform, record_type, name, domain, expected):
    with conn.transaction():
        conn.execute("SET LOCAL ROLE ninja_ingest")
        row = conn.execute(
            "SELECT * FROM operations.record_name_forms(%s, %s, %s, %s)",
            (platform, record_type, name, domain),
        ).fetchone()
    assert row == expected


def test_name_kinds_are_covered_data_with_unique_ranks_and_valid_patterns(conn):
    assert conn.execute(
        "SELECT classification, is_global FROM operations.change_history_registry "
        "WHERE table_name = 'source_name_kinds'"
    ).fetchone() == ("covered", True)
    assert conn.execute(
        """SELECT count(*), min(a.action) FROM operations.source_name_kinds_change_history h
             JOIN operations.change_actions a ON a.id = h.action_id"""
    ).fetchone() == (10, "source_name_kind.introduce")
    with pytest.raises(psycopg.errors.UniqueViolation), conn.transaction():
        conn.execute(
            "INSERT INTO operations.source_name_kinds VALUES ('X', 'agent.x', 'label', 300, '', '')"
        )
    with pytest.raises(psycopg.errors.InvalidRegularExpression), conn.transaction():
        conn.execute(
            "INSERT INTO operations.source_name_kinds VALUES ('X', 'agent.x', 'label', 7, '(', '')"
        )


def test_roaming_by_names_needs_five_names_and_no_serial_or_vm_uuid(conn):
    _history(
        conn,
        "lmi-clone",
        "LogMeIn",
        "agent.remote_access",
        [f"ctxdesktop1{i:02d}.utaw.org" for i in range(6)],
    )
    _history(
        conn,
        "lmi-rename",
        "LogMeIn",
        "agent.remote_access",
        ["lion65dw", "lion65thdw", "lion65thnvr"],
    )
    _history(conn, "ninja-vm", "Ninja", "agent.rmm", [f"vdi-{i}" for i in range(6)], vm_uuid="42a1")
    _history(
        conn,
        "s1-renamed",
        "SentinelOne",
        "agent.edr",
        [f"lab-{i}" for i in range(6)],
        serial="SN-12345",
    )
    _history(
        conn,
        "lmi-old",
        "LogMeIn",
        "agent.remote_access",
        [f"old-{i}" for i in range(6)],
        start=NOW - timedelta(days=200),
    )
    # Formatting and domain changes are not names.
    _history(
        conn,
        "lmi-format",
        "LogMeIn",
        "agent.remote_access",
        ["PC-1", "pc-1.corp", "PC_1", "pc 1", "Pc-1.other"],
    )
    # A placeholder serial is not usable, exactly as identity matching decides.
    _history(
        conn,
        "lmi-placeholder",
        "Ninja",
        "agent.rmm",
        [f"mcs-{i}" for i in range(5)],
        serial="Default string",
    )
    # A name set 120 days ago and still in effect counts; one that ended before
    # the window does not.
    _history(
        conn,
        "lmi-boundary",
        "LogMeIn",
        "agent.remote_access",
        ["early-0"],
        start=NOW - timedelta(days=120),
        until=NOW - timedelta(days=10),
    )
    _history(
        conn, "lmi-boundary", "LogMeIn", "agent.remote_access", [f"late-{i}" for i in range(4)]
    )
    _history(
        conn,
        "lmi-ended",
        "LogMeIn",
        "agent.remote_access",
        ["gone-0"],
        start=NOW - timedelta(days=120),
        until=NOW - timedelta(days=100),
    )
    _history(conn, "lmi-ended", "LogMeIn", "agent.remote_access", [f"kept-{i}" for i in range(4)])
    with conn.transaction():
        conn.execute("SET LOCAL ROLE ninja_ingest")
        conn.execute("SELECT operations.refresh_identity_roaming_records(1)")
    rows = conn.execute(
        "SELECT external_id, basis, serial_count, name_count FROM operations.identity_roaming_records "
        "ORDER BY external_id"
    ).fetchall()
    assert rows == [
        ("lmi-boundary", "names", 0, 5),
        ("lmi-clone", "names", 0, 6),
        ("lmi-placeholder", "names", 0, 5),
        ("s1-image", "serials", 4, 4),
    ]


def test_computer_names_follow_the_rules(conn):
    old = NOW - timedelta(days=60)
    cases = {}

    # Recently reporting OS name beats a silent one.
    d = cases["reporting"] = _computer(conn, "pc-old")
    reporting, _ = _record(conn, d, "Ninja", "agent.rmm", "PC-NEW", online=True)
    _record(conn, d, "SentinelOne", "agent.edr", "PC-OLD", online=False, seen=old)

    # A record's own contact decides, not the source's latest: a stale duplicate
    # record of the same source is silent although another record is live.
    d = cases["duplicate"] = _computer(conn, "ws-1")
    live, _ = _record(
        conn, d, "Ninja", "agent.rmm", "WS-1", contact=NOW - timedelta(hours=2), seen=old
    )
    _record(conn, d, "Ninja", "agent.rmm", "WS-OLD", contact=old, seen=NOW)

    # A silent current OS name beats the stored name an agent once reported.
    d = cases["silent"] = _computer(conn, "laptop-7")
    silent, key = _record(conn, d, "SentinelOne", "agent.edr", "LAPTOP-8", online=False, seen=old)
    _history(conn, key, "SentinelOne", "agent.edr", ["LAPTOP-7", "LAPTOP-8"])

    # With only withdrawn agents, a name an agent reported stays (clone image name last).
    d = cases["stable"] = _computer(conn, "clone-07")
    clone, key = _record(conn, d, "Ninja", "agent.rmm", "CTXMCSGOLD", active=False)
    _history(conn, key, "Ninja", "agent.rmm", ["CLONE-07", "CTXMCSGOLD"])

    # Withdrawn agents: the most recently seen wins over rank.
    d = cases["withdrawn"] = _computer(conn, "rd13_retired")
    _record(conn, d, "Ninja", "agent.rmm", "RD13-OLD", active=False, seen=old)
    newest, _ = _record(conn, d, "SentinelOne", "agent.edr", "RD13", active=False)

    # A label names a Computer no OS name covers.
    d = cases["label"] = _computer(conn, "utaw-82-mgt03")
    label, _ = _record(conn, d, "R-U-ON", "agent.monitoring", "UTAW-82-MGT", online=True)

    # The 15-character cut gives way to the one longer current OS name.
    d = cases["cut"] = _computer(conn, "3rd_fl_conferen")
    _record(conn, d, "Ninja", "agent.rmm", "3RD_FL_CONFEREN", online=True)
    full, _ = _record(conn, d, "SentinelOne", "agent.edr", "3RD_FL_CONFERENCE_ROOM", online=True)

    # A roaming record carries no name.
    d = cases["roaming"] = _computer(conn, "kept-name")
    _record(conn, d, "LogMeIn", "agent.remote_access", "CTXDESKTOP105.utaw.org", key="lmi-clone")

    # The operator's name wins.
    d = cases["operator"] = _computer(conn, "auto-name")
    _record(conn, d, "Ninja", "agent.rmm", "AUTO-NAME", online=True)
    conn.execute(
        """INSERT INTO operations.device_operator_decisions
           VALUES (1, gen_random_uuid(), 'name', '{"name": "Front-Desk"}', 'asked', 'op', now(), 1, %s)""",
        (d,),
    )

    # An archived documentation asset is a withdrawn label.
    d = cases["archived"] = _computer(conn, "asset-x")
    archived, _ = _record(conn, d, "Hudu", "cmdb.asset", "ASSET-Y")
    conn.execute(
        "INSERT INTO operations.v_device_source_record_lifecycle_current VALUES (%s, 'archived')",
        (archived,),
    )

    assert _name(conn, cases["reporting"]) == ("pc-new", "reporting_os", reporting)
    assert _name(conn, cases["duplicate"]) == ("ws-1", "reporting_os", live)
    assert _name(conn, cases["silent"]) == ("laptop-8", "silent_os", silent)
    assert _name(conn, cases["stable"]) == ("clone-07", "stable_os", clone)
    assert _name(conn, cases["withdrawn"]) == ("rd13", "withdrawn_os", newest)
    assert _name(conn, cases["label"]) == ("utaw-82-mgt", "current_label", label)
    assert _name(conn, cases["cut"]) == ("3rd_fl_conference_room", "reporting_os", full)
    assert _name(conn, cases["roaming"]) == ("kept-name", "unconfirmed", None)
    assert _name(conn, cases["operator"]) == ("front-desk", "operator", None)
    assert _name(conn, cases["archived"]) == ("asset-y", "withdrawn_label", archived)

    shadow = dict(
        (row[0], row[1])
        for row in conn.execute(
            "SELECT device_id, outcome FROM operations.computer_name_shadow(1)"
        ).fetchall()
    )
    assert shadow[cases["stable"]] == "same"
    assert shadow[cases["label"]] == "rename"
    assert shadow[cases["cut"]] == "rename"


def test_unclassified_names_are_listed_until_classified(conn):
    device = _computer(conn, "probe-1")
    _record(conn, device, "NewTool", "agent.thing", "PROBE-1")
    _record(conn, device, "NewTool", "agent.thing", "", key="nameless")
    assert conn.execute("SELECT * FROM operations.source_name_kind_unclassified(1)").fetchall() == [
        ("NewTool", "agent.thing", 1)
    ]
    conn.execute(
        "INSERT INTO operations.source_name_kinds VALUES ('NewTool', 'agent.thing', 'label', 10, '', 't')"
    )
    assert (
        conn.execute("SELECT * FROM operations.source_name_kind_unclassified(1)").fetchall() == []
    )


def test_the_finding_type_and_policy_register_once(conn):
    row = conn.execute(
        """SELECT finding_class, subject_scope, display_name, alertable
             FROM operations.finding_types WHERE name = 'source_name_kind_unclassified'"""
    ).fetchone()
    assert row == ("admin", "global", "Source names not classified", False)
    active = conn.execute(
        "SELECT version, policy FROM operations.condition_policy_versions WHERE active"
    ).fetchone()
    assert active[0] == "conditions-registry-7"
    assert [d["name"] for d in active[1]["definitions"]] == ["source_name_kind_unclassified"]
