"""Source-scoped device lookup.

Maps a source's own external id to the resolved Operations device. This is a
*direct* lookup, not identity resolution — the caller already knows which
external record it holds and only needs the device it was linked to.

Parameterised by source name because aggregators resolve keys belonging to
several vendors; `ingest/inventory/software.py` carries an equivalent
Ninja-only query and should migrate onto this helper separately.
"""

from __future__ import annotations

import uuid

from ingest import db

_TENANT_ID = 1
_GUC = f"SET LOCAL operations.tenant_id = {_TENANT_ID}"


def load_device_map(source_name: str) -> dict[str, tuple[uuid.UUID, uuid.UUID | None]]:
    """Return {external_id: (device_id, client_id)} for one source.

    Only live devices are included — a soft-deleted device must not be
    resurrected by an aggregator still pointing at it.
    """
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(_GUC)
        cur.execute(
            """
            SELECT dl.external_id, dl.device_id, d.client_id
              FROM operations.device_links dl
              JOIN operations.devices d ON d.id = dl.device_id
              JOIN operations.sources s ON s.id = dl.source_id AND s.name = %s
             WHERE dl.tenant_id = %s AND d.deleted_at IS NULL
            """,
            (source_name, _TENANT_ID),
        )
        return {
            external_id: (device_id, client_id)
            for external_id, device_id, client_id in cur.fetchall()
        }
