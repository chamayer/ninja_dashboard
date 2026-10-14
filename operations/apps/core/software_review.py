"""Software review queue: undecided software grouped by publisher.

Design 4.7/4.8: every undecided installed title is one finding (rare software
on few devices, non-approved software above that). Title findings are never
hidden under a publisher: the queue groups them by publisher and offers two
remediation options, approve the title or approve the publisher. A decision is
the action that closes the prompt, so a global decision resolves the matching
prompt findings at once instead of waiting for the next reconcile run.
"""

from __future__ import annotations

import json
from typing import Any

# The decision-prompt finding types, as a query predicate (they close when a
# decision covers the title or its publisher).
PROMPTS_SQL = """
SELECT finding.id::text, finding_type.name, finding.severity, finding.finding_details,
       finding.last_seen_at, finding_type.default_decision_scope
  FROM operations.findings finding
  JOIN operations.finding_types finding_type ON finding_type.id = finding.finding_type_id
 WHERE finding.tenant_id = %s
   AND finding.status IN ('open', 'acknowledged')
   AND finding_type.name IN ('whitelist_suggestion', 'rare_recent')
"""

DEVICES_SQL = """
SELECT DISTINCT lower(installation.canonical_name), installation.device_id::text,
       device.canonical_hostname, client.slug, client.display_name
  FROM operations.software_installations_current installation
  JOIN operations.devices device
    ON device.tenant_id = installation.tenant_id AND device.id = installation.device_id
   AND device.deleted_at IS NULL
  LEFT JOIN operations.clients client
    ON client.tenant_id = installation.tenant_id AND client.id = installation.client_id
 WHERE installation.tenant_id = %s
   AND installation.stale_since IS NULL AND installation.deleted_at IS NULL
   AND lower(installation.canonical_name) = ANY(%s)
"""

_RESOLVE_SQL = """
UPDATE operations.findings finding
   SET status = 'resolved',
       closed_at = COALESCE(finding.closed_at, now()),
       last_seen_at = now(),
       finding_details = finding.finding_details || %(resolution)s::jsonb
  FROM operations.finding_types finding_type
 WHERE finding_type.id = finding.finding_type_id
   AND finding.tenant_id = %(tenant_id)s
   AND finding.status IN ('open', 'acknowledged')
   AND {predicate}
"""

DEVICE_COUNTS_SQL = """
SELECT (finding.finding_details->>'fleet_device_count')::int AS devices, count(*)
  FROM operations.findings finding
  JOIN operations.finding_types finding_type ON finding_type.id = finding.finding_type_id
 WHERE finding.tenant_id = %s AND finding.status IN ('open', 'acknowledged')
   AND finding_type.name IN ('whitelist_suggestion', 'rare_recent')
   AND finding.finding_details->>'fleet_device_count' IS NOT NULL
 GROUP BY 1
"""


def rare_limit_preview(distribution: dict[int, int], limit: int, current: int) -> dict[str, int]:
    """How undecided titles would split at ``limit`` devices, against ``current``.

    ``distribution`` maps a device count to the number of undecided titles with
    that many devices. A title is rare at or below the limit and non-approved
    above it, so every undecided title is exactly one of the two.
    """
    total = sum(distribution.values())
    rare = sum(count for devices, count in distribution.items() if devices <= limit)
    rare_now = sum(count for devices, count in distribution.items() if devices <= current)
    return {
        "limit": limit, "total": total, "rare": rare, "non_approved": total - rare,
        "moves": abs(rare - rare_now),
    }


