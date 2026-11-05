"""A resolver cycle includes existing and concurrently dirtied Computers."""

import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import ingest
from ingest.identity.computer_client_ownership import reconcile_cycle, reconcile_dirty


class Cursor:
    def __init__(self):
        self.devices = [UUID(int=2), UUID(int=3)]
        self.dirty = set()
        self.projected = []
        self.rows = []
        self.result = None

    def execute(self, sql, params):
        if "set_config('operations.tenant_id'" in sql:
            return
        if "SELECT id FROM operations.devices" in sql:
            _, last, _, limit = params
            self.rows = [(value,) for value in self.devices if last is None or value > last][:limit]
        elif "SELECT owner.device_id" in sql:
            self.rows = [(value,) for value in sorted(self.dirty)][: params[1]]
        elif "operations.project_computer_client" in sql:
            device_id = params[1]
            self.projected.append(device_id)
            self.dirty.discard(device_id)
            if device_id == UUID(int=2):
                # Created after the sweep began; its key sorts before the cursor.
                self.dirty.add(UUID(int=1))
            self.result = ("resolved",)
        else:
            raise AssertionError(sql)

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.result


class ReconcileCycleTests(unittest.TestCase):
    def test_dirty_drain_does_not_repeat_full_sweep(self):
        cursor = Cursor()
        cursor.dirty.add(UUID(int=1))
        projected_per_guard = []

        @contextmanager
        def transaction():
            yield cursor

        @contextmanager
        def guarded_transaction(_tenant_id):
            before = len(cursor.projected)
            yield cursor
            projected_per_guard.append(len(cursor.projected) - before)

        with patch.object(
            ingest,
            "db",
            SimpleNamespace(transaction=transaction, findings_transaction=guarded_transaction),
            create=True,
        ):
            self.assertEqual(reconcile_dirty(1), {"resolved": 1})
        self.assertEqual(cursor.projected, [UUID(int=1)])
        self.assertEqual(projected_per_guard, [1])

    def test_sweeps_and_drains_new_lower_key(self):
        cursor = Cursor()
        projected_per_guard = []

        @contextmanager
        def transaction():
            yield cursor

        @contextmanager
        def guarded_transaction(tenant_id):
            self.assertEqual(tenant_id, 1)
            before = len(cursor.projected)
            yield cursor
            projected_per_guard.append(len(cursor.projected) - before)

        with patch.object(
            ingest,
            "db",
            SimpleNamespace(transaction=transaction, findings_transaction=guarded_transaction),
            create=True,
        ):
            result = reconcile_cycle(1, batch_size=1)
        self.assertEqual(cursor.projected, [UUID(int=2), UUID(int=3), UUID(int=1)])
        self.assertEqual(result, {"resolved": 3})
        self.assertEqual(projected_per_guard, [1, 1, 1])

    def test_projector_failure_is_not_hidden(self):
        cursor = Cursor()
        original = cursor.execute

        def execute(sql, params):
            if "operations.project_computer_client" in sql:
                raise RuntimeError("projection failed")
            return original(sql, params)

        cursor.execute = execute

        @contextmanager
        def transaction():
            yield cursor

        @contextmanager
        def guarded_transaction(_tenant_id):
            yield cursor

        with patch.object(
            ingest,
            "db",
            SimpleNamespace(transaction=transaction, findings_transaction=guarded_transaction),
            create=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "projection failed"):
                reconcile_cycle(1)


if __name__ == "__main__":
    unittest.main()
