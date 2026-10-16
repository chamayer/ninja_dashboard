"""One timeline per Computer from the change history (ADR-0033, History page).

``operations.computer_history(computers, before, limit)`` returns the recorded
changes of every covered table whose rows belong to any of the given Computers
(the page passes the Computer and every Computer merged into it), newest
first, with the action that made each change. It runs as the caller, so each
history table's row-level security applies; ``before`` pages by time.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION operations.computer_history(
    p_computers uuid[],
    p_before timestamptz DEFAULT NULL,
    p_limit integer DEFAULT 100
) RETURNS TABLE (
    recorded_at timestamptz,
    table_name text,
    entity_key text,
    operation char(1),
    changed_columns text[],
    before_values jsonb,
    after_values jsonb,
    action_id uuid,
    action text,
    actor_kind text,
    actor_id bigint,
    process text,
    reason text
)
LANGUAGE plpgsql STABLE
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_sql text;
BEGIN
    IF p_limit IS NULL OR p_limit < 1 OR p_limit > 500 THEN
        RAISE EXCEPTION 'computer_history: limit must be between 1 and 500';
    END IF;
    SELECT string_agg(format(
        $q$(SELECT h.recorded_at, %L::text AS table_name, h.entity_key, h.operation,
                   h.changed_columns, h.before_values, h.after_values, h.action_id
              FROM operations.%I h
             WHERE h.computer_id = ANY($1) AND ($2 IS NULL OR h.recorded_at < $2)
             ORDER BY h.recorded_at DESC
             LIMIT $3)$q$,
        r.table_name, r.table_name || '_change_history'), ' UNION ALL ')
      INTO v_sql
      FROM operations.change_history_registry r
     WHERE r.classification = 'covered'
       AND to_regclass('operations.' || r.table_name || '_change_history') IS NOT NULL;
    IF v_sql IS NULL THEN
        RETURN;
    END IF;
    RETURN QUERY EXECUTE format(
        $q$SELECT c.recorded_at, c.table_name, c.entity_key, c.operation, c.changed_columns,
                  c.before_values, c.after_values, c.action_id, a.action::text,
                  a.actor_kind::text, a.actor_id, a.process::text, a.reason
             FROM (%s) c
             JOIN operations.change_actions a ON a.id = c.action_id
            ORDER BY c.recorded_at DESC
            LIMIT $3$q$, v_sql)
    USING p_computers, p_before, p_limit;
END
$fn$;

REVOKE ALL ON FUNCTION operations.computer_history(uuid[], timestamptz, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.computer_history(uuid[], timestamptz, integer)
    TO operations_app, operations_readonly;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0313_vm_guest_name_not_authoritative"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
