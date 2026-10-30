"""One confirmed-association authority (PLAN-004 R4 Stage B, design §2.1, ADR-0049 d1).

``entity_source_links`` plus its history become the only confirmed-association
authority. ``entity_observation_current.device_id`` is its projection and only
``operations.set_source_association`` changes the link, the history and the
projection together. It checks the expected association version, advances the
subject's association version (which advances the tenant generation at commit)
and queues the subject and its key neighbors.

* Links gain ``source_subject_id`` and ``association_version``; backfilled from
  subjects by natural key (verified 2026-10-30: every link has a subject).
* Writers converted inside their own transactions: intake and the resolver go
  through ``associate_record`` / ``associate_unassociated_records``; merge,
  merge split, record split, link move and source-group move call the procedure
  per affected subject; candidate attach calls ``set_source_association_by_key``.
* ``sync_entity_source_links_from_observations`` is retired as an association
  writer. It keeps entity anchoring, refreshes link presence, maps group records
  through the procedure and reports device-projection divergence without
  repairing it.
* Guards, enforced by triggers because production ingest connects as a
  superuser: a changed ``device_id`` needs the association writer; link and
  history writes need the association writer, except presence-only link updates
  (entity, method, confidence, subject and version unchanged) under the presence
  writer. Migrations are exempt.

Drained cutover: apply with ingest, resolver and Jobs stopped. The findings contract
becomes 5, so the new ingest and Jobs worker wait for this migration and an old
process fails at its next findings write; an old writer that still reached the
guards would fail there rather than write a divergent projection.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
SET LOCAL lock_timeout = '120s';
LOCK TABLE operations.entity_observation_current, operations.entity_source_links,
           operations.entity_source_link_history IN SHARE ROW EXCLUSIVE MODE;
SET LOCAL lock_timeout = 0;

ALTER TABLE operations.entity_source_links
    ADD COLUMN source_subject_id uuid,
    ADD COLUMN association_version bigint NOT NULL DEFAULT 0
        CHECK (association_version >= 0);
UPDATE operations.entity_source_links l
   SET source_subject_id = s.id
  FROM operations.source_record_subjects s
 WHERE s.tenant_id = l.tenant_id AND s.subject_kind = 'record'
   AND s.source_instance_id = l.source_instance_id
   AND s.external_namespace = l.external_namespace
   AND s.parent_external_namespace = l.parent_external_namespace
   AND s.parent_external_id = l.parent_external_id
   AND s.external_id = l.external_id;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM operations.entity_source_links WHERE source_subject_id IS NULL) THEN
        RAISE EXCEPTION 'Stage B: % links have no source-record subject',
            (SELECT count(*) FROM operations.entity_source_links WHERE source_subject_id IS NULL);
    END IF;
    IF EXISTS (
        SELECT 1 FROM operations.entity_observation_current o
          LEFT JOIN operations.entity_source_links l
            ON l.tenant_id = o.tenant_id AND l.source_instance_id = o.source_instance_id
           AND l.external_namespace = o.external_namespace
           AND l.parent_external_namespace = o.parent_external_namespace
           AND l.parent_external_id = o.parent_external_id
           AND l.external_id = o.external_id AND l.entity_class_id = 'device'
         WHERE o.device_id IS NOT NULL AND (l.id IS NULL OR l.entity_id <> o.device_id)) THEN
        RAISE EXCEPTION 'Stage B: device projections diverge from their links; review before cutover';
    END IF;
END
$$;
ALTER TABLE operations.entity_source_links
    ALTER COLUMN source_subject_id SET NOT NULL,
    ADD CONSTRAINT entity_source_links_subject_fkey FOREIGN KEY (tenant_id, source_subject_id)
        REFERENCES operations.source_record_subjects (tenant_id, id),
    ADD CONSTRAINT uq_entity_source_links_subject UNIQUE (tenant_id, source_subject_id);
UPDATE operations.change_history_registry
   SET recorded_columns = recorded_columns || ARRAY['source_subject_id', 'association_version']::text[]
 WHERE table_name = 'entity_source_links' AND classification = 'covered'
   AND NOT ('association_version' = ANY (recorded_columns));

-- The one association writer (§2.1). p_entity NULL clears the association.
CREATE FUNCTION operations.set_source_association(
    p_subject uuid, p_entity uuid, p_entity_class text, p_method text, p_confidence numeric,
    p_reason text, p_expected_version bigint, p_actor_kind text DEFAULT 'system',
    p_actor_id bigint DEFAULT NULL, p_process text DEFAULT '', p_evidence jsonb DEFAULT '{}'::jsonb
) RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_tenant bigint := nullif(current_setting('operations.tenant_id', true), '')::bigint;
    s operations.source_record_subjects%ROWTYPE;
    l operations.entity_source_links%ROWTYPE;
    o operations.entity_observation_current%ROWTYPE;
    v_device uuid;
    v_now timestamptz := clock_timestamp();
    v_version bigint;
    v_link uuid;
BEGIN
    IF v_tenant IS NULL THEN
        RAISE EXCEPTION 'set_source_association needs the session tenant';
    END IF;
    IF p_entity_class IS NULL
       OR NOT EXISTS (SELECT 1 FROM operations.entity_classes WHERE name = p_entity_class) THEN
        RAISE EXCEPTION 'set_source_association: unknown entity class %', p_entity_class;
    END IF;
    SELECT * INTO s FROM operations.source_record_subjects
     WHERE tenant_id = v_tenant AND id = p_subject AND subject_kind = 'record' FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'set_source_association: unknown source record %', p_subject;
    END IF;
    IF p_expected_version IS NOT NULL AND s.association_version <> p_expected_version THEN
        RAISE EXCEPTION 'set_source_association: association changed (expected version %, now %)',
                        p_expected_version, s.association_version
              USING ERRCODE = 'serialization_failure';
    END IF;
    IF p_entity IS NOT NULL THEN
        PERFORM 1 FROM operations.entities e
         WHERE e.tenant_id = v_tenant AND e.id = p_entity AND e.entity_class_id = p_entity_class;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'set_source_association: no % entity % in this tenant',
                            p_entity_class, p_entity;
        END IF;
        IF p_entity_class = 'device' THEN
            SELECT d.id INTO v_device FROM operations.devices d
             WHERE d.tenant_id = v_tenant AND d.entity_id = p_entity;
            IF v_device IS NULL THEN
                RAISE EXCEPTION 'set_source_association: entity % has no Computer', p_entity;
            END IF;
        END IF;
    END IF;
    SELECT * INTO o FROM operations.entity_observation_current
     WHERE tenant_id = v_tenant AND observation_id = s.observation_id;
    SELECT * INTO l FROM operations.entity_source_links
     WHERE tenant_id = v_tenant AND source_instance_id = s.source_instance_id
       AND external_namespace = s.external_namespace
       AND parent_external_namespace = s.parent_external_namespace
       AND parent_external_id = s.parent_external_id
       AND external_id = s.external_id
       FOR UPDATE;
    IF (l.id IS NULL AND p_entity IS NULL)
       OR (l.id IS NOT NULL AND l.entity_id = p_entity AND l.entity_class_id = p_entity_class) THEN
        RETURN s.association_version;
    END IF;

    v_version := s.association_version + 1;
    PERFORM set_config('operations.association_writer', 'on', true);
    UPDATE operations.entity_source_link_history
       SET effective_to = GREATEST(v_now, effective_from + interval '1 microsecond')
     WHERE tenant_id = v_tenant AND source_instance_id = s.source_instance_id
       AND external_namespace = s.external_namespace
       AND parent_external_namespace = s.parent_external_namespace
       AND parent_external_id = s.parent_external_id
       AND external_id = s.external_id AND effective_to IS NULL;
    IF p_entity IS NULL THEN
        -- Derived projector state of the cleared link is rebuilt by its projector.
        DELETE FROM operations.entity_attribute_projection_state
         WHERE tenant_id = v_tenant AND entity_source_link_id = l.id;
        DELETE FROM operations.entity_source_links WHERE id = l.id;
    ELSIF l.id IS NULL THEN
        v_link := gen_random_uuid();
        INSERT INTO operations.entity_source_links (
            id, tenant_id, version, entity_id, entity_class_id, source_instance_id,
            last_seen_binding_id, external_namespace, parent_external_namespace,
            parent_external_id, external_id, first_seen_at, last_seen_at, missing_since,
            match_method, match_confidence, reason, source_subject_id, association_version)
        VALUES (v_link, v_tenant, 1, p_entity, p_entity_class, s.source_instance_id,
                o.last_seen_binding_id, s.external_namespace, s.parent_external_namespace,
                s.parent_external_id, s.external_id, coalesce(o.observed_at, v_now),
                coalesce(o.last_seen_at, v_now),
                CASE WHEN o.active IS FALSE THEN coalesce(o.withdrawn_at, o.last_seen_at) END,
                left(coalesce(p_method, ''), 32), coalesce(p_confidence, 1),
                left(coalesce(p_reason, ''), 120), s.id, v_version);
    ELSE
        UPDATE operations.entity_source_links
           SET entity_id = p_entity, entity_class_id = p_entity_class,
               match_method = left(coalesce(p_method, ''), 32),
               match_confidence = coalesce(p_confidence, 1),
               reason = left(coalesce(p_reason, ''), 120),
               version = version + 1, source_subject_id = s.id, association_version = v_version
         WHERE id = l.id;
    END IF;
    IF p_entity IS NOT NULL THEN
        INSERT INTO operations.entity_source_link_history (
            id, tenant_id, version, entity_id, entity_class_id, source_instance_id,
            last_seen_binding_id, external_namespace, parent_external_namespace,
            parent_external_id, external_id, match_method, match_confidence, actor_kind,
            actor_id, actor_process, reason, evidence, effective_from, effective_to)
        VALUES (gen_random_uuid(), v_tenant, 1, p_entity, p_entity_class, s.source_instance_id,
                coalesce(l.last_seen_binding_id, o.last_seen_binding_id), s.external_namespace,
                s.parent_external_namespace, s.parent_external_id, s.external_id,
                left(coalesce(p_method, ''), 32), coalesce(p_confidence, 1),
                coalesce(p_actor_kind, 'system'), p_actor_id, left(coalesce(p_process, ''), 120),
                left(coalesce(p_reason, ''), 120),
                coalesce(p_evidence, '{}'::jsonb) || jsonb_build_object(
                    'association_version', v_version, 'previous_entity_id', l.entity_id),
                v_now, NULL);
    END IF;
    UPDATE operations.entity_observation_current
       SET device_id = CASE WHEN p_entity_class = 'device' THEN v_device END
     WHERE tenant_id = v_tenant AND observation_id = s.observation_id
       AND device_id IS DISTINCT FROM CASE WHEN p_entity_class = 'device' THEN v_device END;
    UPDATE operations.source_record_subjects
       SET association_version = v_version, updated_at = now()
     WHERE tenant_id = v_tenant AND id = s.id;
    PERFORM operations.source_record_enqueue(v_tenant, 'source_record', s.id);
    PERFORM operations.source_record_enqueue_neighbors(
        v_tenant, s.id, s.source_instance_id,
        coalesce((SELECT array_agg(key_family) FROM operations.source_record_lookup_keys
                   WHERE tenant_id = v_tenant AND subject_id = s.id), '{}'),
        coalesce((SELECT array_agg(normalized_value) FROM operations.source_record_lookup_keys
                   WHERE tenant_id = v_tenant AND subject_id = s.id), '{}'));
    PERFORM set_config('operations.association_writer', '', true);
    RETURN v_version;
END
$fn$;

-- By natural key; p_require_unassociated refuses a different current entity.
CREATE FUNCTION operations.set_source_association_by_key(
    p_tenant bigint, p_source_instance uuid, p_external_namespace text,
    p_parent_external_namespace text, p_parent_external_id text, p_external_id text,
    p_entity uuid, p_entity_class text, p_method text, p_reason text,
    p_actor_kind text, p_actor_id bigint, p_process text, p_evidence jsonb,
    p_require_unassociated boolean
) RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_subject uuid;
    v_version bigint;
    v_current uuid;
BEGIN
    PERFORM set_config('operations.tenant_id', p_tenant::text, true);
    SELECT s.id, s.association_version, l.entity_id INTO v_subject, v_version, v_current
      FROM operations.source_record_subjects s
      LEFT JOIN operations.entity_source_links l
        ON l.tenant_id = s.tenant_id AND l.source_subject_id = s.id
     WHERE s.tenant_id = p_tenant AND s.subject_kind = 'record'
       AND s.source_instance_id = p_source_instance
       AND s.external_namespace = p_external_namespace
       AND s.parent_external_namespace = p_parent_external_namespace
       AND s.parent_external_id = p_parent_external_id
       AND s.external_id = p_external_id;
    IF v_subject IS NULL THEN
        RAISE EXCEPTION 'no managed source record for this identity';
    END IF;
    IF p_require_unassociated AND v_current IS NOT NULL AND v_current <> p_entity THEN
        RAISE EXCEPTION 'The stable source identity is already attached elsewhere.';
    END IF;
    RETURN operations.set_source_association(
        v_subject, p_entity, p_entity_class, p_method, 1, p_reason, v_version,
        p_actor_kind, p_actor_id, p_process, p_evidence);
END
$fn$;

-- Computer association of one received record (intake, resolver). Returns true
-- when the association changed. p_only_if_unassociated keeps an existing device
-- association (the resolver's "device_id IS NULL" contract).
CREATE FUNCTION operations.associate_record(
    p_tenant bigint, p_source_instance uuid, p_external_namespace text,
    p_parent_external_namespace text, p_parent_external_id text, p_external_id text,
    p_device uuid, p_method text, p_process text, p_only_if_unassociated boolean
) RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_subject uuid;
    v_version bigint;
    v_entity uuid;
    v_current uuid;
    v_class text;
BEGIN
    PERFORM set_config('operations.tenant_id', p_tenant::text, true);
    SELECT d.entity_id INTO v_entity FROM operations.devices d
     WHERE d.tenant_id = p_tenant AND d.id = p_device AND d.deleted_at IS NULL;
    IF v_entity IS NULL THEN
        RAISE EXCEPTION 'associate_record: unknown or deleted Computer %', p_device;
    END IF;
    SELECT s.id, s.association_version, l.entity_id, l.entity_class_id
      INTO v_subject, v_version, v_current, v_class
      FROM operations.source_record_subjects s
      LEFT JOIN operations.entity_source_links l
        ON l.tenant_id = s.tenant_id AND l.source_subject_id = s.id
     WHERE s.tenant_id = p_tenant AND s.subject_kind = 'record'
       AND s.source_instance_id = p_source_instance
       AND s.external_namespace = p_external_namespace
       AND s.parent_external_namespace = p_parent_external_namespace
       AND s.parent_external_id = p_parent_external_id
       AND s.external_id = p_external_id;
    IF v_subject IS NULL THEN
        RAISE EXCEPTION 'associate_record: no managed source record for this identity';
    END IF;
    IF v_class = 'device' AND v_current = v_entity THEN
        RETURN false;
    END IF;
    IF p_only_if_unassociated AND v_class = 'device' THEN
        RETURN false;
    END IF;
    PERFORM operations.set_source_association(
        v_subject, v_entity, 'device', p_method, 1, 'system.' || p_method, v_version,
        'system', NULL, p_process, '{}'::jsonb);
    RETURN true;
END
$fn$;

CREATE FUNCTION operations.associate_observation(
    p_tenant bigint, p_observation uuid, p_device uuid, p_method text, p_process text,
    p_only_if_unassociated boolean
) RETURNS boolean
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
    SELECT operations.associate_record(
        o.tenant_id, o.source_instance_id, o.external_namespace, o.parent_external_namespace,
        o.parent_external_id, o.external_id, p_device, p_method, p_process,
        p_only_if_unassociated)
      FROM operations.entity_observation_current o
     WHERE o.tenant_id = p_tenant AND o.observation_id = p_observation
$fn$;

-- The resolver's group attachment: every unattached record of one source key.
CREATE FUNCTION operations.associate_unassociated_records(
    p_tenant bigint, p_platform text, p_entity_key text, p_device uuid, p_method text,
    p_process text
) RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    r record;
    v_count integer := 0;
BEGIN
    FOR r IN SELECT o.observation_id FROM operations.entity_observation_current o
              WHERE o.tenant_id = p_tenant AND o.platform = p_platform
                AND o.entity_key = p_entity_key AND o.device_id IS NULL
              ORDER BY o.observation_id LOOP
        IF operations.associate_observation(p_tenant, r.observation_id, p_device, p_method,
                                            p_process, true) THEN
            v_count := v_count + 1;
        END IF;
    END LOOP;
    RETURN v_count;
END
$fn$;

-- Repoint every link of one entity (merge and its split). Returns the link ids.
CREATE OR REPLACE FUNCTION operations.move_computer_links(
    p_tenant bigint, p_from_entity uuid, p_to_entity uuid, p_reason text
) RETURNS uuid[]
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_links uuid[] := '{}';
    r record;
BEGIN
    PERFORM set_config('operations.tenant_id', p_tenant::text, true);
    FOR r IN SELECT l.id, l.source_subject_id, l.entity_class_id, s.association_version
               FROM operations.entity_source_links l
               JOIN operations.source_record_subjects s
                 ON s.tenant_id = l.tenant_id AND s.id = l.source_subject_id
              WHERE l.tenant_id = p_tenant AND l.entity_id = p_from_entity
              ORDER BY l.id LOOP
        PERFORM operations.set_source_association(
            r.source_subject_id, p_to_entity, r.entity_class_id, 'merge', 1, p_reason,
            r.association_version, 'system', NULL, 'operations.computer_merge',
            jsonb_build_object('from_entity_id', p_from_entity));
        v_links := v_links || r.id;
    END LOOP;
    PERFORM operations.retire_entity_relationships(p_tenant, p_from_entity, 'computer_merged');
    RETURN v_links;
END
$fn$;

-- Presence-only link refresh for source deletion events (§2.1 presence row).
CREATE FUNCTION operations.mark_source_links_missing(
    p_tenant bigint, p_source_instance uuid, p_keys jsonb, p_missing_since timestamptz
) RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_count integer;
BEGIN
    PERFORM set_config('operations.link_presence_writer', 'on', true);
    UPDATE operations.entity_source_links link
       SET missing_since = p_missing_since, reason = 'source_deleted', version = link.version + 1
      FROM jsonb_to_recordset(p_keys) AS k(external_namespace text,
           parent_external_namespace text, parent_external_id text, external_id text)
     WHERE link.tenant_id = p_tenant AND link.source_instance_id = p_source_instance
       AND link.external_namespace = k.external_namespace
       AND link.parent_external_namespace = k.parent_external_namespace
       AND link.parent_external_id = k.parent_external_id
       AND link.external_id = k.external_id
       AND link.missing_since IS NULL AND link.last_seen_at <= p_missing_since;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    PERFORM set_config('operations.link_presence_writer', '', true);
    RETURN v_count;
END
$fn$;

-- Retired as an association writer (Stage B). Anchors entities, refreshes link
-- presence, maps group records through set_source_association and reports any
-- device-projection divergence without repairing it.
CREATE OR REPLACE FUNCTION operations.sync_entity_source_links_from_observations()
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = operations, pg_temp
AS $function$
DECLARE
    anchored_clients integer := 0;
    anchored_devices integer := 0;
    presence_updates integer := 0;
    group_mappings integer := 0;
    divergent integer := 0;
    r record;
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

    PERFORM set_config('operations.link_presence_writer', 'on', true);
    UPDATE entity_source_links l
       SET last_seen_binding_id = o.last_seen_binding_id,
           last_seen_at = o.last_seen_at,
           missing_since = CASE WHEN o.active THEN NULL
                                ELSE COALESCE(o.withdrawn_at, o.last_seen_at) END,
           version = l.version + 1
      FROM entity_observation_current o
     WHERE o.tenant_id = l.tenant_id AND o.source_instance_id = l.source_instance_id
       AND o.external_namespace = l.external_namespace
       AND o.parent_external_namespace = l.parent_external_namespace
       AND o.parent_external_id = l.parent_external_id
       AND o.external_id = l.external_id
       AND (l.last_seen_binding_id, l.last_seen_at, l.missing_since) IS DISTINCT FROM
           (o.last_seen_binding_id, o.last_seen_at,
            CASE WHEN o.active THEN NULL ELSE COALESCE(o.withdrawn_at, o.last_seen_at) END);
    GET DIAGNOSTICS presence_updates = ROW_COUNT;
    PERFORM set_config('operations.link_presence_writer', '', true);

    -- Group records follow their client mapping (client_resolver owns that
    -- mapping on the group observation); the procedure records it.
    FOR r IN
        SELECT s.tenant_id, s.id AS subject_id, s.association_version, c.entity_id
          FROM entity_observation_current o
          JOIN source_record_subjects s
            ON s.tenant_id = o.tenant_id AND s.observation_id = o.observation_id
          JOIN clients c ON c.tenant_id = o.tenant_id AND c.id = o.client_id
          LEFT JOIN entity_source_links l
            ON l.tenant_id = s.tenant_id AND l.source_subject_id = s.id
         WHERE o.entity_type = 'org' AND o.device_id IS NULL AND c.entity_id IS NOT NULL
           AND (l.id IS NULL OR (l.entity_class_id = 'client' AND l.entity_id <> c.entity_id))
         ORDER BY s.tenant_id, s.id
    LOOP
        PERFORM set_config('operations.tenant_id', r.tenant_id::text, true);
        PERFORM operations.set_source_association(
            r.subject_id, r.entity_id, 'client', 'compatibility', 1,
            'system.group_mapping', r.association_version, 'system', NULL,
            'ingest.entity_link_sync', jsonb_build_object('group_mapping', TRUE));
        group_mappings := group_mappings + 1;
    END LOOP;

    SELECT count(*) INTO divergent
      FROM entity_observation_current o
      LEFT JOIN entity_source_links l
        ON l.tenant_id = o.tenant_id AND l.source_instance_id = o.source_instance_id
       AND l.external_namespace = o.external_namespace
       AND l.parent_external_namespace = o.parent_external_namespace
       AND l.parent_external_id = o.parent_external_id
       AND l.external_id = o.external_id
     WHERE (o.device_id IS NOT NULL
            AND (l.id IS NULL OR l.entity_class_id <> 'device' OR l.entity_id <> o.device_id))
        OR (o.device_id IS NULL AND l.entity_class_id = 'device');
    IF divergent > 0 THEN
        RAISE WARNING 'entity link parity: % device projections differ from their links', divergent;
    END IF;

    RETURN jsonb_build_object(
        'anchored_clients', anchored_clients,
        'anchored_devices', anchored_devices,
        'presence_updates', presence_updates,
        'group_mappings', group_mappings,
        'divergent_projections', divergent
    );
END
$function$;
"""

