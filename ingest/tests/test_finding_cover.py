"""Cover is a live relation decided by the state writer; assessments only carry a ready signal."""

from __future__ import annotations

from pathlib import Path

from shared.conditions.contracts import Condition, Participant, Readiness

from ingest import finding_cover

DEVICE = "11111111-1111-1111-1111-111111111111"


def _condition(*participants, row_kind="entity"):
    return Condition(1, row_kind, "f1", "stale_required_platform", "k", "open", tuple(participants))


def test_every_participant_gets_a_ready_signal_so_the_engine_never_reads_it_as_unknown():
    device = Participant("device", DEVICE, "affected", 1)
    context = Participant("client", "33333333-3333-3333-3333-333333333333", "context", 1)
    signals = finding_cover.ready_signals(_condition(device, context))
    assert [s.readiness for s in signals] == [Readiness.READY, Readiness.READY]
    assert {s.participant for s in signals} == {device, context}
    assert {s.prerequisite for s in signals} == {finding_cover.RULE}


def test_the_signal_never_names_a_blocker_because_cover_is_not_evidence():
    (signal,) = finding_cover.ready_signals(_condition(Participant("device", DEVICE, "affected", 1)))
    assert signal.blocker_references == ()
    assert not signal.reason.startswith("covered_by")


def test_record_assessment_adds_the_ready_signals_only_when_the_policy_has_the_rule():
    source = (Path(finding_cover.__file__).parent / "conditions.py").read_text(encoding="utf-8")
    assert "if finding_cover.RULE in profile.rules:" in source
    assert "signals += finding_cover.ready_signals(condition)" in source
    assert "cover_signals" not in source


def test_the_module_no_longer_reads_the_database():
    source = Path(finding_cover.__file__).read_text(encoding="utf-8")
    assert "cur.execute" not in source
    assert "covered_by_map" not in source
