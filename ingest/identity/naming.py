"""Name Computers through the one writer (ADR-0034 section 6).

``operations.write_computer_names`` is the only writer of a Computer's name;
these helpers call it in the caller's transaction, so a Computer is renamed
the moment a record attaches to it or leaves it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

TENANT_ID = 1

_writer_installed = False


def write_computer_names(cur: Any, device_ids: Iterable | None, tenant_id: int = TENANT_ID) -> int:
    """Name these Computers now; ``None`` reconciles every Computer of the tenant.

    Returns the Computers whose name or provenance changed. Before migration
    0328 is applied the writer does not exist and nothing is written.
    """
    global _writer_installed
    if not _writer_installed:
        cur.execute(
            "SELECT to_regprocedure('operations.write_computer_names(uuid[],bigint)') IS NOT NULL"
        )
        _writer_installed = bool(cur.fetchone()[0])
        if not _writer_installed:
            return 0
    ids = None if device_ids is None else sorted({str(d) for d in device_ids if d})
    if ids == []:
        return 0
    cur.execute(
        "SELECT operations.write_computer_names(%s::uuid[], %s::bigint)", (ids, tenant_id)
    )
    return cur.fetchone()[0] or 0


_ATTACHMENTS = """
SELECT eo.source_instance_id::text, eo.external_id, eo.entity_type, eo.device_id
  FROM unnest(%s::uuid[], %s::text[], %s::text[]) AS k(source_instance_id, external_id, entity_type)
  JOIN operations.entity_observation_current eo
    ON eo.tenant_id = %s AND eo.source_instance_id = k.source_instance_id
   AND eo.external_id = k.external_id AND eo.entity_type = k.entity_type
"""


def attachments(cur: Any, rows: Iterable[dict[str, Any]], tenant_id: int = TENANT_ID) -> dict:
    """The Computer each of these records is attached to now, by record identity."""
    keys = {
        (str(r["source_instance_id"]), str(r["external_id"]), r["entity_type"])
        for r in rows
        if r.get("entity_type") != "org" and r.get("external_id")
    }
    if not keys:
        return {}
    si, ext, et = (list(column) for column in zip(*sorted(keys), strict=True))
    cur.execute(_ATTACHMENTS, (si, ext, et, tenant_id))
    return {(a, b, c): device_id for a, b, c, device_id in cur.fetchall()}


def name_changed_attachments(cur: Any, before: dict, after: dict) -> int:
    """Name every Computer a record joined or left between the two snapshots."""
    touched: set[uuid.UUID] = set()
    for key in before.keys() | after.keys():
        old, new = before.get(key), after.get(key)
        if old != new:
            touched.update(d for d in (old, new) if d)
    return write_computer_names(cur, touched)
