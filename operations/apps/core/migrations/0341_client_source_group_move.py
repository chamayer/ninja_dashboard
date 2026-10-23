"""Record automatic client mappings and move a source group (ADR-0040 decisions 1-2).

* ``operations.record_automatic_client_mapping_v1``: the resolver records why a
  source group joined its client (``state = 'automatic'``,
  ``provenance = 'resolver'``). It writes only when the link has no current
  decision, so it never overrides an operator.
* ``operations.move_client_source_group_v1``: moves a source group to another
  client. Collectors take a group's client from its link
  (``v_client_source_link``), so the link moves now, with its history, rather
  than at the next link sync; otherwise the next collection would put the
  group back. It also
  - moves the group's org record and its device records still on the old
    client;
  - records an operator decision naming both clients (a link keeps its id
    when its client changes, so the old decision must not carry over);
  - repoints the enabled name alias that sent this name to the old client;
  - moves each Computer whose active records now all belong to the new
    client (``move_computer_to_client``); a Computer left with records on two
    clients is raised by ``computer_client_conflict`` on the next evaluation.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION operations.record_automatic_client_mapping_v1(
    p_tenant_id bigint,
    p_source_link_id uuid,
    p_reason text
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
BEGIN
    IF p_tenant_id <> 1
       OR length(btrim(coalesce(p_reason, ''))) NOT BETWEEN 1 AND 500
       OR NOT EXISTS (SELECT 1 FROM operations.v_client_source_link
                       WHERE tenant_id = p_tenant_id AND id = p_source_link_id) THEN
        RAISE EXCEPTION 'Invalid automatic client mapping';
    END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, true);
    IF EXISTS (SELECT 1 FROM operations.client_source_mapping_decisions
                WHERE tenant_id = p_tenant_id AND source_link_id = p_source_link_id
                  AND superseded_at IS NULL) THEN
        RETURN false;
    END IF;
    INSERT INTO operations.client_source_mapping_decisions
        (tenant_id, source_link_id, state, provenance, reason)
    VALUES (p_tenant_id, p_source_link_id, 'automatic', 'resolver', btrim(p_reason));
    RETURN true;
END
$fn$;

CREATE FUNCTION operations.move_client_source_group_v1(
    p_tenant_id bigint,
    p_source_link_id uuid,
    p_client_id uuid,
    p_reason text,
    p_actor_id bigint
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    l operations.entity_source_links%ROWTYPE;
    v_from_name text;
    v_to_name text;
    v_observed text;
    v_records integer;
    v_moved integer := 0;
    v_mixed integer := 0;
    v_device uuid;
    v_now timestamptz := clock_timestamp();
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

    -- The link moves now, with its history, as the link sync would record it.
    UPDATE operations.entity_source_link_history
       SET effective_to = GREATEST(v_now, effective_from + interval '1 microsecond')
     WHERE tenant_id = p_tenant_id AND source_instance_id = l.source_instance_id
       AND external_namespace = l.external_namespace
       AND parent_external_namespace = l.parent_external_namespace
       AND parent_external_id = l.parent_external_id
       AND external_id = l.external_id AND effective_to IS NULL;
    UPDATE operations.entity_source_links
       SET entity_id = p_client_id, match_method = 'operator', match_confidence = 1,
           reason = 'operator.client_mapping_move', version = version + 1
     WHERE id = l.id;
    INSERT INTO operations.entity_source_link_history (
        id, tenant_id, version, entity_id, entity_class_id, source_instance_id,
        last_seen_binding_id, external_namespace, parent_external_namespace,
        parent_external_id, external_id, match_method, match_confidence, actor_kind,
        actor_id, actor_process, reason, evidence, effective_from, effective_to)
    VALUES (gen_random_uuid(), p_tenant_id, 1, p_client_id, 'client', l.source_instance_id,
            l.last_seen_binding_id, l.external_namespace, l.parent_external_namespace,
            l.parent_external_id, l.external_id, 'operator', 1, 'user', p_actor_id,
            'operations.ui', left(p_reason, 240),
            jsonb_build_object('moved_from_client_id', l.entity_id), v_now, NULL);

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
$fn$;

REVOKE ALL ON FUNCTION operations.record_automatic_client_mapping_v1(bigint, uuid, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.record_automatic_client_mapping_v1(bigint, uuid, text)
    TO ninja_ingest;
REVOKE ALL ON FUNCTION operations.move_client_source_group_v1(bigint, uuid, uuid, text, bigint)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.move_client_source_group_v1(bigint, uuid, uuid, text, bigint)
    TO operations_app;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0340_computer_client_conflict"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
