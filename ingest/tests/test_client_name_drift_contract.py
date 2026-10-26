import uuid
from pathlib import Path

from ingest.identity import client_resolver

PROMPT = uuid.UUID(int=1)


class _Cursor:
    """The mapped groups, then (for the rename check) each group's past names."""

    def __init__(self, rows, history=()):
        self.results = [rows, list(history)]

    def execute(self, sql, params=None):
        pass

    def fetchall(self):
        return self.results.pop(0) if self.results else []


def _row(source, name, state="automatic", client=PROMPT, client_name="Prompt"):
    return (uuid.uuid4(), client, client_name, hash(source) % 50, source, source, name, state,
            uuid.UUID(int=hash(source) % 1000))


def _was(source, name):
    """A past name of the group ``_row(source, ...)``."""
    return (uuid.UUID(int=hash(source) % 1000), source, name)


def _findings(monkeypatch, rows, history=(), renamed=None):
    emitted, unseen = [], []
    monkeypatch.setattr(client_resolver, "_emit_finding", lambda cur, *a, **k: emitted.append(k))
    monkeypatch.setattr(
        client_resolver, "_resolve_unseen_client_name_conflicts", lambda cur, keys: unseen.append(keys)
    )
    monkeypatch.setattr(
        client_resolver,
        "_rename_client",
        lambda cur, client_id, old, rename: (renamed if renamed is not None else []).append(
            (client_id, old, rename["to"])
        ) or True,
    )
    client_resolver._check_name_drift(_Cursor(rows, history))
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


def test_every_group_renamed_at_its_source_renames_the_client(monkeypatch):
    renamed = []
    emitted, active = _findings(
        monkeypatch,
        [_row("Ninja", "MDA"), _row("Hudu", "MDA"), _row("R-U-ON", "mda")],
        history=[_was("Ninja", "Prompt"), _was("Ninja", "MDA"), _was("Hudu", "Prompt")],
        renamed=renamed,
    )
    assert renamed == [(PROMPT, "Prompt", "MDA")]
    assert emitted == [] and active == set()


def test_a_partial_rename_says_which_sources_still_use_the_old_name(monkeypatch):
    renamed = []
    emitted, _ = _findings(
        monkeypatch,
        [_row("Ninja", "MDA"), _row("Hudu", "MDA"), _row("LogMeIn", "Prompt")],
        history=[_was("Ninja", "Prompt"), _was("Hudu", "Prompt")],
        renamed=renamed,
    )
    assert renamed == []
    rename = emitted[0]["details"]["rename"]
    assert rename["to"] == "MDA" and rename["renamed"] == ["Hudu", "Ninja"]
    assert rename["pending"] == [{"source": "LogMeIn", "observed_name": "Prompt"}]
    assert all("_group" not in row for row in emitted[0]["details"]["rows"])


def test_no_rename_without_the_old_name_in_history_or_after_a_decision(monkeypatch):
    renamed = []
    # Always reported another name: a difference, not a rename.
    emitted, _ = _findings(monkeypatch, [_row("Ninja", "ADH")], renamed=renamed)
    assert renamed == [] and emitted[0]["details"]["rename"] is None
    # Confirmed as it is (e.g. an undone rename): stays.
    emitted, _ = _findings(
        monkeypatch, [_row("Ninja", "MDA", state="explicit")],
        history=[_was("Ninja", "Prompt")], renamed=renamed,
    )
    assert renamed == [] and emitted == []


def test_sources_renamed_to_different_names_are_not_renamed(monkeypatch):
    renamed = []
    emitted, _ = _findings(
        monkeypatch,
        [_row("Ninja", "MDA"), _row("Hudu", "MDA Group")],
        history=[_was("Ninja", "Prompt"), _was("Hudu", "Prompt")],
        renamed=renamed,
    )
    assert renamed == [] and emitted[0]["details"]["rename"]["to"] == ["MDA", "MDA Group"]
