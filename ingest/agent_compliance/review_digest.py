"""Daily Review digest.

Rolls all current Review-class findings (confirmed_gap=false on
missing/stale required platform) into a single notification delivered
to the `review_digest` notification route. Confirmed-gap alerts have
their own first-success delivery path in `alerts.py`; this is the
counterpart for the judgment-call queue so operators get one daily
summary instead of being paged on every Review item.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Json

from ingest import db
from ingest.agent_compliance import alerts
from ingest.config import settings

log = logging.getLogger(__name__)


def send_review_digest(now: datetime) -> int:
    """Send today's Review digest if enabled, route configured, and
    there is at least one Review-class finding to report. Returns 1 if
    delivered, 0 otherwise."""
    if not settings.AGENT_COMPLIANCE_REVIEW_DIGEST_ENABLED:
        log.info("Review digest disabled")
        return 0

    findings = _load_review_findings()
    if not findings:
        log.info("Review digest: no Review-class findings, skipping")
        return 0

    route = _load_digest_route()
    if not route:
        log.info("Review digest route not configured or disabled")
        return 0

    payload = _build_payload(findings, now)
    status, response_code, response_preview = alerts._send_route(route, payload)
    _record_digest_event(
        now=now,
        route_id=route["route_id"],
        status=status,
        response_code=response_code,
        response_preview=response_preview,
        payload=payload,
        item_count=len(findings),
    )
    if status == "sent":
        log.info("Review digest sent: %d items", len(findings))
        return 1
    log.warning("Review digest delivery returned %s", status)
    return 0


def _load_review_findings() -> list[dict[str, Any]]:
    with db.pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT
                    finding_signature,
                    finding_type,
                    affected_platform,
                    client_name,
                    hostname,
                    device_type,
                    severity,
                    summary,
                    first_seen_at,
                    last_seen_at
                FROM ninja_agent_compliance.v_active_findings
                WHERE NOT confirmed_gap
                  AND finding_type IN (
                      'missing_required_platform',
                      'stale_required_platform'
                  )
                ORDER BY client_name, hostname, finding_type
                """
            )
            return cur.fetchall()


def _load_digest_route() -> dict[str, Any] | None:
    with db.pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT route_id, route_key, route_type, display_name,
                       target_ref, config
                FROM ninja_agent_compliance.notification_routes
                WHERE route_key = 'review_digest' AND enabled
                """
            )
            return cur.fetchone()


def _build_payload(
    findings: list[dict[str, Any]], now: datetime
) -> dict[str, Any]:
    by_customer: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for f in findings:
        by_customer[f["client_name"]] = by_customer.get(f["client_name"], 0) + 1
        by_type[f["finding_type"]] = by_type.get(f["finding_type"], 0) + 1
    return {
        "event_type": "review_digest",
        "generated_at": now.isoformat(),
        "total_open": len(findings),
        "by_customer": [
            {"customer": k, "count": v}
            for k, v in sorted(by_customer.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "by_finding_type": [
            {"finding_type": k, "count": v}
            for k, v in sorted(by_type.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "items_sample": [
            {
                "customer": f["client_name"],
                "hostname": f["hostname"],
                "finding_type": f["finding_type"],
                "affected_platform": f["affected_platform"],
                "severity": f["severity"],
                "summary": f["summary"],
                "first_seen_at": f["first_seen_at"].isoformat()
                    if f["first_seen_at"] else None,
            }
            for f in findings[:100]
        ],
    }


def _record_digest_event(
    now: datetime,
    route_id: int,
    status: str,
    response_code: int | None,
    response_preview: str | None,
    payload: dict[str, Any],
    item_count: int,
) -> None:
    """Append a row to alert_events tagged as a digest delivery so the
    Alerts dashboard can show the digest history alongside per-finding
    deliveries. Uses a synthetic finding_signature so it does not
    collide with per-finding events."""
    signature = f"review_digest:{now.strftime('%Y-%m-%dT%H')}"
    with db.transaction() as cur:
        cur.execute(
            """
            INSERT INTO ninja_agent_compliance.alert_events (
                finding_signature, finding_id, route_id, event_type,
                attempted_at, status, response_code, response_preview, payload
            )
            VALUES (%s, NULL, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                signature,
                route_id,
                "review_digest",
                now,
                status,
                response_code,
                response_preview,
                Json({"item_count": item_count, **payload}),
            ),
        )
