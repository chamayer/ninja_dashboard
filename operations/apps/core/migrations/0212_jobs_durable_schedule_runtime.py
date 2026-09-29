"""Activate durable Jobs schedules through restricted ingest APIs."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = """
CREATE FUNCTION operations.jobs_reconcile_schedule_v2(
    p_tenant_id BIGINT,
    p_definition_key TEXT,
    p_definition_digest TEXT,
    p_scope_identity TEXT,
    p_configuration_revision TEXT,
    p_cadence JSONB,
    p_enabled BOOLEAN,
    p_capability_reason TEXT
) RETURNS UUID
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT; DECLARE v_id UUID; DECLARE v_next_due TIMESTAMPTZ;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_scope_identity IS NULL OR length(p_scope_identity) NOT BETWEEN 1 AND 256
       OR p_configuration_revision !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_cadence) <> 'object' OR p_capability_reason IS NULL
       OR (
            (p_cadence->>'kind' = 'interval' AND COALESCE((p_cadence->>'minutes')::integer, 0) BETWEEN 1 AND 10080)
            OR (p_cadence->>'kind' = 'daily' AND COALESCE((p_cadence->>'hour')::integer, -1) BETWEEN 0 AND 23)
          ) IS NOT TRUE
    THEN RAISE EXCEPTION 'Jobs schedule reconciliation is invalid'; END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    IF NOT EXISTS (SELECT 1 FROM operations.job_definition_versions
                   WHERE definition_key = p_definition_key AND definition_digest = p_definition_digest)
    THEN RAISE EXCEPTION 'Jobs definition snapshot is not registered'; END IF;
    v_next_due := CASE p_cadence->>'kind'
        WHEN 'interval' THEN now() + make_interval(mins => (p_cadence->>'minutes')::integer)
        ELSE CASE WHEN date_trunc('day', now()) + make_interval(hours => (p_cadence->>'hour')::integer) > now()
             THEN date_trunc('day', now()) + make_interval(hours => (p_cadence->>'hour')::integer)
             ELSE date_trunc('day', now()) + INTERVAL '1 day' + make_interval(hours => (p_cadence->>'hour')::integer) END
        END;
    INSERT INTO operations.job_schedules (
        tenant_id, definition_key, definition_digest, scope_identity, enabled,
        capability_reason, cadence, anchor_at, time_zone, next_due_at, configuration_revision
    ) VALUES (
        p_tenant_id, p_definition_key, p_definition_digest, p_scope_identity, p_enabled,
        p_capability_reason, p_cadence, now(), 'UTC', CASE WHEN p_enabled THEN v_next_due ELSE NULL END,
        p_configuration_revision
    ) ON CONFLICT (tenant_id, definition_key, scope_identity) DO UPDATE
       SET definition_digest = EXCLUDED.definition_digest, enabled = EXCLUDED.enabled,
           capability_reason = EXCLUDED.capability_reason, cadence = EXCLUDED.cadence,
           configuration_revision = EXCLUDED.configuration_revision,
           anchor_at = CASE WHEN operations.job_schedules.enabled IS DISTINCT FROM EXCLUDED.enabled
                              OR operations.job_schedules.configuration_revision IS DISTINCT FROM EXCLUDED.configuration_revision
                         THEN now() ELSE operations.job_schedules.anchor_at END,
           next_due_at = CASE WHEN NOT EXCLUDED.enabled THEN NULL
                              WHEN operations.job_schedules.enabled IS DISTINCT FROM EXCLUDED.enabled
                                OR operations.job_schedules.configuration_revision IS DISTINCT FROM EXCLUDED.configuration_revision
                              THEN v_next_due ELSE operations.job_schedules.next_due_at END
     RETURNING id INTO v_id;
    RETURN v_id;
END
$function$;

CREATE FUNCTION operations.jobs_list_due_schedules_v1(p_tenant_id BIGINT)
RETURNS TABLE (schedule_id UUID, due_at TIMESTAMPTZ, cadence JSONB)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1 THEN
        RAISE EXCEPTION 'Jobs schedule tenant context is invalid';
    END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    RETURN QUERY SELECT schedule.id, schedule.next_due_at, schedule.cadence
      FROM operations.job_schedules AS schedule
     WHERE schedule.tenant_id = p_tenant_id AND schedule.enabled
       AND schedule.next_due_at <= now()
     ORDER BY schedule.next_due_at, schedule.id;
END
$function$;

ALTER FUNCTION operations.jobs_reconcile_schedule_v2(BIGINT, TEXT, TEXT, TEXT, TEXT, JSONB, BOOLEAN, TEXT)
    OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_list_due_schedules_v1(BIGINT) OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_reconcile_schedule_v2(BIGINT, TEXT, TEXT, TEXT, TEXT, JSONB, BOOLEAN, TEXT),
    operations.jobs_list_due_schedules_v1(BIGINT)
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.jobs_reconcile_schedule_v2(BIGINT, TEXT, TEXT, TEXT, TEXT, JSONB, BOOLEAN, TEXT),
    operations.jobs_list_due_schedules_v1(BIGINT)
    TO ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0211_fix_jobs_claim_v3_ambiguity"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
