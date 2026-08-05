"""Device compatibility-cache projector.

Sole writer of the source-derived cache columns on `operations.devices`.
Per ADR-0012 no evidence producer — connector, resolver, evaluator or UI
action — may write these; they are projected here from the generic
effective-value contract and nowhere else.

    os_name, os_family  <- effective attributes of the same name
    os_group            <- derived from os_family via operations.os_group_mappings
    device_role         <- effective attribute
    device_type         <- derived; see below

## Why device_type is derived rather than mapped

There is deliberately no `form_factor` attribute definition, and adding one
would be wrong. No source *states* form factor. Ninja supplies `nodeClass`;
the reading that `NMS_` means a network device is ours, not Ninja's. Recording
that inference as a source claim would make our interpretation look like
evidence, which is precisely the defect ADR-0005 exists to prevent.

So form factor is computed here from three asset-nature signals, mirroring
`_infer_form_factor` in `ingest/identity/resolver.py` exactly:

    network.device  OR node_class starts 'NMS_'                  -> network-device
    vm.host         OR node_class ends '_VM_HOST' / '_VMM_HOST'  -> hypervisor-host
    vm.guest        OR is_virtual_machine                        -> vm
    otherwise                                                    -> unknown

**Agent presence is not evidence of form factor.** An `agent.*` observation
says an OS is being managed, not that hardware is physical. `unknown` is a
legitimate value and positive asset-nature evidence is required to leave it
(ADR-0005). Note the derivation reads only entity *types* and two mapped
attributes — never the presence of an agent.

## Absence handling

Where the effective contract has no selected value, the existing cache value
is retained rather than blanked. Roughly 75 devices currently have no
effective `os_family`, and clearing them would discard a usable label to
represent "we have no claim right now". The effective contract remains the
authority for consumers that need to distinguish `unknown` from `no_evidence`;
these columns are compatibility caches, not that authority.

Deterministic and rebuildable: drop the column values and re-run.
"""

from __future__ import annotations

import logging

from ingest import db

log = logging.getLogger(__name__)

TENANT_ID = 1

# Shared by the dry-run preview and the write. Produces one target row per
# device that has an entity anchor, with every cache column resolved.
_TARGET_SQL = """
WITH eff AS (
    SELECT e.entity_id, ad.key, e.value_text, e.value_boolean
      FROM operations.entity_attribute_effective_current e
      JOIN operations.attribute_definitions ad
        ON ad.id = e.attribute_definition_id
     WHERE e.tenant_id = %(tenant)s
       AND e.status = 'selected'
       AND ad.key IN ('os_name', 'os_family', 'device_role',
                      'node_class', 'is_virtual_machine')
),
pivot AS (
    SELECT entity_id,
           max(value_text) FILTER (WHERE key = 'os_name')     AS os_name,
           max(value_text) FILTER (WHERE key = 'os_family')   AS os_family,
           max(value_text) FILTER (WHERE key = 'device_role') AS device_role,
           upper(max(value_text) FILTER (WHERE key = 'node_class')) AS node_class,
           bool_or(value_boolean) FILTER (WHERE key = 'is_virtual_machine') AS is_vm,
           -- ADR-0012 section 6: the node_class taxonomy is data, not inline
           -- left()/right() tests. NULL where the class implies no form
           -- factor, which is every agent.* class (ADR-0005).
           (SELECT NULLIF(m.form_factor, '')
              FROM operations.node_class_mappings m
             WHERE upper(max(value_text) FILTER (WHERE key = 'node_class'))
                   LIKE m.pattern
             ORDER BY m.priority, m.id
             LIMIT 1) AS node_class_form_factor
      FROM eff
     GROUP BY entity_id
),
-- Asset-nature signals only. Agent presence is deliberately absent.
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
     WHERE l.tenant_id = %(tenant)s
       AND l.missing_since IS NULL
     GROUP BY l.entity_id
)
SELECT d.id AS device_id,
       COALESCE(p.os_name,     d.os_name)     AS os_name,
       COALESCE(p.os_family,   d.os_family)   AS os_family,
       COALESCE(
           (SELECT g.os_group
              FROM operations.os_group_mappings g
             WHERE COALESCE(p.os_family, d.os_family) LIKE g.pattern
             ORDER BY g.priority, g.pattern
             LIMIT 1),
           d.os_group, 'Unknown'
       ) AS os_group,
       COALESCE(p.device_role, d.device_role, 'unknown') AS device_role,
       CASE
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
           -- Retain a known form factor when no asset-nature evidence is
           -- currently selected. Measured 2026-08-05 against production: 33
           -- devices have a known device_type with neither an asset-nature
           -- observation nor a selected is_virtual_machine claim, so projecting
           -- 'unknown' would downgrade them on a mapping gap rather than on
           -- evidence. The gap is reported as device_type_evidence_missing.
           WHEN COALESCE(d.device_type, 'unknown') <> 'unknown'
               THEN d.device_type
           ELSE 'unknown'
       END AS device_type,
       -- Exposed so the evidence-gap counter can tell "form factor is backed
       -- by an entity type" from "form factor is backed by nothing".
       COALESCE(t.has_network, false)
         OR COALESCE(t.has_vm_host, false)
         OR COALESCE(t.has_vm_guest, false) AS has_asset_nature
  FROM operations.devices d
  LEFT JOIN pivot p ON p.entity_id = d.entity_id
  LEFT JOIN types t ON t.entity_id = d.entity_id
 WHERE d.tenant_id = %(tenant)s
   AND d.deleted_at IS NULL
   AND d.entity_id IS NOT NULL
"""

