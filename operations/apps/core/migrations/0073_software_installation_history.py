"""Dedicated SCD-2 history for software installation inventory."""

# ruff: noqa: I001, RUF012

from django.db import migrations


SQL = """
ALTER TABLE operations.software_installations_current
    ADD COLUMN IF NOT EXISTS material_hash bytea,
    ADD COLUMN IF NOT EXISTS hash_algorithm_version integer NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS operations.software_installation_history (
    id uuid PRIMARY KEY,
    tenant_id bigint NOT NULL REFERENCES operations.tenants(id),
    source_binding_id uuid NOT NULL REFERENCES operations.source_bindings(id),
    client_id uuid NOT NULL REFERENCES operations.clients(id),
    device_id uuid NOT NULL REFERENCES operations.devices(id),
    canonical_name text NOT NULL,
    publisher text,
    version text,
    install_location text,
    install_date date,
    material_hash bytea NOT NULL,
    hash_algorithm_version integer NOT NULL DEFAULT 1,
    effective_from timestamptz NOT NULL,
    effective_to timestamptz,
    last_seen_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL,
    active boolean NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_sw_install_history_effective
    ON operations.software_installation_history (tenant_id, effective_from);
CREATE INDEX IF NOT EXISTS idx_sw_install_history_retention
    ON operations.software_installation_history (tenant_id, effective_to);
CREATE INDEX IF NOT EXISTS idx_sw_install_history_device
    ON operations.software_installation_history
       (tenant_id, device_id, canonical_name, effective_from DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_sw_install_history_open_identity
    ON operations.software_installation_history
       (tenant_id, source_binding_id, device_id, canonical_name)
    WHERE effective_to IS NULL;

ALTER TABLE operations.software_installation_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.software_installation_history FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON operations.software_installation_history;
CREATE POLICY tenant_isolation ON operations.software_installation_history
    USING (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint)
    WITH CHECK (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE
    ON operations.software_installation_history TO operations_app;
GRANT SELECT ON operations.software_installation_history TO operations_readonly;
GRANT SELECT, INSERT, UPDATE
    ON operations.software_installation_history TO ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies = [("operations", "0072_alter_coveragerequirement_options_and_more")]
    operations = [migrations.RunSQL(SQL, migrations.RunSQL.noop)]
