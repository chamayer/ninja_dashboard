"""Link software queue claims to Jobs and retain every execution attempt."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = """
CREATE TABLE operations.job_domain_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id BIGINT NOT NULL REFERENCES operations.tenants(id) CHECK (tenant_id = 1),
    domain_kind TEXT NOT NULL CHECK (domain_kind IN (
        'software.scheduled', 'software.demand', 'software.activity',
        'source.demand', 'source.action'
    )),
    domain_record_id TEXT NOT NULL CHECK (length(domain_record_id) BETWEEN 1 AND 128),
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    job_run_id UUID NOT NULL,
    linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, domain_kind, domain_record_id, attempt_number),
    UNIQUE (tenant_id, domain_kind, domain_record_id, job_run_id),
    FOREIGN KEY (tenant_id, job_run_id)
        REFERENCES operations.operator_job_runs(tenant_id, id)
);
ALTER TABLE operations.job_domain_attempts OWNER TO operations_migrate;
REVOKE ALL ON operations.job_domain_attempts
FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.job_domain_attempts TO operations_app, ninja_ingest;
GRANT INSERT ON operations.job_domain_attempts TO ninja_ingest;
ALTER TABLE operations.job_domain_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.job_domain_attempts FORCE ROW LEVEL SECURITY;
CREATE POLICY job_domain_attempts_tenant_isolation
ON operations.job_domain_attempts
USING (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint)
WITH CHECK (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint);
CREATE TRIGGER immutable_job_domain_attempts
    BEFORE UPDATE OR DELETE OR TRUNCATE ON operations.job_domain_attempts
    FOR EACH STATEMENT EXECUTE FUNCTION operations.reject_jobs_history_mutation();

ALTER TABLE ninja_core.software_scheduled_queue
    ADD COLUMN tenant_id BIGINT, ADD COLUMN job_run_id UUID;
ALTER TABLE ninja_core.software_demand_queue
    ADD COLUMN tenant_id BIGINT, ADD COLUMN job_run_id UUID;
ALTER TABLE ninja_core.software_activity_queue
    ADD COLUMN tenant_id BIGINT, ADD COLUMN job_run_id UUID;

UPDATE ninja_core.software_scheduled_queue SET tenant_id = 1 WHERE tenant_id IS NULL;
UPDATE ninja_core.software_demand_queue SET tenant_id = 1 WHERE tenant_id IS NULL;
UPDATE ninja_core.software_activity_queue SET tenant_id = 1 WHERE tenant_id IS NULL;

DO $software_links$
DECLARE queue_table TEXT;
BEGIN
    FOREACH queue_table IN ARRAY ARRAY[
        'software_scheduled_queue', 'software_demand_queue', 'software_activity_queue'
    ] LOOP
        EXECUTE format(
            'ALTER TABLE ninja_core.%I ALTER COLUMN tenant_id SET NOT NULL', queue_table
        );
        EXECUTE format(
            'ALTER TABLE ninja_core.%I ADD CONSTRAINT %I '
            'FOREIGN KEY (tenant_id) REFERENCES operations.tenants(id)',
            queue_table, queue_table || '_tenant_reference'
        );
        EXECUTE format(
            'ALTER TABLE ninja_core.%I ADD CONSTRAINT %I CHECK (tenant_id = 1)',
            queue_table, queue_table || '_current_tenant'
        );
        EXECUTE format(
            'ALTER TABLE ninja_core.%I ADD CONSTRAINT %I '
            'FOREIGN KEY (tenant_id, job_run_id) '
            'REFERENCES operations.operator_job_runs(tenant_id, id) NOT VALID',
            queue_table, queue_table || '_job_run_reference'
        );
        EXECUTE format(
            'ALTER TABLE ninja_core.%I VALIDATE CONSTRAINT %I',
            queue_table, queue_table || '_job_run_reference'
        );
        EXECUTE format(
            'CREATE INDEX %I ON ninja_core.%I(job_run_id) WHERE job_run_id IS NOT NULL',
            queue_table || '_job_run', queue_table
        );
        EXECUTE format('ALTER TABLE ninja_core.%I ENABLE ROW LEVEL SECURITY', queue_table);
        EXECUTE format('ALTER TABLE ninja_core.%I FORCE ROW LEVEL SECURITY', queue_table);
        EXECUTE format(
            'CREATE POLICY software_queue_tenant_isolation ON ninja_core.%I '
            'USING (tenant_id = NULLIF(current_setting('
            '''operations.tenant_id'', TRUE), '''')::bigint) '
            'WITH CHECK (tenant_id = NULLIF(current_setting('
            '''operations.tenant_id'', TRUE), '''')::bigint)',
            queue_table
        );
    END LOOP;
END
$software_links$;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0218_jobs_domain_queue_tenant_links"),
    ]
    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
