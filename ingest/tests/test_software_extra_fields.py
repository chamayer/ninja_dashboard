"""Ninja's productCode / size / isSystemComponent are captured, and unhashed.

Two separate properties, both of which fail quietly rather than loudly:

1. The collector must keep the fields. They are returned on every row of
   `/queries/software` and were discarded for the life of the collector --
   measured 2026-08-12 across 25,000 rows / 3,112 devices / 4,434 titles:
   productCode 93.8%, size 40.4%, isSystemComponent 7.6%.

2. They must NOT enter the material hash. `_write_installation_current` hashes
   (publisher, version, location, install_date) to decide whether an
   installation materially changed. Adding a field to that set changes every
   hash on the next run and closes/reopens all 490,733 SCD-2 intervals in one
   cycle. Nothing would error -- the history would simply double overnight,
   which is why this deserves a test rather than a comment.
"""

from __future__ import annotations

import re
from pathlib import Path

_SOFTWARE = Path(__file__).resolve().parents[1] / "inventory" / "software.py"

_EXTRA_FIELDS = ("product_code", "size_bytes", "is_system_component")


def _source() -> str:
    return _SOFTWARE.read_text(encoding="utf-8")


def _material_block() -> str:
    """The `material = { ... }` literal that feeds material_hash()."""
    match = re.search(r"material\s*=\s*\{(.*?)\}", _source(), re.DOTALL)
    assert match is not None, "could not locate the material dict"
    return match.group(1)


def test_collector_reads_the_fields_ninja_returns() -> None:
    source = _source()
    assert 'item.get("productCode")' in source
    assert 'item.get("size")' in source
    assert 'item.get("isSystemComponent")' in source


def test_fields_are_persisted_on_the_current_row() -> None:
    source = _source()
    for field in _EXTRA_FIELDS:
        assert f'"{field}": canonical.get("{field}")' in source, field


def test_fields_are_in_the_upsert_column_list() -> None:
    """Present in the row dict but absent from the update list would mean they
    are written on insert and then never refreshed."""
    source = _source()
    upsert = source[source.index("software_installations_current\","):]
    for field in _EXTRA_FIELDS:
        assert f'"{field}"' in upsert, field


def test_the_new_fields_are_not_material() -> None:
    """The 490k-interval trap. See the module docstring."""
    block = _material_block()
    for field in _EXTRA_FIELDS:
        assert field not in block, (
            f"{field} was added to the material hash. Every installation's "
            "hash changes on the next run, closing and reopening all ~490k "
            "SCD-2 intervals in one cycle. These describe the product, not "
            "the installation event -- see migration 091."
        )
    # Also guard the raw Ninja spellings, in case someone maps them directly.
    for raw in ("productCode", "isSystemComponent"):
        assert raw not in block, raw


def test_material_still_hashes_what_it_should() -> None:
    """Guard the other direction: the test above must not be satisfiable by
    emptying the material dict."""
    block = _material_block()
    for field in ("publisher", "version", "location", "install_date"):
        assert field in block, field


def test_query_timestamp_is_not_stored() -> None:
    """`timestamp` is the query's own clock; last_observed_at already records
    when we saw the row. Storing it would imply a fact about the install."""
    source = _source()
    assert 'item.get("timestamp")' not in source
