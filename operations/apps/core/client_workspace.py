"""Presentation data for the client directory and client overview."""

from __future__ import annotations

from datetime import timedelta

from django.db import connection, transaction
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from .models import Finding, MergeCandidate
from .templatetags.human_labels import humanize_label

ACTIVE_FINDING_STATUSES = ("open", "acknowledged", "investigating")
DOMAIN_BY_CATEGORY = {
    "patching": "patching",
    "coverage": "compliance",
    "software": "software",
    "identity": "inventory",
    "lifecycle": "inventory",
    "data_quality": "inventory",
}
DOMAIN_LABEL_BY_CATEGORY = {
    "patching": "Patching",
    "coverage": "Compliance",
    "software": "Software",
    "identity": "Inventory",
    "lifecycle": "Inventory",
    "data_quality": "Inventory",
}
STATE_LABELS = {
    "needs_action": "Needs action",
    "review": "Review",
    "monitor": "Monitor",
    "on_track": "On track",
    "delayed": "Data delayed",
    "unavailable": "Data unavailable",
}
STATE_PRIORITY = {
    "needs_action": 3,
    "review": 2,
    "monitor": 1,
    "on_track": 0,
    "delayed": 0,
    "unavailable": 0,
}
SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
EXPECTED_SOURCES = ("Ninja", "SentinelOne", "ScreenConnect", "LogMeIn")


def _empty_stats() -> dict:
    return {"severities": {}, "types": {}, "subjects": {}, "total": 0, "new": 0}


def _issue_state(stats: dict) -> str:
    severities = stats["severities"]
    if severities.get("critical"):
        return "needs_action"
    if severities.get("high"):
        return "review"
    if any(severities.get(level) for level in ("medium", "low", "info")):
        return "monitor"
    return "on_track"


def _display_state(
    stats: dict, *, has_data: bool = True, data_delayed: bool = False
) -> tuple[str, str]:
    state = _issue_state(stats)
    if state != "on_track":
        return state, STATE_LABELS[state]
    if not has_data:
        return "unavailable", "Data unavailable"
    if data_delayed and state == "on_track":
        return "delayed", "Data delayed"
    return state, STATE_LABELS[state]


def _issue_rollup(*, client_id=None) -> tuple[dict, list[dict]]:
    filters = {
        "tenant_id": 1,
        "status__in": ACTIVE_FINDING_STATUSES,
        "finding_type__category__name__in": DOMAIN_BY_CATEGORY,
    }
    if client_id is not None:
        filters["client_id"] = client_id
    rows = (
        Finding.objects.filter(**filters)
        .filter(Q(snoozed_until__isnull=True) | Q(snoozed_until__lt=timezone.now()))
        .values(
            "client_id",
            "finding_type__category__name",
            "finding_type__name",
            "severity",
        )
        .annotate(
            n=Count("id"),
            subjects=Count("subject_id", distinct=True),
            new=Count(
                "id",
                filter=Q(first_seen_at__gte=timezone.now() - timedelta(hours=24)),
            ),
        )
    )
    stats_by_client: dict = {}
    detail_rows = []
    for row in rows:
        domain_key = DOMAIN_BY_CATEGORY[row["finding_type__category__name"]]
        stats = stats_by_client.setdefault(row["client_id"], {}).setdefault(
            domain_key, _empty_stats()
        )
        severity = row["severity"]
        finding_type = row["finding_type__name"]
        stats["severities"][severity] = stats["severities"].get(severity, 0) + row["n"]
        stats["types"][finding_type] = stats["types"].get(finding_type, 0) + row["n"]
        stats["subjects"][finding_type] = row["subjects"]
        stats["total"] += row["n"]
        stats["new"] += row["new"]
        detail_rows.append({**row, "domain_key": domain_key})
    return stats_by_client, detail_rows


def _count(stats: dict, finding_type: str, *, subjects: bool = False) -> int:
    return stats["subjects" if subjects else "types"].get(finding_type, 0)


def _operator_label(value: str) -> str:
    label = humanize_label(value)
    return label if label != value else value.replace("_", " ").capitalize()


