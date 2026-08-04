from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
GRANT USAGE, CREATE ON SCHEMA operations TO operations_view_owner;

CREATE OR REPLACE VIEW operations.v_entity_observation_admin_metadata
WITH (security_barrier = true) AS
SELECT observation.observation_id, observation.tenant_id,
       observation.source_binding_id, observation.source_instance_id,
       observation.client_id, observation.device_id,
       observation.entity_type, observation.entity_key,
       observation.external_namespace, observation.parent_external_namespace,
       observation.parent_external_id, observation.external_id,
       observation.platform, observation.subplatform,
       observation.observed_at, observation.last_seen_at,
       observation.last_received_at, observation.active,
       observation.withdrawn_at,
       observation.canonical_data->>'hostname' AS canonical_hostname,
       observation.canonical_data->>'platform_group_id' AS platform_group_id
  FROM operations.entity_observation_current observation
 WHERE observation.tenant_id = operations.current_tenant_id();

ALTER VIEW operations.v_entity_observation_admin_metadata
    OWNER TO operations_view_owner;
REVOKE CREATE ON SCHEMA operations FROM operations_view_owner;

REVOKE ALL ON operations.v_entity_observation_admin_metadata
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.v_entity_observation_admin_metadata
    TO operations_app, operations_readonly;

CREATE OR REPLACE FUNCTION operations.can_reveal_restricted_evidence(
    p_tenant_id integer,
    p_actor_id bigint
) RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, operations
SET row_security = on
AS $function$
    SELECT EXISTS (
        SELECT 1
          FROM operations.users app_user
         WHERE app_user.id = p_actor_id
           AND app_user.tenant_id = p_tenant_id
           AND app_user.is_active
           AND (
               app_user.is_superuser
               OR EXISTS (
                   SELECT 1
                     FROM operations.user_permissions user_permission
                     JOIN operations.auth_permission permission
                       ON permission.id = user_permission.permission_id
                     JOIN operations.django_content_type content_type
                       ON content_type.id = permission.content_type_id
                    WHERE user_permission.tenant_id = p_tenant_id
                      AND user_permission.user_id = p_actor_id
                      AND content_type.app_label = 'operations'
                      AND permission.codename = 'view_restricted_evidence'
               )
               OR EXISTS (
                   SELECT 1
                     FROM operations.user_groups user_group
                     JOIN operations.auth_group_permissions group_permission
                       ON group_permission.group_id = user_group.group_id
                     JOIN operations.auth_permission permission
                       ON permission.id = group_permission.permission_id
                     JOIN operations.django_content_type content_type
                       ON content_type.id = permission.content_type_id
                    WHERE user_group.tenant_id = p_tenant_id
                      AND user_group.user_id = p_actor_id
                      AND content_type.app_label = 'operations'
                      AND permission.codename = 'view_restricted_evidence'
               )
           )
    );
$function$;

CREATE OR REPLACE FUNCTION operations.reveal_entity_observation(
    p_tenant_id integer,
    p_actor_id bigint,
    p_entity_id uuid,
    p_observation_id uuid,
    p_ip_address inet,
    p_user_agent text
) RETURNS TABLE (
    source_name text,
    entity_type varchar,
    external_namespace varchar,
    external_id text,
    observed_at timestamptz,
    raw_data jsonb,
    canonical_data jsonb
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, operations
SET row_security = on
AS $function$
BEGIN
    IF p_tenant_id <> operations.current_tenant_id() THEN
        RAISE EXCEPTION 'Tenant context mismatch' USING ERRCODE = '42501';
    END IF;
    IF NOT operations.can_reveal_restricted_evidence(p_tenant_id, p_actor_id) THEN
        RAISE EXCEPTION 'Restricted evidence permission required' USING ERRCODE = '42501';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM operations.entity_observation_current observation
         WHERE observation.tenant_id = p_tenant_id
           AND observation.observation_id = p_observation_id
           AND EXISTS (
               SELECT 1
                 FROM operations.entity_source_links link
                WHERE link.tenant_id = observation.tenant_id
                  AND link.entity_id = p_entity_id
                  AND link.source_instance_id = observation.source_instance_id
                  AND link.external_namespace = observation.external_namespace
                  AND link.parent_external_namespace = observation.parent_external_namespace
                  AND link.parent_external_id = observation.parent_external_id
                  AND link.external_id = observation.external_id
           )
    ) THEN
        RAISE EXCEPTION 'Observation evidence not found' USING ERRCODE = 'P0002';
    END IF;

    INSERT INTO operations.audit_log (
        audit_id, tenant_id, actor_id, actor_kind, source, action,
        entity_type, entity_id, before_state, after_state,
        ip_address, user_agent, occurred_at
    ) VALUES (
        gen_random_uuid(), p_tenant_id, p_actor_id, 'user', 'ui',
        'restricted_evidence.revealed', 'entity_observation', p_observation_id,
        NULL,
        jsonb_build_object(
            'canonical_entity_id', p_entity_id,
            'record_kind', 'observation',
            'record_id', p_observation_id
        ),
        p_ip_address, left(COALESCE(p_user_agent, ''), 2000), clock_timestamp()
    );

    RETURN QUERY
    SELECT source.name::text, observation.entity_type,
           observation.external_namespace, observation.external_id,
           observation.observed_at, observation.raw_data,
           observation.canonical_data
      FROM operations.entity_observation_current observation
      JOIN operations.source_instances source_instance
        ON source_instance.tenant_id = observation.tenant_id
       AND source_instance.id = observation.source_instance_id
      JOIN operations.sources source ON source.id = source_instance.source_id
     WHERE observation.tenant_id = p_tenant_id
       AND observation.observation_id = p_observation_id;
