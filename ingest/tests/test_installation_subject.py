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

from ingest import software_reconcile as sr
from ingest.tests.test_software_reconcile import TYPES, _ctx, _desired, _title

DEVICE_A, DEVICE_B, CLIENT = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _path(installation, device, title="Acme Tool"):
    # (installation_uuid, device, client, title_key, name, publisher, location,
    #  title decision, publisher decision): the PATH_INSTALLS_SQL row shape.
    return (installation, device, CLIENT, title.lower(), title, "Acme",
            r"C:\Users\x\AppData\Local\Temp\acme", None, None)


def test_installation_scope_resolves_to_the_installation_uuid() -> None:
    install = uuid.uuid4()
    desired, _ = _desired(_ctx([_title("Acme Tool", 2)], paths=[_path(install, DEVICE_A)]))
    [finding] = desired["install_path_suspicious"]
    assert finding.subject_type == "software_installation"
    assert finding.subject_id == str(install)
    assert finding.device_id == str(DEVICE_A)


def test_installation_scope_keeps_per_pair_identity_in_the_condition_key() -> None:
    """Two devices, one title: the keys must differ.

    Product and version scope deliberately drop client and device because the
    claim is about the title. An installation claim is about the pair, so the
    same reduction would silently collapse the two rows into one.
    """
    a, b = uuid.uuid4(), uuid.uuid4()
    desired, _ = _desired(_ctx([_title("Acme Tool", 2)],
                               paths=[_path(a, DEVICE_A), _path(b, DEVICE_B)]))
    keys = {d.condition_key for d in desired["install_path_suspicious"]}
    type_id = TYPES["install_path_suspicious"].id
    assert keys == {sr.condition_key(1, None, None, type_id, f"Acme Tool@{a}"),
                    sr.condition_key(1, None, None, type_id, f"Acme Tool@{b}")}


def test_subject_survives_a_version_upgrade() -> None:
    """The installation handle (migration 089) does not change with the
    version, so the subject and key stay put across an upgrade."""
    install = uuid.uuid4()
    first, _ = _desired(_ctx([_title("Acme Tool", 1)], paths=[_path(install, DEVICE_A)]))
    second, _ = _desired(_ctx([_title("Acme Tool", 1)], paths=[_path(install, DEVICE_A)],
                              versions=[("acme tool", str(uuid.uuid4()), "2.0", 1)]))
    assert ([d.condition_key for d in first["install_path_suspicious"]]
            == [d.condition_key for d in second["install_path_suspicious"]])
