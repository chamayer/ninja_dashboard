"""Shared relationship evidence resolution and effective-edge projection."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from psycopg.types.json import Json

from ingest import db

log = logging.getLogger(__name__)


def write_current_evidence(
    cur,
    *,
    tenant_id: int,
    source_instance_id: uuid.UUID,
    native_record_type: str,
    external_relationship_id: str,
    relationship_type: str,
    source_endpoint: dict[str, Any],
    target_endpoint: dict[str, Any],
    material_hash: bytes,
    observed_at: datetime,
) -> uuid.UUID:
    """Upsert one stable source relationship without heartbeat projection work."""
    if not external_relationship_id.strip():
        raise ValueError("Relationship evidence requires a stable external ID.")
    if not source_endpoint.get("external_id") or not target_endpoint.get("external_id"):
        raise ValueError("Relationship evidence requires both supplied endpoint IDs.")
    cur.execute("SET LOCAL operations.tenant_id = %s", (tenant_id,))
    cur.execute(
        """
        SELECT id, relationship_type_id, material_hash, active,
               source_endpoint_source_instance_id, source_endpoint_source_hint,
               source_external_namespace, source_parent_external_namespace,
               source_parent_external_id, source_external_id,
               target_endpoint_source_instance_id, target_endpoint_source_hint,
               target_external_namespace, target_parent_external_namespace,
               target_parent_external_id, target_external_id
          FROM operations.entity_relationship_evidence_current
         WHERE tenant_id = %s AND source_instance_id = %s
           AND external_relationship_id = %s
         FOR UPDATE
        """,
        (tenant_id, source_instance_id, external_relationship_id),
    )
    previous = cur.fetchone()
    endpoint_identity = {
        "source": {
            "source_instance_id": str(source_endpoint.get("source_instance_id") or ""),
            "source_hint": str(source_endpoint.get("source_hint") or ""),
            "external_namespace": str(source_endpoint.get("external_namespace") or ""),
            "parent_external_namespace": str(
                source_endpoint.get("parent_external_namespace") or ""
            ),
            "parent_external_id": str(source_endpoint.get("parent_external_id") or ""),
            "external_id": str(source_endpoint["external_id"]),
        },
        "target": {
            "source_instance_id": str(target_endpoint.get("source_instance_id") or ""),
            "source_hint": str(target_endpoint.get("source_hint") or ""),
            "external_namespace": str(target_endpoint.get("external_namespace") or ""),
            "parent_external_namespace": str(
                target_endpoint.get("parent_external_namespace") or ""
            ),
            "parent_external_id": str(target_endpoint.get("parent_external_id") or ""),
            "external_id": str(target_endpoint["external_id"]),
        },
    }
    cur.execute(
        """
        INSERT INTO operations.entity_relationship_evidence_current (
            id, tenant_id, version, source_instance_id, native_record_type,
            external_relationship_id, relationship_type_id,
            source_endpoint_source_instance_id, source_endpoint_source_hint,
            source_external_namespace, source_parent_external_namespace,
            source_parent_external_id, source_external_id,
            target_endpoint_source_instance_id, target_endpoint_source_hint,
            target_external_namespace, target_parent_external_namespace,
            target_parent_external_id, target_external_id,
            resolution_status, authority_eligible, authority_tier,
            authority_priority, material_hash, active, first_observed_at,
            last_observed_at, withdrawn_at
        ) VALUES (
            gen_random_uuid(), %s, 1, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            'unresolved', FALSE, 0, 0, %s, TRUE, %s, %s, NULL
        )
        ON CONFLICT (tenant_id, source_instance_id, external_relationship_id)
        DO UPDATE SET native_record_type = EXCLUDED.native_record_type,
                      relationship_type_id = EXCLUDED.relationship_type_id,
                      source_endpoint_source_instance_id =
                          EXCLUDED.source_endpoint_source_instance_id,
                      source_endpoint_source_hint = EXCLUDED.source_endpoint_source_hint,
                      source_external_namespace = EXCLUDED.source_external_namespace,
                      source_parent_external_namespace =
                          EXCLUDED.source_parent_external_namespace,
                      source_parent_external_id = EXCLUDED.source_parent_external_id,
                      source_external_id = EXCLUDED.source_external_id,
                      target_endpoint_source_instance_id =
                          EXCLUDED.target_endpoint_source_instance_id,
                      target_endpoint_source_hint = EXCLUDED.target_endpoint_source_hint,
                      target_external_namespace = EXCLUDED.target_external_namespace,
                      target_parent_external_namespace =
                          EXCLUDED.target_parent_external_namespace,
                      target_parent_external_id = EXCLUDED.target_parent_external_id,
                      target_external_id = EXCLUDED.target_external_id,
                      material_hash = EXCLUDED.material_hash,
                      active = TRUE, withdrawn_at = NULL,
                      last_observed_at = EXCLUDED.last_observed_at,
                      version = CASE WHEN
                          entity_relationship_evidence_current.material_hash
                              IS DISTINCT FROM EXCLUDED.material_hash
                          OR NOT entity_relationship_evidence_current.active
                          THEN entity_relationship_evidence_current.version + 1
                          ELSE entity_relationship_evidence_current.version END
        RETURNING id
        """,
        (
            tenant_id,
            source_instance_id,
            native_record_type,
            external_relationship_id,
            relationship_type,
            source_endpoint.get("source_instance_id"),
            str(source_endpoint.get("source_hint") or ""),
            str(source_endpoint.get("external_namespace") or ""),
            str(source_endpoint.get("parent_external_namespace") or ""),
            str(source_endpoint.get("parent_external_id") or ""),
            str(source_endpoint["external_id"]),
            target_endpoint.get("source_instance_id"),
            str(target_endpoint.get("source_hint") or ""),
            str(target_endpoint.get("external_namespace") or ""),
            str(target_endpoint.get("parent_external_namespace") or ""),
            str(target_endpoint.get("parent_external_id") or ""),
            str(target_endpoint["external_id"]),
            material_hash,
            observed_at,
            observed_at,
        ),
    )
    evidence_id = cur.fetchone()[0]
    previous_endpoint = None
    if previous is not None:
        previous_endpoint = {
            "source": {
                "source_instance_id": str(previous[4] or ""),
                "source_hint": previous[5],
                "external_namespace": previous[6],
                "parent_external_namespace": previous[7],
                "parent_external_id": previous[8],
                "external_id": previous[9],
            },
            "target": {
                "source_instance_id": str(previous[10] or ""),
                "source_hint": previous[11],
                "external_namespace": previous[12],
                "parent_external_namespace": previous[13],
                "parent_external_id": previous[14],
                "external_id": previous[15],
            },
        }
    material_changed = (
        previous is None
        or previous[1] != relationship_type
        or bytes(previous[2]) != material_hash
        or not previous[3]
        or previous_endpoint != endpoint_identity
    )
    if material_changed and previous is not None and previous[3]:
        cur.execute(
            """
            UPDATE operations.entity_relationship_evidence_history
               SET effective_to = %s
             WHERE tenant_id = %s AND evidence_current_id = %s
               AND effective_to IS NULL AND effective_from < %s
            """,
            (observed_at, tenant_id, evidence_id, observed_at),
        )
        if cur.rowcount == 0:
            cur.execute(
                """
                DELETE FROM operations.entity_relationship_evidence_history
                 WHERE tenant_id = %s AND evidence_current_id = %s
                   AND effective_to IS NULL AND effective_from = %s
                """,
                (tenant_id, evidence_id, observed_at),
            )
    if material_changed:
        cur.execute(
            """
            INSERT INTO operations.entity_relationship_evidence_history (
                id, tenant_id, evidence_current_id, relationship_type_id,
                source_entity_id, target_entity_id, endpoint_identity,
                resolution_status, authority_eligible, authority_tier,
                authority_priority, material_hash, effective_from, effective_to
            )
            SELECT gen_random_uuid(), current.tenant_id, current.id,
                   current.relationship_type_id, current.source_entity_id,
                   current.target_entity_id, %s, current.resolution_status,
                   current.authority_eligible, current.authority_tier,
                   current.authority_priority, current.material_hash, %s, NULL
              FROM operations.entity_relationship_evidence_current current
             WHERE current.id = %s
            """,
            (Json(endpoint_identity), observed_at, evidence_id),
        )
    return evidence_id


def withdraw_current_evidence(
    cur,
    *,
    tenant_id: int,
    source_instance_id: uuid.UUID,
    external_relationship_ids: list[str],
    withdrawn_at: datetime,
) -> int:
    """Withdraw only the reporting source's missing relationship evidence."""
    if not external_relationship_ids:
        return 0
    cur.execute("SET LOCAL operations.tenant_id = %s", (tenant_id,))
    cur.execute(
        """
        UPDATE operations.entity_relationship_evidence_current
           SET active = FALSE, withdrawn_at = %s, version = version + 1
         WHERE tenant_id = %s AND source_instance_id = %s
           AND external_relationship_id = ANY(%s)
           AND active
        RETURNING id
        """,
        (withdrawn_at, tenant_id, source_instance_id, external_relationship_ids),
    )
    withdrawn_ids = [row[0] for row in cur.fetchall()]
    if not withdrawn_ids:
        return 0
    cur.execute(
        """
        UPDATE operations.entity_relationship_evidence_history
           SET effective_to = %s
         WHERE tenant_id = %s AND evidence_current_id = ANY(%s)
           AND effective_to IS NULL AND effective_from < %s
        """,
        (withdrawn_at, tenant_id, withdrawn_ids, withdrawn_at),
    )
    if cur.rowcount != len(withdrawn_ids):
        raise RuntimeError("relationship evidence current/history withdrawal mismatch")
    return len(withdrawn_ids)


