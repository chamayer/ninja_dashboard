"""Relationship rules become the cover authority (PLAN-003 M3, part 2).

Part of the coordinated M2-M4 artifact.

* The closed action registry gets the system effects and the registered UI
  actions (``ui.<FINDING_ACTIONS key>``).
* Each ``finding_types.covered_by`` entry becomes an enabled ``covers`` rule
  (same Computer, parent active) whose actions are queue selection and both
  notification effects. ``compute_finding_state`` and ``refresh_finding_state``
  read the cover chain from these rules instead of ``covered_by``; behavior is
  otherwise unchanged and cover stays live.
* ``covered_by`` remains the editing surface of the Finding types page: a
  trigger rewrites that type's rules whenever it changes. Rules it no longer
  lists are disabled, not deleted, so their history stays. Runtime roles cannot
  edit rules directly, so the rules and ``covered_by`` cannot diverge.
* ``finding_relationships`` stays empty until the unified queue reads it (R3);
  cover is still decided live in finding state.
"""

from __future__ import annotations

import importlib
from typing import ClassVar

from django.db import migrations

_writer = importlib.import_module("apps.core.migrations.0365_findings_writer_contract")
_state = importlib.import_module("apps.core.migrations.0301_finding_state")

UI_ACTIONS = (
    "retire_computers",
    "merge_computers",
    "confirm_computers_separate",
    "split_computer_records",
    "confirm_computers_in_use",
    "move_computer_client",
    "keep_computer_client",
    "computer_client_source_wrong",
    "approve_remote_access_all",
    "approve_remote_access_client",
    "software_approve_title",
    "software_approve_publisher",
    "software_reject",
    "software_reject_publisher",
    "software_investigate",
    "software_investigate_publisher",
    "capability_confirm",
    "capability_reject",
    "archive_hudu_assets",
)

_OLD_CHAIN = """            SELECT ft.name, p.v
              FROM operations.finding_types ft
             CROSS JOIN LATERAL jsonb_array_elements_text(ft.covered_by) p(v)
            UNION
            SELECT chain.child, p2.v
              FROM chain
              JOIN operations.finding_types ft2 ON ft2.name = chain.ancestor
             CROSS JOIN LATERAL jsonb_array_elements_text(ft2.covered_by) p2(v)"""

_NEW_CHAIN = """            SELECT ct.name, pt.name
              FROM operations.finding_relationship_rules r
              JOIN operations.finding_types ct ON ct.id = r.child_type_id
              JOIN operations.finding_types pt ON pt.id = r.parent_type_id
             WHERE r.enabled AND r.kind = 'covers'
            UNION
            SELECT chain.child, pt2.name
              FROM chain
              JOIN operations.finding_types ft2 ON ft2.name = chain.ancestor
              JOIN operations.finding_relationship_rules r2
                ON r2.child_type_id = ft2.id AND r2.enabled AND r2.kind = 'covers'
              JOIN operations.finding_types pt2 ON pt2.id = r2.parent_type_id"""

_OLD_DEPENDENTS = """                  JOIN operations.finding_types ft ON ft.covered_by ? c.type_name
                UNION
                SELECT ct.subject_type, ct.subject_id, ct.tenant_id, ft.name
                  FROM covered_types ct
                  JOIN operations.finding_types ft ON ft.covered_by ? ct.name"""

_NEW_DEPENDENTS = """                  JOIN operations.finding_types pt ON pt.name = c.type_name
                  JOIN operations.finding_relationship_rules r
                    ON r.parent_type_id = pt.id AND r.enabled AND r.kind = 'covers'
                  JOIN operations.finding_types ft ON ft.id = r.child_type_id
                UNION
                SELECT ct.subject_type, ct.subject_id, ct.tenant_id, ft.name
                  FROM covered_types ct
                  JOIN operations.finding_types pt ON pt.name = ct.name
                  JOIN operations.finding_relationship_rules r
                    ON r.parent_type_id = pt.id AND r.enabled AND r.kind = 'covers'
                  JOIN operations.finding_types ft ON ft.id = r.child_type_id"""


def _replace_once(sql: str, old: str, new: str) -> str:
    assert sql.count(old) == 1, old[:60]
    return sql.replace(old, new)


def _compute_sql(new: bool) -> str:
    body = _writer._compute_sql()
    return _replace_once(body, _OLD_CHAIN, _NEW_CHAIN) if new else body


def _refresh_sql(new: bool) -> str:
    body = _writer._function(_state.FORWARD_SQL, "refresh_finding_state")
    return _replace_once(body, _OLD_DEPENDENTS, _NEW_DEPENDENTS) if new else body


