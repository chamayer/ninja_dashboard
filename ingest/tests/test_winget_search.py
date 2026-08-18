"""The Winget enricher must match one exact package, never union top-N.

`_search` queried `/v2/packages?query=<title>&take=5` and unioned the tags,
publisher and package identifier of every one of the top-5 results into one
row -- the same failure `test_chocolatey_search.py` documents for the
Chocolatey enricher (092), wearing a different cause: Winget's endpoint does
filter by query, but "top-5 relevance matches" still is not "the one right
package."

Measured 2026-08-18 against `safety_signal`: 374 of 379 stored rows (98.7%)
carried more than one publisher or package identifier -- the union signature.
Querying "01 transaction pro exporter 6.0" returned Chinese chat, video and
shopping apps in the same top-5 batch, and their tags -- "chat", "video",
"taobao" -- were stored as if they described the exporter.
"""

from __future__ import annotations

import re
from pathlib import Path

_WINGET = Path(__file__).resolve().parents[1] / "intel" / "winget.py"


def _source() -> str:
    return _WINGET.read_text(encoding="utf-8")


def _code_only() -> str:
    """Comments name the broken form in order to explain it."""
    return "\n".join(
        line for line in _source().splitlines()
        if not line.lstrip().startswith("#")
    )


def _load_search():
    """Import _search and _normalize without pulling in httpx or
    ingest.config (pydantic), neither installed on a bare workstation. Same
    workaround as test_product_authorization.py."""
    import sys
    import types

    if "httpx" not in sys.modules:
        stub = types.ModuleType("httpx")
        stub.Client = object
        stub.HTTPError = Exception
        sys.modules["httpx"] = stub
    if "ingest.config" not in sys.modules:
        stub = types.ModuleType("ingest.config")
        stub.settings = types.SimpleNamespace()
        sys.modules["ingest.config"] = stub
    import ingest.intel.winget as mod
    return mod


def test_tags_are_not_unioned_across_the_top_n_results() -> None:
    code = _code_only()
    assert "tags.add" not in code, (
        "accumulating tags into one set across every result in the response "
        "is the original defect -- one result's tags described none of them"
    )
    assert "publishers.add" not in code
    assert "package_ids.add" not in code


def test_only_an_exact_name_match_is_accepted() -> None:
    code = _code_only()
    assert "_normalize(canonical)" in code
    assert "_normalize(name) == wanted" in code
    # No relevance fallback: returning the first or best-scored candidate when
    # nothing matches exactly is what let unrelated packages' tags through.
    assert "packages[0]" not in code
    assert "difflib" not in code, "a similarity threshold was measured and rejected for Chocolatey; same reasoning applies here"


def test_normalize_matches_the_chocolatey_enricher() -> None:
    """Same regex, same behavior, so a title's identity does not depend on
    which enricher is asked."""
    mod = _load_search()
    assert mod._normalize("Google Chrome") == mod._normalize("google-chrome") == "googlechrome"
    assert mod._normalize("7-Zip") == "7zip"


def test_search_returns_only_the_matched_package() -> None:
    """Behavioral: three candidates, only the middle one's normalized name
    matches -- its tags/publisher/id must come back, not a union, and the
    other two candidates' names still land in titles_found."""
    mod = _load_search()

    class _FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "Packages": [
                    {
                        "Id": "Some.Unrelated",
                        "Latest": {"Name": "Totally Different App", "Tags": ["chat", "video"], "Publisher": "Wrong Co"},
                    },
                    {
                        "Id": "Mozilla.Firefox",
                        "Latest": {"Name": "Mozilla Firefox", "Tags": ["browser", "web"], "Publisher": "Mozilla"},
                    },
                    {
                        "Id": "Another.Unrelated",
                        "Latest": {"Name": "Yet Another Thing", "Tags": ["shopping"], "Publisher": "Other Co"},
                    },
                ]
            }

    class _FakeClient:
        def get(self, url, params=None):
            return _FakeResponse()

    tags, publisher, package_id, titles_found = mod._search(_FakeClient(), "Mozilla Firefox")
    assert tags == ["browser", "web"]
    assert publisher == "Mozilla"
    assert package_id == "Mozilla.Firefox"
    # Returns as soon as the match is found -- titles_found holds what was
    # seen up to and including the match, not the whole response. The third
    # candidate's tags are never even read.
    assert titles_found == ["Totally Different App", "Mozilla Firefox"]


def test_search_returns_nothing_but_records_candidates_on_no_match() -> None:
    """A queried title absent from the top-5 must not fall back to the
    nearest guess -- the exact defect that put chat-app tags on an exporter."""
    mod = _load_search()

    class _FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "Packages": [
                    {"Id": "x", "Latest": {"Name": "Something Else Entirely", "Tags": ["a"], "Publisher": "P"}},
                ]
            }

    class _FakeClient:
        def get(self, url, params=None):
            return _FakeResponse()

    tags, publisher, package_id, titles_found = mod._search(_FakeClient(), "01 Transaction Pro Exporter 6.0")
    assert tags == []
    assert publisher == ""
    assert package_id == ""
    assert titles_found == ["Something Else Entirely"]


def test_migration_clears_the_poisoned_rows() -> None:
    """The fix alone changes nothing for 30 days -- refresh is stale-gated."""
    migration = (
        Path(__file__).resolve().parents[2]
        / "sql" / "migrations" / "103_clear_poisoned_winget_signals.sql"
    ).read_text(encoding="utf-8")
    assert "DELETE FROM operations.safety_signal" in migration
    assert "source = 'winget'" in migration
    # Must not take out the other feeds.
    for other in ("chocolatey", "otx", "threatfox", "abusech"):
        assert f"'{other}'" not in migration
