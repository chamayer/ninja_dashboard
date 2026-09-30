"""Focused contract checks for governed intelligence successor admission."""

from __future__ import annotations

from pathlib import Path

from ingest.intel.material import MaterialCount


_INGEST = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (_INGEST / relative).read_text(encoding="utf-8")


def test_material_count_preserves_integer_compatibility() -> None:
    changed = MaterialCount(7, material_changed=True)
    unchanged = MaterialCount(0, material_changed=False)

    assert isinstance(changed, int)
    assert changed + 1 == 8
    assert changed.material_changed is True
    assert unchanged.material_changed is False


def test_worker_never_infers_material_change_from_a_positive_count() -> None:
    queue = _source("operator_job_queue.py")

    assert 'getattr(result, "material_changed", False)' in queue
    assert 'result > 0 and any(' not in queue


def test_refresh_upserts_ignore_timestamp_only_reobservations() -> None:
    for relative in (
        "intel/nvd.py",
        "intel/cpe_dict.py",
        "intel/cisa_kev.py",
        "intel/epss.py",
        "intel/winget.py",
        "intel/chocolatey.py",
        "intel/otx.py",
        "intel/abusech.py",
        "intel/endoflife.py",
        "intel/capability_match.py",
        "intel/category_match.py",
        "intel/lolrmm.py",
    ):
        source = _source(relative)
        assert "IS DISTINCT FROM" in source, relative


def test_full_matcher_compares_semantic_output_sets() -> None:
    matcher = _source("intel/matcher.py")

    assert "CREATE TEMP TABLE cve_match_before" in matcher
    assert matcher.count("EXCEPT") >= 2
    assert "material_changed=material_changed" in matcher
