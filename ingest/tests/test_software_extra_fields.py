"""Ninja's productCode / size / isSystemComponent are captured, and unhashed.

Two separate properties, both of which fail quietly rather than loudly:

1. The collector must keep the fields. They are returned on every row of
   `/queries/software` -- measured 2026-08-12 across 25,000 rows / 3,112
   devices / 4,434 titles: productCode 93.8%, size 40.4%, isSystemComponent
   7.6%.

2. They must NOT enter the material hash. The hash of (publisher, version,
   location, install_date) decides whether an installation materially changed.
   Changing that set changes every hash on the next run and closes/reopens
   every SCD-2 interval in one cycle. Nothing would error -- the history would
   simply double overnight, which is why this deserves a test.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ingest.inventory import software
from ingest.observations import material_hash

_ITEM = {
    "deviceId": 7, "name": "  Acme Tool ", "publisher": " Acme ", "version": "1.2",
    "location": "C:\\Program Files\\Acme", "installDate": "2026-01-02",
    "productCode": "{GUID}", "size": 1234, "isSystemComponent": False,
    "timestamp": 1_760_000_000,
}


def test_collector_keeps_the_fields_ninja_returns() -> None:
    row = software.normalize(_ITEM)
    assert row["product_code"] == "{GUID}"
    assert row["size_bytes"] == 1234
    assert row["is_system_component"] is False
    assert row["canonical_name"] == "acme tool"


def test_the_hash_is_byte_identical_to_the_previous_collector() -> None:
    """Same four fields, same normalization (install_date raw), same hash."""
    expected = material_hash({
        "publisher": "Acme", "version": "1.2", "location": "C:\\Program Files\\Acme",
        "install_date": "2026-01-02",
    })
    assert software.normalize(_ITEM)["material_hash"] == expected


def test_a_blank_install_date_hashes_as_before() -> None:
    item = {**_ITEM, "installDate": ""}
    expected = material_hash({
        "publisher": "Acme", "version": "1.2", "location": "C:\\Program Files\\Acme",
        "install_date": "",
    })
    row = software.normalize(item)
    assert row["material_hash"] == expected
    assert row["install_date"] is None


def test_the_product_fields_are_not_material() -> None:
    """The every-interval trap. See the module docstring."""
    changed = {**_ITEM, "productCode": "{OTHER}", "size": 99, "isSystemComponent": True}
    assert software.normalize(changed)["material_hash"] == software.normalize(_ITEM)["material_hash"]


def test_material_fields_do_change_the_hash() -> None:
    for key in ("publisher", "version", "location", "installDate"):
        changed = {**_ITEM, key: "different"}
        assert software.normalize(changed)["material_hash"] != software.normalize(_ITEM)["material_hash"], key


def test_collection_time_is_per_device_not_the_query_clock() -> None:
    """Measured 2026-10-13 over 20,000 rows / 1,422 devices: the age of
    `timestamp` ranged from 1.9 h (p10) to 2,580 h (p90), so it is when Ninja
    collected the device's list, not when the query ran."""
    expected = datetime.fromtimestamp(1_760_000_000, tz=UTC)
    assert software.collected_time(1_760_000_000) == expected
    assert software.collected_time(1_760_000_000_000) == expected
    assert software.collected_time(None) is None
    assert software.collected_time("not a time") is None
