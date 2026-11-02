"""An association change refreshes the values it changed (PLAN-012 item 4).

Claims are keyed by record but carry a copy of the record's entity, refreshed
only by the periodic claim projector. Since 0374 the association changes at
once in ``set_source_association``, so a new or merged Computer kept stale or
placeholder OS/role values (``os_group = 'Unknown'``) until the next
collection, and platform evaluation opened ``os_unknown_coverage`` for it.

This migration reuses the existing projectors, scoped, and runs them from the
association procedure in the same transaction:

* ``sync_entity_attribute_claims_from_observations(integer, uuid[])`` and
  ``sync_entity_attribute_effective(integer, uuid[])`` are the current bodies
  (0397 and 0108) with one scope filter. The one-argument functions become
  wrappers, so ingest callers and grants are unchanged.
* ``device_cache_targets`` / ``project_device_cache`` move the
  ``ingest.device_cache_projector`` target SQL into the database, so the
  procedure and the resolver share one rule.
* ``refresh_association_values`` runs claims -> effective -> cache for one
  record (and its companions), its old and new entity, and their Computers.
* ``set_source_association`` calls it after a real change.

Both projectors take a try-advisory-lock. When the periodic projector holds
it, the refresh is deferred to the next collection (today's behavior) with a
database warning; it never waits, so it cannot deadlock with a periodic batch.
Functions only: no table, index, or data change.
"""

from __future__ import annotations

import importlib
from typing import ClassVar

from django.db import migrations


def _between(sql: str, start: str, end: str) -> str:
    begin = sql.index(start)
    finish = sql.index(end, begin) + len(end)
    return sql[begin:finish]


def _replace_once(text: str, old: str, new: str, what: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"{what} text changed; cannot place: {old.strip()[:60]}")
    return text.replace(old, new)


def _claims_function() -> str:
    """0397's claim projector with an observation scope."""
    function = importlib.import_module(
        "apps.core.migrations.0397_source_record_companions"
    )._projector_sql()
    function = _replace_once(
        function,
        "operations.sync_entity_attribute_claims_from_observations(\n"
        "    batch_size integer DEFAULT 500\n)",
        "operations.sync_entity_attribute_claims_from_observations(\n"
        "    batch_size integer,\n    p_observation_ids uuid[]\n)",
        "claim projector header",
    )
    return _replace_once(
        function,
        "        LEFT JOIN entity_types entity_type ON entity_type.name = o.entity_type\n"
        "    )\n",
        "        LEFT JOIN entity_types entity_type ON entity_type.name = o.entity_type\n"
        "        WHERE p_observation_ids IS NULL OR o.observation_id = ANY(p_observation_ids)\n"
        "    )\n",
        "claim projector candidates",
    )


def _effective_function() -> str:
    """0108's effective projector with an entity scope."""
    sql = importlib.import_module(
        "apps.core.migrations.0108_attribute_effective_projection"
    ).PROJECTOR_SQL
    function = _between(
        sql,
        "CREATE OR REPLACE FUNCTION operations.sync_entity_attribute_effective(",
        "$function$;",
    )
    function = _replace_once(
        function,
        "operations.sync_entity_attribute_effective(batch_size integer DEFAULT 500)",
        "operations.sync_entity_attribute_effective(batch_size integer, p_entity_ids uuid[])",
        "effective projector header",
    )
    return (
        _replace_once(
            function,
            "    ) signatures ON TRUE\n    ORDER BY dirty.queued_at, dirty.id\n",
            "    ) signatures ON TRUE\n"
            "    WHERE p_entity_ids IS NULL OR dirty.entity_id = ANY(p_entity_ids)\n"
            "    ORDER BY dirty.queued_at, dirty.id\n",
            "effective projector batch",
        )
        + "\n"
    )


