"""Activate validated policy versions as part of their committed migration."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
CREATE OR REPLACE FUNCTION operations.create_condition_policy_version(
    p_version TEXT, p_digest TEXT, p_policy JSONB
) RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations AS $$
DECLARE item JSONB;
BEGIN
    IF p_version IS NULL OR p_version = '' OR p_digest IS NULL
       OR p_digest !~ '^[0-9a-f]{64}$'
       OR p_policy IS NULL OR jsonb_typeof(p_policy) <> 'object' THEN
        RAISE EXCEPTION 'Invalid condition policy document or digest';
    END IF;
    IF p_policy->>'schema_version' IS DISTINCT FROM '1'
       OR p_policy->>'version' IS DISTINCT FROM p_version
       OR jsonb_typeof(p_policy->'definitions') IS DISTINCT FROM 'array'
       OR jsonb_typeof(p_policy->'rules') IS DISTINCT FROM 'object'
       OR ((p_policy->>'offline_days') ~ '^[1-9][0-9]*$') IS NOT TRUE
       OR ((p_policy->>'freshness_hours') ~ '^[1-9][0-9]*$') IS NOT TRUE THEN
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
        IF item->>'name' IS NULL OR item->>'category' IS NULL
           OR item->>'type' IS NULL OR item->>'label' IS NULL
           OR item->>'lifecycle' NOT IN ('active', 'historical', 'unverified', 'disabled')
           OR NOT EXISTS (
               SELECT 1 FROM operations.finding_types WHERE name = item->>'name'
           ) THEN
            RAISE EXCEPTION 'Invalid or unregistered condition definition: %', item->>'name';
        END IF;
        INSERT INTO operations.condition_policies
            (policy_version, finding_type_id, type_name, category, grouped_type,
             label, definition, offline_days, freshness_hours)
        SELECT p_version, ft.id, item->>'name', item->>'category', item->>'type',
               item->>'label', item, (p_policy->>'offline_days')::INTEGER,
               (p_policy->>'freshness_hours')::INTEGER
          FROM operations.finding_types ft
         WHERE ft.name = item->>'name';
    END LOOP;
    PERFORM operations.activate_condition_policy_version(p_version);
END
$$;
ALTER FUNCTION operations.create_condition_policy_version(TEXT, TEXT, JSONB)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.create_condition_policy_version(TEXT, TEXT, JSONB) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.create_condition_policy_version(TEXT, TEXT, JSONB)
    TO operations_app;

SELECT operations.activate_condition_policy_version('conditions-taxonomy-7');
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0203_simplify_condition_policy_activation"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
