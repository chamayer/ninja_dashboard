"""Cut over from ``audit_log`` to the change history (ADR-0033, workstream 8).

``audit_log`` is replaced: its rows stay (they are shown on the History tab and
the lifecycle page) and the table becomes read-only.

* ``operations.label_change(action, item, actor_kind, actor_id, process,
  tenant)`` names the transaction's change action: an implicit action (the
  one the change-history trigger opened for this transaction's writes)
  becomes explicit with the action, actor and the item as evidence; an
  explicit one keeps its name and gains the item; with none, a new explicit
  action starts. Items are kept in ``evidence -> 'items'``.
* A trigger on ``audit_log`` turns every insert into ``label_change`` (the
  before / after state, source, address and user agent are the item) and
  stores no row; updates and deletes are refused. This covers every writer at
  once: the Operations views, the database functions that audited attribute
  and relationship decisions and evidence reveals, and an ingest process
  still running old code during a deploy.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
SELECT operations.begin_change(
    'audit_log.cutover',
    'ADR-0033: audit_log is replaced by the change history; it becomes read-only.',
    '{"migration": "0319_audit_log_cutover"}'::jsonb,
    'migration', NULL, 'operations.migrations', '0319', NULL, true);

CREATE FUNCTION operations.label_change(
    p_action text,
    p_item jsonb,
    p_actor_kind text DEFAULT 'process',
    p_actor_id bigint DEFAULT NULL,
    p_process text DEFAULT '',
    p_tenant_id bigint DEFAULT NULL
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_action uuid := nullif(current_setting('operations.change_action_id', true), '')::uuid;
    v_explicit boolean;
BEGIN
    IF p_action IS NULL OR p_action = '' THEN
        RAISE EXCEPTION 'label_change: an action name is required';
    END IF;
    SELECT explicit INTO v_explicit FROM operations.change_actions WHERE id = v_action;
    IF v_action IS NULL OR v_explicit IS NULL THEN
        RETURN operations.begin_change(
            p_action, '', jsonb_build_object('items', jsonb_build_array(p_item)),
            p_actor_kind, p_actor_id, coalesce(p_process, ''), '', p_tenant_id, true);
    END IF;
    UPDATE operations.change_actions
       SET action = CASE WHEN explicit THEN action ELSE left(p_action, 120) END,
           actor_kind = CASE WHEN explicit THEN actor_kind ELSE p_actor_kind END,
           actor_id = CASE WHEN explicit THEN actor_id ELSE p_actor_id END,
           process = CASE WHEN explicit OR coalesce(p_process, '') = '' THEN process
                          ELSE left(p_process, 160) END,
           evidence = evidence || jsonb_build_object(
               'items', coalesce(evidence -> 'items', '[]'::jsonb) || jsonb_build_array(p_item)),
           explicit = true
     WHERE id = v_action;
    RETURN v_action;
END
$fn$;
REVOKE ALL ON FUNCTION operations.label_change(text, jsonb, text, bigint, text, bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.label_change(text, jsonb, text, bigint, text, bigint)
    TO operations_app, ninja_ingest;

CREATE FUNCTION operations.audit_log_into_change_history() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'audit_log is read-only since migration 0319 (ADR-0033)';
    END IF;
    PERFORM operations.label_change(
        NEW.action,
        jsonb_strip_nulls(jsonb_build_object(
            'action', NEW.action,
            'entity_type', NEW.entity_type,
            'entity_id', NEW.entity_id,
            'before', NEW.before_state,
            'after', NEW.after_state,
            'source', NEW.source,
            'ip_address', host(NEW.ip_address),
            'user_agent', nullif(NEW.user_agent, ''),
            'occurred_at', coalesce(NEW.occurred_at, now()))),
        CASE WHEN NEW.actor_kind = 'user' THEN 'operator' ELSE 'process' END,
        NEW.actor_id,
        'audit_log:' || coalesce(NEW.source, ''),
        NEW.tenant_id);
    RETURN NULL;
END
$fn$;
CREATE TRIGGER audit_log_into_change_history
    BEFORE INSERT OR UPDATE OR DELETE ON operations.audit_log
    FOR EACH ROW EXECUTE FUNCTION operations.audit_log_into_change_history();

UPDATE operations.change_history_registry
   SET classification = 'history_store',
       reason = 'replaced by the change history in migration 0319; read-only, kept for its rows'
 WHERE table_name = 'audit_log';
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0318_roaming_agent_records"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
