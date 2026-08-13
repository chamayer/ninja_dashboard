"""The Chocolatey enricher must query Search(), and tag one package at a time.

Two independent defects put 1,473 rows of noise in `safety_signal`, and both
are the kind that report success:

1. **Wrong endpoint.** `searchTerm` is a parameter of the OData `Search()`
   function. `Packages()` accepts the query string, ignores the term, and
   returns HTTP 200 with the unfiltered first page of the gallery. No error,
   no warning -- just the wrong packages, every time.
2. **Tags unioned across the response.** `findall` over the whole body merged
   up to five packages' tags into one set, which then described none of them.

Together they gave every enriched title the same 22 tags, beginning
"0install, 1c, 1c83" -- the alphabetically first packages in the gallery.

Verified against the live API 2026-08-12 after the fix: google chrome ->
browser/internet/web, wireshark -> network/protocol/sniffer, anydesk ->
remote/rdp/desktop/control. Seven titles, seven distinct tag sets.
"""

from __future__ import annotations

import re
from pathlib import Path

_CHOCO = Path(__file__).resolve().parents[1] / "intel" / "chocolatey.py"


def _source() -> str:
    return _CHOCO.read_text(encoding="utf-8")


def _code_only() -> str:
    """Comments name the broken form in order to explain it."""
    return "\n".join(
        line for line in _source().splitlines()
        if not line.lstrip().startswith("#")
    )


def test_endpoint_is_search_not_packages() -> None:
    code = _code_only()
    assert "/api/v2/Search()" in code
    assert "/api/v2/Packages()" not in code, (
        "Packages() ignores searchTerm and returns the gallery's first page "
        "with HTTP 200 -- the original defect."
    )


def test_search_sends_the_parameters_search_requires() -> None:
    """Omitting targetFramework or includePrerelease returns HTTP 400."""
    code = _code_only()
    assert "targetFramework" in code
    assert "includePrerelease" in code


def test_tags_are_read_per_entry_not_across_the_response() -> None:
    code = _code_only()
    assert "_ENTRY_ELEMENT.findall" in code, (
        "tags must be extracted per <entry>; a findall for tags over the whole "
        "body merges every result's tags into one meaningless set"
    )
    # The tag regex must be applied with .search inside a block, not .findall
    # over the response.
    assert "_TAG_ELEMENT.findall(body)" not in code
    assert "_TAG_ELEMENT.findall(r.text)" not in code


def test_only_an_exact_match_is_accepted() -> None:
    """Measured 2026-08-12 over 31 real titles: the best correct fuzzy match
    (25415inkscape.inkscape -> InkScape, 0.55) scores below the worst wrong one
    (microsoft edge update -> microsoft-edge-insider, 0.71), so no threshold
    separates them. Writing nothing beats guessing."""
    code = _code_only()
    assert "_normalize(canonical)" in code
    assert "if match is None:" in code
    assert "entries[0]" not in code, (
        "a relevance fallback accepts the gallery's nearest guess for titles "
        "Chocolatey does not carry -- 1.1.3.4 became dotnetcore-sdk"
    )
    assert "difflib" not in code, "similarity thresholds were measured and rejected"


def test_refresh_order_is_by_install_count() -> None:
    """Each run is capped, so ordering decides what the cap buys. Alphabetical
    spent a run on '. .' and '1.1.3.4' at a 3.5% hit rate."""
    code = _code_only()
    assert "ORDER BY COUNT(DISTINCT sic.device_id) DESC" in code
    assert "ORDER BY sic.canonical_name\n" not in code


def test_normalize_ignores_punctuation_and_case() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("_choco_probe", _CHOCO)
    assert spec and spec.loader
    # The module imports `ingest.*` at top level, so exercise the regex
    # directly rather than importing it.
    normalize_re = re.compile(r"[^a-z0-9]+")

    def norm(v: str) -> str:
        return normalize_re.sub("", v.lower())

    assert norm("Google Chrome") == norm("google-chrome") == "googlechrome"
    assert norm("7-Zip") == "7zip"
    assert norm("Notepad++") == "notepad"


def test_migration_clears_the_poisoned_rows() -> None:
    """The fix alone changes nothing for 30 days -- refresh is stale-gated."""
    migration = (
        Path(__file__).resolve().parents[2]
        / "sql" / "migrations" / "092_clear_poisoned_chocolatey_signals.sql"
    ).read_text(encoding="utf-8")
    assert "DELETE FROM operations.safety_signal" in migration
    assert "source = 'chocolatey'" in migration
    # Must not take out the other feeds.
    for other in ("winget", "otx", "threatfox", "abusech"):
        assert f"'{other}'" not in migration
