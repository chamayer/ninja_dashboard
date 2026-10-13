"""Per-device software inventory state for the rebuilt inventory ingest.

The rebuilt ingest receives complete software lists from Ninja (one device on a
software event, every reporting device in the daily fleet check) and applies
them set-based. This table records, per device, when Ninja last collected the
list, when we last received it and how many programs it held, so freshness is
visible per device and a list that suddenly shrinks can be held instead of
removing real installations. A held device stays held until an administrator
releases it; the release is recorded with who and when.

The two inventory Jobs change meaning (device worker and fleet check); their
replay-safe evidence is restated to match.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

DRAIN_EVIDENCE = (
    "The software device worker only reads Ninja software lists and applies them "
    "to local inventory rows in one transaction per batch. Queue entries are "
    "leased and an expired lease resets the entry to pending, so a replay "
    "converges and mutates nothing in Ninja."
)
FLEET_EVIDENCE = (
    "The software fleet check only reads Ninja software lists for the whole fleet "
    "and applies them to local inventory rows in one transaction. A later replay "
    "converges to current source state and has no external mutation."
)

FORWARD_SQL = rf"""
CREATE TABLE operations.software_inventory_devices (
    tenant_id BIGINT NOT NULL REFERENCES operations.tenants(id) CHECK (tenant_id = 1),
    device_id UUID NOT NULL,
    collected_at TIMESTAMPTZ,
    listed_at TIMESTAMPTZ NOT NULL,
    listed_count INTEGER NOT NULL CHECK (listed_count >= 0),
    listed_by TEXT NOT NULL CHECK (listed_by IN ('device', 'fleet')),
    held_at TIMESTAMPTZ,
    held_reason TEXT NOT NULL DEFAULT '' CHECK (length(held_reason) <= 400),
    held_listed_count INTEGER,
    held_previous_count INTEGER,
    release_requested_at TIMESTAMPTZ,
    release_requested_by TEXT NOT NULL DEFAULT '' CHECK (length(release_requested_by) <= 150),
    PRIMARY KEY (tenant_id, device_id),
    FOREIGN KEY (tenant_id, device_id)
        REFERENCES operations.devices(tenant_id, id) ON DELETE CASCADE,
    CHECK ((held_at IS NULL) = (held_reason = ''))
);
CREATE INDEX software_inventory_devices_held_idx
    ON operations.software_inventory_devices (tenant_id, held_at)
    WHERE held_at IS NOT NULL;

ALTER TABLE operations.software_inventory_devices OWNER TO operations_migrate;
REVOKE ALL ON operations.software_inventory_devices
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.software_inventory_devices
    TO operations_app, ninja_ingest, operations_readonly, operations_view_owner;
GRANT INSERT, UPDATE, DELETE ON operations.software_inventory_devices TO ninja_ingest;
GRANT UPDATE (release_requested_at, release_requested_by)
    ON operations.software_inventory_devices TO operations_app;
ALTER TABLE operations.software_inventory_devices ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.software_inventory_devices FORCE ROW LEVEL SECURITY;
CREATE POLICY software_inventory_devices_tenant_isolation
ON operations.software_inventory_devices
USING (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint)
WITH CHECK (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint);

COMMENT ON TABLE operations.software_inventory_devices IS
    'Per-device software inventory state: last Ninja collection, last complete list received, and removal holds for lists that shrank sharply.';

UPDATE operations.job_recovery_policy_authorities
   SET evidence_summary = '{DRAIN_EVIDENCE}', reviewed_at = now()
 WHERE tenant_id = 1 AND definition_key = 'software-queue-drain';
UPDATE operations.job_recovery_policy_authorities
   SET evidence_summary = '{FLEET_EVIDENCE}', reviewed_at = now()
 WHERE tenant_id = 1 AND definition_key = 'software-enqueue-orgs';
"""

REVERSE_SQL = r"""
DROP TABLE IF EXISTS operations.software_inventory_devices;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0284_rare_software_title_grain"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
