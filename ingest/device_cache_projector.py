"""Device compatibility-cache projector.

Sole writer of the source-derived cache columns on `operations.devices`.
The Computer name is not one of them: identity names Computers through
``operations.write_computer_names`` (ADR-0034).
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

# The target rule described above lives in the database (migration 0400:
# ``device_cache_targets`` and ``project_device_cache``), so this cycle-wide
# projection and the association refresh share one copy (PLAN-012 item 4).
_TARGET_SQL = "SELECT * FROM operations.device_cache_targets(%(tenant)s, NULL)"


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
                "SELECT operations.project_device_cache(%(tenant)s, NULL)", params
            )
            counts["rows_written"] = cur.fetchone()[0] or 0

    log.info("device cache projection: %s (dry_run=%s)", counts, dry_run)
    return counts