def build_groups(
    rows: list[tuple],
    *,
    query: str = "",
    kind: str = "",
    suggestion: str = "",
) -> list[dict[str, Any]]:
    """Group prompt findings by publisher, largest decision leverage first."""
    from .models import SoftwareSuggestionRule

    query = query.strip().lower()
    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    type_labels = {"rare_recent": "Rare", "whitelist_suggestion": "Non-approved"}
    suggestion_labels = dict(SoftwareSuggestionRule.Suggestion.choices)
    groups: dict[str, dict[str, Any]] = {}
    for finding_id, type_name, severity, raw_details, last_seen, default_scope in rows:
        details = raw_details if isinstance(raw_details, dict) else {}
        title = details.get("canonical_name") or ""
        publisher = details.get("publisher") or ""
        if kind and type_name != kind:
            continue
        title_suggestion = details.get("suggestion") or "none"
        if suggestion and title_suggestion != suggestion:
            continue
        if query and query not in title.lower() and query not in publisher.lower():
            continue
        signals = [s for s in (details.get("signals") or []) if isinstance(s, str)]
        devices = int(details.get("fleet_device_count") or 0)
        entry = {
            "finding_id": finding_id,
            "type_name": type_name,
            "type_label": type_labels.get(type_name, type_name),
            "severity": severity,
            "title": title,
            "publisher": publisher,
            "devices": devices,
            "clients": int(details.get("client_count") or 0),
            "recent": bool(details.get("recent")),
            "first_seen_at": details.get("first_seen_at"),
            "signals": signals,
            "suggestion": title_suggestion,
            "suggestion_label": suggestion_labels.get(title_suggestion, title_suggestion),
            "default_scope": default_scope or "global",
            "last_seen_at": last_seen,
            "device_targets": [],
        }
        key = publisher.lower()
        group = groups.setdefault(
            key,
            {"publisher": publisher, "titles": [], "devices": 0, "concerns": 0},
        )
        group["titles"].append(entry)
        group["devices"] += devices
        group["concerns"] += int(bool(signals))
    for group in groups.values():
        group["titles"].sort(
            key=lambda t: (severity_rank.get(t["severity"], 9), -t["devices"], t["title"].lower())
        )
        if not group["publisher"]:
            group["suggestion"], group["suggestion_label"] = "decide_titles", "Decide each title"
        elif group["concerns"]:
            group["suggestion"] = "review_titles"
            group["suggestion_label"] = f"Review titles first ({group['concerns']} with concerns)"
        elif any(t["suggestion"] == "approve_publisher" for t in group["titles"]):
            group["suggestion"], group["suggestion_label"] = "approve_publisher", "Approve publisher"
        else:
            group["suggestion"], group["suggestion_label"] = "decide_titles", "Decide each title"
    return sorted(
        groups.values(),
        key=lambda g: (-len(g["titles"]), -g["devices"], g["publisher"].lower()),
    )


def paginate(items: list, page: int, per_page: int = 40) -> tuple[list, int, int]:
    pages = max(1, -(-len(items) // per_page))
    page = min(max(1, page), pages)
    start = (page - 1) * per_page
    return items[start : start + per_page], page, pages


def attach_device_targets(cur: Any, tenant_id: int, groups: list[dict], rare_limit: int) -> None:
    """Device choices for rare titles, so a decision can default to the device."""
    titles = sorted({
        t["title"].lower() for g in groups for t in g["titles"]
        if t["devices"] and t["devices"] <= rare_limit
    })
    if not titles:
        return
    cur.execute(DEVICES_SQL, (tenant_id, titles))
    targets: dict[str, list[dict[str, str]]] = {}
    for title_key, device_id, hostname, client_slug, client_name in cur.fetchall():
        targets.setdefault(title_key, []).append({
            "device_id": device_id, "hostname": hostname or device_id,
            "client_slug": client_slug or "", "client_name": client_name or "",
        })
    for group in groups:
        for title in group["titles"]:
            title["device_targets"] = targets.get(title["title"].lower(), [])


def resolve_decided_prompts(
    cur: Any,
    *,
    tenant_id: int,
    canonical_names: list[str],
    publishers: list[str],
    decision: str,
    actor: str,
    decided_at: str,
) -> int:
    """Close the prompt findings a global decision answers, immediately.

    Any decision answers a title's prompt. A publisher decision also answers its
    titles' non-approved prompts, and their rare prompts only where no other
    signal of concern is recorded (design D9); the reconcile keeps the rest.
    """
    resolution = json.dumps({"resolution": {
        "reason": "decision_recorded",
        "detail": f"A {decision.replace('_', ' ')} decision now covers this software.",
        "resolved_by": actor,
        "resolved_at": decided_at,
    }})
    closed = 0
    names = [n.strip().lower() for n in canonical_names if n.strip()]
    pubs = [p.strip().lower() for p in publishers if p.strip()]
    params = {"tenant_id": tenant_id, "resolution": resolution}
    if names:
        cur.execute(
            _RESOLVE_SQL.format(predicate=(
                "finding_type.name IN ('whitelist_suggestion', 'rare_recent') "
                "AND lower(finding.finding_details->>'canonical_name') = ANY(%(names)s)"
            )),
            {**params, "names": names},
        )
        closed += max(cur.rowcount, 0)
    if pubs:
        cur.execute(
            _RESOLVE_SQL.format(predicate=(
                "lower(finding.finding_details->>'publisher') = ANY(%(pubs)s) AND ("
                "finding_type.name = 'whitelist_suggestion' OR ("
                "finding_type.name = 'rare_recent' AND COALESCE(jsonb_array_length("
                "CASE WHEN jsonb_typeof(finding.finding_details->'signals') = 'array' "
                "THEN finding.finding_details->'signals' END), 0) = 0))"
            )),
            {**params, "pubs": pubs},
        )
        closed += max(cur.rowcount, 0)
    return closed
