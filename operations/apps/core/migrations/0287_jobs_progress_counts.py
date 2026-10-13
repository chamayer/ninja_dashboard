"""Jobs report how far they are: done of total, in a named unit.

Until now a running Job could only record a stage name and a line of text, so
the Jobs pages had no number to show and most Jobs displayed a placeholder
sentence. A run now carries ``progress_done`` / ``progress_total`` /
``progress_unit`` (for example 700 of 3,674 computers), written through a
fenced API like the existing stage API: only the worker holding the run's
claim token can record it. Counts are bounded so a wrong estimate cannot
overflow the bar (done is clamped to total). Recording a count also renews
the heartbeat and lease, as stage progress does, but adds no event row: a
count can change every few seconds.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
ALTER TABLE operations.operator_job_runs
    ADD COLUMN progress_done BIGINT CHECK (progress_done IS NULL OR progress_done >= 0),
    ADD COLUMN progress_total BIGINT CHECK (progress_total IS NULL OR progress_total >= 0),
    ADD COLUMN progress_unit TEXT NOT NULL DEFAULT ''
        CHECK (length(progress_unit) <= 40);

CREATE FUNCTION operations.jobs_record_v1_count(
    p_tenant_id BIGINT, p_run_id UUID, p_claim_token UUID,
    p_done BIGINT, p_total BIGINT, p_unit TEXT
) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_run_id IS NULL OR p_claim_token IS NULL
       OR p_done IS NULL OR p_done < 0
       OR p_total IS NOT NULL AND p_total < 0
       OR p_unit IS NULL OR length(p_unit) > 40
    THEN
        RAISE EXCEPTION 'Jobs progress count is invalid';
    END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    UPDATE operations.operator_job_runs
       SET progress_done = CASE WHEN p_total IS NULL THEN p_done ELSE LEAST(p_done, p_total) END,
           progress_total = p_total,
           progress_unit = p_unit,
           heartbeat_at = now(),
           lease_expires_at = now() + INTERVAL '90 minutes'
     WHERE tenant_id = p_tenant_id AND id = p_run_id
       AND contract_version = 1 AND status = 'running' AND claim_token = p_claim_token;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Jobs progress is unavailable or fenced';
    END IF;
END
$function$;

ALTER FUNCTION operations.jobs_record_v1_count(BIGINT, UUID, UUID, BIGINT, BIGINT, TEXT)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_record_v1_count(BIGINT, UUID, UUID, BIGINT, BIGINT, TEXT)
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.jobs_record_v1_count(BIGINT, UUID, UUID, BIGINT, BIGINT, TEXT)
    TO ninja_ingest;
"""

REVERSE_SQL = r"""
DROP FUNCTION IF EXISTS operations.jobs_record_v1_count(BIGINT, UUID, UUID, BIGINT, BIGINT, TEXT);
ALTER TABLE operations.operator_job_runs
    DROP COLUMN IF EXISTS progress_unit,
    DROP COLUMN IF EXISTS progress_total,
    DROP COLUMN IF EXISTS progress_done;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0286_software_inventory_policy"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
