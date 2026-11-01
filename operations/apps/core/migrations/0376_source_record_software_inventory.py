"""Add source-record keyed software inventory alongside the Computer projection.

This additive store lets later ingest/evaluation work retain a Ninja record's
software before identity resolution. Existing Computer keyed inventory remains
authoritative for current readers until the coordinated projection is implemented.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

SQL = r"""
CREATE TABLE operations.source_record_software_current (
    tenant_id bigint NOT NULL,
    source_record_id uuid NOT NULL,
    canonical_name text NOT NULL,
    display_name text NOT NULL,
    publisher text,
    version text,
    install_location text,
    install_date date,
    product_code text,
    size_bytes bigint,
    is_system_component boolean,
    material_hash bytea NOT NULL,
    hash_algorithm_version integer NOT NULL DEFAULT 1,
    first_observed_at timestamptz NOT NULL,
    last_observed_at timestamptz NOT NULL,
    refreshed_at timestamptz NOT NULL,
    stale_since timestamptz,
    stale_reason text NOT NULL DEFAULT '',
    PRIMARY KEY (tenant_id, source_record_id, canonical_name),
    FOREIGN KEY (tenant_id, source_record_id)
        REFERENCES operations.source_record_subjects (tenant_id, id) ON DELETE CASCADE,
    CHECK ((stale_since IS NULL) = (stale_reason = ''))
);
CREATE INDEX source_record_software_current_title
    ON operations.source_record_software_current (tenant_id, canonical_name)
    WHERE stale_since IS NULL;

CREATE TABLE operations.source_record_software_history (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id bigint NOT NULL,
    source_record_id uuid NOT NULL,
    canonical_name text NOT NULL,
    display_name text NOT NULL,
    publisher text,
    version text,
    install_location text,
    install_date date,
    product_code text,
    size_bytes bigint,
    is_system_component boolean,
    material_hash bytea NOT NULL,
    hash_algorithm_version integer NOT NULL DEFAULT 1,
    effective_from timestamptz NOT NULL,
    effective_to timestamptz,
    last_seen_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL,
    active boolean NOT NULL DEFAULT TRUE,
    FOREIGN KEY (tenant_id, source_record_id)
        REFERENCES operations.source_record_subjects (tenant_id, id) ON DELETE CASCADE,
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);
CREATE UNIQUE INDEX source_record_software_history_open
    ON operations.source_record_software_history
       (tenant_id, source_record_id, canonical_name)
    WHERE effective_to IS NULL;
CREATE INDEX source_record_software_history_lookup
    ON operations.source_record_software_history
       (tenant_id, source_record_id, canonical_name, effective_from DESC);

ALTER TABLE operations.source_record_software_current ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.source_record_software_current FORCE ROW LEVEL SECURITY;
CREATE POLICY source_record_software_current_tenant
    ON operations.source_record_software_current
    USING (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint)
    WITH CHECK (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint);
ALTER TABLE operations.source_record_software_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.source_record_software_history FORCE ROW LEVEL SECURITY;
CREATE POLICY source_record_software_history_tenant
    ON operations.source_record_software_history
    USING (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint)
    WITH CHECK (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint);
REVOKE ALL ON operations.source_record_software_current,
    operations.source_record_software_history FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.source_record_software_current,
    operations.source_record_software_history
    FROM operations_app, ninja_ingest, operations_readonly;
GRANT INSERT, UPDATE, DELETE ON operations.source_record_software_current,
    operations.source_record_software_history TO ninja_ingest;
GRANT SELECT ON operations.source_record_software_current,
    operations.source_record_software_history
    TO operations_app, operations_readonly, ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0375_native_finding_conditions"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(SQL, migrations.RunSQL.noop)]