_UI_ROWS = ",\n    ".join(
    f"('ui.{key}', 'ui_action', 'Registered Finding action {key}')" for key in UI_ACTIONS
)

FORWARD_SQL = (
    rf"""
SELECT operations.begin_change(
    'plan003.m3_cover_rules',
    'Relationship rules seeded from finding_types.covered_by; cover reads the rules',
    '{{}}'::jsonb, 'migration', NULL, 'operations.migrations', '0366', NULL, true);

INSERT INTO operations.finding_action_registry (action_key, kind, description) VALUES
    ('condition.execute', 'system_effect', 'Condition-driven execution (may_execute)'),
    ('notification.dispatch', 'system_effect', 'Notification delivery'),
    ('notification.digest', 'system_effect', 'Review digest delivery'),
    ('source.archive_hudu_asset', 'system_effect', 'Queued Hudu asset archive'),
    ('finding.queue.select', 'system_effect', 'Independent Issues queue selection'),
    {_UI_ROWS}
ON CONFLICT (action_key) DO NOTHING;

-- Rewrites the covers rules derived from one type's covered_by list.
CREATE FUNCTION operations.sync_cover_rules(p_child smallint) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
BEGIN
    UPDATE operations.finding_relationship_rules r
       SET enabled = false, version = r.version + 1
     WHERE r.child_type_id = p_child AND r.kind = 'covers'
       AND r.provenance = 'finding_types.covered_by' AND r.enabled
       AND NOT EXISTS (
           SELECT 1 FROM operations.finding_types c
           CROSS JOIN LATERAL jsonb_array_elements_text(c.covered_by) p(v)
           JOIN operations.finding_types pt ON pt.name = p.v
            WHERE c.id = p_child AND pt.id = r.parent_type_id);
    INSERT INTO operations.finding_relationship_rules AS r
        (parent_type_id, child_type_id, kind, scope_matcher, parent_satisfaction, enabled,
         provenance)
    SELECT pt.id, c.id, 'covers', 'same_computer', 'parent_active', true,
           'finding_types.covered_by'
      FROM operations.finding_types c
     CROSS JOIN LATERAL jsonb_array_elements_text(c.covered_by) p(v)
      JOIN operations.finding_types pt ON pt.name = p.v
     WHERE c.id = p_child
    ON CONFLICT (parent_type_id, child_type_id, kind, scope_matcher) DO UPDATE
       SET enabled = true, version = r.version + 1
     WHERE NOT r.enabled;
    INSERT INTO operations.finding_relationship_rule_actions (rule_id, action_key)
    SELECT r.id, a.k
      FROM operations.finding_relationship_rules r
     CROSS JOIN (VALUES ('finding.queue.select'), ('notification.dispatch'),
                        ('notification.digest')) a(k)
     WHERE r.child_type_id = p_child AND r.provenance = 'finding_types.covered_by'
    ON CONFLICT DO NOTHING;
END
$fn$;
REVOKE ALL ON FUNCTION operations.sync_cover_rules(smallint) FROM PUBLIC;

CREATE FUNCTION operations.finding_types_sync_cover_rules() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
BEGIN
    PERFORM operations.sync_cover_rules(NEW.id);
    RETURN NULL;
END
$fn$;
REVOKE ALL ON FUNCTION operations.finding_types_sync_cover_rules() FROM PUBLIC;

SELECT operations.sync_cover_rules(t.id)
  FROM operations.finding_types t WHERE jsonb_array_length(t.covered_by) > 0;

CREATE TRIGGER sync_cover_rules
    AFTER INSERT OR UPDATE OF covered_by ON operations.finding_types
    FOR EACH ROW EXECUTE FUNCTION operations.finding_types_sync_cover_rules();
"""
    + _compute_sql(new=True)
    + "ALTER FUNCTION operations.compute_finding_state(uuid[]) SET jit = off;\n"
    + _refresh_sql(new=True)
)

REVERSE_SQL = (
    r"""
DROP TRIGGER IF EXISTS sync_cover_rules ON operations.finding_types;
DROP FUNCTION IF EXISTS operations.finding_types_sync_cover_rules();
DROP FUNCTION IF EXISTS operations.sync_cover_rules(smallint);
DELETE FROM operations.finding_relationship_rule_actions;
DELETE FROM operations.finding_relationship_rules;
DELETE FROM operations.finding_action_registry;
"""
    + _compute_sql(new=False)
    + "ALTER FUNCTION operations.compute_finding_state(uuid[]) SET jit = off;\n"
    + _refresh_sql(new=False)
)


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0365_findings_writer_contract"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