def _association_function(*, refresh: bool) -> str:
    """0374's ``set_source_association``, optionally refreshing values."""
    sql = importlib.import_module(
        "apps.core.migrations.0374_source_association_authority"
    ).FORWARD_SQL
    function = _between(sql, "CREATE FUNCTION operations.set_source_association(\n", "$fn$;")
    function = function.replace(
        "CREATE FUNCTION operations.set_source_association(",
        "CREATE OR REPLACE FUNCTION operations.set_source_association(",
        1,
    )
    if refresh:
        function = _replace_once(
            function,
            "    PERFORM set_config('operations.association_writer', '', true);\n"
            "    RETURN v_version;\n",
            "    PERFORM set_config('operations.association_writer', '', true);\n"
            "    -- PLAN-012 item 4: the values this change moved are refreshed now.\n"
            "    PERFORM operations.refresh_association_values(\n"
            "        v_tenant, s.id, ARRAY[l.entity_id, p_entity]);\n"
            "    RETURN v_version;\n",
            "set_source_association tail",
        )
    return function + "\n"


WRAPPERS_SQL = r"""
CREATE OR REPLACE FUNCTION operations.sync_entity_attribute_claims_from_observations(
    batch_size integer DEFAULT 500
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = operations, pg_temp
AS $function$
BEGIN
    RETURN operations.sync_entity_attribute_claims_from_observations(batch_size, NULL::uuid[]);
END;
$function$;

CREATE OR REPLACE FUNCTION operations.sync_entity_attribute_effective(
    batch_size integer DEFAULT 500
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = operations, pg_temp
AS $function$
BEGIN
    RETURN operations.sync_entity_attribute_effective(batch_size, NULL::uuid[]);
END;
$function$;
"""