def _panel(
    *,
    key: str,
    name: str,
    description: str,
    value: str,
    value_label: str,
    facts: list[dict],
    href: str,
    updated_at,
    stats: dict | None = None,
    has_data: bool = True,
    delayed: bool = False,
    forced_state: str | None = None,
) -> dict:
    panel_stats = stats or _empty_stats()
    issue_state = _issue_state(panel_stats)
    state, state_label = _display_state(panel_stats, has_data=has_data, data_delayed=delayed)
    if forced_state:
        issue_state = forced_state
        state = forced_state
        state_label = STATE_LABELS[forced_state]
    return {
        "key": key,
        "name": name,
        "description": description,
        "value": value,
        "value_label": value_label,
        "facts": facts,
        "href": href,
        "issue_state": issue_state,
        "state": state,
        "state_label": state_label,
        "updated_at": updated_at,
    }


def _shared_context() -> tuple[dict, dict, dict]:
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """
            SELECT cl.client_id, COUNT(DISTINCT l.id)::int
            FROM operations.client_links cl
            JOIN operations.sources s ON s.id = cl.source_id
            JOIN ninja_core.locations l
              ON s.name = 'Ninja'
             AND cl.external_id ~ '^[0-9]+$'
             AND l.organization_id = cl.external_id::integer
            WHERE cl.tenant_id = 1
            GROUP BY cl.client_id
            """
        )
        locations = dict(cur.fetchall())
        cur.execute(
            """
            SELECT client_id, COUNT(*)::int
            FROM operations.client_users
            WHERE tenant_id = 1 AND deleted_at IS NULL AND client_id IS NOT NULL
            GROUP BY client_id
            """
        )
        users = dict(cur.fetchall())
        cur.execute(
            """
            SELECT platform, last_observed_at, last_run_ok
            FROM operations.source_health_current
            WHERE tenant_id = 1
            """
        )
        health = {row[0]: {"updated_at": row[1], "run_ok": row[2]} for row in cur.fetchall()}
    return locations, users, health


def _source_updates(source_names: list[str], health: dict) -> list[dict]:
    stale_before = timezone.now() - timedelta(hours=8)
    updates = []
    for name in source_names:
        source = health.get(name, {})
        updated_at = source.get("updated_at")
        delayed = updated_at is None or updated_at < stale_before or source.get("run_ok") is False
        updates.append({"name": name, "updated_at": updated_at, "delayed": delayed})
    return updates