# The converted writers whose bodies otherwise stay as they are in production.
CONVERTED_SQL = r"""
CREATE OR REPLACE FUNCTION operations.merge_computers(p_survivor uuid, p_absorbed uuid, p_reason text, p_evidence jsonb DEFAULT '{}'::jsonb, p_actor_kind text DEFAULT 'process'::text, p_actor_id bigint DEFAULT NULL::bigint, p_process text DEFAULT ''::text)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'operations'
AS $function$
DECLARE
    s operations.devices%ROWTYPE;
    a operations.devices%ROWTYPE;
    v_action uuid;
    v_merge uuid;
    v_observations uuid[];
    v_findings uuid[];
    v_links uuid[];
BEGIN
    SELECT * INTO s FROM operations.devices WHERE id = p_survivor FOR UPDATE;
    SELECT * INTO a FROM operations.devices WHERE id = p_absorbed FOR UPDATE;
    IF s.id IS NULL OR a.id IS NULL THEN
        RAISE EXCEPTION 'merge_computers: unknown Computer';
    END IF;
    IF s.id = a.id THEN
        RAISE EXCEPTION 'merge_computers: a Computer cannot absorb itself';
    END IF;
    IF s.deleted_at IS NOT NULL OR a.deleted_at IS NOT NULL THEN
        RAISE EXCEPTION 'merge_computers: both Computers must be current';
    END IF;
    IF s.tenant_id <> a.tenant_id OR s.client_id <> a.client_id THEN
        RAISE EXCEPTION 'merge_computers: Computers of different clients are never merged';
    END IF;
    PERFORM set_config('operations.tenant_id', s.tenant_id::text, true);

    v_action := operations.begin_change(
        CASE WHEN p_actor_kind = 'operator' THEN 'computer.merge' ELSE 'computer.merge.automatic' END,
        p_reason,
        coalesce(p_evidence, '{}'::jsonb)
            || jsonb_build_object('survivor_id', s.id, 'absorbed_id', a.id),
        p_actor_kind, p_actor_id, coalesce(p_process, ''), '', s.tenant_id, true);

    SELECT coalesce(array_agg(observation_id ORDER BY observation_id), '{}') INTO v_observations
      FROM operations.entity_observation_current
     WHERE tenant_id = s.tenant_id AND device_id = a.id;

    WITH moved AS (
        UPDATE operations.findings
           SET subject_id = s.id,
               finding_details = finding_details || jsonb_build_object(
                   'merge', jsonb_build_object(
                       'reason', 'merged_device',
                       'from_device_id', a.id::text,
                       'into_device_id', s.id::text))
         WHERE tenant_id = s.tenant_id AND subject_type = 'device' AND subject_id = a.id
        RETURNING id
    )
    SELECT coalesce(array_agg(id), '{}') INTO v_findings FROM moved;

    INSERT INTO operations.condition_participants
        (tenant_id, row_kind, finding_id, participant_kind, participant_id, participant_role)
    SELECT tenant_id, row_kind, finding_id, participant_kind, s.id, participant_role
      FROM operations.condition_participants
     WHERE tenant_id = s.tenant_id AND participant_kind = 'device' AND participant_id = a.id
    ON CONFLICT DO NOTHING;
    DELETE FROM operations.condition_participants
     WHERE tenant_id = s.tenant_id AND participant_kind = 'device' AND participant_id = a.id;
    INSERT INTO operations.condition_assessments
        (tenant_id, row_kind, finding_id, participant_kind, participant_id,
         participant_role, condition_identity, policy_version, policy_digest,
         coverage, response, reevaluation_key, currentness, assessed_at)
    SELECT tenant_id, row_kind, finding_id, participant_kind, s.id,
           participant_role, condition_identity, policy_version, policy_digest,
           coverage, response, reevaluation_key, currentness, assessed_at
      FROM operations.condition_assessments
     WHERE tenant_id = s.tenant_id AND participant_kind = 'device' AND participant_id = a.id
    ON CONFLICT DO NOTHING;
    DELETE FROM operations.condition_assessments
     WHERE tenant_id = s.tenant_id AND participant_kind = 'device' AND participant_id = a.id;

    UPDATE operations.software_installations_current winner
       SET publisher = COALESCE(winner.publisher, losing.publisher),
           version = CASE WHEN losing.last_observed_at > winner.last_observed_at
                          THEN COALESCE(losing.version, winner.version)
                          ELSE winner.version END,
           install_location = COALESCE(winner.install_location, losing.install_location),
           install_date = COALESCE(winner.install_date, losing.install_date),
           first_observed_at = LEAST(winner.first_observed_at, losing.first_observed_at),
           last_observed_at = GREATEST(winner.last_observed_at, losing.last_observed_at),
           refreshed_at = GREATEST(winner.refreshed_at, losing.refreshed_at)
      FROM operations.software_installations_current losing
     WHERE winner.tenant_id = s.tenant_id AND losing.tenant_id = s.tenant_id
       AND winner.client_id = losing.client_id
       AND winner.device_id = s.id AND losing.device_id = a.id
       AND winner.canonical_name = losing.canonical_name;
    DELETE FROM operations.software_installations_current losing
     WHERE losing.tenant_id = s.tenant_id AND losing.device_id = a.id
       AND EXISTS (SELECT 1 FROM operations.software_installations_current winner
                    WHERE winner.tenant_id = losing.tenant_id
                      AND winner.client_id = losing.client_id
                      AND winner.device_id = s.id
                      AND winner.canonical_name = losing.canonical_name);
    UPDATE operations.software_installations_current
       SET device_id = s.id
     WHERE tenant_id = s.tenant_id AND device_id = a.id;

    -- Each absorbed record's association moves through the one writer, which
    -- also projects its device_id onto the survivor (PLAN-004 Stage B).
    v_links := operations.move_computer_links(s.tenant_id, a.entity_id, s.entity_id,
                                              'merged into ' || s.id::text);
    IF EXISTS (SELECT 1 FROM operations.entity_observation_current
                WHERE tenant_id = s.tenant_id AND device_id = a.id) THEN
        RAISE EXCEPTION 'merge_computers: records of % have no confirmed link to move', a.id;
    END IF;

    INSERT INTO operations.computer_merges
        (tenant_id, client_id, survivor_id, absorbed_id, action_id, reason, evidence,
         moved_observation_ids, moved_finding_ids, moved_link_ids)
    VALUES (s.tenant_id, s.client_id, s.id, a.id, v_action, p_reason,
            coalesce(p_evidence, '{}'::jsonb), v_observations, v_findings, v_links)
    RETURNING id INTO v_merge;

    UPDATE operations.devices
       SET deleted_at = now(), deleted_reason = 'merged'
     WHERE id = a.id;
    RETURN v_merge;
END
$function$;

CREATE OR REPLACE FUNCTION operations.split_computer_merge(p_merge uuid, p_reason text, p_actor_kind text DEFAULT 'operator'::text, p_actor_id bigint DEFAULT NULL::bigint, p_process text DEFAULT ''::text)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'operations'
AS $function$
DECLARE
    m operations.computer_merges%ROWTYPE;
    v_action uuid;
    r record;
BEGIN
    SELECT * INTO m FROM operations.computer_merges WHERE id = p_merge FOR UPDATE;
    IF m.id IS NULL THEN
        RAISE EXCEPTION 'split_computer_merge: unknown merge';
    END IF;
    IF m.split_at IS NOT NULL THEN
        RAISE EXCEPTION 'split_computer_merge: this merge was already split';
    END IF;
    IF p_reason IS NULL OR p_reason = '' THEN
        RAISE EXCEPTION 'split_computer_merge: a reason is required';
    END IF;
    PERFORM set_config('operations.tenant_id', m.tenant_id::text, true);
    v_action := operations.begin_change(
        'computer.split', p_reason,
        jsonb_build_object('merge_id', m.id, 'survivor_id', m.survivor_id,
                           'absorbed_id', m.absorbed_id),
        p_actor_kind, p_actor_id, coalesce(p_process, ''), '', m.tenant_id, true);

    UPDATE operations.computer_merges
       SET split_action_id = v_action, split_at = now()
     WHERE id = m.id;
    UPDATE operations.devices
       SET deleted_at = NULL, deleted_reason = ''
     WHERE id = m.absorbed_id;
    -- Only the links this merge moved, and only while still on the survivor;
    -- the one writer moves each back and projects its device_id.
    FOR r IN SELECT link.source_subject_id, link.entity_class_id, s.association_version,
                    absorbed.entity_id AS absorbed_entity
               FROM operations.entity_source_links link
               JOIN operations.source_record_subjects s
                 ON s.tenant_id = link.tenant_id AND s.id = link.source_subject_id
               JOIN operations.devices absorbed ON absorbed.id = m.absorbed_id
               JOIN operations.devices survivor ON survivor.id = m.survivor_id
              WHERE link.tenant_id = m.tenant_id AND link.id = ANY(m.moved_link_ids)
                AND link.entity_id = survivor.entity_id
              ORDER BY link.id LOOP
        PERFORM operations.set_source_association(
            r.source_subject_id, r.absorbed_entity, r.entity_class_id, 'split', 1,
            'split from ' || m.survivor_id::text, r.association_version,
            coalesce(p_actor_kind, 'operator'), p_actor_id, coalesce(p_process, ''),
            jsonb_build_object('merge_id', m.id));
    END LOOP;
    PERFORM operations.retire_entity_relationships(
        m.tenant_id, (SELECT entity_id FROM operations.devices WHERE id = m.survivor_id),
        'computer_split');
    UPDATE operations.findings
       SET subject_id = m.absorbed_id,
           finding_details = (finding_details - 'merge')
               || jsonb_build_object('split', jsonb_build_object(
                      'merge_id', m.id::text, 'back_to_device_id', m.absorbed_id::text))
     WHERE tenant_id = m.tenant_id AND subject_type = 'device'
       AND subject_id = m.survivor_id
       AND id = ANY(m.moved_finding_ids)
       AND finding_details -> 'merge' ->> 'from_device_id' = m.absorbed_id::text;
END
$function$;

CREATE OR REPLACE FUNCTION operations.split_computer_records(p_device uuid, p_observation_ids uuid[], p_reason text, p_actor_id bigint DEFAULT NULL::bigint)
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'operations'
AS $function$
DECLARE
    d operations.devices%ROWTYPE;
    v_keys jsonb;
    v_existing jsonb;
    v_rows integer := 0;
    r record;
BEGIN
    SELECT * INTO d FROM operations.devices WHERE id = p_device AND deleted_at IS NULL FOR UPDATE;
    IF d.id IS NULL THEN
        RAISE EXCEPTION 'split_computer_records: unknown or deleted Computer';
    END IF;
    IF p_reason IS NULL OR p_reason = '' THEN
        RAISE EXCEPTION 'split_computer_records: a reason is required';
    END IF;
    PERFORM set_config('operations.tenant_id', d.tenant_id::text, true);
    SELECT coalesce(jsonb_agg(DISTINCT eo.platform || '|' || eo.entity_key), '[]'::jsonb)
      INTO v_keys
      FROM operations.entity_observation_current eo
     WHERE eo.tenant_id = d.tenant_id AND eo.device_id = d.id
       AND eo.observation_id = ANY(p_observation_ids);
    IF jsonb_array_length(v_keys) = 0 THEN
        RAISE EXCEPTION 'split_computer_records: none of the records belong to this Computer';
    END IF;
    PERFORM operations.begin_change(
        'computer.split_records', p_reason,
        jsonb_build_object('device_id', d.id, 'records', v_keys),
        'operator', p_actor_id, 'operations.ui', '', d.tenant_id, true);

    SELECT value INTO v_existing FROM operations.device_operator_decisions
     WHERE tenant_id = d.tenant_id AND device_id = d.id AND dimension = 'identity_excluded_records';
    INSERT INTO operations.device_operator_decisions
        (id, version, tenant_id, device_id, dimension, value, reason, set_by, set_at)
    VALUES (gen_random_uuid(), 1, d.tenant_id, d.id, 'identity_excluded_records',
            (SELECT jsonb_agg(DISTINCT k) FROM jsonb_array_elements_text(
                 coalesce(v_existing, '[]'::jsonb) || v_keys) AS e(k)),
            p_reason, coalesce('user:' || p_actor_id::text, 'operator'), now())
    ON CONFLICT (tenant_id, device_id, dimension) DO UPDATE
       SET value = EXCLUDED.value, reason = EXCLUDED.reason, set_by = EXCLUDED.set_by,
           set_at = EXCLUDED.set_at, version = operations.device_operator_decisions.version + 1;

    -- Detached records are matched again by the resolver; the decision above
    -- keeps them off this Computer. The one writer clears each association.
    FOR r IN SELECT s.id, s.association_version
               FROM operations.entity_observation_current eo
               JOIN operations.source_record_subjects s
                 ON s.tenant_id = eo.tenant_id AND s.observation_id = eo.observation_id
              WHERE eo.tenant_id = d.tenant_id AND eo.device_id = d.id
                AND eo.observation_id = ANY(p_observation_ids)
              ORDER BY s.id LOOP
        PERFORM operations.set_source_association(
            r.id, NULL, 'device', 'operator_split', 1, p_reason, r.association_version,
            'user', p_actor_id, 'operations.ui', jsonb_build_object('split_from', d.id));
        v_rows := v_rows + 1;
    END LOOP;
    RETURN v_rows;
END
$function$;

CREATE OR REPLACE FUNCTION operations.move_client_source_group_v1(p_tenant_id bigint, p_source_link_id uuid, p_client_id uuid, p_reason text, p_actor_id bigint)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'operations'
AS $function$
DECLARE
    l operations.entity_source_links%ROWTYPE;
    v_from_name text;
    v_to_name text;
    v_observed text;
    v_records integer;
    v_moved integer := 0;
    v_mixed integer := 0;
    v_device uuid;
    v_version bigint;
BEGIN
    IF p_tenant_id <> 1 OR length(btrim(coalesce(p_reason, ''))) NOT BETWEEN 1 AND 400 THEN
        RAISE EXCEPTION 'move_client_source_group: a reason is required';
    END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, true);
    SELECT * INTO l FROM operations.entity_source_links
     WHERE tenant_id = p_tenant_id AND id = p_source_link_id AND entity_class_id = 'client'
       FOR UPDATE;
    IF l.id IS NULL THEN
        RAISE EXCEPTION 'move_client_source_group: unknown client source link';
    END IF;
    IF l.entity_id = p_client_id THEN
        RAISE EXCEPTION 'move_client_source_group: the group already belongs to that client';
    END IF;
    SELECT display_name INTO v_from_name FROM operations.clients WHERE id = l.entity_id;
    SELECT display_name INTO v_to_name FROM operations.clients
     WHERE tenant_id = p_tenant_id AND id = p_client_id AND entity_id = p_client_id
       AND deleted_at IS NULL;
    IF v_to_name IS NULL THEN
        RAISE EXCEPTION 'move_client_source_group: unknown or deleted client';
    END IF;
    PERFORM operations.begin_change(
        'client_mapping.move', p_reason,
        jsonb_build_object('source_link_id', l.id, 'from_client_id', l.entity_id,
                           'to_client_id', p_client_id),
        'operator', p_actor_id, 'operations.ui', '', p_tenant_id, true);

    -- The group's own record, then its device records still on the old client.
    UPDATE operations.entity_observation_current
       SET client_id = p_client_id
     WHERE tenant_id = p_tenant_id AND entity_type = 'org' AND device_id IS NULL
       AND source_instance_id = l.source_instance_id
       AND external_namespace = l.external_namespace
       AND parent_external_namespace = l.parent_external_namespace
       AND parent_external_id = l.parent_external_id
       AND external_id = l.external_id;
    SELECT canonical_data ->> 'name' INTO v_observed
      FROM operations.entity_observation_current
     WHERE tenant_id = p_tenant_id AND entity_type = 'org'
       AND source_instance_id = l.source_instance_id AND external_id = l.external_id
     ORDER BY observed_at DESC LIMIT 1;
    UPDATE operations.entity_observation_current
       SET client_id = p_client_id
     WHERE tenant_id = p_tenant_id AND entity_type <> 'org'
       AND source_instance_id = l.source_instance_id
       AND canonical_data ->> 'platform_group_id' = l.external_id
       AND client_id = l.entity_id;
    GET DIAGNOSTICS v_records = ROW_COUNT;

    -- The group record's mapping is its confirmed association (Stage B).
    SELECT association_version INTO v_version FROM operations.source_record_subjects
     WHERE tenant_id = p_tenant_id AND id = l.source_subject_id;
    PERFORM operations.set_source_association(
        l.source_subject_id, p_client_id, 'client', 'operator', 1,
        'operator.client_mapping_move', v_version, 'user', p_actor_id, 'operations.ui',
        jsonb_build_object('moved_from_client_id', l.entity_id, 'reason', left(p_reason, 400)));

    -- A link keeps its id when its client changes: the old decision must not carry over.
    PERFORM operations.decide_client_source_mapping_v1(
        p_tenant_id, l.id, 'explicit',
        left(format('Moved from %s to %s: %s', v_from_name, v_to_name, btrim(p_reason)), 500),
        p_actor_id);

    -- The alias that sent this name to the old client would send the next group there too.
    UPDATE operations.client_name_aliases
       SET client_id = p_client_id, version = version + 1
     WHERE tenant_id = p_tenant_id AND client_id = l.entity_id AND enabled
       AND normalized_name = regexp_replace(lower(coalesce(v_observed, '')), '[\s\-_.]', '', 'g');

    -- Computers follow their records (ADR-0040 decision 3).
    FOR v_device IN
        SELECT DISTINCT o.device_id
          FROM operations.entity_observation_current o
          JOIN operations.devices d ON d.id = o.device_id AND d.deleted_at IS NULL
         WHERE o.tenant_id = p_tenant_id AND o.active AND o.entity_type <> 'org'
           AND o.source_instance_id = l.source_instance_id
           AND o.canonical_data ->> 'platform_group_id' = l.external_id
           AND d.client_id <> p_client_id
    LOOP
        IF EXISTS (SELECT 1 FROM operations.entity_observation_current o
                    WHERE o.tenant_id = p_tenant_id AND o.device_id = v_device AND o.active
                      AND o.client_id IS DISTINCT FROM p_client_id
                      AND o.client_id IS NOT NULL) THEN
            v_mixed := v_mixed + 1;
        ELSE
            PERFORM operations.move_computer_to_client(v_device, p_client_id, p_reason, p_actor_id);
            v_moved := v_moved + 1;
        END IF;
    END LOOP;
    RETURN jsonb_build_object('records', v_records, 'computers_moved', v_moved,
                              'computers_mixed', v_mixed, 'to_client', v_to_name);
END
$function$;
"""

