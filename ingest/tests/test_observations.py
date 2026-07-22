from ingest.observations import material_hash, material_projection


def test_volatile_fields_do_not_change_material_hash():
    base = {
        "hostname": "host-1",
        "last_seen_at": "a",
        "is_online": True,
        "power_state": "on",
    }
    changed_heartbeat = {
        **base,
        "last_seen_at": "b",
        "is_online": False,
        "power_state": "off",
    }
    assert material_hash(base) == material_hash(changed_heartbeat)
    assert material_hash(base) != material_hash({**base, "hostname": "host-2"})


def test_material_fields_change_hash_and_projection_is_sorted():
    base = {"hostname": "host-1", "os_version": "1"}
    changed = {**base, "os_version": "2"}
    assert material_hash(base) != material_hash(changed)
    assert list(material_projection(base)) == ["hostname", "os_version"]


def test_parent_scope_is_part_of_identity_contract():
    first = ("software", "device-a", "agent")
    second = ("software", "device-b", "agent")
    assert first != second
