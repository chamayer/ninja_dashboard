"""Migration 0315 on a real PostgreSQL: a merge moves source links and retires edges.

Production definitions (2026-10-16) for source links, relationship edges and
the relationship queue, after 0306 and 0308; the remediation step runs on a
merge made by the 0308 function (the production state it repairs).
"""

from __future__ import annotations

import importlib
import os
import uuid

import psycopg
import pytest

from apps.core.tests.test_migration_0306_postgres import SCHEMA as FOUNDATION_SCHEMA
from apps.core.tests.test_migration_0308_postgres import TABLES, _computer, _observation

LINKS = """
CREATE TABLE operations.tenants (id bigint PRIMARY KEY);
INSERT INTO operations.tenants VALUES (1);
CREATE TABLE operations.entity_source_links (
    version integer NOT NULL, id uuid PRIMARY KEY, external_namespace varchar(120) NOT NULL,
    parent_external_namespace varchar(120) NOT NULL DEFAULT '',
    parent_external_id text NOT NULL DEFAULT '', external_id text NOT NULL,
    missing_since timestamptz NULL, reason varchar(120) NOT NULL,
    entity_id uuid NOT NULL, entity_class_id varchar(80) NOT NULL DEFAULT 'device',
    source_instance_id uuid NOT NULL DEFAULT '00000000-0000-4000-8000-000000000010',
    tenant_id bigint NOT NULL
);
-- Production definition (2026-10-18), with the one-open-row index whose
-- violation stopped every source refresh after 0315.
CREATE TABLE operations.entity_source_link_history (
    version integer NOT NULL, id uuid PRIMARY KEY, external_namespace varchar(120) NOT NULL,
    parent_external_namespace varchar(120) NOT NULL, parent_external_id text NOT NULL,
    external_id text NOT NULL, match_method varchar(40) NOT NULL,
    match_confidence numeric NOT NULL, actor_kind varchar(16) NOT NULL,
    actor_process varchar(160) NOT NULL, reason varchar(120) NOT NULL, evidence jsonb NOT NULL,
    effective_from timestamptz NOT NULL, effective_to timestamptz NULL, actor_id bigint NULL,
    entity_id uuid NOT NULL, entity_class_id varchar(80) NOT NULL,
    last_seen_binding_id uuid NULL, source_instance_id uuid NOT NULL, tenant_id bigint NOT NULL
);
CREATE UNIQUE INDEX uq_entity_source_link_history_open ON operations.entity_source_link_history
    (tenant_id, source_instance_id, external_namespace, parent_external_namespace,
     parent_external_id, external_id) WHERE effective_to IS NULL;
CREATE TABLE operations.entity_relationships (
    version integer NOT NULL CHECK (version >= 0), id uuid PRIMARY KEY,
    status varchar(16) NOT NULL, selection_reason varchar(40) NOT NULL,
    selected_authority_tier smallint NULL, selected_authority_priority smallint NULL,
    input_hash bytea NOT NULL, projected_at timestamptz NOT NULL,
    source_entity_id uuid NOT NULL, target_entity_id uuid NOT NULL, tenant_id bigint NOT NULL,
    relationship_type_id varchar(80) NOT NULL
);
CREATE TABLE operations.entity_relationship_dirty (
    version integer NOT NULL, id uuid PRIMARY KEY, queued_at timestamptz NOT NULL,
    reason varchar(40) NOT NULL, source_entity_id uuid NOT NULL, target_entity_id uuid NOT NULL,
    tenant_id bigint NOT NULL, relationship_type_id varchar(80) NOT NULL,
    UNIQUE (tenant_id, relationship_type_id, source_entity_id, target_entity_id)
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
            connection.execute(FOUNDATION_SCHEMA)
            connection.execute(TABLES)
            connection.execute(LINKS)
            for name in ("0306_change_history_foundation", "0308_computer_merge_and_split"):
                module = importlib.import_module(f"apps.core.migrations.{name}")
                with connection.transaction():
                    connection.execute("SET LOCAL ROLE operations_migrate")
                    connection.execute(getattr(module, "FOUNDATION_SQL", None) or module.FORWARD_SQL)
            connection.execute("SELECT set_config('operations.tenant_id', '1', false)")
            yield connection


def _link(conn, device):
    """A link with its open history row, as the link sync writes them."""
    link = uuid.uuid4()
    conn.execute(
        """INSERT INTO operations.entity_source_links
               (version, id, external_namespace, external_id, reason, entity_id, tenant_id)
               SELECT 1, %s, 'ninja', %s, 'observation', entity_id, 1
                 FROM operations.devices WHERE id = %s""",
        (link, str(link), device),
    )
    _open_history(conn, link)
    return link


def _open_history(conn, link):
    """The link sync's history insert: one open row for the link's entity."""
    conn.execute(
        """INSERT INTO operations.entity_source_link_history
               SELECT 1, gen_random_uuid(), l.external_namespace, l.parent_external_namespace,
                      l.parent_external_id, l.external_id, 'compatibility', 1, 'system',
                      'ingest.entity_link_sync', l.reason, '{}', clock_timestamp(), NULL, NULL,
                      l.entity_id, l.entity_class_id, NULL, l.source_instance_id, l.tenant_id
                 FROM operations.entity_source_links l
                WHERE l.id = %s
                  AND NOT EXISTS (SELECT 1 FROM operations.entity_source_link_history h
                                   WHERE h.external_id = l.external_id AND h.effective_to IS NULL
                                     AND h.entity_id = l.entity_id)""",
        (link,),
    )


def _edge(conn, os_entity, device):
    conn.execute(
        """INSERT INTO operations.entity_relationships
               SELECT 1, gen_random_uuid(), 'active', 'source_authority', 300, 0, '\\x01',
                      now(), %s, entity_id, 1, 'os_installation_runs_on_computer'
                 FROM operations.devices WHERE id = %s""",
        (os_entity, device),
    )


def _entity(conn, device):
    return conn.execute("SELECT entity_id FROM operations.devices WHERE id = %s", (device,)).fetchone()[0]


def test_remediation_repairs_a_merge_made_before_0315(conn):
    survivor, absorbed = _computer(conn, "pc-r"), _computer(conn, "pc-r")
    link = _link(conn, absorbed)
    os_entity = uuid.uuid4()
    _edge(conn, os_entity, absorbed)
    with conn.transaction():
        merge_id = conn.execute(
            "SELECT operations.merge_computers(%s::uuid, %s::uuid, 'same serial'::text)",
            (survivor, absorbed),
        ).fetchone()[0]
    migration = importlib.import_module("apps.core.migrations.0315_merge_moves_source_links")
    with conn.transaction():
        conn.execute("SET LOCAL ROLE operations_migrate")
        conn.execute(migration.FORWARD_SQL)

    assert conn.execute(
        "SELECT entity_id FROM operations.entity_source_links WHERE id = %s", (link,)
    ).fetchone()[0] == _entity(conn, survivor)
    assert conn.execute(
        "SELECT moved_link_ids FROM operations.computer_merges WHERE id = %s", (merge_id,)
    ).fetchone()[0] == [link]
    assert conn.execute(
        """SELECT status, selection_reason FROM operations.entity_relationships
            WHERE source_entity_id = %s""",
        (os_entity,),
    ).fetchone() == ("no_evidence", "computer_merged")
    assert conn.execute(
        "SELECT count(*) FROM operations.entity_relationship_dirty WHERE source_entity_id = %s",
        (os_entity,),
    ).fetchone()[0] == 1


def test_merge_and_split_move_links_both_ways(conn):
    survivor, absorbed = _computer(conn, "pc-m2"), _computer(conn, "pc-m2")
    _observation(conn, absorbed, "Ninja")
    link = _link(conn, absorbed)
    later = _link(conn, survivor)  # the survivor's own link never moves
    os_entity = uuid.uuid4()
    _edge(conn, os_entity, absorbed)
    with conn.transaction():
        merge_id = conn.execute(
            "SELECT operations.merge_computers(%s::uuid, %s::uuid, 'same serial'::text)",
            (survivor, absorbed),
        ).fetchone()[0]
    links = dict(
        conn.execute(
            "SELECT id, entity_id FROM operations.entity_source_links WHERE id = ANY(%s)",
            ([link, later],),
        ).fetchall()
    )
    assert links == {link: _entity(conn, survivor), later: _entity(conn, survivor)}
    assert conn.execute(
        "SELECT status FROM operations.entity_relationships WHERE source_entity_id = %s",
        (os_entity,),
    ).fetchone()[0] == "no_evidence"

    _edge(conn, uuid.uuid4(), survivor)
    with conn.transaction():
        conn.execute(
            "SELECT operations.split_computer_merge(%s, 'two machines', 'operator', 7, 'ui')",
            (merge_id,),
        )
    links = dict(
        conn.execute(
            "SELECT id, entity_id FROM operations.entity_source_links WHERE id = ANY(%s)",
            ([link, later],),
        ).fetchall()
    )
    assert links == {link: _entity(conn, absorbed), later: _entity(conn, survivor)}
    assert conn.execute(
        """SELECT count(*) FROM operations.entity_relationships
            WHERE target_entity_id = %s AND status = 'active'""",
        (_entity(conn, survivor),),
    ).fetchone()[0] == 0


def test_0317_closes_moved_link_history_so_the_link_sync_can_open_the_new_row(conn):
    """The 2026-10-17 incident: after a link moved, the sync's insert failed."""
    survivor, absorbed = _computer(conn, "pc-h1"), _computer(conn, "pc-h1")
    link = _link(conn, absorbed)
    with conn.transaction():
        conn.execute(
            "SELECT operations.merge_computers(%s::uuid, %s::uuid, 'same serial'::text)",
            (survivor, absorbed),
        )
    # Before 0317 the moved link kept its old open row: the sync insert fails.
    with pytest.raises(psycopg.errors.UniqueViolation), conn.transaction():
        _open_history(conn, link)

    fix = importlib.import_module("apps.core.migrations.0317_close_moved_link_history")
    with conn.transaction():
        conn.execute("SET LOCAL ROLE operations_migrate")
        conn.execute(fix.FORWARD_SQL)
    with conn.transaction():
        _open_history(conn, link)
    open_rows = conn.execute(
        """SELECT entity_id FROM operations.entity_source_link_history
            WHERE external_id = %s AND effective_to IS NULL""",
        (str(link),),
    ).fetchall()
    assert open_rows == [(_entity(conn, survivor),)]

    # A merge after 0317 closes the history itself; so does the split.
    a, b = _computer(conn, "pc-h2"), _computer(conn, "pc-h2")
    link2 = _link(conn, b)
    with conn.transaction():
        merge_id = conn.execute(
            "SELECT operations.merge_computers(%s::uuid, %s::uuid, 'same serial'::text)", (a, b)
        ).fetchone()[0]
    with conn.transaction():
        _open_history(conn, link2)
    with conn.transaction():
        conn.execute(
            "SELECT operations.split_computer_merge(%s, 'two machines', 'operator', 7, 'ui')",
            (merge_id,),
        )
    with conn.transaction():
        _open_history(conn, link2)
    assert conn.execute(
        """SELECT entity_id FROM operations.entity_source_link_history
            WHERE external_id = %s AND effective_to IS NULL""",
        (str(link2),),
    ).fetchall() == [(_entity(conn, b),)]
