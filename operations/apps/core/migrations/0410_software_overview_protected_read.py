"""Prepare protected Software reads without enabling certification or cutover."""

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION operations.read_software_overview(p_tenant bigint, p_client uuid DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    summary operations.software_overview_current%ROWTYPE;
    publication operations.operator_job_runs%ROWTYPE;
    latest operations.operator_job_runs%ROWTYPE;
    inputs jsonb;
    metadata jsonb;
    payload jsonb;
    publication_run uuid;
    oldest_completion timestamptz;
BEGIN
    IF p_tenant IS DISTINCT FROM 1 OR p_tenant IS DISTINCT FROM
        nullif(current_setting('operations.tenant_id', true), '')::bigint THEN
        RAISE EXCEPTION 'Software overview read context is invalid';
    END IF;
    -- There is no client-grained publication. Never leak tenant counts/labels
    -- into a client-scoped request, even when the tenant has only one client.
    IF p_client IS NOT NULL THEN
        RETURN jsonb_build_object('state', 'unavailable', 'reason', 'restricted_scope');
    END IF;
    SELECT * INTO summary FROM operations.software_overview_current WHERE tenant_id = p_tenant;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('state', 'unavailable', 'reason', 'missing');
    END IF;
    SELECT min((owner.value->>'handler_completed_at')::timestamptz)
      INTO oldest_completion FROM jsonb_each(summary.input_watermarks->'owners') owner;
    metadata := jsonb_build_object(
        'computed_at', summary.computed_at, 'published_at', summary.published_at,
        'inventory_observed_at', summary.inventory_observed_at,
        'oldest_input_completed_at', oldest_completion);
    IF NOT summary.contract_ready THEN
        RETURN metadata || jsonb_build_object('state', 'unavailable', 'reason', 'uncertified');
    END IF;
    -- Certification is a separate reviewed gate. This read never grants it.
    IF summary.input_watermarks->>'publication_run_id' IS NULL
       OR jsonb_typeof(summary.input_watermarks->'owners') IS DISTINCT FROM 'object'
       OR summary.input_watermarks->'owners' = '{}'::jsonb THEN
        RETURN metadata || jsonb_build_object('state', 'unavailable', 'reason', 'unverifiable');
    END IF;
    publication_run := (summary.input_watermarks->>'publication_run_id')::uuid;
    SELECT * INTO publication FROM operations.operator_job_runs
     WHERE tenant_id = p_tenant AND id = publication_run AND job_key = 'software-overview'
       AND contract_version = 1 AND scope_identity = 'tenant:1';
    IF NOT FOUND THEN
        RETURN metadata || jsonb_build_object('state', 'unavailable', 'reason', 'unverifiable');
    END IF;
    IF publication.status IN ('failed', 'stalled', 'cancelled') THEN
        RETURN metadata || jsonb_build_object('state', 'stale', 'reason', 'publication_failed');
    END IF;
    IF publication.status <> 'completed' THEN
        RETURN metadata || jsonb_build_object('state', 'pending', 'reason', 'publication_pending');
    END IF;
    IF publication.result->>'overview_generation' IS DISTINCT FROM summary.generation::text THEN
        RETURN metadata || jsonb_build_object('state', 'unavailable', 'reason', 'unverifiable');
    END IF;
    SELECT * INTO latest FROM operations.operator_job_runs
     WHERE tenant_id = p_tenant AND job_key = 'software-overview'
     ORDER BY requested_at DESC, id DESC LIMIT 1;
    IF latest.id <> publication_run AND latest.status IN ('failed', 'stalled', 'cancelled') THEN
        RETURN metadata || jsonb_build_object('state', 'stale', 'reason', 'publication_failed');
    END IF;
    IF latest.id <> publication_run AND latest.status = 'completed' THEN
        RETURN metadata || jsonb_build_object('state', 'unavailable', 'reason', 'unverifiable');
    END IF;
    IF EXISTS (
        SELECT 1 FROM operations.operator_job_runs
         WHERE tenant_id = p_tenant AND job_key = 'software-overview'
           AND id <> publication_run AND status IN ('queued', 'running')
    ) THEN
        RETURN metadata || jsonb_build_object('state', 'pending', 'reason', 'input_changed');
    END IF;
    IF summary.exposure_expires_at <= statement_timestamp()
       OR summary.window_expires_at <= statement_timestamp() THEN
        RETURN metadata || jsonb_build_object('state', 'stale', 'reason', 'expired');
    END IF;
    inputs := operations.software_overview_inputs(p_tenant);
    IF EXISTS (
        SELECT 1 FROM jsonb_each(inputs->'owners') owner
          JOIN operations.operator_job_runs r
            ON r.tenant_id = p_tenant AND r.id = (owner.value->>'run_id')::uuid
         WHERE r.status IN ('failed', 'stalled', 'cancelled')
    ) THEN
        RETURN metadata || jsonb_build_object('state', 'stale', 'reason', 'input_failed');
    END IF;
    IF (inputs->>'ownership_pending')::boolean OR inputs->'active' <> '[]'::jsonb
       OR inputs->'owners' IS DISTINCT FROM summary.input_watermarks->'owners' THEN
        RETURN metadata || jsonb_build_object('state', 'pending', 'reason', 'input_changed');
    END IF;
    -- Explicit allowlist: adding a storage/diagnostic column cannot expose it.
    SELECT jsonb_object_agg(key, value) INTO payload FROM jsonb_each(to_jsonb(summary))
     WHERE key = ANY (ARRAY[
        'installations', 'unique_titles', 'categorized_titles', 'uncategorized_titles',
        'approved_titles', 'rejected_titles', 'investigate_titles', 'pending_decisions',
        'risk_high', 'risk_medium', 'risk_low', 'risk_clean', 'risk_unknown',
        'software_issues', 'whitelist_suggestions', 'publishers_undecided',
        'tech_checklist_devices', 'new_products', 'new_high_risk',
        'top_new_name', 'top_new_display_name', 'top_new_devices'
     ]);
    RETURN metadata || jsonb_build_object('state', 'current', 'reason', 'completed', 'data', payload);
END
$fn$;
ALTER FUNCTION operations.read_software_overview(bigint, uuid) OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.read_software_overview(bigint, uuid)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.read_software_overview(bigint, uuid)
    TO operations_app, operations_readonly;
-- The earlier view checks certification alone. Runtime must use the live
-- decision/input/expiry guard above rather than bypass it through that view.
REVOKE ALL ON operations.v_software_overview FROM operations_app, operations_readonly, ninja_ingest;
"""

REVERSE_SQL = """
DROP FUNCTION operations.read_software_overview(bigint, uuid);
GRANT SELECT ON operations.v_software_overview TO operations_app, operations_readonly;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0409_software_overview_publication_fence"),
    ]
    operations: ClassVar = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