END;
$function$;

CREATE OR REPLACE FUNCTION operations.reveal_entity_attribute_value(
    p_tenant_id integer,
    p_actor_id bigint,
    p_entity_id uuid,
    p_record_kind text,
    p_record_id uuid,
    p_ip_address inet,
    p_user_agent text
) RETURNS TABLE (
    attribute_key varchar,
    attribute_display_name varchar,
    sensitivity varchar,
    source_name text,
    value jsonb
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, operations
SET row_security = on
AS $function$
BEGIN
    IF p_tenant_id <> operations.current_tenant_id() THEN
        RAISE EXCEPTION 'Tenant context mismatch' USING ERRCODE = '42501';
    END IF;
    IF NOT operations.can_reveal_restricted_evidence(p_tenant_id, p_actor_id) THEN
        RAISE EXCEPTION 'Restricted evidence permission required' USING ERRCODE = '42501';
    END IF;
    IF p_record_kind NOT IN ('effective', 'claim') THEN
        RAISE EXCEPTION 'Unsupported attribute evidence kind' USING ERRCODE = '22023';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM operations.entity_attribute_effective_current effective
         WHERE p_record_kind = 'effective'
           AND effective.tenant_id = p_tenant_id
           AND effective.entity_id = p_entity_id
           AND effective.id = p_record_id
        UNION ALL
        SELECT 1 FROM operations.entity_attribute_claim_current claim
         WHERE p_record_kind = 'claim'
           AND claim.tenant_id = p_tenant_id
           AND claim.entity_id = p_entity_id
           AND claim.id = p_record_id
           AND claim.active
    ) THEN
        RAISE EXCEPTION 'Attribute evidence not found' USING ERRCODE = 'P0002';
    END IF;

    INSERT INTO operations.audit_log (
        audit_id, tenant_id, actor_id, actor_kind, source, action,
        entity_type, entity_id, before_state, after_state,
        ip_address, user_agent, occurred_at
    ) VALUES (
        gen_random_uuid(), p_tenant_id, p_actor_id, 'user', 'ui',
        'restricted_evidence.revealed', 'entity_attribute_' || p_record_kind,
        p_record_id, NULL,
        jsonb_build_object(
            'canonical_entity_id', p_entity_id,
            'record_kind', p_record_kind,
            'record_id', p_record_id
        ),
        p_ip_address, left(COALESCE(p_user_agent, ''), 2000), clock_timestamp()
    );

    IF p_record_kind = 'effective' THEN
        RETURN QUERY
        SELECT definition.key, definition.display_name, definition.sensitivity,
               NULL::text,
               CASE
                 WHEN effective.cardinality = 'set' THEN (
                     SELECT COALESCE(jsonb_agg(
                         CASE member.value_type
                           WHEN 'text' THEN to_jsonb(member.value_text)
                           WHEN 'number' THEN to_jsonb(member.value_number)
                           WHEN 'boolean' THEN to_jsonb(member.value_boolean)
                           WHEN 'timestamp' THEN to_jsonb(member.value_timestamp)
                           WHEN 'entity_reference' THEN to_jsonb(member.value_entity_id)
                           WHEN 'structured' THEN member.value_json
                           ELSE 'null'::jsonb
                         END ORDER BY encode(member.member_key, 'hex')
                     ), '[]'::jsonb)
                       FROM operations.entity_attribute_effective_member_current member
                      WHERE member.tenant_id = effective.tenant_id
                        AND member.effective_id = effective.id
                 )
                 ELSE CASE effective.value_type
                   WHEN 'text' THEN to_jsonb(effective.value_text)
                   WHEN 'number' THEN to_jsonb(effective.value_number)
                   WHEN 'boolean' THEN to_jsonb(effective.value_boolean)
                   WHEN 'timestamp' THEN to_jsonb(effective.value_timestamp)
                   WHEN 'entity_reference' THEN to_jsonb(effective.value_entity_id)
                   WHEN 'structured' THEN effective.value_json
                   ELSE 'null'::jsonb
                 END
               END
          FROM operations.entity_attribute_effective_current effective
          JOIN operations.attribute_definitions definition
            ON definition.id = effective.attribute_definition_id
         WHERE effective.tenant_id = p_tenant_id
           AND effective.entity_id = p_entity_id
           AND effective.id = p_record_id;
    ELSE
        RETURN QUERY
        SELECT definition.key, definition.display_name, definition.sensitivity,
               source.name::text,
               CASE claim.value_type
                 WHEN 'text' THEN to_jsonb(claim.value_text)
                 WHEN 'number' THEN to_jsonb(claim.value_number)
                 WHEN 'boolean' THEN to_jsonb(claim.value_boolean)
                 WHEN 'timestamp' THEN to_jsonb(claim.value_timestamp)
                 WHEN 'entity_reference' THEN to_jsonb(claim.value_entity_id)
                 WHEN 'structured' THEN claim.value_json
                 ELSE 'null'::jsonb
               END
          FROM operations.entity_attribute_claim_current claim
          JOIN operations.attribute_definitions definition
            ON definition.id = claim.attribute_definition_id
          JOIN operations.source_instances source_instance
            ON source_instance.tenant_id = claim.tenant_id
           AND source_instance.id = claim.source_instance_id
          JOIN operations.sources source ON source.id = source_instance.source_id
         WHERE claim.tenant_id = p_tenant_id
           AND claim.entity_id = p_entity_id
           AND claim.id = p_record_id
           AND claim.active;
    END IF;
