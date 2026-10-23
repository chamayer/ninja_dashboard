"""Capability inputs for the software findings run.

The data that decides whether software with an alertable capability (remote
access, RMM, endpoint security) is permitted at a client: the effective
product capabilities, operator authorizations, and the products a client's
required platforms sanction. Moved here from the retired per-installation
classifier (``ingest/software_findings.py``); ``software_reconcile`` reads
them when capability enforcement is enabled.
"""

from __future__ import annotations


def _column_exists(cur, qualified_table: str, column: str) -> bool:
    """Catalog probe, so the optional column is never queried blindly.

    Deliberately not a `try/except UndefinedColumn`. A failed statement aborts
    the whole transaction, and recovering from it would mean rolling back --
    which would also discard the `SET LOCAL operations.tenant_id` the
    findings run uses. Every RLS-protected read afterwards would then
    return nothing and the run would report a successful zero-row pass. Asking
    the catalog first costs one cheap query and cannot poison the transaction.

    `to_regclass` yields NULL for a missing table rather than raising, so an
    absent table answers False too.
    """
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM pg_attribute
             WHERE attrelid = to_regclass(%s)
               AND attname = %s
               AND attnum > 0
               AND NOT attisdropped
        )
        """,
        (qualified_table, column),
    )
    row = cur.fetchone()
    return bool(row and row[0])


def capability_schema_ready(cur) -> bool:
    """Catalog probe that never aborts the findings transaction."""
    cur.execute(
        """
        SELECT bool_and(to_regclass(name) IS NOT NULL)
          FROM unnest(%s::text[]) AS name
        """,
        ([
            "catalog.capability",
            "catalog.v_product_capability_effective",
            "operations.platform_product_map",
            # Authorization is what suppresses an unauthorized finding, so a
            # missing table must fail closed to "capability not ready" rather
            # than leave enforcement running with nothing able to permit.
            "operations.product_authorizations",
        ],),
    )
    row = cur.fetchone()
    if not row or not row[0]:
        return False
    return _column_exists(cur, "catalog.capability", "unauthorized_finding_type")


def load_effective_capabilities(cur) -> dict:
    """Global product capability truth, including its registered finding name."""
    cur.execute(
        """
        SELECT e.product_uuid, e.capability, e.state, e.alertable,
               e.evidence_sources, c.unauthorized_finding_type
          FROM catalog.v_product_capability_effective e
          JOIN catalog.capability c ON c.key = e.capability
        """
    )
    out: dict = {}
    for product_uuid, capability, state, alertable, sources, finding_type in cur.fetchall():
        out.setdefault(product_uuid, []).append(
            {
                "capability": capability,
                "state": state,
                "alertable": bool(alertable),
                "sources": sources,
                "finding_type": finding_type,
            }
        )
    return out


def load_authorizations(cur, tenant_id: int) -> dict:
    """scope -> capability -> {"permit": set, "deny": set}.

    The scope key is the client UUID, or None for the global tier. Withdrawn
    rows are excluded here rather than at the call site: a withdrawn
    authorization has no force, and filtering later would make that depend on
    every caller remembering to.
    """
    cur.execute(
        """
        SELECT client_id, capability, polarity, product_uuid
          FROM operations.product_authorizations
         WHERE tenant_id = %s AND withdrawn_at IS NULL
        """,
        (tenant_id,),
    )
    out: dict = {}
    for client_id, capability, polarity, product_uuid in cur.fetchall():
        tier = out.setdefault(client_id, {}).setdefault(
            capability, {"permit": set(), "deny": set()}
        )
        tier["permit" if polarity else "deny"].add(product_uuid)
    return out


def load_sanctioned_product_identities(cur, tenant_id: int) -> dict:
    """Per client: capability -> exact catalog product UUIDs allowed by policy."""
    cur.execute(
        """
        WITH required_platforms AS (
            SELECT c.id AS client_id, rpi.platform
              FROM operations.clients c
              JOIN operations.requirement_profiles default_profile
                ON default_profile.tenant_id = c.tenant_id
               AND default_profile.is_tenant_default
              JOIN operations.requirement_profile_items rpi
                ON rpi.tenant_id = c.tenant_id
               AND rpi.profile_id = COALESCE(c.requirement_profile_id, default_profile.id)
             WHERE c.tenant_id = %s AND c.deleted_at IS NULL
               AND rpi.platform <> ''
        )
        SELECT rp.client_id, ppm.capability, ppm.product_uuid
          FROM required_platforms rp
          JOIN operations.agents a ON a.name = rp.platform
          JOIN operations.platform_product_map ppm
            ON ppm.agent_id = a.id AND ppm.enabled
        """,
        (tenant_id,),
    )
    out: dict = {}
    for client_id, capability, product_uuid in cur.fetchall():
        out.setdefault(client_id, {}).setdefault(capability, set()).add(product_uuid)
    return out
