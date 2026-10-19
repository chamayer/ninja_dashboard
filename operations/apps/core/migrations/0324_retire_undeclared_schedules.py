"""The Jobs catalog decides which tenant schedules are retired.

Measured 2026-10-19: Jobs health reported "Required Job is disabled" for
schedules that were replaced long ago (0263, 0265, 0266) and only switched
off. ``jobs_disable_retired_tenant_schedules_v1`` (0274), which the scheduler
calls on every poll, disabled undeclared schedules that were still enabled
but never marked them retired, so superseded schedules accumulated.

It now retires every tenant schedule the catalog no longer declares
(disabled, no next due time, ``last_outcome = 'retired'``) and changes a row
only when that state differs, so the every-minute call writes nothing once
the catalog and the table agree. An already retired schedule keeps its
reason; a newly retired one says why.

The schedules replaced by source refreshes are repaired here with their
established replacement reasons. ``source-actions`` is not among them: it is
declared and idles until a source action is pending (capability
``pending_work`` in the registry).
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION operations.jobs_disable_retired_tenant_schedules_v1(
    p_tenant_id BIGINT,
    p_declared_keys TEXT[]
) RETURNS INTEGER
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT; DECLARE v_count INTEGER;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_declared_keys IS NULL
       OR EXISTS (
            SELECT 1 FROM unnest(p_declared_keys) AS key
             WHERE key IS NULL OR key !~ '^[a-z0-9][a-z0-9-]{1,119}$'
       )
    THEN RAISE EXCEPTION 'Jobs schedule retirement is invalid'; END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    UPDATE operations.job_schedules AS schedule
       SET enabled = FALSE,
           next_due_at = NULL,
           capability_reason = CASE
               WHEN schedule.last_outcome = 'retired' THEN schedule.capability_reason
               ELSE 'Retired — no longer declared in the Jobs catalog.'
           END,
           last_outcome = 'retired'
     WHERE schedule.tenant_id = p_tenant_id
       AND schedule.scope_identity = 'tenant:1'
       AND NOT (schedule.definition_key = ANY(p_declared_keys))
       -- Only rows whose retirement state differs: this runs every poll.
       AND (schedule.enabled
            OR schedule.next_due_at IS NOT NULL
            OR schedule.last_outcome IS DISTINCT FROM 'retired');
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END
$function$;

-- Replaced by per-binding source refreshes (0263, 0265) and binding-scoped
-- refreshes (0266); verified 2026-10-19: every replacement binding ran in the
-- last 24 hours. Their replacement reasons stay.
UPDATE operations.job_schedules
   SET enabled = FALSE, next_due_at = NULL, last_outcome = 'retired'
 WHERE tenant_id = 1
   AND scope_identity = 'tenant:1'
   AND definition_key IN (
       'patches', 'agent-observations', 'documentation-observations',
       'source-demand', 'source-demand-recovery',
       'intel-nvd', 'intel-cpe-dict', 'intel-kev', 'intel-epss', 'intel-winget',
       'intel-chocolatey', 'intel-lolrmm', 'intel-otx', 'intel-abusech', 'intel-endoflife'
   )
   AND (enabled OR next_due_at IS NOT NULL OR last_outcome IS DISTINCT FROM 'retired');
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0323_maintenance_cadence_and_retired_schedules"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
