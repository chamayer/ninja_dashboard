from __future__ import annotations

import uuid
from datetime import UTC, datetime

from ingest import platform_findings as pf

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


class _Cursor:
    def __init__(self, rows, table_exists=True):
        self.rows = rows
        self.table_exists = table_exists
        self.last = ""

    def execute(self, sql, params=None):
        self.last = sql

    def fetchone(self):
        return (self.table_exists,)

    def fetchall(self):
        return self.rows


def test_each_held_computer_is_one_admin_finding(monkeypatch):
    device = uuid.uuid4()
    rows = [(device, "PC-1", NOW, "Ninja listed 3 programs", 120, 3, None)]
    emitted, assessed = [], []
    monkeypatch.setattr(pf, "_upsert_admin_finding", lambda cur, **kw: emitted.append(kw) or "f1")
    monkeypatch.setattr(pf, "_record_platform_assessment",
                        lambda *args, **kw: assessed.append(args[3]))
    counts = {"software_inventory_held": 0}

    keys = pf._eval_inventory_holds(_Cursor(rows), 77, NOW, counts, dry_run=False)

    assert keys == [f"software_inventory_held:{device}"]
    assert counts["software_inventory_held"] == 1
    assert emitted[0]["finding_type_id"] == 77
    assert emitted[0]["details"]["previous_program_count"] == 120
    assert emitted[0]["subject_ref"]["device_id"] == str(device)
    assert assessed == ["software_inventory_held"]


def test_nothing_is_emitted_before_the_type_or_table_exists(monkeypatch):
    monkeypatch.setattr(pf, "_upsert_admin_finding", lambda *a, **k: 1 / 0)
    counts = {"software_inventory_held": 0}
    assert pf._eval_inventory_holds(_Cursor([]), None, NOW, counts, dry_run=False) == []
    # Not measured (None), so nothing is resolved as recovered either.
    assert pf._eval_inventory_holds(_Cursor([], table_exists=False), 77, NOW, counts,
                                    dry_run=False) is None


def test_entity_link_divergence_emits_one_admin_finding(monkeypatch):
    class Cursor(_Cursor):
        def __init__(self):
            self.results = [(True,), (3,)]
            self.params = None

        def fetchone(self):
            return self.results.pop(0)

        def execute(self, sql, params=None):
            self.last = sql
            self.params = params

    emitted, assessed = [], []
    monkeypatch.setattr(
        pf, "_upsert_admin_finding", lambda cur, **kw: emitted.append(kw) or uuid.uuid4()
    )
    monkeypatch.setattr(
        pf, "_record_platform_assessment", lambda *args, **kw: assessed.append(args[3])
    )
    counts = {"entity_link_divergence": 0}

    cursor = Cursor()
    keys = pf._eval_entity_link_divergence(cursor, 91, NOW, counts, dry_run=False)

    assert keys == ["entity_link_divergence:device-projection"]
    assert counts["entity_link_divergence"] == 1
    assert emitted[0]["finding_type_id"] == 91
    assert emitted[0]["details"]["divergent_projection_count"] == 3
    assert emitted[0]["details"]["authority"] == "entity_source_links"
    assert assessed == ["entity_link_divergence"]
    assert "observation.tenant_id = %s" in cursor.last
    assert cursor.params == (pf.TENANT_ID,)


def test_clean_parity_refreshes_existing_finding_assessment(monkeypatch):
    finding_id = uuid.uuid4()

    class Cursor(_Cursor):
        def __init__(self):
            self.results = [(True,), (0,), (finding_id,)]

        def fetchone(self):
            return self.results.pop(0)

    assessed = []
    monkeypatch.setattr(
        pf, "_record_platform_assessment", lambda *args, **kw: assessed.append(args)
    )
    counts = {"entity_link_divergence": 0}

    keys = pf._eval_entity_link_divergence(Cursor(), 91, NOW, counts, dry_run=False)

    assert keys == []
    assert counts["entity_link_divergence"] == 0
    assert assessed[0][1] == finding_id
    assert assessed[0][2] == "entity_link_divergence:device-projection"


def test_unclassified_records_make_one_source_instance_policy_finding(monkeypatch):
    source_instance = uuid.uuid4()

    class Cursor(_Cursor):
        def __init__(self):
            self.fetchone_results = [(True,)]
            self.fetchall_results = [
                [(source_instance, "Ninja", "unknown.agent", 17)],
                [],
            ]

        def fetchone(self):
            return self.fetchone_results.pop(0)

        def fetchall(self):
            return self.fetchall_results.pop(0)

    emitted, assessed = [], []
    monkeypatch.setattr(
        pf, "_upsert_admin_finding", lambda cur, **kw: emitted.append(kw) or uuid.uuid4()
    )
    monkeypatch.setattr(
        pf, "_record_platform_assessment", lambda *args, **kw: assessed.append(args[3])
    )
    counts = {"source_record_policy_incomplete": 0}

    keys = pf._eval_source_record_policy_gaps(Cursor(), 92, NOW, counts, dry_run=False)

    assert keys == [
        f"source_record_policy_incomplete:{source_instance}:unknown.agent"
    ]
    assert counts["source_record_policy_incomplete"] == 1
    assert emitted[0]["details"]["affected_record_count"] == 17
    assert emitted[0]["details"]["record_role"] == "unclassified"
    assert assessed == ["source_record_policy_incomplete"]


def test_clean_source_role_assessment_refreshes_stale_admin_episode(monkeypatch):
    finding_id, signal_id = uuid.uuid4(), uuid.uuid4()

    class Cursor(_Cursor):
        def __init__(self):
            self.fetchone_results = [(True,)]
            self.fetchall_results = [[], [(finding_id, "old-policy-key", str(signal_id))]]

        def fetchone(self):
            return self.fetchone_results.pop(0)

        def fetchall(self):
            return self.fetchall_results.pop(0)

    assessed = []
    monkeypatch.setattr(
        pf, "_record_platform_assessment", lambda *args, **kw: assessed.append(args)
    )
    counts = {"source_record_policy_incomplete": 0}

    keys = pf._eval_source_record_policy_gaps(Cursor(), 92, NOW, counts, dry_run=False)

    assert keys == []
    assert assessed[0][1] == finding_id
    assert assessed[0][2] == "old-policy-key"


def test_an_absent_condition_records_its_measured_recovery(monkeypatch):
    """PLAN-036 follow-up: a recovered condition gets a clearing assessment."""
    recorded = []
    monkeypatch.setattr(
        pf, "_record_platform_assessment", lambda *a, **k: recorded.append((a, k))
    )
    signal = uuid.uuid4()

    class Cur:
        def __init__(self):
            self.rows = [[("jobs_timeout",)], [
                (uuid.uuid4(), "jobs_timeout:a", "platform_signal", signal),
                (uuid.uuid4(), "jobs_timeout:b", "legacy_context", None),
            ]]

        def execute(self, sql, params=None):
            self.params = params

        def fetchone(self):
            return self.rows.pop(0)[0]

        def fetchall(self):
            return self.rows.pop(0)

    cur = Cur()
    assert pf.record_absent_recoveries(cur, 5, ["jobs_timeout:c"], NOW) == 2
    assert cur.params == (pf.TENANT_ID, 5, ["jobs_timeout:c"])
    subjects = [args[4] for args, _ in recorded]
    assert subjects == [signal, pf._subject("jobs_timeout", "jobs_timeout:b")]
    assert all(kwargs == {"measured": True} for _, kwargs in recorded)
    assert pf.record_absent_recoveries(cur, None, [], NOW) == 0
