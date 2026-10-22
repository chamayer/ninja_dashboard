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

from shared import software_coverage

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

def _details(raw: Any) -> dict[str, Any]:
    """Finding details from a raw cursor row.

    Django's database connection hands back jsonb as text, so a raw query row
    carries a JSON string rather than a dict.
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def evidence_labels(details: dict[str, Any]) -> list[str]:
    """The supporting facts recorded on a finding, in the signal vocabulary."""
    from .models import SoftwareSuggestionRule

    names = dict(SoftwareSuggestionRule.Signal.choices)
    return [
        names.get(code, code.replace("_", " ")).lower()
        for code in (details.get("evidence") or [])
        if isinstance(code, str)
    ]


# Computers a rare prompt is about: only installations its decisions leave
# uncovered (ADR-0039), flagged per coverage scope.
DEVICES_SQL = f"""
SELECT lower(i.canonical_name), i.device_id::text,
       device.canonical_hostname, client.slug, client.display_name,
       bool_or({software_coverage.UNDECIDED}) AS undecided,
       bool_or({software_coverage.TITLE_OPEN}) AS title_open
  FROM operations.software_installations_current i
  JOIN operations.devices device
    ON device.tenant_id = i.tenant_id AND device.id = i.device_id
   AND device.deleted_at IS NULL
  LEFT JOIN operations.clients client
    ON client.tenant_id = i.tenant_id AND client.id = i.client_id
  {software_coverage.EFFECTIVE_DECISION_JOINS}
 WHERE i.tenant_id = %s
   AND i.stale_since IS NULL AND i.deleted_at IS NULL
   AND lower(i.canonical_name) = ANY(%s)
 GROUP BY 1, 2, 3, 4, 5
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

