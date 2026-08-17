"""Regression coverage for device-detail Ninja patch-signal lookup."""

from __future__ import annotations

from types import SimpleNamespace

from apps.core.views import _ninja_patch_device_ids


def _link(source_name: str, external_id: str):
    return SimpleNamespace(
        source=SimpleNamespace(name=source_name),
        external_id=external_id,
    )


def test_patch_signal_ids_ignore_unrelated_and_out_of_range_source_links() -> None:
    """A large non-Ninja ID must not break a device that has a valid Ninja ID."""
    links = [
        _link("Ninja", "12345"),
        _link("SentinelOne", "2435736664543458197"),
        _link("Ninja", "2147483648"),
        _link("Ninja", "12345"),
        _link("Ninja", "not-a-number"),
    ]

    assert _ninja_patch_device_ids(links) == [12345]
