"""Migration 0394: participant reconciliation without a lock per finding."""

from __future__ import annotations

import importlib


def test_reconciliation_drops_only_the_per_finding_lock():
    module = importlib.import_module(
        "apps.core.migrations.0394_reconcile_participants_without_finding_lock"
    )
    forward, reverse = (
        module.Migration.operations[0].sql,
        module.Migration.operations[0].reverse_sql,
    )
    # The exclusive tenant guard serializes these writers; the per-finding lock
    # made every guard check (a pg_locks scan) slower as an evaluation went on.
    assert "pg_advisory_xact_lock" not in forward
    assert "pg_advisory_xact_lock" in reverse
    assert forward == reverse.replace(module._LOCK, "")
