"""Migration 0293: a title's publisher is the one most installs report."""

from __future__ import annotations

import importlib

_MIGRATION = importlib.import_module("apps.core.migrations.0293_software_title_main_publisher")
FORWARD = _MIGRATION.FORWARD_SQL
REVERSE = _MIGRATION.REVERSE_SQL


def test_forward_takes_the_most_common_publisher_and_reverse_restores_max():
    assert "mode() WITHIN GROUP (ORDER BY sic.publisher) AS publisher" in FORWARD
    assert "MAX(sic.publisher) AS publisher" not in FORWARD
    assert "MAX(sic.publisher) AS publisher" in REVERSE


def test_the_dependent_safety_view_is_dropped_first_and_recreated_last():
    for sql in (FORWARD, REVERSE):
        drop_safety = sql.index("DROP MATERIALIZED VIEW operations.v_software_safety;")
        drop_title = sql.index("DROP MATERIALIZED VIEW operations.software_title_current;")
        make_title = sql.index("CREATE MATERIALIZED VIEW operations.software_title_current")
        make_safety = sql.index("CREATE MATERIALIZED VIEW operations.v_software_safety")
        assert drop_safety < drop_title < make_title < make_safety


def test_unique_indexes_stay_so_concurrent_refresh_keeps_working():
    assert "CREATE UNIQUE INDEX software_title_current_pk" in FORWARD
    assert "CREATE UNIQUE INDEX v_software_safety_pk" in FORWARD


def test_write_privileges_are_revoked_and_read_grants_match_production():
    assert FORWARD.count("REVOKE INSERT, UPDATE, DELETE, TRUNCATE") == 2
    assert "TO operations_app, ninja_ingest, operations_readonly, metabase_ro;" in FORWARD
    # The safety view was never readable by ingest.
    safety = FORWARD[FORWARD.index("CREATE MATERIALIZED VIEW operations.v_software_safety"):]
    assert "GRANT SELECT ON operations.v_software_safety\n    TO operations_app, operations_readonly, metabase_ro;" in safety


def test_no_percent_signs_that_a_database_driver_could_misread():
    assert "%" not in FORWARD and "%" not in REVERSE


def test_it_follows_the_previous_migration():
    assert _MIGRATION.Migration.dependencies == [("operations", "0292_software_routine_helper")]
