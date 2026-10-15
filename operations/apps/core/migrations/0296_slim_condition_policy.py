"""Slim the condition policy to behavior, and add the generic ``parent_open`` rule.

The policy was carrying things that are not behavior: finding labels, categories,
the Issues taxonomy, URL aliases, and an offline threshold nobody reads any more.
Changing any of them meant a new immutable policy version, which makes every
existing assessment non-current. They live on ``finding_types`` now (migration
0295, the Finding types page) and in the Device status settings.

This migration:

* teaches ``create_condition_policy_version`` to accept a schema 2 document (rules,
  which rules apply to which type, freshness) as well as schema 1. For schema 2 the
  per-type label, category and group stored in ``condition_policies`` are copied from
  the registry at install time, and ``offline_days`` may be empty.
* creates and activates ``conditions-registry-1``, built from the active policy:
  schema 2, no presentation, no ``offline_days``, plus the ``parent_open`` rule
  (suppress attention) attached to every type. Which types are actually covered, and
  by what, is ``finding_types.covered_by``; the rule is generic, so changing a cover
  never needs a policy version.

Activation marks assessments of earlier versions as not current until each evaluator
runs again.
"""

from __future__ import annotations

import hashlib
import json
from typing import ClassVar

from django.db import migrations

POLICY_VERSION = "conditions-registry-1"

PARENT_OPEN_RULE = {
    "effect": "suppress_attention",
    "requires": [],
    "explanation": (
        "Another open finding on the same computer already explains this one. The "
        "finding is covered, not cleared, and returns when that finding clears."
    ),
}

FUNCTION_SQL = """
ALTER TABLE operations.condition_policies ALTER COLUMN offline_days DROP NOT NULL;

CREATE OR REPLACE FUNCTION operations.create_condition_policy_version(
    p_version TEXT, p_digest TEXT, p_policy JSONB
) RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations AS $$
DECLARE
    item JSONB;
    doc_schema TEXT;
BEGIN
    IF p_version IS NULL OR p_version = '' OR p_digest IS NULL
       OR p_digest !~ '^[0-9a-f]{64}$'
       OR p_policy IS NULL OR jsonb_typeof(p_policy) <> 'object' THEN
        RAISE EXCEPTION 'Invalid condition policy document or digest';
    END IF;
    doc_schema := p_policy->>'schema_version';
    IF doc_schema IS NULL OR doc_schema NOT IN ('1', '2')
       OR p_policy->>'version' IS DISTINCT FROM p_version
       OR jsonb_typeof(p_policy->'definitions') IS DISTINCT FROM 'array'
       OR jsonb_typeof(p_policy->'rules') IS DISTINCT FROM 'object'
       OR ((p_policy->>'freshness_hours') ~ '^[1-9][0-9]*$') IS NOT TRUE
       OR (doc_schema = '1' AND ((p_policy->>'offline_days') ~ '^[1-9][0-9]*$') IS NOT TRUE)
       OR (doc_schema = '2' AND p_policy ? 'offline_days') THEN
        RAISE EXCEPTION 'Invalid condition policy contract';
    END IF;
    IF jsonb_array_length(p_policy->'definitions')
       <> (SELECT count(*) FROM operations.finding_types)
       OR (SELECT count(*) FROM jsonb_array_elements(p_policy->'definitions'))
          <> (SELECT count(DISTINCT value->>'name')
              FROM jsonb_array_elements(p_policy->'definitions')) THEN
        RAISE EXCEPTION 'Condition policy must contain each registered finding type exactly once';
    END IF;
    INSERT INTO operations.condition_policy_versions(version, digest, policy, active)
    VALUES (p_version, p_digest, p_policy, FALSE);
    FOR item IN SELECT value FROM jsonb_array_elements(p_policy->'definitions') LOOP
        IF item->>'name' IS NULL
           OR (doc_schema = '1' AND (item->>'category' IS NULL
                                 OR item->>'type' IS NULL OR item->>'label' IS NULL))
           OR item->>'lifecycle' NOT IN ('active', 'historical', 'unverified', 'disabled')
           OR NOT EXISTS (
               SELECT 1 FROM operations.finding_types WHERE name = item->>'name'
           ) THEN
            RAISE EXCEPTION 'Invalid or unregistered condition definition: %', item->>'name';
        END IF;
        INSERT INTO operations.condition_policies
            (policy_version, finding_type_id, type_name, category, grouped_type,
             label, definition, offline_days, freshness_hours)
        SELECT p_version, ft.id, item->>'name',
               COALESCE(item->>'category', ft.issue_category),
               COALESCE(item->>'type', ft.issue_group),
               COALESCE(item->>'label', ft.display_name),
               item, (p_policy->>'offline_days')::INTEGER,
               (p_policy->>'freshness_hours')::INTEGER
          FROM operations.finding_types ft
         WHERE ft.name = item->>'name';
    END LOOP;
    PERFORM operations.activate_condition_policy_version(p_version);
END
$$;
ALTER FUNCTION operations.create_condition_policy_version(TEXT, TEXT, JSONB)
    OWNER TO operations_migrate;
"""


def build_policy(active: dict) -> dict:
    """The active policy as schema 2: behavior only, plus the ``parent_open`` rule."""
    policy = json.loads(json.dumps(active))
    policy["schema_version"] = 2
    policy["version"] = POLICY_VERSION
    for key in ("offline_days", "issue_taxonomy", "issue_categories", "issue_type_aliases"):
        policy.pop(key, None)
    policy.setdefault("rules", {})["parent_open"] = json.loads(json.dumps(PARENT_OPEN_RULE))
    for definition in policy["definitions"]:
        for key in ("label", "category", "type"):
            definition.pop(key, None)
        if "parent_open" not in definition["rules"]:
            definition["rules"] = [*definition["rules"], "parent_open"]
    return policy


def digest(policy: dict) -> str:
    # The same digest the loaders verify when they parse the active policy.
    return hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()


def install(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM operations.condition_policy_versions WHERE version = %s",
            (POLICY_VERSION,),
        )
        if cursor.fetchone() is not None:
            return
        cursor.execute(
            "SELECT policy FROM operations.condition_policy_versions WHERE active "
            "ORDER BY version DESC LIMIT 1"
        )
        active = cursor.fetchone()
        if active is None:
            return  # a fresh database has no policy to slim
        current = json.loads(active[0]) if isinstance(active[0], str) else active[0]
        policy = build_policy(current)
        cursor.execute(
            "SELECT operations.create_condition_policy_version(%s, %s, %s::jsonb)",
            (POLICY_VERSION, digest(policy), json.dumps(policy, separators=(",", ":"))),
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0295_finding_types_registry"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FUNCTION_SQL, migrations.RunSQL.noop),
        migrations.RunPython(install, migrations.RunPython.noop),
    ]