# ``ingest.device_cache_projector._TARGET_SQL`` with ``%(tenant)s`` as
# ``p_tenant`` and an optional Computer scope. Keep the two identical until
# the Python fallback is removed.
CACHE_SQL = r"""
CREATE FUNCTION operations.device_cache_targets(p_tenant bigint, p_device_ids uuid[])
RETURNS TABLE (
    device_id uuid, os_name text, os_family text, os_group text,
    device_role text, device_type text, has_asset_nature boolean
)
LANGUAGE sql
STABLE
SET search_path = pg_catalog, operations
AS $function$
WITH scope AS (
    SELECT d.entity_id
      FROM operations.devices d
     WHERE d.tenant_id = p_tenant AND d.id = ANY(p_device_ids)
),
eff AS (
    SELECT e.entity_id, ad.key, e.value_text, e.value_boolean
      FROM operations.entity_attribute_effective_current e
      JOIN operations.attribute_definitions ad
        ON ad.id = e.attribute_definition_id
     WHERE e.tenant_id = p_tenant
       AND e.status = 'selected'
       AND ad.key IN ('os_name', 'os_family', 'device_role',
                      'node_class', 'is_virtual_machine')
       AND (p_device_ids IS NULL OR e.entity_id IN (SELECT entity_id FROM scope))
),
pivot AS (
    SELECT entity_id,
           max(value_text) FILTER (WHERE key = 'os_name')     AS os_name,
           max(value_text) FILTER (WHERE key = 'os_family')   AS os_family,
           max(value_text) FILTER (WHERE key = 'device_role') AS device_role,
           upper(max(value_text) FILTER (WHERE key = 'node_class')) AS node_class,
           bool_or(value_boolean) FILTER (WHERE key = 'is_virtual_machine') AS is_vm,
           (SELECT NULLIF(m.form_factor, '')
              FROM operations.node_class_mappings m
             WHERE upper(max(value_text) FILTER (WHERE key = 'node_class'))
                   LIKE m.pattern
             ORDER BY m.priority, m.id
             LIMIT 1) AS node_class_form_factor
      FROM eff
     GROUP BY entity_id
),
types AS (
    SELECT l.entity_id,
           bool_or(o.entity_type = 'network.device') AS has_network,
           bool_or(o.entity_type = 'vm.host')        AS has_vm_host,
           bool_or(o.entity_type = 'vm.guest')       AS has_vm_guest
      FROM operations.entity_source_links l
      JOIN operations.entity_observation_current o
        ON o.tenant_id          = l.tenant_id
       AND o.source_instance_id = l.source_instance_id
       AND o.external_namespace = l.external_namespace
       AND o.external_id        = l.external_id
     WHERE l.tenant_id = p_tenant
       AND l.missing_since IS NULL
       AND (p_device_ids IS NULL OR l.entity_id IN (SELECT entity_id FROM scope))
     GROUP BY l.entity_id
)
SELECT d.id,
       COALESCE(p.os_name,     d.os_name)::text,
       COALESCE(p.os_family,   d.os_family)::text,
       COALESCE(
           (SELECT g.os_group
              FROM operations.os_group_mappings g
             WHERE COALESCE(p.os_family, d.os_family) LIKE g.pattern
             ORDER BY g.priority, g.pattern
             LIMIT 1),
           d.os_group, 'Unknown'
       )::text,
       COALESCE(p.device_role, d.device_role, 'unknown')::text,
       (CASE
           WHEN COALESCE(t.has_network, false)
             OR p.node_class_form_factor = 'network-device'
               THEN 'network-device'
           WHEN COALESCE(t.has_vm_host, false)
             OR p.node_class_form_factor = 'hypervisor-host'
               THEN 'hypervisor-host'
           WHEN COALESCE(t.has_vm_guest, false)
             OR p.node_class_form_factor = 'vm'
             OR COALESCE(p.is_vm, false)
               THEN 'vm'
           WHEN COALESCE(d.device_type, 'unknown') <> 'unknown'
               THEN d.device_type
           ELSE 'unknown'
       END)::text,
       COALESCE(t.has_network, false)
         OR COALESCE(t.has_vm_host, false)
         OR COALESCE(t.has_vm_guest, false)
  FROM operations.devices d
  LEFT JOIN pivot p ON p.entity_id = d.entity_id
  LEFT JOIN types t ON t.entity_id = d.entity_id
 WHERE d.tenant_id = p_tenant
   AND d.deleted_at IS NULL
   AND d.entity_id IS NOT NULL
   AND (p_device_ids IS NULL OR d.id = ANY(p_device_ids))
$function$;

-- The one writer of the five cache columns (ADR-0012), callable for the
-- whole fleet (NULL) or for the Computers an association change touched.
CREATE FUNCTION operations.project_device_cache(p_tenant bigint, p_device_ids uuid[])
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE
    written integer;
BEGIN
    UPDATE operations.devices d
       SET os_name        = t.os_name,
           os_family      = t.os_family,
           os_group       = t.os_group,
           device_role    = t.device_role,
           device_type    = t.device_type,
           updated_at     = now(),
           updated_reason = 'device cache projection'
      FROM operations.device_cache_targets(p_tenant, p_device_ids) t
     WHERE d.id = t.device_id
       AND (t.os_name     IS DISTINCT FROM d.os_name
         OR t.os_family   IS DISTINCT FROM d.os_family
         OR t.os_group    IS DISTINCT FROM d.os_group
         OR t.device_role IS DISTINCT FROM d.device_role
         OR t.device_type IS DISTINCT FROM d.device_type);
    GET DIAGNOSTICS written = ROW_COUNT;
    RETURN written;
END
$function$;

CREATE FUNCTION operations.refresh_association_values(
    p_tenant bigint, p_subject uuid, p_entities uuid[]
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE
    v_observations uuid[];
    v_entities uuid[];
    v_claims jsonb;
    v_effective jsonb;
    v_devices integer;
BEGIN
    SELECT array_agg(DISTINCT e) INTO v_entities
      FROM unnest(p_entities) e WHERE e IS NOT NULL;
    SELECT array_agg(observation_id) INTO v_observations
      FROM (
          SELECT s.observation_id FROM operations.source_record_subjects s
           WHERE s.tenant_id = p_tenant AND s.id = p_subject
             AND s.observation_id IS NOT NULL
          UNION
          SELECT c.observation_id FROM operations.source_record_companions c
           WHERE c.tenant_id = p_tenant AND c.owner_subject_id = p_subject
      ) records;
    IF v_observations IS NULL OR v_entities IS NULL THEN
        RETURN jsonb_build_object('status', 'nothing_to_refresh');
    END IF;

    v_claims := operations.sync_entity_attribute_claims_from_observations(
        10000, v_observations);
    IF v_claims->>'status' = 'busy' THEN
        RAISE WARNING 'association value refresh deferred (claims busy) for subject %',
                      p_subject;
        RETURN jsonb_build_object('status', 'deferred', 'stage', 'claims');
    END IF;
    v_effective := operations.sync_entity_attribute_effective(5000, v_entities);
    IF v_effective->>'status' = 'busy' THEN
        RAISE WARNING 'association value refresh deferred (effective busy) for subject %',
                      p_subject;
        RETURN jsonb_build_object('status', 'deferred', 'stage', 'effective');
    END IF;
    v_devices := operations.project_device_cache(
        p_tenant,
        ARRAY(SELECT d.id FROM operations.devices d
               WHERE d.tenant_id = p_tenant AND d.entity_id = ANY(v_entities)
                 AND d.deleted_at IS NULL));
    RETURN jsonb_build_object(
        'status', 'complete', 'claims', v_claims, 'effective', v_effective,
        'devices_written', v_devices);
END
$function$;
"""