_CHANGED_PREDICATE = """
       t.os_name     IS DISTINCT FROM d.os_name
    OR t.os_family   IS DISTINCT FROM d.os_family
    OR t.os_group    IS DISTINCT FROM d.os_group
    OR t.device_role IS DISTINCT FROM d.device_role
    OR t.device_type IS DISTINCT FROM d.device_type
"""


def project(*, dry_run: bool = True, tenant_id: int = TENANT_ID) -> dict[str, int]:
    """Project cache columns from the effective contract.

    Returns per-column change counts. Default is dry-run: nothing is written
    unless `dry_run=False` is passed.
    """
    params = {"tenant": tenant_id}
    with db.transaction() as cur:
        cur.execute(f"SET LOCAL operations.tenant_id = {int(tenant_id)}")

        cur.execute(
            f"""
            WITH target AS ({_TARGET_SQL})
            SELECT
                count(*) FILTER (WHERE t.os_name     IS DISTINCT FROM d.os_name),
                count(*) FILTER (WHERE t.os_family   IS DISTINCT FROM d.os_family),
                count(*) FILTER (WHERE t.os_group    IS DISTINCT FROM d.os_group),
                count(*) FILTER (WHERE t.device_role IS DISTINCT FROM d.device_role),
                count(*) FILTER (WHERE t.device_type IS DISTINCT FROM d.device_type),
                count(*) FILTER (
                    WHERE d.device_type <> 'unknown' AND t.device_type = d.device_type
                      -- A form factor backed by a vm.guest / vm.host /
                      -- network.device observation IS evidenced; it just is not
                      -- evidenced by an is_virtual_machine claim. Without this
                      -- the counter reported 379 where the real gap was 33,
                      -- and 346 correctly-evidenced devices looked broken.
                      AND NOT t.has_asset_nature
                      AND NOT EXISTS (
                          SELECT 1 FROM operations.entity_attribute_effective_current e2
                          JOIN operations.attribute_definitions a2
                            ON a2.id = e2.attribute_definition_id
                         WHERE e2.entity_id = d.entity_id
                           AND e2.status = 'selected'
                           AND a2.key = 'is_virtual_machine'
                      )
                ),
                count(*)
              FROM target t
              JOIN operations.devices d ON d.id = t.device_id
            """,
            params,
        )
        (
            os_name, os_family, os_group, device_role,
            device_type, evidence_missing, considered,
        ) = cur.fetchone()
        counts = {
            "considered": considered,
            "os_name": os_name,
            "os_family": os_family,
            "os_group": os_group,
            "device_role": device_role,
            "device_type": device_type,
            # Known form factor retained because no effective claim backs it —
            # a mapping gap to close, surfaced rather than silently absorbed.
            "device_type_evidence_missing": evidence_missing,
            "rows_written": 0,
        }

        if not dry_run:
            cur.execute(
                f"""
                WITH target AS ({_TARGET_SQL})
                UPDATE operations.devices d
                   SET os_name        = t.os_name,
                       os_family      = t.os_family,
                       os_group       = t.os_group,
                       device_role    = t.device_role,
                       device_type    = t.device_type,
                       updated_at     = now(),
                       updated_reason = 'device cache projection'
                  FROM target t
                 WHERE d.id = t.device_id
                   AND ({_CHANGED_PREDICATE})
                """,
                params,
            )
            counts["rows_written"] = cur.rowcount or 0

    log.info("device cache projection: %s (dry_run=%s)", counts, dry_run)
    return counts
