"""A source group with a client is not unmatched (stale rows, 2026-10-23)."""

from pathlib import Path

_SOURCE = (Path(__file__).parents[1] / "identity" / "resolver.py").read_text(encoding="utf-8")


def test_rows_for_groups_with_a_client_are_cleared_before_findings_are_raised():
    section = _SOURCE[_SOURCE.index("# unmatched_source_group — one finding per pending row") :]
    clear = section.index("DELETE FROM operations.unmatched_source_groups u")
    close = section.index("SET status = 'resolved', closed_at = NOW()")
    raise_ = section.index("INSERT INTO operations.findings (")
    assert clear < close < raise_
    assert "FROM operations.v_client_source_link link" in section[clear:close]
    # Only pending rows keep a finding open; operator suppressions stay.
    assert "AND f.status IN ('open', 'acknowledged', 'investigating')" in section[close:raise_]
    assert "u.status = 'pending'" in section[close:raise_]
