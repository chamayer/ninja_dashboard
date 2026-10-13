"""Per-device condition readiness for software finding types.

A device's readiness (identity settled, recent agent contact) does not depend
on which software finding it takes part in. The previous classifier assessed it
again for every (finding, device) pair: one title finding could cover about
4,000 devices, and each assessment rewrote the whole participant list. This
table holds one engine decision per (device, software finding type), refreshed
by the software jobs; title-level findings derive their per-device state from it
(design D1) and are notifiable when at least one exposed device is ready (D4).
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE TABLE operations.software_device_readiness (
    tenant_id BIGINT NOT NULL REFERENCES operations.tenants(id) CHECK (tenant_id = 1),
    device_id UUID NOT NULL,
    finding_type_id SMALLINT NOT NULL REFERENCES operations.finding_types(id),
    policy_version TEXT NOT NULL CHECK (length(policy_version) BETWEEN 1 AND 200),
    policy_digest TEXT NOT NULL CHECK (length(policy_digest) BETWEEN 1 AND 200),
    disposition TEXT NOT NULL
        CHECK (disposition IN ('eligible', 'suppressed', 'blocked', 'unknown')),
    may_notify BOOLEAN NOT NULL,
    may_execute BOOLEAN NOT NULL,
    reasons TEXT[] NOT NULL DEFAULT '{}',
    blockers TEXT[] NOT NULL DEFAULT '{}',
    assessed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, device_id, finding_type_id),
    FOREIGN KEY (tenant_id, device_id)
        REFERENCES operations.devices(tenant_id, id) ON DELETE CASCADE
);
CREATE INDEX software_device_readiness_type_idx
    ON operations.software_device_readiness (tenant_id, finding_type_id, may_execute);

ALTER TABLE operations.software_device_readiness OWNER TO operations_migrate;
REVOKE ALL ON operations.software_device_readiness
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.software_device_readiness
    TO operations_app, ninja_ingest, operations_readonly, operations_view_owner;
GRANT INSERT, UPDATE, DELETE ON operations.software_device_readiness TO ninja_ingest;
ALTER TABLE operations.software_device_readiness ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.software_device_readiness FORCE ROW LEVEL SECURITY;
CREATE POLICY software_device_readiness_tenant_isolation
ON operations.software_device_readiness
USING (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint)
WITH CHECK (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint);

COMMENT ON TABLE operations.software_device_readiness IS
    'One condition-engine decision per (device, software finding type) under the active policy. Derived; rebuilt by the software readiness job.';
"""

REVERSE_SQL = r"""
DROP TABLE IF EXISTS operations.software_device_readiness;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0281_jobs_wait_reason_names_interrupted_holder"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
