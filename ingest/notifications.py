"""Operations-native notification dispatcher (Track 2).

Reads open findings + admin findings, matches them against enabled
`notification_rules` (most-specific-first), respects `suppression_rules`
and per-rule cooldown via `notification_state`, sends via the rule's
`notification_route` (webhook / email / zendesk), records every attempt
in `notification_events`.

Legacy reference: ingest/agent_compliance/alerts.py — same routing
semantics, ported to the operations schema.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any

import httpx
from psycopg.rows import dict_row
from psycopg.types.json import Json

from ingest import db
from ingest.config import settings

log = logging.getLogger(__name__)

_TENANT_ID = 1

_SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
_CONFIDENCE_RANK = {"": 0, "possible": 1, "probable": 2, "confirmed": 3}


def dispatch(tenant_id: int = _TENANT_ID) -> int:
    """Dispatch all eligible pending findings. Returns count sent."""
    if not settings.NOTIFY_ENABLED:
        log.info("notifications: NOTIFY_ENABLED false — skipping dispatch")
        return 0

    now = datetime.now(timezone.utc)
    sent = 0

    with db.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SET LOCAL operations.tenant_id = {tenant_id}")
        rules = _load_rules(cur, tenant_id)
        if not rules:
            log.info("notifications: no enabled rules — nothing to dispatch")
            return 0
        suppressions = _load_suppressions(cur, tenant_id)
        findings = _load_pending_findings(cur, tenant_id)

    log.info(
        "notifications: %d candidate findings, %d rules, %d suppressions",
        len(findings), len(rules), len(suppressions),
    )

    for f in findings:
        if _is_suppressed(f, suppressions):
            _record_event(f, None, "", "suppressed", "", "", {}, now)
            continue
        rule = _match_rule(f, rules)
        if rule is None:
            continue
        fingerprint = f.get("condition_key") or _fallback_fingerprint(f)
        if _in_cooldown(fingerprint, rule, now):
            continue
        route = _load_route(rule["route_id"])
        if route is None:
            _record_event(f, rule["id"], "", "skipped_no_route", "", "", {}, now)
            continue
        payload = _build_payload(f)
        status, code, preview = _send(route, payload)
        _record_event(
            f, rule["id"],
            route.get("channel") or "",
            status, code or "", preview or "",
            payload, now,
        )
        if status == "sent":
            _upsert_state(fingerprint, rule["id"], now, rule["cooldown_hours"])
            sent += 1

    log.info("notifications: sent %d", sent)
    return sent


# ── loaders ─────────────────────────────────────────────────────────────


def _load_rules(cur, tenant_id: int) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT r.id, r.finding_type_id, r.finding_class, r.min_severity,
               r.min_confidence, r.client_id, r.match_criteria,
               r.route_id, r.urgency_hours, r.cooldown_hours,
               ft.name AS finding_type_name
        FROM operations.notification_rules r
        JOIN operations.finding_types ft ON ft.id = r.finding_type_id
        WHERE r.tenant_id = %s AND r.enabled = TRUE
        ORDER BY
            (r.client_id IS NULL),
            (r.match_criteria->>'platform' IS NULL),
            (r.match_criteria->>'device_scope' IS NULL)
        """,
        (tenant_id,),
    )
    return cur.fetchall()


