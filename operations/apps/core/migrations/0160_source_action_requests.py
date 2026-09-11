"""Generic, auditable requests for mutations in an external source."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
CREATE TABLE operations.source_action_requests (
    id                     BIGSERIAL PRIMARY KEY,
    tenant_id              BIGINT NOT NULL REFERENCES operations.tenants(id),
    finding_id             UUID NOT NULL REFERENCES operations.findings(id),
    source_instance_id     UUID NOT NULL REFERENCES operations.source_instances(id),
    action_key             TEXT NOT NULL,
    parent_external_id     TEXT NOT NULL DEFAULT '',
    external_id            TEXT NOT NULL,
    requested_by_id        INTEGER REFERENCES operations.users(id),
    reason                 TEXT NOT NULL DEFAULT '',
    status                 TEXT NOT NULL DEFAULT 'pending'
                           CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'cancelled')),
    attempts               SMALLINT NOT NULL DEFAULT 0,
    queued_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at             TIMESTAMPTZ,
    lease_expires_at       TIMESTAMPTZ,
    completed_at           TIMESTAMPTZ,
    outcome                JSONB NOT NULL DEFAULT '{}'::jsonb,
    error                  TEXT NOT NULL DEFAULT ''
);

CREATE UNIQUE INDEX uq_source_action_requests_pending_target
    ON operations.source_action_requests (
        tenant_id, action_key, source_instance_id, parent_external_id, external_id
    ) WHERE status IN ('pending', 'processing');
CREATE INDEX idx_source_action_requests_pending
    ON operations.source_action_requests (status, queued_at)
    WHERE status = 'pending';

ALTER TABLE operations.source_action_requests OWNER TO operations_migrate;
REVOKE ALL ON operations.source_action_requests
FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT, INSERT ON operations.source_action_requests TO operations_app;
GRANT SELECT, UPDATE ON operations.source_action_requests TO ninja_ingest;
GRANT USAGE, SELECT ON SEQUENCE operations.source_action_requests_id_seq
TO operations_app, ninja_ingest;

UPDATE operations.finding_types
   SET description = 'A current Hudu record has linked external source records, but none currently resolve. Review or archive the Hudu record.'
 WHERE name = 'cmdb_asset_stale';
"""

REVERSE_SQL = """
DROP TABLE IF EXISTS operations.source_action_requests;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0159_manage_lifecycle_permission"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
