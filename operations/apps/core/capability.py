"""Operations read/write access to capability evidence (migration 093).

Two things this module exists to contain.

**Schema readiness.** The capability tables are created by *ingest's* raw SQL
migration 093, and ingest and Operations start concurrently with neither
waiting for the other. Operations must therefore never assume the tables are
there: reads degrade to "not available yet" and writes fail closed with an
explicit error, instead of 500ing on `UndefinedTable`.

The probe asks `pg_catalog` rather than catching the error, for the same reason
`software_findings._column_exists` does: a failed statement aborts the
transaction, and recovering by rolling back would discard the tenant GUC that
surrounding Operations code depends on.

**Write boundary.** Operations may insert operator assertions and may only ever
*withdraw* them -- migration 093 grants column-level UPDATE on
`(withdrawn_at, withdrawn_reason)` and nothing else. Changing a conclusion is
withdrawing the old assertion and inserting a new one, which keeps the actor,
the timestamp and the original polarity intact. The functions here follow that
shape so the database never has to refuse.
"""

from __future__ import annotations

import logging

from django.db import connection

log = logging.getLogger(__name__)

CURATOR_PERMISSION = "core.curate_software_capability"

_REQUIRED_RELATIONS = (
    "catalog.capability",
    "catalog.capability_assertion_operator",
    "catalog.capability_assertion_machine",
    "catalog.v_product_capability_effective",
)


class CapabilitySchemaUnavailable(RuntimeError):
    """Raised by write paths when migration 093 has not been applied yet."""


def schema_ready() -> bool:
    """True when every relation migration 093 creates is present.

    `to_regclass` returns NULL for a missing relation rather than raising, so
    this never poisons the caller's transaction.
    """
    with connection.cursor() as cur:
        cur.execute(
            "SELECT bool_and(to_regclass(name) IS NOT NULL) "
            "FROM unnest(%s::text[]) AS name",
            (list(_REQUIRED_RELATIONS),),
        )
        row = cur.fetchone()
    return bool(row and row[0])


def require_schema() -> None:
    if not schema_ready():
        raise CapabilitySchemaUnavailable(
            "Capability tables are not present yet. They are created by ingest "
            "migration 093; this is expected briefly after a deploy while the "
            "ingest container applies pending SQL migrations."
        )


def effective_for_products(product_uuids: list[str]) -> dict[str, list[dict]]:
    """Effective capability rows keyed by product uuid.

    Returns an empty mapping when the schema is not ready, so a caller renders
    "not available" rather than failing. Absence of a row means *unknown*, and
    callers must present it that way rather than as "no capability".
    """
    if not product_uuids or not schema_ready():
        return {}
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT product_uuid::text, capability, state, alertable,
                   evidence_sources, best_confidence
              FROM catalog.v_product_capability_effective
             WHERE product_uuid = ANY(%s::uuid[])
             ORDER BY product_uuid, capability
            """,
            (product_uuids,),
        )
        out: dict[str, list[dict]] = {}
        for uuid_, capability, state, alertable, sources, confidence in cur.fetchall():
            out.setdefault(uuid_, []).append(
                {
                    "capability": capability,
                    "state": state,
                    "alertable": alertable,
                    "sources": sources,
                    "confidence": confidence,
                }
            )
    return out


def products_for_title(canonical_name: str) -> list[str]:
    """Stable product identities currently observed for one display title.

    A display title can legitimately resolve to more than one product when the
    observed publisher changed. The caller must show each identity rather than
    guessing which global product an operator intended to curate.
    """
    if not canonical_name or not schema_ready():
        return []
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT p.product_uuid::text
              FROM operations.software_installations_current sic
              JOIN catalog.software_versions sv ON sv.id = sic.software_version_id
              JOIN catalog.products p ON p.id = sv.product_id
             WHERE sic.tenant_id = 1
               AND sic.stale_since IS NULL AND sic.deleted_at IS NULL
               AND LOWER(sic.canonical_name) = LOWER(%s)
             ORDER BY p.product_uuid::text
            """,
            (canonical_name,),
        )
        return [row[0] for row in cur.fetchall()]


def confirm(product_uuid: str, capability: str, polarity: bool,
            actor: str, rationale: str = "") -> None:
    """Record an operator judgement.

    A prior current assertion is withdrawn rather than overwritten, so the
    history of who said what, and when, survives. This is also the only shape
    the grants permit.
    """
    require_schema()
    if not actor:
        raise ValueError("an operator assertion must record its actor")
    with connection.cursor() as cur:
        cur.execute(
            """
            UPDATE catalog.capability_assertion_operator
               SET withdrawn_at = now(),
                   withdrawn_reason = 'superseded by a later operator decision'
             WHERE product_uuid = %s AND capability = %s AND withdrawn_at IS NULL
            """,
            (product_uuid, capability),
        )
        cur.execute(
            """
            INSERT INTO catalog.capability_assertion_operator
                (product_uuid, capability, polarity, rationale, confirmed_by)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (product_uuid, capability, polarity, rationale, actor),
        )


def withdraw(product_uuid: str, capability: str, reason: str) -> int:
    """Withdraw the current operator assertion, restoring machine evidence."""
    require_schema()
    if not reason:
        raise ValueError("withdrawal requires a reason (ADR-0012)")
    with connection.cursor() as cur:
        cur.execute(
            """
            UPDATE catalog.capability_assertion_operator
               SET withdrawn_at = now(), withdrawn_reason = %s
             WHERE product_uuid = %s AND capability = %s AND withdrawn_at IS NULL
            """,
            (reason, product_uuid, capability),
        )
        return cur.rowcount or 0
