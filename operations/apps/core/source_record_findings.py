"""Read helpers for source-record findings shown on a Computer detail page."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID


def associated_source_record_finding_ids(
    cur: Any,
    tenant_id: int,
    device_entity_id: UUID | str,
    active_statuses: Sequence[str],
) -> list[UUID]:
    """Find active source-record findings whose episode overlaps this link history."""
    cur.execute(
        """
        SELECT DISTINCT f.subject_id
          FROM operations.findings f
          JOIN operations.source_record_subjects s
            ON s.tenant_id = f.tenant_id AND s.id = f.subject_id
           AND s.subject_kind = 'record'
          JOIN operations.entity_source_link_history h
            ON h.tenant_id = s.tenant_id
           AND h.source_instance_id = s.source_instance_id
           AND h.external_namespace = s.external_namespace
           AND h.parent_external_namespace = s.parent_external_namespace
           AND h.parent_external_id = s.parent_external_id
           AND h.external_id = s.external_id
           AND h.entity_class_id = 'device'
           AND h.entity_id = %s
           AND h.effective_from <= f.last_seen_at
           AND (h.effective_to IS NULL OR h.effective_to > f.first_seen_at)
         WHERE f.tenant_id = %s AND f.subject_type = 'source_record'
           AND f.condition_namespace = 'entity'
           AND f.status = ANY(%s)
        """,
        [str(device_entity_id), tenant_id, list(active_statuses)],
    )
    return [row[0] for row in cur.fetchall()]
