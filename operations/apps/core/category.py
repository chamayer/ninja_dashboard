"""Operations read/write access to descriptive category evidence (migration 104).

Mirrors `capability.py` exactly, on the descriptive-taxonomy axis instead of
the security-relevant one. The two are separate tables and separate write
paths for the same reason migration 104 keeps `catalog.software_category`
apart from `catalog.capability`: a category can never alert, so nothing here
carries an `alertable` axis, but the write boundary and the withdraw-then-
reinsert shape are identical -- both are global truth, so both go through the
same "operator writes, only ever withdraws" grant discipline.

**Schema readiness.** Same concurrent-startup hazard as capability: migration
104's tables are ingest's raw SQL, and Operations must never assume they are
present. Reads degrade to "not available yet"; writes fail closed.
"""

from __future__ import annotations

import logging

from django.db import connection

log = logging.getLogger(__name__)

# Category truth is global exactly like capability truth -- see
# SoftwareCatalog.Meta.permissions in models.py for why that means a
# dedicated permission rather than an ordinary operator right, even though a
# category can never raise a finding. Defaults to nobody.
CURATOR_PERMISSION = "operations.curate_software_category"

_REQUIRED_RELATIONS = (
    "catalog.software_category",
    "catalog.category_assertion_operator",
    "catalog.category_assertion_machine",
    "catalog.v_product_category_effective",
)


class CategorySchemaUnavailable(RuntimeError):
    """Raised by write paths when migration 104 has not been applied yet."""


def schema_ready() -> bool:
    """True when every relation migration 104 creates is present."""
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
        raise CategorySchemaUnavailable(
            "Category tables are not present yet. They are created by ingest "
            "migration 104; this is expected briefly after a deploy while the "
            "ingest container applies pending SQL migrations."
        )


def effective_for_products(product_uuids: list[str]) -> dict[str, list[dict]]:
    """Effective category rows keyed by product uuid.

    Returns an empty mapping when the schema is not ready, so a caller renders
    "not available" rather than failing. Absence of a row means *unknown*.
    """
    if not product_uuids or not schema_ready():
        return {}
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT product_uuid::text, category, state,
                   evidence_sources, best_confidence
              FROM catalog.v_product_category_effective
             WHERE product_uuid = ANY(%s::uuid[])
             ORDER BY product_uuid, category
            """,
            (product_uuids,),
        )
        out: dict[str, list[dict]] = {}
        for uuid_, category, state, sources, confidence in cur.fetchall():
            out.setdefault(uuid_, []).append(
                {
                    "category": category,
                    "state": state,
                    "sources": sources,
                    "confidence": confidence,
                }
            )
    return out


def products_for_title(canonical_name: str) -> list[str]:
    """Stable product identities currently observed for one display title.

    Same reasoning as capability.products_for_title: a display title can
    resolve to more than one product identity, so every one is shown rather
    than guessing which one an operator intended to curate.
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


def confirm(product_uuid: str, category: str, polarity: bool,
            actor: str, rationale: str = "") -> None:
    """Record an operator judgement.

    A prior current assertion is withdrawn rather than overwritten, so the
    history of who said what, and when, survives -- the only shape the grants
    permit (column-level UPDATE on withdrawn_at/withdrawn_reason only).
    """
    require_schema()
    if not actor:
        raise ValueError("an operator assertion must record its actor")
    with connection.cursor() as cur:
        cur.execute(
            """
            UPDATE catalog.category_assertion_operator
               SET withdrawn_at = now(),
                   withdrawn_reason = 'superseded by a later operator decision'
             WHERE product_uuid = %s AND category = %s AND withdrawn_at IS NULL
            """,
            (product_uuid, category),
        )
        cur.execute(
            """
            INSERT INTO catalog.category_assertion_operator
                (product_uuid, category, polarity, rationale, confirmed_by)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (product_uuid, category, polarity, rationale, actor),
        )


def withdraw(product_uuid: str, category: str, reason: str) -> int:
    """Withdraw the current operator assertion, restoring machine evidence."""
    require_schema()
    if not reason:
        raise ValueError("withdrawal requires a reason (ADR-0012)")
    with connection.cursor() as cur:
        cur.execute(
            """
            UPDATE catalog.category_assertion_operator
               SET withdrawn_at = now(), withdrawn_reason = %s
             WHERE product_uuid = %s AND category = %s AND withdrawn_at IS NULL
            """,
            (reason, product_uuid, category),
        )
        return cur.rowcount or 0