def build_client_workspace(client, existing: dict) -> dict:
    """Build a cross-domain, client-scoped overview context."""
    locations, users, health = _shared_context()
    stats_by_client, issue_details = _issue_rollup(client_id=client.id)
    stats = stats_by_client.get(client.id, {})
    source_names = list(dict.fromkeys(link.source.name for link in existing["client_links"]))
    source_updates = _source_updates(source_names, health)
    any_delayed = any(source["delayed"] for source in source_updates)
    latest_update = max(
        (source["updated_at"] for source in source_updates if source["updated_at"]),
        default=None,
    )

    attention_groups = []
    for row in issue_details:
        domain_key = row["domain_key"]
        view_name = "patching_queue" if domain_key == "patching" else "findings_queue"
        attention_groups.append(
            {
                "domain": DOMAIN_LABEL_BY_CATEGORY[row["finding_type__category__name"]],
                "domain_key": domain_key,
                "severity": row["severity"],
                "severity_rank": SEVERITY_RANK.get(row["severity"], 0),
                "finding_type": row["finding_type__name"],
                "title": _operator_label(row["finding_type__name"]),
                "count": row["n"],
                "affected": row["subjects"],
                "new": row["new"],
                "href": (
                    f"{reverse(view_name)}?client={client.slug}"
                    f"&type={row['finding_type__name']}"
                ),
            }
        )
    attention_groups.sort(
        key=lambda item: (-item["severity_rank"], -item["affected"], item["domain"])
    )

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """
            SELECT open_now, open_7d_ago, severe_open_now, severe_open_7d_ago
            FROM operations.client_health_trend_current
            WHERE tenant_id = 1 AND client_id = %s
            """,
            [str(client.id)],
        )
        trend = cur.fetchone()

    device = existing["dev_overview"]
    total = device["total"]
    online = device["online"]
    offline = device["offline"]
    stale = device["stale"]
    if not total:
        device_state = "unavailable"
    elif stale:
        device_state = "review"
    elif offline:
        device_state = "monitor"
    else:
        device_state = "on_track"

    inventory = stats.get("inventory", _empty_stats())
    patching = stats.get("patching", _empty_stats())
    compliance = stats.get("compliance", _empty_stats())
    software = stats.get("software", _empty_stats())
    missing = _count(compliance, "missing_required_platform", subjects=True)
    covered = max(total - missing, 0)
    percent_covered = round(covered / total * 100) if total else 0
    ninja_delayed = any(source["delayed"] for source in source_updates if source["name"] == "Ninja")
    current_sources = sum(not source["delayed"] for source in source_updates)

    domains = [
        _panel(
            key="devices",
            name="Devices",
            description="Availability and recent contact",
            value=f"{online:,} of {total:,}",
            value_label="currently online",
            facts=[
                {"label": f"{offline:,} offline"},
                {"label": f"{stale:,} not seen in 7 days"},
                {"label": f"{device['servers']:,} servers"},
                {"label": f"{device['workstations']:,} workstations"},
            ],
            href=reverse("org_devices", kwargs={"org_slug": client.slug}),
            updated_at=latest_update,
            forced_state=device_state,
        ),
        _panel(
            key="inventory",
            name="Inventory",
            description="Asset identity and record quality",
            value=f"{inventory['total']:,}",
            value_label="items need review",
            facts=[
                {"label": f"{_count(inventory, 'identity_conflict'):,} identity conflicts"},
                {"label": f"{_count(inventory, 'device_unenrolled'):,} lifecycle reviews"},
                {"label": f"{locations.get(client.id, 0):,} locations represented"},
            ],
            href=f"{reverse('findings_queue')}?client={client.slug}&category=identity",
            updated_at=latest_update,
            stats=inventory,
            has_data=total > 0,
            delayed=any_delayed,
        ),
        _panel(
            key="patching",
            name="Patching",
            description="Updates, failures, and restart readiness",
            value=f"{device['in_patch_scope']:,}",
            value_label="devices receiving patch management",
            facts=[
                {"label": f"{_count(patching, 'patching_stalled'):,} stalled"},
                {"label": f"{_count(patching, 'device_never_patched'):,} never patched"},
                {"label": f"{_count(patching, 'reboot_pending'):,} awaiting restart"},
            ],
            href=f"{reverse('patching_queue')}?client={client.slug}",
            updated_at=health.get("Ninja", {}).get("updated_at"),
            stats=patching,
            has_data=total > 0 and "Ninja" in source_names,
            delayed=ninja_delayed,
        ),
        _panel(
            key="compliance",
            name="Compliance",
            description="Devices meeting service requirements",
            value=f"{percent_covered}%",
            value_label="meet current requirements",
            facts=[
                {"label": f"{missing:,} missing requirements"},
                {
                    "label": (
                        f"{_count(compliance, 'stale_required_platform', subjects=True):,}"
                        " not reporting"
                    )
                },
                {"label": f"{compliance['new']:,} new since yesterday"},
            ],
            href=f"{reverse('findings_queue')}?client={client.slug}&category=coverage",
            updated_at=latest_update,
            stats=compliance,
            has_data=total > 0 and bool(source_updates),
            delayed=any_delayed,
        ),
        _panel(
            key="software",
            name="Software",
            description="Applications and review decisions",
            value=f"{existing['software_count']:,}",
            value_label="applications observed",
            facts=[
                {"label": f"{software['total']:,} findings need review"},
                {"label": f"{software['new']:,} new since yesterday"},
                {"label": f"{existing['software_decisions']:,} decisions recorded"},
            ],
            href=reverse("org_software", kwargs={"org_slug": client.slug}),
            updated_at=health.get("Ninja", {}).get("updated_at"),
            stats=software,
            has_data="Ninja" in source_names,
            delayed=ninja_delayed,
        ),
        _panel(
            key="data",
            name="Data Health",
            description="Collection completeness and freshness",
            value=f"{current_sources} of {len(source_updates)}",
            value_label="data connections current",
            facts=[
                {"label": f"{len(source_updates) - current_sources} delayed"},
                {"label": "All expected areas remain visible"},
            ],
            href=reverse("sources_status"),
            updated_at=latest_update,
            has_data=bool(source_updates),
            delayed=any_delayed,
            forced_state=(
                "unavailable" if not source_updates else "delayed" if any_delayed else "on_track"
            ),
        ),
    ]
    result = {
        "location_count": locations.get(client.id, 0),
        "client_user_count": users.get(client.id, 0),
        "source_updates": source_updates,
        "workspace_updated_at": latest_update,
        "attention_groups": attention_groups,
        "client_domains": domains,
        "areas_needing_attention": sum(
            STATE_PRIORITY.get(panel["issue_state"], 0) > 0 for panel in domains
        ),
    }
    if trend:
        change = trend[0] - trend[1]
        result["issue_trend"] = {
            "open_now": trend[0],
            "open_7d_ago": trend[1],
            "open_change": change,
            "open_change_abs": abs(change),
            "severe_now": trend[2],
            "severe_7d_ago": trend[3],
        }
    return result


