"""The CPE candidate lookup must be shaped like the index that serves it.

`intel.cpes` carries exactly one non-primary index:

    cpes_vendor_product_idx ON intel.cpes (lower(vendor), lower(product))

A predicate on `LOWER(vendor) || '|' || LOWER(product)` is a *different*
expression, so PostgreSQL cannot use that index and falls back to a parallel
sequential scan of the whole table. The matcher runs this lookup once per
installed title -- roughly 21k times per full refresh -- so the difference is
between an index probe and 21k scans of 1.8M rows.

Measured 2026-08-12 against production, same inputs, identical 9,662 rows
returned: parallel seq scan removing 596,768 rows per worker, versus a 20 ms
index scan.

This is a ratchet. The concatenated form is not a style preference and it does
not announce itself -- the query stays correct and simply gets slower as
`intel.cpes` grows, which is exactly how it survived the 164,860 -> 1,799,966
backfill unnoticed.
"""

from __future__ import annotations

import re
from pathlib import Path

_MATCHER = Path(__file__).resolve().parents[1] / "intel" / "matcher.py"


def _source() -> str:
    return _MATCHER.read_text(encoding="utf-8")


def _code_only() -> str:
    """Source with `#` comment lines removed.

    The rule is about the SQL the module executes, not about prose. The
    comment beside the fixed query names the offending expression in order to
    explain it, and a scan that could not tell those apart would force the
    explanation to be deleted to satisfy the check.
    """
    return "\n".join(
        line for line in _source().splitlines()
        if not line.lstrip().startswith("#")
    )


def test_no_concatenated_vendor_product_predicate() -> None:
    """The form that defeats the index must not reappear."""
    source = _code_only()
    # Any SQL concatenation of vendor and product into one comparable string.
    offending = re.search(
        r"LOWER\s*\(\s*vendor\s*\)\s*\|\|.*?LOWER\s*\(\s*product\s*\)",
        source,
        re.IGNORECASE | re.DOTALL,
    )
    assert offending is None, (
        "matcher.py builds a concatenated vendor||product predicate. "
        "intel.cpes is indexed on (lower(vendor), lower(product)) as two "
        "columns, so the concatenated form cannot use it and seq-scans "
        "1.8M rows once per title. Join on the two columns instead."
    )


def test_tier1_lookup_joins_on_both_indexed_columns() -> None:
    """The replacement must actually match the index, not merely differ."""
    source = _source()
    assert "LOWER(c.vendor) = k.vendor" in source
    assert "LOWER(c.product) = k.product" in source


def test_tier1_lookup_pairs_vendor_and_product_positionally() -> None:
    """`unnest` of two arrays is positional -- the pairing must not drift.

    Building the two lists from one ordered sequence is what guarantees
    vendors[i] belongs with products[i]; deriving them from the set twice
    would not, because set iteration order is not contractual.
    """
    source = _source()
    assert "pairs = sorted(tier1_pairs)" in source
    assert "[v for v, _ in pairs], [p for _, p in pairs]" in source
