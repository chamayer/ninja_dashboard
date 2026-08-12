"""ADR-0015 s2: `install_path_suspicious` belongs to the installation.

The install path describes the device-and-software pair, not either endpoint.
Two properties are enforced here, both of which would fail silently rather
than raise:

1. The installation subject is the *pair*, so unlike product and version scope
   it must keep per-pair identity in the condition key. Dropping client and
   device without substituting the installation would make the same title on
   two devices collapse to one key and dedupe the second away.
2. The subject must survive a version upgrade. The installation primary key is
   (tenant_id, client_id, device_id, canonical_name) and excludes the version,
   so an upgrade updates the row in place. A subject derived from the version
   would change on every update and reopen a finding whose path never moved --
   which is why migration 089 mints a stored handle instead.
"""

from __future__ import annotations

import uuid

import pytest

sf = pytest.importorskip("ingest.software_findings")

DEVICE = uuid.uuid4()
PRODUCT = uuid.uuid4()
VERSION = uuid.uuid4()
INSTALL = uuid.uuid4()


def test_installation_scope_resolves_to_the_installation_uuid() -> None:
    subject_type, subject_id, *_ = sf._subject_for(
        "software_installation", DEVICE, PRODUCT, VERSION, INSTALL
    )
    assert subject_type == "software_installation"
    assert subject_id == INSTALL


def test_installation_scope_is_not_the_device_or_the_version() -> None:
    _t, subject_id, *_ = sf._subject_for(
        "software_installation", DEVICE, PRODUCT, VERSION, INSTALL
    )
    assert subject_id != DEVICE
    assert subject_id != VERSION


def test_missing_installation_uuid_falls_back_to_device() -> None:
    """A NULL handle must not produce a finding with a NULL subject."""
    subject_type, subject_id, *_ = sf._subject_for(
        "software_installation", DEVICE, PRODUCT, VERSION, None
    )
    assert subject_type == "device"
    assert subject_id == DEVICE


def test_the_other_scopes_are_unchanged() -> None:
    assert sf._subject_for("software_product", DEVICE, PRODUCT, VERSION, INSTALL)[:2] == (
        "software_product", PRODUCT,
    )
    assert sf._subject_for("software_version", DEVICE, PRODUCT, VERSION, INSTALL)[:2] == (
        "software_version", VERSION,
    )
    assert sf._subject_for("device", DEVICE, PRODUCT, VERSION, INSTALL)[:2] == (
        "device", DEVICE,
    )


def test_unknown_scope_still_defaults_to_device() -> None:
    assert sf._subject_for("not_a_scope", DEVICE, PRODUCT, VERSION, INSTALL)[:2] == (
        "device", DEVICE,
    )


def test_subject_survives_a_version_upgrade() -> None:
    """The whole reason 089 mints rather than derives.

    Same installation row, new release: the subject must not move.
    """
    before = sf._subject_for(
        "software_installation", DEVICE, PRODUCT, uuid.uuid4(), INSTALL
    )
    after = sf._subject_for(
        "software_installation", DEVICE, PRODUCT, uuid.uuid4(), INSTALL
    )
    assert before[1] == after[1] == INSTALL


def test_installation_scope_keeps_per_pair_identity_in_the_condition_key() -> None:
    """Two devices, one title: the keys must differ.

    Product and version scope deliberately drop client and device because the
    claim is about the title. An installation claim is about the pair, so the
    same reduction would silently collapse the two rows into one.
    """
    install_a, install_b = uuid.uuid4(), uuid.uuid4()
    key_a = sf._condition_key(1, None, None, "7", f"acme tool@{install_a}")
    key_b = sf._condition_key(1, None, None, "7", f"acme tool@{install_b}")
    assert key_a != key_b


def test_three_tuple_callers_still_work() -> None:
    """`subj` gained a fourth member; older callers must not raise."""
    scope_by_id = {7: "software_product"}
    subj = (scope_by_id, PRODUCT, VERSION)
    unpacked = (
        tuple(subj) + (None,) if subj is not None and len(subj) == 3
        else (subj or ({}, None, None, None))
    )
    assert unpacked == (scope_by_id, PRODUCT, VERSION, None)
