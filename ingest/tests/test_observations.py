from ingest.observations import material_hash, material_projection


def test_volatile_fields_do_not_change_material_hash():
    base = {"hostname": "host-1", "last_seen_at": "a", "is_online": True}
    changed_heartbeat = {**base, "last_seen_at": "b", "is_online": False}
    assert material_hash(base) == material_hash(changed_heartbeat)


def test_material_fields_change_hash_and_projection_is_sorted():
    base = {"hostname": "host-1", "os_version": "1"}
    changed = {**base, "os_version": "2"}
    assert material_hash(base) != material_hash(changed)
    assert list(material_projection(base)) == ["hostname", "os_version"]