SECURITY_SQL = r"""
REVOKE ALL ON FUNCTION operations.sync_entity_attribute_claims_from_observations(integer, uuid[])
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.sync_entity_attribute_claims_from_observations(integer, uuid[])
    TO ninja_ingest;
REVOKE ALL ON FUNCTION operations.sync_entity_attribute_effective(integer, uuid[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.sync_entity_attribute_effective(integer, uuid[])
    TO ninja_ingest, operations_app;
ALTER FUNCTION operations.sync_entity_attribute_effective(integer, uuid[])
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.device_cache_targets(bigint, uuid[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.device_cache_targets(bigint, uuid[]) TO ninja_ingest;
REVOKE ALL ON FUNCTION operations.project_device_cache(bigint, uuid[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.project_device_cache(bigint, uuid[]) TO ninja_ingest;
REVOKE ALL ON FUNCTION operations.refresh_association_values(bigint, uuid, uuid[]) FROM PUBLIC;
"""

REVERSE_SQL = r"""
DROP FUNCTION operations.refresh_association_values(bigint, uuid, uuid[]);
DROP FUNCTION operations.project_device_cache(bigint, uuid[]);
DROP FUNCTION operations.device_cache_targets(bigint, uuid[]);
"""


def _forward() -> str:
    return (
        _claims_function()
        + _effective_function()
        + WRAPPERS_SQL
        + CACHE_SQL
        + _association_function(refresh=True)
        + SECURITY_SQL
    )


def _reverse() -> str:
    # Restore the 0374 procedure first (it calls the dropped refresh), then the
    # 0397/0108 one-argument bodies, then drop the scoped variants.
    claims = importlib.import_module(
        "apps.core.migrations.0397_source_record_companions"
    )._projector_sql()
    effective = _between(
        importlib.import_module(
            "apps.core.migrations.0108_attribute_effective_projection"
        ).PROJECTOR_SQL,
        "CREATE OR REPLACE FUNCTION operations.sync_entity_attribute_effective(",
        "$function$;",
    )
    return (
        _association_function(refresh=False)
        + REVERSE_SQL
        + claims
        + effective
        + "\n"
        + "DROP FUNCTION operations.sync_entity_attribute_claims_from_observations(integer, uuid[]);\n"
        + "DROP FUNCTION operations.sync_entity_attribute_effective(integer, uuid[]);\n"
    )


class Migration(migrations.Migration):
    dependencies: ClassVar = [
        ("operations", "0399_close_legacy_activity_queue_finding"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(_forward(), _reverse()),
    ]
