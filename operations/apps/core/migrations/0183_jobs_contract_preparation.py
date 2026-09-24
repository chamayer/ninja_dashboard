"""Prepare inert M1/M2 Jobs contract storage without activating converted work."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
DO $preflight$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM operations.operator_job_runs AS job
        JOIN operations.users AS requester ON requester.id = job.requested_by_id
        WHERE job.tenant_id <> requester.tenant_id
    ) THEN
        RAISE EXCEPTION 'Existing Job requester tenant mismatch; review required';
    END IF;
END
$preflight$;

CREATE TABLE operations.job_definition_versions (
    definition_key TEXT NOT NULL CHECK (length(definition_key) BETWEEN 1 AND 120),
    definition_digest TEXT NOT NULL CHECK (definition_digest ~ '^[0-9a-f]{64}$'),
    handler_version TEXT NOT NULL CHECK (length(handler_version) BETWEEN 1 AND 120),
    metadata JSONB NOT NULL CHECK (
        jsonb_typeof(metadata) = 'object'
        AND octet_length(metadata::text) <= 65536
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (definition_key, definition_digest)
);
ALTER TABLE operations.job_definition_versions OWNER TO operations_migrate;
REVOKE ALL ON operations.job_definition_versions
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;

CREATE FUNCTION operations.reject_jobs_history_mutation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $function$
BEGIN
    RAISE EXCEPTION 'Jobs history is append-only';
END
$function$;
ALTER FUNCTION operations.reject_jobs_history_mutation() OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.reject_jobs_history_mutation()
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;

CREATE TRIGGER immutable_job_definitions
    BEFORE UPDATE OR DELETE OR TRUNCATE ON operations.job_definition_versions
    FOR EACH STATEMENT EXECUTE FUNCTION operations.reject_jobs_history_mutation();

ALTER TABLE operations.operator_job_runs
    ADD COLUMN contract_version SMALLINT NOT NULL DEFAULT 0,
    ADD COLUMN definition_digest TEXT,
    ADD COLUMN trigger_kind TEXT,
    ADD COLUMN scope_identity TEXT,
    ADD COLUMN request_payload JSONB,
    ADD COLUMN coalescing_key TEXT,
    ADD COLUMN correlation_id UUID,
    ADD COLUMN parent_run_id UUID,
    ADD COLUMN root_run_id UUID,
    ADD COLUMN retry_of_run_id UUID,
    ADD COLUMN wait_category TEXT,
    ADD COLUMN wait_reason TEXT,
    ADD COLUMN input_revisions JSONB,
    ADD COLUMN output_revisions JSONB,
    ADD COLUMN result JSONB,
    ADD COLUMN terminal_reason TEXT,
    ADD COLUMN cancellation_requested_by_id INTEGER,
    ADD COLUMN cancellation_requested_at TIMESTAMPTZ,
    ADD COLUMN cancellation_reason TEXT,
    ADD COLUMN deadline_at TIMESTAMPTZ,
    ADD COLUMN worker_incarnation UUID,
    ADD COLUMN claim_token UUID,
    ADD COLUMN claim_generation BIGINT,
    ADD COLUMN child_start_identity JSONB,
    ADD CONSTRAINT jobs_contract_preparation_only CHECK (contract_version = 0),
    ADD CONSTRAINT jobs_tenant_id_unique UNIQUE (tenant_id, id),
    ADD CONSTRAINT jobs_identity_reference_unique
        UNIQUE (tenant_id, id, job_key, definition_digest, scope_identity),
    ADD CONSTRAINT jobs_definition_reference
        FOREIGN KEY (job_key, definition_digest)
        REFERENCES operations.job_definition_versions (definition_key, definition_digest),
    ADD CONSTRAINT jobs_parent_reference
        FOREIGN KEY (tenant_id, parent_run_id)
        REFERENCES operations.operator_job_runs (tenant_id, id),
    ADD CONSTRAINT jobs_root_reference
        FOREIGN KEY (tenant_id, root_run_id)
        REFERENCES operations.operator_job_runs (tenant_id, id),
    ADD CONSTRAINT jobs_retry_reference
        FOREIGN KEY (tenant_id, retry_of_run_id)
        REFERENCES operations.operator_job_runs (tenant_id, id);

ALTER TABLE operations.users
    ADD CONSTRAINT jobs_user_tenant_reference_unique UNIQUE (tenant_id, id);
ALTER TABLE operations.operator_job_runs
    ADD CONSTRAINT jobs_requester_tenant_reference
        FOREIGN KEY (tenant_id, requested_by_id)
        REFERENCES operations.users (tenant_id, id) NOT VALID,
    ADD CONSTRAINT jobs_canceller_tenant_reference
        FOREIGN KEY (tenant_id, cancellation_requested_by_id)
        REFERENCES operations.users (tenant_id, id);
ALTER TABLE operations.operator_job_runs
    VALIDATE CONSTRAINT jobs_requester_tenant_reference;

CREATE TABLE operations.job_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id BIGINT NOT NULL REFERENCES operations.tenants(id) CHECK (tenant_id = 1),
    definition_key TEXT NOT NULL,
    definition_digest TEXT NOT NULL,
    scope_identity TEXT NOT NULL CHECK (length(scope_identity) BETWEEN 1 AND 256),
    request_identity TEXT NOT NULL CHECK (request_identity ~ '^[0-9a-f]{64}$'),
    run_id UUID NOT NULL,
    actor_id INTEGER,
    trigger_kind TEXT NOT NULL
        CHECK (trigger_kind IN ('automatic', 'operator', 'dependency', 'recovery')),
    requested_input_revisions JSONB NOT NULL
        CHECK (jsonb_typeof(requested_input_revisions) = 'object'
               AND octet_length(requested_input_revisions::text) <= 65536),
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_kind <> 'operator' OR actor_id IS NOT NULL),
    UNIQUE (tenant_id, id),
    UNIQUE (tenant_id, id, definition_key, definition_digest, scope_identity),
    UNIQUE (tenant_id, definition_key, definition_digest, scope_identity, request_identity),
    FOREIGN KEY (definition_key, definition_digest)
        REFERENCES operations.job_definition_versions (definition_key, definition_digest),
    FOREIGN KEY (tenant_id, run_id, definition_key, definition_digest, scope_identity)
        REFERENCES operations.operator_job_runs
            (tenant_id, id, job_key, definition_digest, scope_identity),
    FOREIGN KEY (tenant_id, actor_id) REFERENCES operations.users (tenant_id, id)
);
CREATE INDEX jobs_requests_run ON operations.job_requests (tenant_id, run_id, requested_at);

CREATE TABLE operations.job_schedules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id BIGINT NOT NULL REFERENCES operations.tenants(id) CHECK (tenant_id = 1),
    definition_key TEXT NOT NULL,
    definition_digest TEXT NOT NULL,
    scope_identity TEXT NOT NULL CHECK (length(scope_identity) BETWEEN 1 AND 256),
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    capability_reason TEXT NOT NULL,
    cadence JSONB NOT NULL CHECK (
        jsonb_typeof(cadence) = 'object' AND octet_length(cadence::text) <= 4096
    ),
    anchor_at TIMESTAMPTZ NOT NULL,
    time_zone TEXT NOT NULL CHECK (length(time_zone) BETWEEN 1 AND 120),
    next_due_at TIMESTAMPTZ,
    last_consumed_due_at TIMESTAMPTZ,
    last_requested_at TIMESTAMPTZ,
    last_request_id UUID,
    last_run_id UUID,
    last_outcome TEXT,
    configuration_revision TEXT NOT NULL
        CHECK (configuration_revision ~ '^[0-9a-f]{64}$'),
    CONSTRAINT jobs_schedule_preparation_only CHECK (NOT enabled),
    UNIQUE (tenant_id, id),
    UNIQUE (tenant_id, definition_key, scope_identity),
    FOREIGN KEY (definition_key, definition_digest)
        REFERENCES operations.job_definition_versions (definition_key, definition_digest),
    FOREIGN KEY (tenant_id, last_request_id) REFERENCES operations.job_requests (tenant_id, id),
    FOREIGN KEY (tenant_id, last_run_id) REFERENCES operations.operator_job_runs (tenant_id, id)
);
CREATE INDEX jobs_schedules_due ON operations.job_schedules (tenant_id, next_due_at, id)
    WHERE enabled;

CREATE TABLE operations.job_schedule_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id BIGINT NOT NULL REFERENCES operations.tenants(id) CHECK (tenant_id = 1),
    schedule_id UUID NOT NULL,
    definition_key TEXT NOT NULL,
    definition_digest TEXT NOT NULL,
    configuration_revision TEXT NOT NULL
        CHECK (configuration_revision ~ '^[0-9a-f]{64}$'),
    due_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    outcome TEXT NOT NULL
        CHECK (outcome IN ('requested', 'coalesced', 'skipped', 'deferred')),
    consumed_ticks BIGINT NOT NULL CHECK (consumed_ticks >= 0),
    reason TEXT NOT NULL,
    request_id UUID,
    run_id UUID,
    UNIQUE (tenant_id, schedule_id, configuration_revision, due_at),
    CHECK (
        outcome NOT IN ('requested', 'coalesced')
        OR (request_id IS NOT NULL AND run_id IS NOT NULL)
    ),
    FOREIGN KEY (tenant_id, schedule_id) REFERENCES operations.job_schedules (tenant_id, id),
    FOREIGN KEY (definition_key, definition_digest)
        REFERENCES operations.job_definition_versions (definition_key, definition_digest),
    FOREIGN KEY (tenant_id, request_id) REFERENCES operations.job_requests (tenant_id, id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES operations.operator_job_runs (tenant_id, id)
);

DO $security$
DECLARE jobs_table TEXT;
BEGIN
    FOREACH jobs_table IN ARRAY ARRAY[
        'job_requests', 'job_schedules', 'job_schedule_events'
    ] LOOP
        EXECUTE format('ALTER TABLE operations.%I OWNER TO operations_migrate', jobs_table);
        EXECUTE format(
            'REVOKE ALL ON operations.%I FROM PUBLIC, operations_app, ninja_ingest, '
            'operations_readonly, metabase_ro',
            jobs_table
        );
        EXECUTE format('ALTER TABLE operations.%I ENABLE ROW LEVEL SECURITY', jobs_table);
        EXECUTE format('ALTER TABLE operations.%I FORCE ROW LEVEL SECURITY', jobs_table);
        EXECUTE format(
            'CREATE POLICY jobs_tenant_isolation ON operations.%I '
            'USING (tenant_id = NULLIF(current_setting('
            '''operations.tenant_id'', TRUE), '''')::bigint) '
            'WITH CHECK (tenant_id = NULLIF(current_setting('
            '''operations.tenant_id'', TRUE), '''')::bigint)',
            jobs_table
        );
    END LOOP;
END
$security$;

CREATE TRIGGER immutable_job_requests
    BEFORE UPDATE OR DELETE OR TRUNCATE ON operations.job_requests
    FOR EACH STATEMENT EXECUTE FUNCTION operations.reject_jobs_history_mutation();
CREATE TRIGGER immutable_job_schedule_events
    BEFORE UPDATE OR DELETE OR TRUNCATE ON operations.job_schedule_events
    FOR EACH STATEMENT EXECUTE FUNCTION operations.reject_jobs_history_mutation();
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0182_software_job_lane_and_operations_controls"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