# Open prompts by how many computers each is about (its uncovered ones).
DEVICE_COUNTS_SQL = f"""
SELECT ({software_coverage.PROMPT_DEVICES_SQL.replace("finding_details", "finding.finding_details")})::int
           AS devices, count(*)
  FROM operations.findings finding
  JOIN operations.finding_types finding_type ON finding_type.id = finding.finding_type_id
 WHERE finding.tenant_id = %s AND finding.status IN ('open', 'acknowledged')
   AND finding_type.name IN ('whitelist_suggestion', 'rare_recent')
   AND {software_coverage.PROMPT_DEVICES_SQL.replace("finding_details", "finding.finding_details")}
       IS NOT NULL
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
        details = _details(raw_details)
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
        # The prompt is about its uncovered installations (ADR-0039).
        devices = software_coverage.prompt_devices(details) or 0
        entry = {
            "finding_id": finding_id,
            "type_name": type_name,
            "type_label": type_labels.get(type_name, type_name),
            "severity": severity,
            "title": title,
            "publisher": publisher,
            "devices": devices,
            "clients": software_coverage.prompt_clients(details),
            "fleet_devices": int(details.get("fleet_device_count") or devices),
            "covered_devices": max(int(details.get("fleet_device_count") or devices) - devices, 0),
            "title_publisher": details.get("title_publisher") or publisher,
            "uncovered_publishers": [
                p for p in (details.get("uncovered_publishers") or []) if isinstance(p, str)
            ],
            "uncovered_publisher_count": int(details.get("uncovered_publisher_count") or 0),
            "coverage_scope": details.get("coverage_scope") or software_coverage.SCOPE_UNDECIDED,
            "recent": bool(details.get("recent")),
            "first_seen_at": details.get("first_seen_at"),
            "signals": signals,
            "evidence": evidence_labels(details),
            "suggestion": title_suggestion,
            "suggestion_label": suggestion_labels.get(title_suggestion, title_suggestion),
            "default_scope": default_scope or "global",
            "last_seen_at": last_seen,
            "device_targets": [],
        }
        key = publisher.lower()
        group = groups.setdefault(
            key,
            {"publisher": publisher, "titles": [], "devices": 0, "clients": 0, "concerns": 0},
        )
        group["titles"].append(entry)
        group["devices"] += devices
        group["clients"] = max(group["clients"], entry["clients"])
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
        elif all(t["suggestion"] == "supports_approval" for t in group["titles"]):
            group["suggestion"], group["suggestion_label"] = "supports_approval", "Supports approval"
        elif any(t["suggestion"] == "approve_publisher" for t in group["titles"]):
            group["suggestion"], group["suggestion_label"] = "approve_publisher", "Approve publisher"
        else:
            group["suggestion"], group["suggestion_label"] = "decide_titles", "Decide each title"
    return sorted(
        groups.values(),
        key=lambda g: (-len(g["titles"]), -g["devices"], g["publisher"].lower()),
    )


SORT_COLUMNS = (
    ("title", "Title", False),
    ("publisher", "Publisher", False),
    ("publisher_status", "Publisher status", False),
    ("type", "Type", False),
    ("devices", "Devices", True),
    ("clients", "Clients", True),
    ("signals", "Signals", False),
    ("suggestion", "Suggested", False),
)


def sort_titles(titles: list[dict[str, Any]], key: str, direction: str) -> list[dict[str, Any]]:
    """Sort every title as one table, by any displayed column."""
    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    keys = {
        "title": lambda t: t["title"].lower(),
        "publisher": lambda t: (t["publisher"] == "", t["publisher"].lower()),
        "publisher_status": lambda t: _STATUS_ORDER.get(t.get("publisher_status", "none"), 9),
        "type": lambda t: (t["type_label"], severity_rank.get(t["severity"], 9)),
        "devices": lambda t: t["devices"],
        "clients": lambda t: t["clients"],
        "signals": lambda t: (len(t["signals"]), ", ".join(t["signals"])),
        "suggestion": lambda t: t["suggestion_label"],
    }
    if key not in keys:
        key = "devices"
        direction = "desc"
    ordered = sorted(titles, key=lambda t: t["title"].lower())
    return sorted(ordered, key=keys[key], reverse=(direction == "desc"))


GROUP_COLUMNS = (
    ("publisher", "Publisher", False),
    ("publisher_status", "Publisher status", False),
    ("titles", "Titles", True),
    ("installs", "Installs", True),
    ("clients", "Clients (widest title)", True),
    ("flagged", "Flagged titles", True),
    ("suggestion", "Suggested", False),
)


def sort_groups(groups: list[dict[str, Any]], key: str, direction: str) -> list[dict[str, Any]]:
    """Sort the publisher rows by any of their totals."""
    keys = {
        "publisher": lambda g: (g["publisher"] == "", g["publisher"].lower()),
        "publisher_status": lambda g: _STATUS_ORDER.get(g.get("publisher_status", "none"), 9),
        "titles": lambda g: len(g["titles"]),
        "installs": lambda g: g["devices"],
        "clients": lambda g: g["clients"],
        "flagged": lambda g: g["concerns"],
        "suggestion": lambda g: g["suggestion_label"],
    }
    if key not in keys:
        key, direction = "titles", "desc"
    ordered = sorted(groups, key=lambda g: g["publisher"].lower())
    return sorted(ordered, key=keys[key], reverse=(direction == "desc"))


GROUP_TITLES_SHOWN = 50


def trim_group_titles(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cap the titles listed under each publisher; the rest stay one click away."""
    return [
        {**group, "titles": group["titles"][:GROUP_TITLES_SHOWN],
         "title_count": len(group["titles"])}
        for group in groups
    ]


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
    targets: dict[str, list[dict[str, Any]]] = {}
    for title_key, device_id, hostname, client_slug, client_name, undecided, title_open in (
        cur.fetchall()
    ):
        targets.setdefault(title_key, []).append({
            "device_id": device_id, "hostname": hostname or device_id,
            "client_slug": client_slug or "", "client_name": client_name or "",
            software_coverage.SCOPE_UNDECIDED: undecided,
            software_coverage.SCOPE_TITLE_OPEN: title_open,
        })
    for group in groups:
        for title in group["titles"]:
            scope = title.get("coverage_scope") or software_coverage.SCOPE_UNDECIDED
            title["device_targets"] = [
                target for target in targets.get(title["title"].lower(), []) if target[scope]
            ]


_APPROVED = ("approve", "approve_publisher")
_DECISION_LABELS = {
    "approve": "Approved", "approve_publisher": "Approved",
    "investigate": "Investigating", "reject": "Rejected",
}

# Per open title under an approved publisher: how many live installs carry a
# different publisher text or none, which is what keeps the approval off them.
HOLD_SQL = """
SELECT pair.title_key, count(*) AS installs,
       count(*) FILTER (WHERE COALESCE(installation.publisher, '') = '') AS blank,
       count(*) FILTER (WHERE COALESCE(installation.publisher, '') <> ''
                          AND lower(installation.publisher) <> pair.publisher_key) AS differs,
       array_agg(DISTINCT installation.publisher) FILTER (
           WHERE COALESCE(installation.publisher, '') <> ''
             AND lower(installation.publisher) <> pair.publisher_key) AS other_names
  FROM unnest(%s::text[], %s::text[]) AS pair(title_key, publisher_key)
  JOIN operations.software_installations_current installation
    ON installation.tenant_id = %s AND lower(installation.canonical_name) = pair.title_key
   AND installation.stale_since IS NULL AND installation.deleted_at IS NULL
 GROUP BY pair.title_key
"""


HOLD_NAMES_SHOWN = 3


