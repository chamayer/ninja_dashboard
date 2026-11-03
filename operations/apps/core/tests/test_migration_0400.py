"""Migration 0400: an association change refreshes the values it changed (PLAN-012 item 4).

Rehearsed 2026-11-02 on a schema-only clone of production (synthetic rows):
move, no-op, busy deferral, catch-up and reverse behaved as designed, and
``device_cache_targets`` matched the Python projector target on every dev
Computer. These checks keep the reused projector bodies and call order from
drifting.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

migration = importlib.import_module(
    "apps.core.migrations.0400_association_refreshes_computer_values"
)
_PROJECTOR = (
    Path(__file__).resolve().parents[4] / "ingest" / "device_cache_projector.py"
).read_text(encoding="utf-8")


def test_scoped_projectors_reuse_the_current_bodies_with_one_filter():
    claims = migration._claims_function()
    assert "owner_observation.canonical_data AS owner_canonical_data" in claims  # 0397 body
    assert "WHERE p_observation_ids IS NULL OR o.observation_id = ANY(p_observation_ids)" in claims
    effective = migration._effective_function()
    assert "WHERE p_entity_ids IS NULL OR dirty.entity_id = ANY(p_entity_ids)" in effective
    assert "FOR UPDATE OF dirty SKIP LOCKED" in effective


def test_one_argument_functions_stay_and_delegate():
    wrappers = migration.WRAPPERS_SQL
    assert "sync_entity_attribute_claims_from_observations(batch_size, NULL::uuid[])" in wrappers
    assert "sync_entity_attribute_effective(batch_size, NULL::uuid[])" in wrappers


def test_association_refreshes_after_a_real_change_only():
    function = migration._association_function(refresh=True)
    refresh = function.index("operations.refresh_association_values(")
    # The no-change early return comes first; the refresh runs at the end.
    assert function.index("RETURN s.association_version;") < refresh
    assert refresh < function.rindex("RETURN v_version;")
    assert "ARRAY[l.entity_id, p_entity]" in function
    assert "refresh_association_values" not in migration._association_function(refresh=False)


def test_refresh_order_and_deferral_never_wait():
    sql = migration.CACHE_SQL
    body = sql[sql.index("CREATE FUNCTION operations.refresh_association_values") :]
    claims = body.index("sync_entity_attribute_claims_from_observations(")
    effective = body.index("sync_entity_attribute_effective(")
    cache = body.index("project_device_cache(")
    assert claims < effective < cache
    assert body.count("'deferred'") == 2
    assert "pg_advisory_xact_lock(" not in migration._forward()


def test_device_cache_columns_have_one_database_writer():
    forward = migration._forward()
    writers = re.findall(r"UPDATE operations\.devices\b", forward)
    assert len(writers) == 1
    assert forward.index("UPDATE operations.devices") > forward.index(
        "CREATE FUNCTION operations.project_device_cache"
    )


def test_database_rule_keeps_the_projector_signals():
    # The projector's documented signals and fallbacks (ADR-0005, 2026-08-05).
    for fragment in (
        "WHEN COALESCE(d.device_type, 'unknown') <> 'unknown'",
        "COALESCE(p.device_role, d.device_role, 'unknown')",
        "d.os_group, 'Unknown'",
        "l.missing_since IS NULL",
    ):
        assert fragment in migration.CACHE_SQL


def test_python_projector_has_no_copy_of_the_rule():
    # One copy (PLAN-012 item 4): the projector reads and writes through the database.
    assert "operations.device_cache_targets(%(tenant)s, NULL)" in _PROJECTOR
    assert "operations.project_device_cache(%(tenant)s, NULL)" in _PROJECTOR
    assert "UPDATE operations.devices" not in _PROJECTOR
    assert "entity_attribute_effective_current e\n" not in _PROJECTOR
    assert "_has_db_projector" not in _PROJECTOR


def test_reverse_restores_the_procedure_before_dropping_the_refresh():
    reverse = migration._reverse()
    assert reverse.index("CREATE OR REPLACE FUNCTION operations.set_source_association(") < (
        reverse.index("DROP FUNCTION operations.refresh_association_values")
    )
