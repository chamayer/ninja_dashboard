"""Immutable generic source-event capture and safe withdrawal confirmation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from psycopg.types.json import Json

_TENANT_ID = 1
_NINJA_DELETE = "NODE_DELETED"


def _plain_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Json):
        value = value.obj
    return value if isinstance(value, dict) else {}


def _stable_hash(payload: dict[str, Any]) -> bytes:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).digest()


def capture_ninja_events(cur, rows: list[dict[str, Any]]) -> dict[str, int | str]:
    """Capture new Ninja activities without logging protected event content."""
    totals: dict[str, int | str] = {
        "status": "complete",
        "inserted": 0,
        "confirmed": 0,
        "unresolved": 0,
        "out_of_order": 0,
    }
    # SET LOCAL cannot take a bind parameter. ingest/ uses raw psycopg3,
    # which binds server-side, so %s arrives as $1 and Postgres raises
    # `syntax error at or near "$1"`. set_config() is the parameterisable
    # equivalent. NOTE: the same pattern in operations/ is fine — Django's
    # backend uses client-side binding (ClientCursor), so %s is already
    # interpolated by the time Postgres sees it. Do not "fix" those.
    # This broke the activities ingest for ~21h after 0.107.0.
    cur.execute(
        "SELECT set_config('operations.tenant_id', %s, true)",
        (str(_TENANT_ID),),
    )
    cur.execute("SELECT to_regclass('operations.source_events') IS NOT NULL")
    if not cur.fetchone()[0]:
        totals["status"] = "migration_pending"
        return totals

    cur.execute(
        """
        SELECT si.id
          FROM operations.source_instances si
          JOIN operations.sources source ON source.id = si.source_id
         WHERE si.tenant_id = %s AND si.enabled
           AND lower(source.name) = lower('Ninja')
         ORDER BY si.id
        """,
        (_TENANT_ID,),
    )
    source_instances = [row[0] for row in cur.fetchall()]
    if len(source_instances) != 1:
        totals["status"] = "source_instance_ambiguous"
        return totals
    source_instance_id = source_instances[0]

    for row in rows:
        payload = _plain_payload(row.get("data"))
        event_id = payload.get("id", row.get("id"))
        event_type = payload.get("statusCode", row.get("activity_type"))
        event_at = row.get("activity_time")
        if event_id is None or not event_type or not isinstance(event_at, datetime):
            continue
        subject_id = payload.get("deviceId")
        actor_id = payload.get("userId")
        actor_display = {
            key: payload[key]
            for key in ("userName", "username", "userEmail", "email")
            if payload.get(key) not in (None, "")
        }
        received_at = datetime.now(timezone.utc)
        source_event_id = None
        cur.execute(
            """
            INSERT INTO operations.source_events (
                id, tenant_id, version, source_instance_id, source_binding_id,
                external_event_id, event_type, event_at, received_at,
                subject_external_namespace, subject_parent_external_namespace,
                subject_parent_external_id, subject_external_id,
                source_actor_id, source_actor_display, outcome, raw_event,
                raw_hash, processing_status, processing_reason, processed_at
            ) VALUES (
                gen_random_uuid(), %s, 1, %s, NULL, %s, %s, %s, %s,
                %s, '', '', %s, %s, %s, %s, %s, %s, 'recorded', '', NULL
            )
            ON CONFLICT (tenant_id, source_instance_id, external_event_id)
            DO NOTHING RETURNING id
            """,
            (
                _TENANT_ID,
                source_instance_id,
                str(event_id),
                str(event_type),
                event_at,
                received_at,
                "device" if subject_id is not None else "",
                str(subject_id) if subject_id is not None else "",
                str(actor_id) if actor_id is not None else "",
                Json(actor_display),
                str(payload.get("activityResult") or "")[:80],
                Json(payload),
                _stable_hash(payload),
            ),
        )
        inserted = cur.fetchone()
        if inserted is None:
            continue
        source_event_id = inserted[0]
        totals["inserted"] = int(totals["inserted"]) + 1
        if event_type != _NINJA_DELETE:
            continue
        if subject_id is None:
            cur.execute(
                """
                UPDATE operations.source_events
                   SET processing_status = 'unresolved',
                       processing_reason = 'source event supplied no stable subject identity',
                       processed_at = clock_timestamp()
                 WHERE id = %s
                """,
                (source_event_id,),
            )
            totals["unresolved"] = int(totals["unresolved"]) + 1
            continue
        cur.execute(
            """
            WITH withdrawn AS (
                UPDATE operations.entity_observation_current current
                   SET active = FALSE, withdrawn_at = %s
                 WHERE current.tenant_id = %s
                   AND current.source_instance_id = %s
                   AND current.external_namespace IN ('device', 'device-health')
                   AND current.external_id = %s
                   AND current.active
                   AND current.last_seen_at <= %s
                RETURNING current.tenant_id, current.source_instance_id,
                          current.external_namespace,
                          current.parent_external_namespace,
                          current.parent_external_id, current.external_id
            ), closed AS (
                UPDATE operations.entity_observation_history history
                   SET effective_to = %s, closed_by_source_event_id = %s
                  FROM withdrawn
                 WHERE history.tenant_id = withdrawn.tenant_id
                   AND history.source_instance_id = withdrawn.source_instance_id
                   AND history.external_namespace = withdrawn.external_namespace
                   AND history.parent_external_namespace =
                       withdrawn.parent_external_namespace
                   AND history.parent_external_id = withdrawn.parent_external_id
                   AND history.external_id = withdrawn.external_id
                   AND history.effective_to IS NULL
                   AND history.effective_from < %s
                RETURNING history.id
            ), missing_links AS (
                UPDATE operations.entity_source_links link
                   SET missing_since = %s, reason = 'source_deleted',
                       version = link.version + 1
                  FROM withdrawn
                 WHERE link.tenant_id = %s
                   AND link.source_instance_id = %s
                   AND link.external_namespace = withdrawn.external_namespace
                   AND link.parent_external_namespace =
                       withdrawn.parent_external_namespace
                   AND link.parent_external_id = withdrawn.parent_external_id
                   AND link.external_id = withdrawn.external_id
                   AND link.missing_since IS NULL
                   AND link.last_seen_at <= %s
                RETURNING link.id
            )
            SELECT (SELECT count(*) FROM withdrawn),
                   (SELECT count(*) FROM closed),
                   (SELECT count(*) FROM missing_links)
            """,
            (
                event_at,
                _TENANT_ID,
                source_instance_id,
                str(subject_id),
                event_at,
                event_at,
                source_event_id,
                event_at,
                event_at,
                _TENANT_ID,
                source_instance_id,
                event_at,
            ),
        )
        withdrawn, closed, missing_links = cur.fetchone()
        if withdrawn and withdrawn == closed:
            status = "confirmed"
            reason = "source deletion confirmed exact stable identity withdrawal"
            totals["confirmed"] = int(totals["confirmed"]) + 1
        else:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM operations.entity_observation_current current
                     WHERE current.tenant_id = %s
                       AND current.source_instance_id = %s
                       AND current.external_namespace IN ('device', 'device-health')
                       AND current.external_id = %s
                       AND current.active
                       AND current.last_seen_at > %s
                )
                """,
                (_TENANT_ID, source_instance_id, str(subject_id), event_at),
            )
            out_of_order = bool(cur.fetchone()[0])
            status = "out_of_order" if out_of_order else "unresolved"
            reason = (
                "newer source evidence supersedes deletion event"
                if out_of_order
                else "stable subject identity did not resolve to active evidence"
            )
            totals[status] = int(totals[status]) + 1
        cur.execute(
            """
            UPDATE operations.source_events
               SET processing_status = %s, processing_reason = %s,
                   processed_at = clock_timestamp()
             WHERE id = %s
            """,
            (status, reason, source_event_id),
        )
        if withdrawn != closed:
            raise RuntimeError(
                "source deletion current/history mismatch: "
                f"withdrawn={withdrawn}, closed={closed}, links={missing_links}"
            )
    return totals
