"""Durable targeted software reclassification requests."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
CREATE TABLE operations.software_reclassification_targets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id BIGINT NOT NULL REFERENCES operations.tenants(id) CHECK (tenant_id = 1),
    target_key TEXT NOT NULL CHECK (length(target_key) BETWEEN 3 AND 300),
    software_version_id BIGINT REFERENCES catalog.software_versions(id),
    canonical_name TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL CHECK (length(source) BETWEEN 1 AND 80),
    queued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    consumed_at TIMESTAMPTZ,
    CHECK (
        (software_version_id IS NOT NULL AND canonical_name = '')
        OR (software_version_id IS NULL AND canonical_name <> '')
    )
);
CREATE UNIQUE INDEX software_reclassification_targets_pending_unique
    ON operations.software_reclassification_targets (tenant_id, target_key, source)
    WHERE consumed_at IS NULL;
CREATE INDEX software_reclassification_targets_pending
    ON operations.software_reclassification_targets (tenant_id, queued_at)
    WHERE consumed_at IS NULL;

ALTER TABLE operations.software_reclassification_targets OWNER TO operations_migrate;
REVOKE ALL ON operations.software_reclassification_targets
    FROM PUBLIC, operations_app, operations_readonly, metabase_ro;
GRANT SELECT, INSERT, UPDATE ON operations.software_reclassification_targets TO ninja_ingest;
ALTER TABLE operations.software_reclassification_targets ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.software_reclassification_targets FORCE ROW LEVEL SECURITY;
CREATE POLICY software_reclassification_targets_tenant ON operations.software_reclassification_targets
    USING (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint)
    WITH CHECK (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint);
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0249_jobs_restore_published_revisions"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