END;
$function$;

ALTER FUNCTION operations.can_reveal_restricted_evidence(integer, bigint)
    OWNER TO operations_migrate;
ALTER FUNCTION operations.reveal_entity_observation(
    integer, bigint, uuid, uuid, inet, text
) OWNER TO operations_migrate;
ALTER FUNCTION operations.reveal_entity_attribute_value(
    integer, bigint, uuid, text, uuid, inet, text
) OWNER TO operations_migrate;

REVOKE ALL ON FUNCTION operations.can_reveal_restricted_evidence(integer, bigint)
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
REVOKE ALL ON FUNCTION operations.reveal_entity_observation(
    integer, bigint, uuid, uuid, inet, text
) FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
REVOKE ALL ON FUNCTION operations.reveal_entity_attribute_value(
    integer, bigint, uuid, text, uuid, inet, text
) FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.reveal_entity_observation(
    integer, bigint, uuid, uuid, inet, text
) TO operations_app;
GRANT EXECUTE ON FUNCTION operations.reveal_entity_attribute_value(
    integer, bigint, uuid, text, uuid, inet, text
) TO operations_app;

REVOKE SELECT ON operations.entity_observation_current
    FROM operations_app, operations_readonly, metabase_ro;
GRANT SELECT (observation_id) ON operations.entity_observation_current
    TO operations_app;

REVOKE ALL ON operations.entity_attribute_effective_current,
    operations.entity_attribute_effective_member_current,
    operations.entity_attribute_effective_claim_support,
    operations.entity_attribute_conflict_current,
    operations.entity_attribute_conflict_claim_support
FROM operations_app, operations_readonly, metabase_ro;
GRANT SELECT ON operations.v_entity_attribute_effective_current
    TO operations_app, operations_readonly;
"""


REVERSE_SQL = r"""
DROP FUNCTION IF EXISTS operations.reveal_entity_attribute_value(
    integer, bigint, uuid, text, uuid, inet, text
);
DROP FUNCTION IF EXISTS operations.reveal_entity_observation(
    integer, bigint, uuid, uuid, inet, text
);
DROP FUNCTION IF EXISTS operations.can_reveal_restricted_evidence(integer, bigint);
DROP VIEW IF EXISTS operations.v_entity_observation_admin_metadata;
GRANT SELECT ON operations.entity_observation_current,
    operations.entity_attribute_effective_current,
    operations.entity_attribute_effective_member_current,
    operations.entity_attribute_effective_claim_support,
    operations.entity_attribute_conflict_current,
    operations.entity_attribute_conflict_claim_support
TO operations_app;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0116_generic_admin_read_models"),
    ]

    operations: ClassVar[list] = [
        migrations.AlterModelOptions(
            name="user",
            options={
                "permissions": (
                    ("view_clients", "Can view clients"),
                    ("view_devices", "Can view devices"),
                    ("view_software", "Can view software"),
                    ("view_findings", "Can view findings"),
                    ("write_decisions", "Can write decisions"),
                    ("approve_merges", "Can approve merges"),
                    ("manage_findings", "Can manage findings"),
                    ("manage_client_policy", "Can manage client policy"),
                    ("manage_catalog", "Can manage software catalog"),
                    ("manage_collectors", "Can manage collectors"),
                    ("manage_sources", "Can manage sources"),
                    ("manage_secrets", "Can manage secrets"),
                    ("manage_users", "Can manage Operations users"),
                    ("manage_taxonomy", "Can manage reference taxonomy"),
                    ("run_queries", "Can run saved queries"),
                    (
                        "view_restricted_evidence",
                        "Can view restricted source evidence",
                    ),
                )
            },
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