def resolve_current_evidence() -> int:
    """Resolve only exact complete stable endpoint identities."""
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            "SELECT to_regclass("
            "'operations.entity_relationship_evidence_current'"
            ") IS NOT NULL"
        )
        if not cur.fetchone()[0]:
            return 0
        cur.execute(
            """
            WITH resolved AS (
                SELECT evidence.id,
                       source_link.entity_id AS source_entity_id,
                       target_link.entity_id AS target_entity_id
                  FROM operations.entity_relationship_evidence_current evidence
                  LEFT JOIN operations.entity_source_links source_link
                    ON source_link.tenant_id = evidence.tenant_id
                   AND source_link.source_instance_id =
                       evidence.source_endpoint_source_instance_id
                   AND source_link.external_namespace =
                       evidence.source_external_namespace
                   AND source_link.parent_external_namespace =
                       evidence.source_parent_external_namespace
                   AND source_link.parent_external_id =
                       evidence.source_parent_external_id
                   AND source_link.external_id = evidence.source_external_id
                  LEFT JOIN operations.entity_source_links target_link
                    ON target_link.tenant_id = evidence.tenant_id
                   AND target_link.source_instance_id =
                       evidence.target_endpoint_source_instance_id
                   AND target_link.external_namespace =
                       evidence.target_external_namespace
                   AND target_link.parent_external_namespace =
                       evidence.target_parent_external_namespace
                   AND target_link.parent_external_id =
                       evidence.target_parent_external_id
                   AND target_link.external_id = evidence.target_external_id
                 WHERE evidence.active
                   AND evidence.resolution_status <> 'invalid'
                   AND (
                       evidence.source_entity_id IS DISTINCT FROM source_link.entity_id
                       OR evidence.target_entity_id IS DISTINCT FROM target_link.entity_id
                   )
            )
            UPDATE operations.entity_relationship_evidence_current evidence
               SET source_entity_id = resolved.source_entity_id,
                   target_entity_id = resolved.target_entity_id,
                   version = evidence.version + 1
              FROM resolved
             WHERE evidence.id = resolved.id
            """
        )
        resolved = cur.rowcount
        if resolved:
            cur.execute(
                """
                UPDATE operations.entity_relationship_evidence_history history
                   SET source_entity_id = current.source_entity_id,
                       target_entity_id = current.target_entity_id,
                       resolution_status = current.resolution_status,
                       authority_eligible = current.authority_eligible,
                       authority_tier = current.authority_tier,
                       authority_priority = current.authority_priority
                  FROM operations.entity_relationship_evidence_current current
                 WHERE history.tenant_id = current.tenant_id
                   AND history.evidence_current_id = current.id
                   AND history.effective_to IS NULL
                """
            )
        return resolved


def project_all(batch_size: int = 5000, max_batches: int = 100) -> dict[str, Any]:
    totals: dict[str, Any] = {
        "status": "complete",
        "batches": 0,
        "resolved": resolve_current_evidence(),
        "processed": 0,
        "relationship_writes": 0,
        "support_writes": 0,
    }
    with db.transaction() as cur:
        cur.execute(
            "SELECT to_regprocedure("
            "'operations.sync_entity_relationships(integer)'"
            ") IS NOT NULL"
        )
        if not cur.fetchone()[0]:
            totals["status"] = "migration_pending"
            return totals

    for _ in range(max_batches):
        with db.transaction() as cur:
            cur.execute(
                "SELECT * FROM operations.sync_entity_relationships(%s)",
                (batch_size,),
            )
            processed, relationship_writes, support_writes = cur.fetchone()
        if int(processed or 0) == 0:
            break
        totals["batches"] += 1
        totals["processed"] += int(processed or 0)
        totals["relationship_writes"] += int(relationship_writes or 0)
        totals["support_writes"] += int(support_writes or 0)
    else:
        totals["status"] = "batch_limit"

    log.info("Generic relationship projection: %s", totals)
    return totals
