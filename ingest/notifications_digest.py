"""Daily review digest (Track 2.3).

Aggregates findings with confidence < confirmed (the review class,
per legacy review_digest.py:27-60) into totals + by_client + by_type,
sends to any notification_route with mode='digest'.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone

from psycopg.rows import dict_row

from ingest import db
from ingest.config import settings
from ingest.notifications import _send

log = logging.getLogger(__name__)

_TENANT_ID = 1


def send_digest(tenant_id: int = _TENANT_ID) -> int:
    """Assemble + send the review digest. Returns count of routes fired."""
    if not settings.NOTIFY_DIGEST_ENABLED:
        log.info("digest: NOTIFY_DIGEST_ENABLED false — skipping")
        return 0

    now = datetime.now(timezone.utc)
    with db.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SET LOCAL operations.tenant_id = {tenant_id}")
        cur.execute(
            """
            SELECT f.severity, f.confidence, ft.name AS finding_type,
                   c.display_name AS client_name, f.finding_details,
                   f.last_seen_at
            FROM operations.findings f
            JOIN operations.finding_types ft ON ft.id = f.finding_type_id
            LEFT JOIN operations.clients c ON c.id = f.client_id
            WHERE f.tenant_id = %s
              AND f.status IN ('open', 'acknowledged')
              AND (f.confidence <> 'confirmed' OR f.confidence = '')
            ORDER BY f.severity DESC, f.last_seen_at DESC
            LIMIT 500
            """,
            (tenant_id,),
        )
        rows = cur.fetchall()

        cur.execute(
            """
            SELECT id, channel, target FROM operations.notification_routes
            WHERE tenant_id = %s AND mode = 'digest'
            """,
            (tenant_id,),
        )
        routes = cur.fetchall()

    if not routes:
        log.info("digest: no digest routes configured")
        return 0

    by_client: Counter = Counter()
    by_type: Counter = Counter()
    for r in rows:
        by_client[r["client_name"] or "—"] += 1
        by_type[r["finding_type"]] += 1

    payload = {
        "title": "Operations review digest",
        "severity": "info",
        "confidence": "",
        "platform": "",
        "hostname": "",
        "details": {
            "generated_at": now.isoformat(),
            "total": len(rows),
            "by_client": dict(by_client.most_common(20)),
            "by_type": dict(by_type.most_common(20)),
            "sample": [
                {
                    "severity": r["severity"],
                    "confidence": r["confidence"],
                    "finding_type": r["finding_type"],
                    "client": r["client_name"],
                    "hostname": (r["finding_details"] or {}).get("hostname", ""),
                    "last_seen_at": r["last_seen_at"].isoformat() if r["last_seen_at"] else "",
                }
                for r in rows[:100]
            ],
        },
    }

    fired = 0
    for route in routes:
        status, _code, _preview = _send(route, payload)
        log.info("digest: route %s (%s) → %s", route["id"], route["channel"], status)
        if status == "sent":
            fired += 1
    return fired
