import uuid
from pathlib import Path

from ingest.identity import client_resolver

PROMPT = uuid.UUID(int=1)


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, params=None):
        pass

    def fetchall(self):
        return self.rows


def _row(source, name, state="automatic", client=PROMPT, client_name="Prompt"):
    return (uuid.uuid4(), client, client_name, hash(source) % 50, source, "x", name, state)


def _findings(monkeypatch, rows):
    emitted, unseen = [], []
    monkeypatch.setattr(client_resolver, "_emit_finding", lambda cur, *a, **k: emitted.append(k))
    monkeypatch.setattr(
        client_resolver, "_resolve_unseen_client_name_conflicts", lambda cur, keys: unseen.append(keys)
    )
    client_resolver._check_name_drift(_Cursor(rows))
    return emitted, unseen[0]


def test_one_critical_finding_per_client_with_a_row_per_source(monkeypatch):
    emitted, active = _findings(
        monkeypatch,
        [_row("Ninja", "MDA"), _row("Hudu", "MDA"), _row("LogMeIn", "PROMPT"),
         _row("SentinelOne", "Prompt", state="explicit")],
    )
    [finding] = emitted
    assert finding["client_id"] == PROMPT and finding["severity"] == "critical"
    assert active == {finding["condition_key"]}
    details = finding["details"]
    assert details["differing_count"] == 2 and details["source_count"] == 4
    assert [(r["source"], r["status"]) for r in details["rows"]] == [
        ("Hudu", "differs"),
        ("Ninja", "differs"),
        ("LogMeIn", "matches"),
        ("SentinelOne", "matches"),
    ]
    assert details["no_source_matches"] is False


def test_names_the_resolver_treats_as_equal_and_decided_rows_raise_nothing(monkeypatch):
    emitted, active = _findings(
        monkeypatch,
        [_row("Ninja", "Star-Funding", client_name="Star Funding"),
         _row("Hudu", "StarFunding", client_name="Star Funding"),
         _row("LogMeIn", "SF", state="explicit", client_name="Star Funding"),
         _row("R-U-ON", "SF test", state="ignored", client_name="Star Funding")],
    )
    assert emitted == [] and active == set()


def test_no_source_using_the_client_name_is_called_out(monkeypatch):
    emitted, _ = _findings(monkeypatch, [_row("Ninja", "ADH", client_name="All Data Health")])
    assert emitted[0]["details"]["no_source_matches"] is True


def test_client_mapping_findings_refresh_current_evaluation_fields():
    source = (Path(__file__).parents[1] / "identity" / "client_resolver.py").read_text()
    emit = source[source.index("def _emit_finding"):source.index("def _resolve_finding")]
    unnamed = source[
        source.index("def _emit_unnamed_source_group_finding") : source.index("def _emit_finding")
    ]

    assert "subject_ref      = EXCLUDED.subject_ref" in emit
    assert "severity         = EXCLUDED.severity" in emit
    assert "severity = EXCLUDED.severity" in unnamed


def test_client_name_drift_closes_entity_findings_with_closed_at():
    source = (Path(__file__).parents[1] / "identity" / "client_resolver.py").read_text()
    resolve_one = source[source.index("def _resolve_entity_finding"):source.index("def _check_name_drift")]
    resolve_unseen = source[source.index("def _resolve_unseen_client_name_conflicts"):source.index("def _check_mapping_topology")]

    assert "closed_at = NOW()" in resolve_one
    assert "closed_at = NOW()" in resolve_unseen
    assert "resolved_at" not in resolve_one
    assert "resolved_at" not in resolve_unseen
