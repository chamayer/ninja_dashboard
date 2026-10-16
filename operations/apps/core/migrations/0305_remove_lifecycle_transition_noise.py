"""Remove lifecycle transitions that were written by mistake.

Until the evaluator fix shipped with this migration, every evaluator run
applied two lifecycle steps that disagreed for a Computer whose source record
was still listed but had not made contact for a long time:
``_sync_source_withdrawal_lifecycle`` set it to ``active`` and
``_sync_lifecycle_status`` moved it straight back. Each run wrote both moves to
``audit_log``: two opposite ``lifecycle.transition`` rows with the same
evaluator run, describing a change that never took effect (the Computer's state
never left its original value outside the transaction). Measured 2026-10-16:
485,220 such rows (242,610 run pairs) against 4,419 real transitions.

Where the two steps disagreed and the run did change the state (for example
offline aging, then a momentary active, then needs review), the run wrote the
real change as two rows through a false ``active``. Those 286 run pairs keep one
row: the false step to ``active`` is removed and the remaining row's
``before_state`` becomes the state the run started from.

The removal is recorded in one ``audit_log.cleanup`` row per tenant with the
counts and the reason. It is not reversible: the removed rows describe nothing
that happened.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
DO $cleanup$
DECLARE
    v_tenant bigint;
    v_pairs bigint;
    v_merged bigint;
BEGIN
    FOR v_tenant IN SELECT id FROM operations.tenants ORDER BY id LOOP
        PERFORM set_config('operations.tenant_id', v_tenant::text, TRUE);

        -- Two opposite transitions of one Computer in one evaluator run:
        -- the run started and ended in the same state.
        WITH run_pairs AS (
            SELECT entity_id, after_state->>'evaluator_run_id' AS run_id
              FROM operations.audit_log
             WHERE tenant_id = v_tenant
               AND action = 'lifecycle.transition'
               AND after_state ? 'evaluator_run_id'
             GROUP BY entity_id, after_state->>'evaluator_run_id'
            HAVING count(*) = 2
               AND min(before_state->>'lifecycle_status') = min(after_state->>'lifecycle_status')
               AND max(before_state->>'lifecycle_status') = max(after_state->>'lifecycle_status')
        )
        DELETE FROM operations.audit_log a
         USING run_pairs p
         WHERE a.tenant_id = v_tenant
           AND a.action = 'lifecycle.transition'
           AND a.entity_id = p.entity_id
           AND a.after_state->>'evaluator_run_id' = p.run_id;
        GET DIAGNOSTICS v_pairs = ROW_COUNT;

        -- A real change written through a false active: keep one row that
        -- starts from the state the run started from.
        WITH run_steps AS (
            SELECT entity_id, after_state->>'evaluator_run_id' AS run_id
              FROM operations.audit_log
             WHERE tenant_id = v_tenant
               AND action = 'lifecycle.transition'
               AND after_state ? 'evaluator_run_id'
             GROUP BY entity_id, after_state->>'evaluator_run_id'
            HAVING count(*) = 2
               AND count(*) FILTER (
                   WHERE after_state->>'lifecycle_status' = 'active'
                     AND after_state->>'evidence_kind' = 'source_evidence_restored') = 1
               AND count(*) FILTER (
                   WHERE before_state->>'lifecycle_status' = 'active'
                     AND after_state->>'evidence_kind' IS DISTINCT FROM 'source_evidence_restored') = 1
        ), false_step AS (
            SELECT a.audit_id, a.entity_id, s.run_id, a.before_state
              FROM operations.audit_log a
              JOIN run_steps s
                ON s.entity_id = a.entity_id
               AND s.run_id = a.after_state->>'evaluator_run_id'
             WHERE a.tenant_id = v_tenant
               AND a.action = 'lifecycle.transition'
               AND a.after_state->>'lifecycle_status' = 'active'
               AND a.after_state->>'evidence_kind' = 'source_evidence_restored'
        ), kept AS (
            UPDATE operations.audit_log r
               SET before_state = f.before_state,
                   after_state = r.after_state
                       || jsonb_build_object('intermediate_transition_removed', '0305')
              FROM false_step f
             WHERE r.tenant_id = v_tenant
               AND r.action = 'lifecycle.transition'
               AND r.entity_id = f.entity_id
               AND r.after_state->>'evaluator_run_id' = f.run_id
               AND r.audit_id <> f.audit_id
            RETURNING r.audit_id
        )
        -- ``kept`` runs to completion whether or not it is read (PostgreSQL
        -- executes every data-modifying WITH clause exactly once).
        DELETE FROM operations.audit_log a
         USING false_step f
         WHERE a.audit_id = f.audit_id;
        GET DIAGNOSTICS v_merged = ROW_COUNT;

        IF v_pairs > 0 OR v_merged > 0 THEN
            INSERT INTO operations.audit_log (
                audit_id, tenant_id, actor_id, actor_kind, source, action,
                entity_type, entity_id, before_state, after_state,
                ip_address, user_agent, occurred_at
            ) VALUES (
                gen_random_uuid(), v_tenant, NULL, 'system', 'migration',
                'audit_log.cleanup', 'audit_log', NULL, NULL,
                jsonb_build_object(
                    'migration', '0305_remove_lifecycle_transition_noise',
                    'removed_rows', v_pairs,
                    'merged_transitions', v_merged,
                    'reason',
                    'Lifecycle transitions written in opposite pairs within one evaluator '
                    || 'run (two lifecycle steps disagreeing), never a real state change; '
                    || 'and false intermediate active steps inside real changes.'
                ),
                NULL, '', now()
            );
        END IF;
    END LOOP;
END
$cleanup$;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0304_finding_cover_is_live"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
