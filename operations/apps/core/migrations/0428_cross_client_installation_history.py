"""Preserve installation finding subjects across cross-client repairs."""

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
CREATE TABLE operations.retired_installation_subjects (
    tenant_id bigint NOT NULL,
    installation_uuid uuid NOT NULL,
    client_id uuid NOT NULL,
    device_id uuid NOT NULL,
    canonical_name text NOT NULL,
    display_name text NOT NULL,
    version text,
    action_id uuid NOT NULL REFERENCES operations.change_actions(id),
    retired_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, installation_uuid)
);

ALTER TABLE operations.retired_installation_subjects OWNER TO operations_migrate;
ALTER TABLE operations.retired_installation_subjects ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.retired_installation_subjects FORCE ROW LEVEL SECURITY;
CREATE POLICY retired_installation_tenant ON operations.retired_installation_subjects
    USING (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint)
    WITH CHECK (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint);
REVOKE ALL ON operations.retired_installation_subjects
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;

INSERT INTO operations.change_history_registry
    (table_name, classification, reason, recorded_columns, secret_columns, key_columns,
     computer_column, computer_condition_column, computer_condition_value, client_column,
     is_global, capture)
VALUES
    ('retired_installation_subjects', 'history_store',
     'Original installation finding subject and scope at a repair action',
     '{}', '{}', ARRAY['tenant_id', 'installation_uuid'], 'device_id', NULL, NULL,
     'client_id', false, NULL);

CREATE FUNCTION operations.archive_repair_installation_subjects(
    p_tenant bigint, p_first uuid, p_second uuid, p_action uuid
) RETURNS text[]
LANGUAGE plpgsql
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_at timestamptz;
    v_titles text[];
BEGIN
    -- Keep legacy finding labels in their recorded scope. Source inventory
    -- and the underlying legacy inventory rows remain owned by their writers.
    IF p_tenant IS NULL
       OR p_tenant IS DISTINCT FROM nullif(current_setting('operations.tenant_id', true), '')::bigint
       OR p_first IS NULL OR p_second IS NULL OR p_first = p_second
       OR p_action IS NULL
       OR p_action IS DISTINCT FROM nullif(current_setting('operations.change_action_id', true), '')::uuid THEN
        RAISE EXCEPTION 'Invalid cross-client installation history context';
    END IF;
    PERFORM operations.assert_tenant_guard(p_tenant, 'exclusive');

    SELECT occurred_at INTO v_at
      FROM operations.change_actions
     WHERE tenant_id = p_tenant AND id = p_action
       AND action IN ('computer.merge.cross_client', 'computer.split.cross_client')
       AND explicit
       AND evidence ->> 'survivor_id' = p_first::text
       AND evidence ->> 'absorbed_id' = p_second::text;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Installation history requires a matching repair action';
    END IF;

    WITH legacy_subjects AS (
        SELECT tenant_id, installation_uuid, client_id, device_id, canonical_name,
               display_name, version
          FROM operations.software_installations_current
         WHERE tenant_id = p_tenant AND device_id IN (p_first, p_second)
    ), archived AS (
        INSERT INTO operations.retired_installation_subjects
            (tenant_id, installation_uuid, client_id, device_id, canonical_name,
             display_name, version, action_id, retired_at)
        SELECT tenant_id, installation_uuid, client_id, device_id, canonical_name,
               display_name, version, p_action, v_at
          FROM legacy_subjects
        ON CONFLICT (tenant_id, installation_uuid) DO NOTHING
    )
    SELECT coalesce(array_agg(DISTINCT canonical_name ORDER BY canonical_name), '{}')
      INTO v_titles FROM legacy_subjects;
    RETURN v_titles;
END
$fn$;
ALTER FUNCTION operations.archive_repair_installation_subjects(bigint, uuid, uuid, uuid)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.archive_repair_installation_subjects(bigint, uuid, uuid, uuid)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;

CREATE FUNCTION operations.retired_installation_finding_context(p_tenant bigint, p_finding uuid)
RETURNS TABLE (display_name text, canonical_name text, version text, retired_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
    SELECT retired.display_name, retired.canonical_name, retired.version, retired.retired_at
      FROM operations.findings f
      JOIN operations.retired_installation_subjects retired
        ON retired.tenant_id = f.tenant_id AND retired.installation_uuid = f.subject_id
       AND (f.client_id IS NULL OR retired.client_id = f.client_id)
     WHERE p_tenant = nullif(current_setting('operations.tenant_id', true), '')::bigint
       AND f.tenant_id = p_tenant AND f.id = p_finding
       AND f.subject_type = 'software_installation'
$fn$;
ALTER FUNCTION operations.retired_installation_finding_context(bigint, uuid) OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.retired_installation_finding_context(bigint, uuid)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.retired_installation_finding_context(bigint, uuid)
    TO operations_app;
"""

REVERSE_SQL = """
LOCK TABLE operations.retired_installation_subjects IN ACCESS EXCLUSIVE MODE;
ALTER TABLE operations.retired_installation_subjects NO FORCE ROW LEVEL SECURITY;
SET LOCAL row_security = off;
DO $fn$
BEGIN
    -- As table owner, check every tenant before allowing rollback.
    IF EXISTS (
        SELECT 1 FROM operations.retired_installation_subjects
    ) THEN
        RAISE EXCEPTION 'The installation retirement archive contains finding history';
    END IF;
END
$fn$;
DROP FUNCTION operations.retired_installation_finding_context(bigint, uuid);
DROP FUNCTION operations.archive_repair_installation_subjects(bigint, uuid, uuid, uuid);
DROP TABLE operations.retired_installation_subjects;
DELETE FROM operations.change_history_registry WHERE table_name = 'retired_installation_subjects';
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0427_identity_identifier_rule"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
