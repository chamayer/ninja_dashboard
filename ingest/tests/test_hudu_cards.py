"""Card resolution for the Hudu aggregator.

Verdicts must stay total and mutually exclusive: every asset lands in exactly
one of linked / divergent / stale / unlinked, and only `linked` carries a
device. Measured against the live instance, `divergent` is ~1% and `stale`
~400 assets, so a regression that collapses these buckets would silently
mis-attach documentation to devices.
"""

from __future__ import annotations

import pytest

pytest.importorskip("httpx", reason="ingest HTTP deps ship in the container")

from ingest.connectors.hudu import _provenance, _resolve_cards  # noqa: E402

DEV_A = "11111111-1111-4111-8111-111111111111"
DEV_B = "22222222-2222-4222-8222-222222222222"
NINJA_MAP = {"296": (DEV_A, "client-a"), "304": (DEV_A, "client-a"), "999": (DEV_B, "client-b")}


def _asset(*cards):
    return {"id": 1, "cards": list(cards)}


def _ninja(sync_id):
    return {"integrator_name": "ninja", "sync_id": sync_id, "sync_type": "device"}


def _ninja_location(sync_id):
    return {"integrator_name": "ninja", "sync_id": sync_id, "sync_type": "location"}


def _auvik(sync_identifier):
    return {
        "integrator_name": "auvik", "sync_id": None,
        "sync_identifier": sync_identifier, "sync_type": "device",
    }


def test_single_card_links():
    relayed, verdict, device_id, client_id = _resolve_cards(_asset(_ninja(296)), NINJA_MAP)
    assert (verdict, device_id, client_id) == ("linked", DEV_A, "client-a")
    assert relayed[0]["key"] == "296" and relayed[0]["integrated"] is True


def test_multiple_cards_on_one_device_converge():
    # agent + VM-guest records for the same machine — the common case (54% of
    # servers carry 2+ Ninja cards).
    _, verdict, device_id, _ = _resolve_cards(_asset(_ninja(296), _ninja(304)), NINJA_MAP)
    assert (verdict, device_id) == ("linked", DEV_A)


def test_superseded_card_is_ignored_not_an_error():
    # 2606 no longer resolves; the live one still wins.
    _, verdict, device_id, _ = _resolve_cards(_asset(_ninja(2606), _ninja(296)), NINJA_MAP)
    assert (verdict, device_id) == ("linked", DEV_A)


def test_cards_spanning_two_devices_attach_nothing():
    _, verdict, device_id, client_id = _resolve_cards(_asset(_ninja(296), _ninja(999)), NINJA_MAP)
    assert (verdict, device_id, client_id) == ("divergent", None, None)


def test_all_cards_unresolvable_is_stale():
    _, verdict, device_id, _ = _resolve_cards(_asset(_ninja(2606)), NINJA_MAP)
    assert (verdict, device_id) == ("stale", None)


def test_no_integrated_card_is_unlinked_not_stale():
    # Second-hand only: never had a first-party pointer, so nothing went stale.
    _, verdict, device_id, _ = _resolve_cards(_asset(_auvik("MTMz")), NINJA_MAP)
    assert (verdict, device_id) == ("unlinked", None)


def test_no_cards_at_all_is_unlinked():
    _, verdict, _, _ = _resolve_cards(_asset(), NINJA_MAP)
    assert verdict == "unlinked"


def test_auvik_uses_sync_identifier_since_sync_id_is_null():
    relayed, _, _, _ = _resolve_cards(_asset(_auvik("MTMz")), NINJA_MAP)
    assert relayed[0]["key"] == "MTMz"
    assert relayed[0]["integrated"] is False


def test_provenance_second_hand_only_when_every_relay_unintegrated():
    assert _provenance([{"integrated": False}]) == "second_hand"
    # 178 live assets carry ninja+auvik together; one integrated relay is
    # enough to make the record first-party.
    assert _provenance([{"integrated": False}, {"integrated": True}]) == "first_party"
    assert _provenance([]) == "first_party"


def test_location_card_never_resolves_to_a_device():
    # Ninja location ids are a separate namespace from device ids. Resolving
    # location 296 against the device map attached a Hudu "Main Office"
    # record to an unrelated machine in production.
    relayed, verdict, device_id, _ = _resolve_cards(_asset(_ninja_location(296)), NINJA_MAP)
    assert (verdict, device_id) == ("unlinked", None)
    assert relayed[0]["sync_type"] == "location"
    assert relayed[0]["resolved_device_id"] is None


def test_location_card_alongside_device_card_does_not_disturb_linking():
    _, verdict, device_id, _ = _resolve_cards(
        _asset(_ninja_location(999), _ninja(296)), NINJA_MAP
    )
    # 999 is a *location* id here; only the device card may resolve.
    assert (verdict, device_id) == ("linked", DEV_A)


def test_location_only_asset_is_unlinked_not_stale():
    # Never had a device pointer, so nothing went stale.
    _, verdict, _, _ = _resolve_cards(_asset(_ninja_location(2606)), NINJA_MAP)
    assert verdict == "unlinked"


def test_cardless_vendor_entries_are_skipped():
    junk = {"integrator_name": "", "sync_id": 296}
    missing_key = {"integrator_name": "ninja", "sync_id": None, "sync_identifier": None}
    relayed, verdict, _, _ = _resolve_cards(_asset(junk, missing_key), NINJA_MAP)
    assert relayed == [] and verdict == "unlinked"