def _load_suppressions(cur, tenant_id: int) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT s.id, s.finding_type_id, s.subject_match, s.expires_at,
               ft.name AS finding_type_name
        FROM operations.suppression_rules s
        JOIN operations.finding_types ft ON ft.id = s.finding_type_id
        WHERE s.tenant_id = %s
          AND (s.expires_at IS NULL OR s.expires_at > NOW())
        """,
        (tenant_id,),
    )
    return cur.fetchall()


def _load_pending_findings(cur, tenant_id: int) -> list[dict[str, Any]]:
    """Union of entity + admin findings, both open/acknowledged."""
    cur.execute(
        """
        SELECT f.id, f.finding_type_id, f.client_id,
               f.subject_type, f.subject_id, f.finding_details,
               f.condition_key, f.severity, f.confidence, f.status,
               f.first_seen_at, f.last_seen_at, f.last_detected_at,
               ft.name AS finding_type_name,
               ft.finding_class AS finding_class,
               'entity' AS finding_row_kind
        FROM operations.findings f
        JOIN operations.finding_types ft ON ft.id = f.finding_type_id
        WHERE f.tenant_id = %s AND f.status IN ('open', 'acknowledged')

        UNION ALL

        SELECT af.id, af.finding_type_id, NULL AS client_id,
               '' AS subject_type, NULL AS subject_id,
               af.details AS finding_details,
               af.condition_key, af.severity, '' AS confidence, af.status,
               af.first_detected_at AS first_seen_at,
               af.last_detected_at AS last_seen_at,
               af.last_detected_at AS last_detected_at,
               ft.name AS finding_type_name,
               ft.finding_class AS finding_class,
               'admin' AS finding_row_kind
        FROM operations.admin_findings af
        JOIN operations.finding_types ft ON ft.id = af.finding_type_id
        WHERE af.tenant_id = %s AND af.status IN ('open', 'acknowledged')
        """,
        (tenant_id, tenant_id),
    )
    return cur.fetchall()


def _load_route(route_id) -> dict[str, Any] | None:
    with db.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SET LOCAL operations.tenant_id = {_TENANT_ID}")
        cur.execute(
            "SELECT id, channel, target, mode FROM operations.notification_routes"
            " WHERE tenant_id = %s AND id = %s",
            (_TENANT_ID, route_id),
        )
        return cur.fetchone()


# ── matching + cooldown ─────────────────────────────────────────────────


def _is_suppressed(finding: dict, suppressions: list[dict]) -> bool:
    ft_id = finding["finding_type_id"]
    details = finding.get("finding_details") or {}
    for s in suppressions:
        if s["finding_type_id"] != ft_id:
            continue
        subj = s.get("subject_match") or {}
        if not subj:
            return True
        if _subject_matches(subj, finding, details):
            return True
    return False


def _subject_matches(subj: dict, finding: dict, details: dict) -> bool:
    for key, want in subj.items():
        if want in (None, ""):
            continue
        if key == "client_id":
            if str(finding.get("client_id")) != str(want):
                return False
        elif key == "device_id":
            if str(finding.get("subject_id")) != str(want):
                return False
        elif key == "platform":
            if str(details.get("platform")) != str(want):
                return False
        elif key == "finding_type":
            if finding.get("finding_type_name") != want:
                return False
    return True


def _match_rule(finding: dict, rules: list[dict]) -> dict | None:
    ft_id = finding["finding_type_id"]
    details = finding.get("finding_details") or {}
    fclass = finding.get("finding_class") or ""
    sev_rank = _SEVERITY_RANK.get(finding.get("severity") or "", 0)
    conf_rank = _CONFIDENCE_RANK.get(finding.get("confidence") or "", 0)
    for r in rules:
        if r["finding_type_id"] != ft_id:
            continue
        if r.get("finding_class") and r["finding_class"] != fclass:
            continue
        rmin_sev = r.get("min_severity") or ""
        if rmin_sev and _SEVERITY_RANK.get(rmin_sev, 0) > sev_rank:
            continue
        rmin_conf = r.get("min_confidence") or ""
        if rmin_conf and _CONFIDENCE_RANK.get(rmin_conf, 0) > conf_rank:
            continue
        rclient = r.get("client_id")
        if rclient and str(rclient) != str(finding.get("client_id")):
            continue
        crit = r.get("match_criteria") or {}
        want_platform = crit.get("platform")
        if want_platform and str(details.get("platform")) != str(want_platform):
            continue
        want_scope = crit.get("device_scope")
        if want_scope and str(details.get("device_scope")) != str(want_scope):
            continue
        return r
    return None


def _in_cooldown(fingerprint: str, rule: dict, now: datetime) -> bool:
    if not fingerprint:
        return False
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(f"SET LOCAL operations.tenant_id = {_TENANT_ID}")
        cur.execute(
            "SELECT next_allowed_at FROM operations.notification_state"
            " WHERE tenant_id = %s AND fingerprint = %s AND rule_id = %s",
            (_TENANT_ID, fingerprint, rule["id"]),
        )
        row = cur.fetchone()
    if not row or row[0] is None:
        return False
    nxt = row[0]
    if nxt.tzinfo is None:
        nxt = nxt.replace(tzinfo=timezone.utc)
    return nxt > now


def _upsert_state(fingerprint: str, rule_id, now: datetime, cooldown_hours: int) -> None:
    if not fingerprint:
        return
    nxt = now + timedelta(hours=cooldown_hours or 0)
    with db.transaction() as cur:
        cur.execute(f"SET LOCAL operations.tenant_id = {_TENANT_ID}")
        cur.execute(
            """
            INSERT INTO operations.notification_state
                (id, tenant_id, fingerprint, rule_id,
                 last_sent_at, next_allowed_at, send_count)
            VALUES (gen_random_uuid(), %s, %s, %s, %s, %s, 1)
            ON CONFLICT (tenant_id, fingerprint, rule_id)
            DO UPDATE SET
                last_sent_at = EXCLUDED.last_sent_at,
                next_allowed_at = EXCLUDED.next_allowed_at,
                send_count = operations.notification_state.send_count + 1
            """,
            (_TENANT_ID, fingerprint, rule_id, now, nxt),
        )


def _fallback_fingerprint(finding: dict) -> str:
    raw = f"{finding['finding_type_name']}:{finding.get('subject_id') or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


# ── senders ─────────────────────────────────────────────────────────────


def _send(route: dict, payload: dict) -> tuple[str, int | None, str | None]:
    channel = route["channel"]
    if channel == "webhook":
        return _send_webhook(route, payload)
    if channel == "email":
        return _send_email(route, payload)
    if channel == "zendesk":
        return _send_zendesk(payload)
    return "skipped_unknown_channel", None, channel


def _send_webhook(route: dict, payload: dict) -> tuple[str, int | None, str | None]:
    target = route.get("target") or ""
    url = os.environ.get(target) if target and not target.startswith("http") else target
    if not url:
        return "skipped_no_route", None, None
    try:
        resp = httpx.post(url, json=payload, timeout=20)
        preview = (resp.text or "")[:500]
        return ("sent" if resp.is_success else "failed"), resp.status_code, preview
    except Exception as exc:
        return "failed", None, str(exc)[:500]


def _send_email(route: dict, payload: dict) -> tuple[str, int | None, str | None]:
    host = settings.notify_smtp_host
    to_addr = route.get("target") or settings.notify_email_to
    if not host or not to_addr:
        return "skipped_no_route", None, None
    msg = EmailMessage()
    msg["From"] = settings.notify_email_from or settings.notify_smtp_username
    msg["To"] = to_addr
    msg["Subject"] = f"[{payload['severity'].upper()}] {payload['title']}"
    msg.set_content(_text_body(payload))
    try:
        with smtplib.SMTP(host, settings.notify_smtp_port, timeout=20) as smtp:
            if settings.notify_smtp_starttls:
                smtp.starttls()
            pw = settings.notify_smtp_password.get_secret_value()
            if settings.notify_smtp_username and pw:
                smtp.login(settings.notify_smtp_username, pw)
            smtp.send_message(msg)
        return "sent", None, "email sent"
    except Exception as exc:
        return "failed", None, str(exc)[:500]


def _send_zendesk(payload: dict) -> tuple[str, int | None, str | None]:
    url = settings.notify_zendesk_url
    requester = settings.notify_zendesk_requester_email
    if not url or not requester:
        return "skipped_no_route", None, None
    if not url.endswith("/api/v2/requests"):
        url = url.rstrip("/") + "/api/v2/requests"
    body = {
        "request": {
            "requester": {
                "email": requester,
                "name": settings.notify_zendesk_requester_name or "Operations",
            },
            "subject": f"[{payload['severity'].upper()}] {payload['title']}",
            "comment": {"body": _text_body(payload)},
        }
    }
    auth = None
    token = settings.notify_zendesk_auth_token.get_secret_value()
    if settings.notify_zendesk_auth_username and token:
        auth = (settings.notify_zendesk_auth_username, token)
    try:
        resp = httpx.post(url, json=body, auth=auth, timeout=20)
        preview = (resp.text or "")[:500]
        return ("sent" if resp.is_success else "failed"), resp.status_code, preview
    except Exception as exc:
        return "failed", None, str(exc)[:500]


def _build_payload(finding: dict) -> dict:
    details = finding.get("finding_details") or {}
    return {
        "title": finding["finding_type_name"],
        "severity": finding.get("severity") or "info",
        "confidence": finding.get("confidence") or "",
        "client_id": str(finding.get("client_id") or ""),
        "subject_type": finding.get("subject_type") or "",
        "subject_id": str(finding.get("subject_id") or ""),
        "hostname": details.get("hostname") or "",
        "platform": details.get("platform") or "",
        "details": details,
        "condition_key": finding.get("condition_key") or "",
        "first_seen_at": (finding.get("first_seen_at") or "").isoformat() if finding.get("first_seen_at") else "",
        "last_seen_at": (finding.get("last_seen_at") or "").isoformat() if finding.get("last_seen_at") else "",
    }


def _text_body(payload: dict) -> str:
    return "\n".join([
        payload["title"],
        "",
        f"Severity: {payload['severity']}",
        f"Confidence: {payload['confidence'] or 'n/a'}",
        f"Platform: {payload['platform'] or 'n/a'}",
        f"Host: {payload['hostname'] or 'n/a'}",
        "",
        "Details:",
        json.dumps(payload["details"], indent=2, default=str),
    ])


def _record_event(
    finding: dict,
    rule_id,
    channel: str,
    status: str,
    response_code,
    response_preview: str,
    payload: dict,
    now: datetime,
) -> None:
    fingerprint = finding.get("condition_key") or _fallback_fingerprint(finding)
    ref = {
        "response_code": response_code,
        "response_preview": response_preview,
        "payload": payload,
    }
    with db.transaction() as cur:
        cur.execute(f"SET LOCAL operations.tenant_id = {_TENANT_ID}")
        cur.execute(
            """
            INSERT INTO operations.notification_events
                (id, tenant_id, rule_id, fingerprint, channel, status,
                 payload_ref, error, sent_at)
            VALUES (gen_random_uuid(), %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                _TENANT_ID, rule_id, fingerprint,
                channel,
                status, Json(ref),
                response_preview if status == "failed" else "",
                now,
            ),
        )
