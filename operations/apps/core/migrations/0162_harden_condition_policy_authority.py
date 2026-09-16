"""Harden the database boundary for governed condition policies."""

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
        -- PostgreSQL core has no SHA-256 text digest function and this
        -- project deliberately does not install pgcrypto. The application
        -- boundary verifies the exact SHA-256 before invoking this function;
        -- the database still enforces its format and structural contract.
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
END
$$;

CREATE OR REPLACE FUNCTION operations.activate_condition_policy_version(p_version TEXT)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('operations.condition_policy_activation'));
    IF NOT EXISTS (
        SELECT 1 FROM operations.condition_policy_versions
        WHERE version = p_version
    ) OR NOT EXISTS (
        SELECT 1 FROM operations.condition_policies
        WHERE policy_version = p_version
    ) THEN
        RAISE EXCEPTION 'Unknown or invalid condition policy version: %', p_version;
    END IF;
    UPDATE operations.condition_policy_versions SET active = FALSE WHERE active;
    UPDATE operations.condition_policy_versions SET active = TRUE WHERE version = p_version;
END
$$;
"""


REVERSE_SQL = """
CREATE OR REPLACE FUNCTION operations.activate_condition_policy_version(p_version TEXT)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM operations.condition_policy_versions
                   WHERE version = p_version) THEN
        RAISE EXCEPTION 'Unknown condition policy version: %', p_version;
    END IF;
    UPDATE operations.condition_policy_versions SET active = FALSE WHERE active;
    UPDATE operations.condition_policy_versions SET active = TRUE WHERE version = p_version;
END
$$;

CREATE OR REPLACE FUNCTION operations.create_condition_policy_version(
    p_version TEXT, p_digest TEXT, p_policy JSONB
) RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE item JSONB;
BEGIN
    IF p_version IS NULL OR p_version = '' OR p_digest IS NULL OR p_policy IS NULL
       OR jsonb_typeof(p_policy) <> 'object' THEN
        RAISE EXCEPTION 'Invalid condition policy document';
    END IF;
    IF jsonb_array_length(COALESCE(p_policy->'definitions', '[]'::jsonb))
       <> (SELECT count(*) FROM operations.finding_types) THEN
        RAISE EXCEPTION 'Condition policy must contain every registered finding type';
    END IF;
    INSERT INTO operations.condition_policy_versions(version, digest, policy, active)
    VALUES (p_version, p_digest, p_policy, FALSE);
    FOR item IN SELECT value FROM jsonb_array_elements(p_policy->'definitions') LOOP
        INSERT INTO operations.condition_policies
            (policy_version, finding_type_id, type_name, category, grouped_type,
             label, definition, offline_days, freshness_hours)
        SELECT p_version, ft.id, item->>'name', item->>'category', item->>'type',
               item->>'label', item, (p_policy->>'offline_days')::INTEGER,
               (p_policy->>'freshness_hours')::INTEGER
          FROM operations.finding_types ft WHERE ft.name = item->>'name';
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Condition type is not registered: %', item->>'name';
        END IF;
    END LOOP;
END
$$;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [("operations", "0161_live_condition_contract")]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