def hold_reasons(title: dict[str, Any], installs: int, blank: int, differs: int,
                 other_names: list[str]) -> list[str]:
    """Why an approved publisher does not cover this open title, in plain words."""
    reasons = []
    if title["type_name"] == "rare_recent" and title["signals"]:
        reasons.append("rare with a concern, so the publisher approval does not cover it")
    if differs:
        shown = sorted(other_names)[:HOLD_NAMES_SHOWN]
        names = ", ".join(shown) + (" …" if len(other_names) > len(shown) else "")
        reasons.append(f"publisher name differs on {differs} of {installs} installs ({names})")
    if blank:
        reasons.append(f"no publisher on {blank} of {installs} installs")
    if not reasons:
        reasons.append("covered now; closes on the next software check")
    return reasons


def publisher_decisions(tenant_id: int, keys: list[str]) -> dict[str, dict[str, Any]]:
    """Stored publisher-level decisions by lower-case publisher: the global one
    and how many narrower (client or computer) ones exist."""
    from django.db.models.functions import Lower

    from .models import SoftwareDecision

    rows = (
        SoftwareDecision.objects.filter(tenant_id=tenant_id)
        .exclude(publisher="")
        .annotate(publisher_key=Lower("publisher"))
        .filter(publisher_key__in=keys)
        .select_related("decided_by")
    )
    decisions: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = decisions.setdefault(row.publisher_key, {"global": None, "narrower": 0})
        if row.client_id is None and row.device_id is None:
            entry["global"] = {
                "decision": row.decision,
                "label": _DECISION_LABELS.get(row.decision, row.decision),
                "approved": row.decision in _APPROVED, "decided_at": row.decided_at,
                "decided_by": row.decided_by.get_username() if row.decided_by else "",
                "reason": row.reason or "",
            }
        else:
            entry["narrower"] += 1
    return decisions


def attach_publisher_status(cur: Any, tenant_id: int, groups: list[dict]) -> None:
    """The publisher's current decision on each group, and per title why it is still open.

    Run before ``trim_group_titles`` so the override can name every open title.
    """
    keys = sorted({
        key for g in groups
        for key in [g.get("publisher", "").lower()] + [t["publisher"].lower() for t in g["titles"]]
        if key
    })
    if not keys:
        return
    decisions = publisher_decisions(tenant_id, keys)
    held = [
        t for g in groups for t in g["titles"]
        if (decisions.get(t["publisher"].lower()) or {}).get("global")
        and decisions[t["publisher"].lower()]["global"]["approved"]
    ]
    facts: dict[str, tuple] = {}
    if held:
        cur.execute(HOLD_SQL, (
            [t["title"].lower() for t in held], [t["publisher"].lower() for t in held], tenant_id,
        ))
        facts = {row[0]: row[1:] for row in cur.fetchall()}
    for title in held:
        installs, blank, differs, other_names = facts.get(title["title"].lower(), (0, 0, 0, None))
        title["hold_reasons"] = hold_reasons(title, installs, blank, differs, other_names or [])
    for group in groups:
        status = decisions.get(group.get("publisher", "").lower())
        if not status:
            continue
        group["decision"] = status["global"]
        group["narrower_decisions"] = status["narrower"]
        if status["global"] and status["global"]["approved"]:
            group["open_title_names"] = [t["title"] for t in group["titles"] if t["title"]]
            group["suggestion"] = "decide_titles"
            group["suggestion_label"] = "Publisher approved; decide what it does not cover"


PUBLISHER_STATUS_CHOICES = (
    ("approved", "Approved"),
    ("investigating", "Investigating"),
    ("rejected", "Rejected"),
    ("none", "No publisher-wide decision"),
)
_STATUS_BY_DECISION = {
    "approve": "approved",
    "approve_publisher": "approved",
    "investigate": "investigating",
    "reject": "rejected",
}


_STATUS_LABELS = dict(PUBLISHER_STATUS_CHOICES)
_STATUS_ORDER = {value: rank for rank, (value, _label) in enumerate(PUBLISHER_STATUS_CHOICES)}


def stamp_publisher_status(tenant_id: int, groups: list[dict]) -> None:
    """Record each publisher's publisher-wide status on its group and titles.

    Runs on every group before sorting, filtering and paging, so the
    Publisher status column sorts and filters across all pages. Uses the same
    stored decisions as ``attach_publisher_status``. Client or computer
    decisions are not publisher-wide and count as "none".
    """
    keys = sorted({g["publisher"].lower() for g in groups if g["publisher"]})
    decisions = publisher_decisions(tenant_id, keys) if keys else {}
    for group in groups:
        decided = (decisions.get(group["publisher"].lower()) or {}).get("global")
        status = _STATUS_BY_DECISION.get(decided["decision"], "none") if decided else "none"
        group["publisher_status"] = status
        group["publisher_status_label"] = _STATUS_LABELS[status]
        for title in group["titles"]:
            title["publisher_status"] = status
            title["publisher_status_label"] = _STATUS_LABELS[status]


def filter_by_publisher_status(groups: list[dict], status: str) -> list[dict]:
    """Keep the publisher groups stamped with ``status``."""
    return [group for group in groups if group.get("publisher_status") == status]


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
