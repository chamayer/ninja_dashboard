from contextlib import contextmanager

from ingest.agent_compliance import ingest


def test_compliance_projection_ignores_shared_observation_only_fields(monkeypatch):
    captured: dict[str, object] = {}

    class Cursor:
        def executemany(self, query, rows):
            captured["query"] = query
            captured["rows"] = rows

    @contextmanager
    def transaction():
        yield Cursor()

    monkeypatch.setattr(ingest.db, "transaction", transaction)
    ingest._insert_observations(
        17,
        [{
            "observed_at": "2026-10-05T19:00:00Z",
            "platform": "Ninja",
            "source_id": 1,
            "source_name": "Ninja",
            "hostname": "device-1",
            "norm_name": "device-1",
            "match_name": "device-1",
            "raw_data": {},
            "external_namespace": "device",
        }],
    )

    row = captured["rows"][0]
    assert row["source_run_id"] == 17
    assert "external_namespace" not in row
    assert "external_namespace" not in captured["query"]