GUARDS_SQL = r"""
CREATE FUNCTION operations.guard_device_projection() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, operations
AS $fn$
BEGIN
    IF session_user = 'operations_migrate'
       OR current_setting('operations.association_writer', true) = 'on' THEN
        RETURN NEW;
    END IF;
    IF (TG_OP = 'INSERT' AND NEW.device_id IS NOT NULL)
       OR (TG_OP = 'UPDATE' AND NEW.device_id IS DISTINCT FROM OLD.device_id) THEN
        RAISE EXCEPTION 'entity_observation_current.device_id is projected from its confirmed '
                        'link; use operations.set_source_association (PLAN-004 Stage B)';
    END IF;
    RETURN NEW;
END
$fn$;
CREATE TRIGGER guard_device_projection
    BEFORE INSERT OR UPDATE OF device_id ON operations.entity_observation_current
    FOR EACH ROW EXECUTE FUNCTION operations.guard_device_projection();

CREATE FUNCTION operations.guard_source_link_writes() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, operations
AS $fn$
BEGIN
    IF session_user = 'operations_migrate'
       OR current_setting('operations.association_writer', true) = 'on' THEN
        RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END IF;
    IF TG_TABLE_NAME = 'entity_source_links' AND TG_OP = 'UPDATE'
       AND current_setting('operations.link_presence_writer', true) = 'on'
       AND (NEW.entity_id, NEW.entity_class_id, NEW.match_method, NEW.match_confidence,
            NEW.source_subject_id, NEW.association_version)
           IS NOT DISTINCT FROM
           (OLD.entity_id, OLD.entity_class_id, OLD.match_method, OLD.match_confidence,
            OLD.source_subject_id, OLD.association_version) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION '% on operations.% is reserved to operations.set_source_association '
                    '(presence-only link updates: the presence entrypoints)', TG_OP, TG_TABLE_NAME;
END
$fn$;
CREATE TRIGGER guard_source_link_writes
    BEFORE INSERT OR UPDATE OR DELETE ON operations.entity_source_links
    FOR EACH ROW EXECUTE FUNCTION operations.guard_source_link_writes();
CREATE TRIGGER guard_source_link_writes
    BEFORE INSERT OR UPDATE OR DELETE ON operations.entity_source_link_history
    FOR EACH ROW EXECUTE FUNCTION operations.guard_source_link_writes();

-- Belt and braces: at commit, a projected device_id must equal its device link.
CREATE FUNCTION operations.check_device_projection() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_device uuid;
BEGIN
    SELECT d.id INTO v_device
      FROM operations.entity_observation_current o
      JOIN operations.entity_source_links l
        ON l.tenant_id = o.tenant_id AND l.source_instance_id = o.source_instance_id
       AND l.external_namespace = o.external_namespace
       AND l.parent_external_namespace = o.parent_external_namespace
       AND l.parent_external_id = o.parent_external_id
       AND l.external_id = o.external_id AND l.entity_class_id = 'device'
      JOIN operations.devices d ON d.tenant_id = l.tenant_id AND d.entity_id = l.entity_id
     WHERE o.tenant_id = NEW.tenant_id AND o.observation_id = NEW.observation_id;
    IF (SELECT device_id FROM operations.entity_observation_current
         WHERE tenant_id = NEW.tenant_id AND observation_id = NEW.observation_id)
       IS DISTINCT FROM v_device THEN
        RAISE EXCEPTION 'observation % device_id differs from its confirmed link', NEW.observation_id;
    END IF;
    RETURN NULL;
END
$fn$;
CREATE CONSTRAINT TRIGGER check_device_projection
    AFTER INSERT OR UPDATE OF device_id ON operations.entity_observation_current
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION operations.check_device_projection();

REVOKE ALL ON FUNCTION
    operations.set_source_association(uuid, uuid, text, text, numeric, text, bigint, text, bigint, text, jsonb),
    operations.set_source_association_by_key(bigint, uuid, text, text, text, text, uuid, text, text, text, text, bigint, text, jsonb, boolean),
    operations.associate_record(bigint, uuid, text, text, text, text, uuid, text, text, boolean),
    operations.associate_observation(bigint, uuid, uuid, text, text, boolean),
    operations.associate_unassociated_records(bigint, text, text, uuid, text, text),
    operations.mark_source_links_missing(bigint, uuid, jsonb, timestamptz),
    operations.guard_device_projection(), operations.guard_source_link_writes(),
    operations.check_device_projection()
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    operations.set_source_association(uuid, uuid, text, text, numeric, text, bigint, text, bigint, text, jsonb),
    operations.set_source_association_by_key(bigint, uuid, text, text, text, text, uuid, text, text, text, text, bigint, text, jsonb, boolean)
    TO operations_app, ninja_ingest;
GRANT EXECUTE ON FUNCTION
    operations.associate_record(bigint, uuid, text, text, text, text, uuid, text, text, boolean),
    operations.associate_observation(bigint, uuid, uuid, text, text, boolean),
    operations.associate_unassociated_records(bigint, text, text, uuid, text, text),
    operations.mark_source_links_missing(bigint, uuid, jsonb, timestamptz)
    TO ninja_ingest;
-- Version boundary: processes built for contract 4 stop at their next findings
-- write, and the new ingest and Jobs worker wait for 5 before admitting work.
UPDATE operations.finding_contract SET version = 5, published_at = now();
-- Direct runtime DML on the authority and its history is not granted (§2.1);
-- the triggers above also bind superuser connections.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
    ON operations.entity_source_links, operations.entity_source_link_history
    FROM operations_app, ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0373_source_record_cases"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL + CONVERTED_SQL + GUARDS_SQL, migrations.RunSQL.noop),
    ]
