"""Keep source-link history intervals valid when observations share a timestamp."""

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION operations.sync_entity_source_links_from_observations()
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = operations, pg_temp
AS $function$
DECLARE
    anchored_clients integer := 0;
    anchored_devices integer := 0;
    inserted_links integer := 0;
    updated_links integer := 0;
    inserted_history integer := 0;
BEGIN
    IF EXISTS (
        SELECT 1 FROM clients c JOIN devices d ON d.id = c.id
         WHERE c.entity_id IS NULL OR d.entity_id IS NULL
    ) THEN
        RAISE EXCEPTION 'Client/device UUID collision prevents safe generic entity anchoring';
    END IF;

    INSERT INTO entities (
        id, tenant_id, entity_class_id, scope_kind, client_id, version,
        created_at, created_reason, updated_at, updated_reason,
        retired_at, retired_reason, deleted_at, deleted_reason
    )
    SELECT c.id, c.tenant_id, 'client', 'tenant', NULL, 1,
           c.created_at, 'system.compatibility_backfill', c.updated_at,
           'system.compatibility_backfill', NULL, '', c.deleted_at,
           c.deleted_reason
      FROM clients c WHERE c.entity_id IS NULL
    ON CONFLICT (id) DO NOTHING;

    UPDATE clients c SET entity_id = e.id
      FROM entities e
     WHERE c.entity_id IS NULL AND e.id = c.id
       AND e.tenant_id = c.tenant_id AND e.entity_class_id = 'client';
    GET DIAGNOSTICS anchored_clients = ROW_COUNT;

    INSERT INTO entities (
        id, tenant_id, entity_class_id, scope_kind, client_id, version,
        created_at, created_reason, updated_at, updated_reason,
        retired_at, retired_reason, deleted_at, deleted_reason
    )
    SELECT d.id, d.tenant_id, 'device', 'client', d.client_id, 1,
           d.created_at, 'system.compatibility_backfill', d.updated_at,
           'system.compatibility_backfill',
           CASE WHEN d.lifecycle_status = 'retired' THEN d.updated_at END,
           CASE WHEN d.lifecycle_status = 'retired'
                THEN 'system.compatibility_backfill' ELSE '' END,
           d.deleted_at, d.deleted_reason
      FROM devices d WHERE d.entity_id IS NULL
    ON CONFLICT (id) DO NOTHING;

    UPDATE devices d SET entity_id = e.id
      FROM entities e
     WHERE d.entity_id IS NULL AND e.id = d.id
       AND e.tenant_id = d.tenant_id AND e.entity_class_id = 'device';
    GET DIAGNOSTICS anchored_devices = ROW_COUNT;

    CREATE TEMP TABLE IF NOT EXISTS resolved_source_links (
        tenant_id bigint NOT NULL, entity_id uuid NOT NULL,
        entity_class_id varchar(80) NOT NULL, source_instance_id uuid NOT NULL,
        last_seen_binding_id uuid, external_namespace varchar(120) NOT NULL,
        parent_external_namespace varchar(120) NOT NULL,
        parent_external_id text NOT NULL, external_id text NOT NULL,
        first_seen_at timestamptz NOT NULL, last_seen_at timestamptz NOT NULL,
        missing_since timestamptz,
        PRIMARY KEY (tenant_id, source_instance_id, external_namespace,
                     parent_external_namespace, parent_external_id, external_id)
    ) ON COMMIT DROP;
    TRUNCATE resolved_source_links;

    INSERT INTO resolved_source_links
    WITH first_seen AS (
        SELECT tenant_id, source_instance_id, external_namespace,
               parent_external_namespace, parent_external_id, external_id,
               MIN(effective_from) AS first_seen_at
          FROM entity_observation_history
         GROUP BY tenant_id, source_instance_id, external_namespace,
                  parent_external_namespace, parent_external_id, external_id
    )
    SELECT o.tenant_id, COALESCE(d.entity_id, c.entity_id),
           CASE WHEN d.entity_id IS NOT NULL THEN 'device' ELSE 'client' END,
           o.source_instance_id, o.last_seen_binding_id,
           o.external_namespace, o.parent_external_namespace,
           o.parent_external_id, o.external_id,
           COALESCE(f.first_seen_at, o.observed_at), o.last_seen_at,
           CASE WHEN o.active THEN NULL
                ELSE COALESCE(o.withdrawn_at, o.last_seen_at) END
      FROM entity_observation_current o
      LEFT JOIN devices d ON d.tenant_id = o.tenant_id AND d.id = o.device_id
      LEFT JOIN clients c ON c.tenant_id = o.tenant_id AND c.id = o.client_id
                         AND o.device_id IS NULL AND o.entity_type = 'org'
      LEFT JOIN first_seen f ON f.tenant_id = o.tenant_id
                            AND f.source_instance_id = o.source_instance_id
                            AND f.external_namespace = o.external_namespace
                            AND f.parent_external_namespace = o.parent_external_namespace
                            AND f.parent_external_id = o.parent_external_id
                            AND f.external_id = o.external_id
     WHERE COALESCE(d.entity_id, c.entity_id) IS NOT NULL;

    UPDATE entity_source_link_history h
       SET effective_to = GREATEST(
           r.last_seen_at, h.effective_from + interval '1 microsecond')
      FROM entity_source_links l
      JOIN resolved_source_links r
        ON r.tenant_id = l.tenant_id
       AND r.source_instance_id = l.source_instance_id
       AND r.external_namespace = l.external_namespace
       AND r.parent_external_namespace = l.parent_external_namespace
       AND r.parent_external_id = l.parent_external_id
       AND r.external_id = l.external_id
     WHERE h.tenant_id = l.tenant_id
       AND h.source_instance_id = l.source_instance_id
       AND h.external_namespace = l.external_namespace
       AND h.parent_external_namespace = l.parent_external_namespace
       AND h.parent_external_id = l.parent_external_id
       AND h.external_id = l.external_id
       AND h.effective_to IS NULL
       AND (l.entity_id, l.entity_class_id) IS DISTINCT FROM
           (r.entity_id, r.entity_class_id);

    UPDATE entity_source_links l
       SET entity_id = r.entity_id, entity_class_id = r.entity_class_id,
           last_seen_binding_id = r.last_seen_binding_id,
           last_seen_at = r.last_seen_at, missing_since = r.missing_since,
           match_method = CASE WHEN (l.entity_id, l.entity_class_id)
               IS DISTINCT FROM (r.entity_id, r.entity_class_id)
               THEN 'compatibility' ELSE l.match_method END,
           match_confidence = CASE WHEN (l.entity_id, l.entity_class_id)
               IS DISTINCT FROM (r.entity_id, r.entity_class_id)
               THEN 1 ELSE l.match_confidence END,
           reason = CASE WHEN (l.entity_id, l.entity_class_id)
               IS DISTINCT FROM (r.entity_id, r.entity_class_id)
               THEN 'system.compatibility_reattachment' ELSE l.reason END,
           version = l.version + 1
      FROM resolved_source_links r
     WHERE l.tenant_id = r.tenant_id
       AND l.source_instance_id = r.source_instance_id
       AND l.external_namespace = r.external_namespace
       AND l.parent_external_namespace = r.parent_external_namespace
       AND l.parent_external_id = r.parent_external_id
       AND l.external_id = r.external_id
       AND (l.entity_id, l.entity_class_id, l.last_seen_binding_id,
            l.last_seen_at, l.missing_since) IS DISTINCT FROM
           (r.entity_id, r.entity_class_id, r.last_seen_binding_id,
            r.last_seen_at, r.missing_since);
    GET DIAGNOSTICS updated_links = ROW_COUNT;

    INSERT INTO entity_source_links (
        id, tenant_id, version, entity_id, entity_class_id,
        source_instance_id, last_seen_binding_id, external_namespace,
        parent_external_namespace, parent_external_id, external_id,
        first_seen_at, last_seen_at, missing_since, match_method,
        match_confidence, reason
    )
    SELECT gen_random_uuid(), r.tenant_id, 1, r.entity_id, r.entity_class_id,
           r.source_instance_id, r.last_seen_binding_id, r.external_namespace,
           r.parent_external_namespace, r.parent_external_id, r.external_id,
           r.first_seen_at, r.last_seen_at, r.missing_since, 'compatibility', 1,
           'system.compatibility_backfill'
      FROM resolved_source_links r
    ON CONFLICT (tenant_id, source_instance_id, external_namespace,
                 parent_external_namespace, parent_external_id, external_id)
    DO NOTHING;
    GET DIAGNOSTICS inserted_links = ROW_COUNT;

    INSERT INTO entity_source_link_history (
        id, tenant_id, version, entity_id, entity_class_id,
        source_instance_id, last_seen_binding_id, external_namespace,
        parent_external_namespace, parent_external_id, external_id,
        match_method, match_confidence, actor_kind, actor_id,
        actor_process, reason, evidence, effective_from, effective_to
    )
    SELECT gen_random_uuid(), l.tenant_id, 1, l.entity_id, l.entity_class_id,
           l.source_instance_id, l.last_seen_binding_id, l.external_namespace,
           l.parent_external_namespace, l.parent_external_id, l.external_id,
           l.match_method, l.match_confidence, 'system', NULL,
           'ingest.entity_link_sync', l.reason,
           jsonb_build_object('compatibility_projection', TRUE),
           CASE WHEN EXISTS (
               SELECT 1 FROM entity_source_link_history prior
                WHERE prior.tenant_id = l.tenant_id
                  AND prior.source_instance_id = l.source_instance_id
                  AND prior.external_namespace = l.external_namespace
                  AND prior.parent_external_namespace = l.parent_external_namespace
                  AND prior.parent_external_id = l.parent_external_id
                  AND prior.external_id = l.external_id
           ) THEN clock_timestamp() ELSE l.first_seen_at END, NULL
      FROM entity_source_links l
      LEFT JOIN entity_source_link_history h
        ON h.tenant_id = l.tenant_id
       AND h.source_instance_id = l.source_instance_id
       AND h.external_namespace = l.external_namespace
       AND h.parent_external_namespace = l.parent_external_namespace
       AND h.parent_external_id = l.parent_external_id
       AND h.external_id = l.external_id
       AND h.entity_id = l.entity_id
       AND h.entity_class_id = l.entity_class_id
       AND h.effective_to IS NULL
     WHERE h.id IS NULL;
    GET DIAGNOSTICS inserted_history = ROW_COUNT;

    RETURN jsonb_build_object(
        'anchored_clients', anchored_clients,
        'anchored_devices', anchored_devices,
        'inserted_links', inserted_links,
        'updated_links', updated_links,
        'inserted_history', inserted_history
    );
END;
$function$;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar = [("operations", "0175_seed_final_issue_taxonomy")]
    operations: ClassVar = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
