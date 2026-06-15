"""Alert evaluation and webhook delivery for agent compliance."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any

import httpx
from psycopg.rows import dict_row
from psycopg.types.json import Json

from ingest import db
from ingest.config import settings

log = logging.getLogger(__name__)


def process_alerts(run_id: int, now: datetime) -> int:
    if not settings.AGENT_COMPLIANCE_ALERTS_ENABLED:
        log.info("Agent compliance alerts disabled")
        return 0

    with db.pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT f.*
                FROM ninja_agent_compliance.compliance_findings f
                WHERE f.run_id = %s
                  AND f.status = 'active'
                  AND f.confirmed_gap
                  AND NOT EXISTS (
                      SELECT 1
                      FROM ninja_agent_compliance.alert_suppressions s
                      WHERE s.enabled
                        AND (s.client_id IS NULL OR s.client_id = f.client_id)
                        AND (s.norm_name IS NULL OR s.norm_name = f.norm_name)
                        AND (s.finding_type IS NULL OR s.finding_type = f.finding_type)
                        AND (s.affected_platform IS NULL OR s.affected_platform = f.affected_platform)
                        AND (s.expires_at IS NULL OR s.expires_at > now())
                  )
                ORDER BY f.severity DESC, f.client_name, f.hostname
                """,
                (run_id,),
            )
            findings = cur.fetchall()

    sent = 0
    for finding in findings:
        rule = _match_rule(finding)
        if not rule:
            continue
        route = _load_route(rule["route_id"] if rule else None)
        if not route:
            continue
        summary_hash = _summary_hash(finding)
        _upsert_state(finding, summary_hash, now)
        if _has_successful_delivery(finding["finding_signature"]):
            continue
        event_type = "new"
        payload = _payload(finding, event_type)
        status, response_code, response_preview = _send_route(route, payload)
        _record_event(
            finding=finding,
            route_id=route["route_id"] if route else None,
            event_type=event_type,
            status=status,
            response_code=response_code,
            response_preview=response_preview,
            payload=payload,
            now=now,
        )
        if status == "sent":
            _mark_notified(finding["finding_signature"], now)
            sent += 1
    _mark_resolved(now)
    return sent


def _match_rule(finding: dict[str, Any]) -> dict[str, Any] | None:
    with db.pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT rule_id, cooldown_hours, route_id
                FROM ninja_agent_compliance.alert_rules
                WHERE enabled
                  AND finding_type = %s
                  AND (affected_platform IS NULL OR affected_platform = %s)
                  AND (client_id IS NULL OR client_id = %s)
                  AND (device_scope IS NULL OR device_scope IN ('all', %s))
                ORDER BY
                  client_id NULLS LAST,
                  affected_platform NULLS LAST,
                  device_scope NULLS LAST
                LIMIT 1
                """,
                (
                    finding["finding_type"],
                    finding["affected_platform"],
                    finding["client_id"],
                    finding["device_type"],
                ),
            )
            return cur.fetchone()


def _load_route(route_id: int | None) -> dict[str, Any] | None:
    if route_id is None:
        return None
    with db.pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT route_id, route_key, route_type, display_name, target_ref, config
                FROM ninja_agent_compliance.notification_routes
                WHERE route_id = %s AND enabled
                """,
                (route_id,),
            )
            return cur.fetchone()