def build_client_directory(clients: list) -> dict:
    """Build the sortable fleet client-directory rows."""
    locations, users, health = _shared_context()
    stats_by_client, _ = _issue_rollup()
    merge_reviews = {
        row["client_id"]: row["n"]
        for row in MergeCandidate.objects.filter(
            tenant_id=1,
            status=MergeCandidate.Status.OPEN,
            client_id__isnull=False,
        )
        .values("client_id")
        .annotate(n=Count("id"))
    }
    rows = []
    attention_count = 0
    delayed_count = 0
    for client in clients:
        source_names = client.source_names
        updates = _source_updates(source_names, health)
        delayed_sources = [source for source in updates if source["delayed"]]
        if not source_names:
            data_state, data_label, data_sort = "unavailable", "No data connection", 2
        elif delayed_sources:
            data_state, data_label, data_sort = "delayed", f"{len(delayed_sources)} delayed", 1
            delayed_count += 1
        else:
            data_state, data_label, data_sort = "on_track", "Current", 0

        client_stats = stats_by_client.get(client.id, {})
        domains = []
        domain_specs = (
            (
                "patching",
                "Patching",
                client.device_count > 0 and "Ninja" in source_names,
                f"{reverse('patching_queue')}?client={client.slug}",
            ),
            (
                "compliance",
                "Compliance",
                client.device_count > 0 and bool(source_names),
                f"{reverse('findings_queue')}?client={client.slug}&category=coverage",
            ),
            (
                "software",
                "Software",
                "Ninja" in source_names,
                reverse("org_software", kwargs={"org_slug": client.slug}),
            ),
            (
                "inventory",
                "Inventory",
                client.device_count > 0,
                f"{reverse('findings_queue')}?client={client.slug}&category=identity",
            ),
        )
        for key, name, has_data, href in domain_specs:
            stats = client_stats.get(key, _empty_stats())
            state, state_label = _display_state(
                stats,
                has_data=has_data,
                data_delayed=bool(delayed_sources),
            )
            domains.append(
                {
                    "key": key,
                    "name": name,
                    "state": state,
                    "state_label": state_label,
                    "count": stats["total"],
                    "href": href,
                }
            )
        needs_attention = any(STATE_PRIORITY.get(domain["state"], 0) > 0 for domain in domains)
        attention_count += int(needs_attention)
        rows.append(
            {
                "client": client,
                "devices": client.device_count,
                "locations": locations.get(client.id, 0),
                "users": users.get(client.id, 0),
                "domains": domains,
                "data_state": data_state,
                "data_label": data_label,
                "data_sort": data_sort,
                "review_count": merge_reviews.get(client.id, 0),
                "needs_attention": needs_attention,
            }
        )
    return {
        "directory_rows": rows,
        "directory_attention": attention_count,
        "directory_delayed": delayed_count,
        "all_location_count": sum(locations.values()),
        "all_user_count": sum(users.values()),
    }