def _summary_hash(finding: dict[str, Any]) -> str:
    text = json.dumps({
        "severity": finding["severity"],
        "summary": finding["summary"],
        "details": finding["details"],
    }, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _has_successful_delivery(signature: str) -> bool:
    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM ninja_agent_compliance.alert_events
                WHERE finding_signature = %s
                  AND status = 'sent'
                LIMIT 1
                """,
                (signature,),
            )
            return cur.fetchone() is not None


def _upsert_state(
    finding: dict[str, Any],
    summary_hash: str,
    now: datetime,
) -> None:
    with db.transaction() as cur:
        cur.execute(
            """
            INSERT INTO ninja_agent_compliance.alert_state (
                finding_signature, finding_type, affected_platform, severity,
                summary_hash, first_seen_at, last_seen_at, last_alerted_at,
                status, repeat_count, resolved_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'active', %s, NULL)
            ON CONFLICT (finding_signature) DO UPDATE
            SET finding_type = EXCLUDED.finding_type,
                affected_platform = EXCLUDED.affected_platform,
                severity = EXCLUDED.severity,
                summary_hash = EXCLUDED.summary_hash,
                last_seen_at = EXCLUDED.last_seen_at,
                status = 'active',
                resolved_at = NULL
            """,
            (
                finding["finding_signature"],
                finding["finding_type"],
                finding["affected_platform"],
                finding["severity"],
                summary_hash,
                now,
                now,
                None,
                0,
            ),
        )


def _mark_notified(signature: str, now: datetime) -> None:
    with db.transaction() as cur:
        cur.execute(
            """
            UPDATE ninja_agent_compliance.alert_state
            SET last_alerted_at = %s,
                repeat_count = repeat_count + 1,
                status = 'active',
                resolved_at = NULL
            WHERE finding_signature = %s
            """,
            (now, signature),
        )


def _payload(finding: dict[str, Any], event_type: str) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "finding_type": finding["finding_type"],
        "affected_platform": finding["affected_platform"],
        "severity": finding["severity"],
        "client_name": finding["client_name"],
        "hostname": finding["hostname"],
        "norm_name": finding["norm_name"],
        "device_type": finding["device_type"],
        "summary": finding["summary"],
        "details": finding["details"],
    }


def _send_route(
    route: dict[str, Any] | None,
    payload: dict[str, Any],
) -> tuple[str, int | None, str | None]:
    if route is None:
        return "skipped_no_route", None, None
    route_type = route["route_type"]
    if route_type == "webhook":
        return _send_webhook(route, payload)
    if route_type == "email":
        return _send_email(payload)
    if route_type == "zendesk":
        return _send_zendesk(payload)
    return "skipped_unknown_route", None, route_type


def _send_webhook(
    route: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[str, int | None, str | None]:
    ref = route.get("target_ref") or settings.AGENT_COMPLIANCE_ALERT_WEBHOOK_URL_REF
    url = os.environ.get(ref)
    if not url:
        return "skipped_no_route", None, None
    try:
        resp = httpx.post(url, json=payload, timeout=20)
        preview = resp.text[:500] if resp.text else None
        if resp.is_success:
            return "sent", resp.status_code, preview
        return "failed", resp.status_code, preview
    except Exception as exc:
        return "failed", None, str(exc)[:500]


def _send_email(payload: dict[str, Any]) -> tuple[str, int | None, str | None]:
    if not settings.AGENT_COMPLIANCE_SMTP_HOST or not settings.AGENT_COMPLIANCE_ALERT_EMAIL_TO:
        return "skipped_no_route", None, None
    msg = EmailMessage()
    msg["From"] = settings.AGENT_COMPLIANCE_ALERT_EMAIL_FROM or settings.AGENT_COMPLIANCE_SMTP_USERNAME
    msg["To"] = settings.AGENT_COMPLIANCE_ALERT_EMAIL_TO
    msg["Subject"] = f"[{payload['severity'].upper()}] {payload['summary']}"
    msg.set_content(_text_body(payload))
    try:
        with smtplib.SMTP(
            settings.AGENT_COMPLIANCE_SMTP_HOST,
            settings.AGENT_COMPLIANCE_SMTP_PORT,
            timeout=20,
        ) as smtp:
            if settings.AGENT_COMPLIANCE_SMTP_STARTTLS:
                smtp.starttls()
            password = settings.AGENT_COMPLIANCE_SMTP_PASSWORD.get_secret_value()
            if settings.AGENT_COMPLIANCE_SMTP_USERNAME and password:
                smtp.login(settings.AGENT_COMPLIANCE_SMTP_USERNAME, password)
            smtp.send_message(msg)
        return "sent", None, "email sent"
    except Exception as exc:
        return "failed", None, str(exc)[:500]


def _send_zendesk(payload: dict[str, Any]) -> tuple[str, int | None, str | None]:
    if (
        not settings.AGENT_COMPLIANCE_ZENDESK_URL
        or not settings.AGENT_COMPLIANCE_ZENDESK_REQUESTER_EMAIL
    ):
        return "skipped_no_route", None, None
    url = settings.AGENT_COMPLIANCE_ZENDESK_URL.rstrip("/")
    if not url.endswith("/api/v2/requests"):
        url = f"{url}/api/v2/requests"
    body = {
        "request": {
            "requester": {
                "email": settings.AGENT_COMPLIANCE_ZENDESK_REQUESTER_EMAIL,
                "name": settings.AGENT_COMPLIANCE_ZENDESK_REQUESTER_NAME,
            },
            "subject": f"[{payload['severity'].upper()}] {payload['summary']}",
            "comment": {"body": _text_body(payload)},
        }
    }
    auth = None
    token = settings.AGENT_COMPLIANCE_ZENDESK_AUTH_TOKEN.get_secret_value()
    if settings.AGENT_COMPLIANCE_ZENDESK_AUTH_USERNAME and token:
        auth = (settings.AGENT_COMPLIANCE_ZENDESK_AUTH_USERNAME, token)
    try:
        resp = httpx.post(url, json=body, auth=auth, timeout=20)
        preview = resp.text[:500] if resp.text else None
        if resp.is_success:
            return "sent", resp.status_code, preview
        return "failed", resp.status_code, preview
    except Exception as exc:
        return "failed", None, str(exc)[:500]


def _text_body(payload: dict[str, Any]) -> str:
    return "\n".join([
        payload["summary"],
        "",
        f"Severity: {payload['severity']}",
        f"Finding type: {payload['finding_type']}",
        f"Affected platform: {payload.get('affected_platform') or 'multiple'}",
        f"Client: {payload.get('client_name') or 'n/a'}",
        f"Host: {payload.get('hostname') or 'n/a'}",
        f"Device type: {payload.get('device_type') or 'n/a'}",
        "",
        "Details:",
        json.dumps(payload.get("details") or {}, indent=2, default=str),
    ])


def _record_event(
    finding: dict[str, Any],
    route_id: int | None,
    event_type: str,
    status: str,
    response_code: int | None,
    response_preview: str | None,
    payload: dict[str, Any],
    now: datetime,
) -> None:
    with db.transaction() as cur:
        cur.execute(
            """
            INSERT INTO ninja_agent_compliance.alert_events (
                finding_signature, finding_id, route_id, event_type,
                attempted_at, status, response_code, response_preview, payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                finding["finding_signature"],
                finding["finding_id"],
                route_id,
                event_type,
                now,
                status,
                response_code,
                response_preview,
                Json(payload),
            ),
        )


def _mark_resolved(now: datetime) -> None:
    with db.transaction() as cur:
        cur.execute(
            """
            UPDATE ninja_agent_compliance.alert_state s
            SET status = 'resolved',
                resolved_at = COALESCE(resolved_at, %s)
            WHERE status = 'active'
              AND NOT EXISTS (
                  SELECT 1
                  FROM ninja_agent_compliance.compliance_findings f
                  WHERE f.finding_signature = s.finding_signature
                    AND f.status = 'active'
                    AND f.last_seen_at > %s - INTERVAL '1 day'
              )
            """,
            (now, now),
        )
