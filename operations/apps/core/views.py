from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from urllib import request as _urllib_request
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, connection, transaction
from django.db.models import Count, Prefetch, Q
from django.db.models.expressions import RawSQL
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_POST

from . import capability as capability_evidence
from .client_workspace import build_client_directory, build_client_workspace
from .csv_export import csv_response, wants_csv
from .decorators import require_admin
from .device_status import DEFAULTS as DEVICE_STATUS_DEFAULTS
from .device_status import POLICY_NAME as DEVICE_STATUS_POLICY_NAME
from .device_status import get_device_status_policy
from .forms import ClientPolicyForm
from .models import (
    AdminFinding,
    Agent,
    AuditLog,
    Client,
    ClientCandidate,
    ClientNameAlias,
    ClientOrgExclude,
    ClientPolicy,
    ClientSourceLink,
    CoverageRequirement,
    Device,
    DeviceOperatorDecision,
    DevicePatchingOverride,
    EntityType,
    EvaluatorConfig,
    Finding,
    FindingCategory,
    FindingType,
    MergeCandidate,
    NotificationEvent,
    NotificationRoute,
    NotificationRule,
    ProductAuthorization,
    RequirementProfile,
    SoftwareCatalog,
    SoftwareDecision,
    Source,
    SuppressionRule,
)

DEVICE_PAGE_SIZE = 100

_FINDING_ACTIVE_STATUSES = (
    Finding.Status.OPEN,
    Finding.Status.ACKNOWLEDGED,
    Finding.Status.INVESTIGATING,
)

_COALESCED_OFFLINE_FINDING_TYPES = (
    "missing_required_platform",
    "stale_required_platform",
)

# These are title-level policy recommendations, not incidents. Their
# authoritative state changes live in SoftwareDecision, whose scope resolves
# device before client before global.
_SOFTWARE_POLICY_CANDIDATE_TYPES = ("whitelist_suggestion",)

log = logging.getLogger(__name__)


def _online_device_ids(source_name: str = "") -> RawSQL:
    """Return the tenant-safe device set with current source contact."""
    if source_name:
        return RawSQL(
            """
            SELECT device_id
            FROM operations.device_session_current
            WHERE tenant_id = %s AND %s = ANY(online_sources)
            """,
            (1, source_name),
        )
    return RawSQL(
        """
        SELECT device_id
        FROM operations.device_session_current
        WHERE tenant_id = %s AND cardinality(online_sources) > 0
        """,
        (1,),
    )


def _finding_type_groups(
    categories: list[FindingCategory], finding_types: list[FindingType]
) -> list[dict]:
    """Group the type selector by its data-owned category."""
    by_category: dict[int | None, list[FindingType]] = {}
    for finding_type in finding_types:
        by_category.setdefault(finding_type.category_id, []).append(finding_type)

    groups = [
        {"label": category.name, "types": by_category.pop(category.id, [])}
        for category in categories
        if by_category.get(category.id)
    ]
    if ungrouped := by_category.pop(None, []):
        groups.append({"label": "Other", "types": ungrouped})
    return groups


def _affected_device_rows(findings) -> list[dict]:
    """Return each device exposed to the filtered finding queryset once.

    A finding can be directly about a device or about a software release. The
    latter reaches devices through the established exposure view, so this CTE
    consumes the caller's already-filtered queryset rather than recreating its
    predicates. It remains tenant-scoped at every relationship boundary.
    """
    matching = findings.order_by().values("id")
    matching_sql, matching_params = matching.query.get_compiler(
        connection=connection
    ).as_sql()
    with connection.cursor() as cur:
        cur.execute(
            f"""
            WITH matching AS ({matching_sql}),
            impacted AS (
                SELECT f.subject_id AS device_id, ft.name AS finding_type
                FROM operations.findings f
                JOIN matching m ON m.id = f.id
                JOIN operations.finding_types ft ON ft.id = f.finding_type_id
                WHERE f.tenant_id = 1 AND f.subject_type = 'device'

                UNION

                SELECT e.device_id, e.finding_type
                FROM operations.v_device_software_exposure e
                JOIN matching m ON m.id = e.finding_id
                WHERE e.tenant_id = 1
            )
            SELECT d.id::text,
                   COALESCE(d.canonical_hostname, ''),
                   COALESCE(c.display_name, ''),
                   COALESCE(d.os_name, ''),
                   COALESCE(ws.os_release_id, ''),
                   COALESCE(ws.os_build_number, ''),
                   array_agg(DISTINCT impacted.finding_type
                             ORDER BY impacted.finding_type)
            FROM impacted
            JOIN operations.devices d
              ON d.tenant_id = 1 AND d.id = impacted.device_id
             AND d.deleted_at IS NULL
            JOIN operations.clients c
              ON c.tenant_id = 1 AND c.id = d.client_id
             AND c.deleted_at IS NULL
            LEFT JOIN operations.device_windows_servicing_current ws
              ON ws.tenant_id = 1 AND ws.device_id = d.id
            GROUP BY d.id, d.canonical_hostname, c.display_name,
                     d.os_name, ws.os_release_id, ws.os_build_number
            ORDER BY c.display_name, d.canonical_hostname, d.id
            """,
            matching_params,
        )
        return [
            {
                "device_id": row[0],
                "hostname": row[1],
                "client": row[2],
                "os_name": row[3],
                "os_release_id": row[4],
                "os_build_number": row[5],
                "finding_types": list(row[6] or []),
            }
            for row in cur.fetchall()
        ]

# Fallback only. The real list is read from operations.sources so that
# registering a source makes it appear everywhere it should — dashboard tile,
# staleness check, coverage drilldown — without a code change. Used verbatim
# if that query fails, so a DB hiccup degrades the dashboard rather than
# breaking it.
_SOURCES_FALLBACK = ("Ninja", "SentinelOne", "ScreenConnect", "LogMeIn")


def _registered_sources() -> tuple[str, ...]:
    """Enabled source platform names, from configuration rather than a literal.

    Reads the platform recorded on each enabled instance, falling back to the
    source name — matching how ingest.sources.load_sources resolves it.
    """
    try:
        # transaction.atomic() is required, not stylistic: SET LOCAL only
        # applies inside a transaction, and under autocommit the GUC stays
        # unset — the RLS policy then casts '' to bigint and raises DataError.
        # Same wrapping as every other raw query in this module.
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                """
                SELECT DISTINCT COALESCE(NULLIF(si.config->>'platform', ''), s.name)
                  FROM operations.sources s
                  JOIN operations.source_instances si ON si.source_id = s.id
                 WHERE si.tenant_id = 1 AND si.enabled
                 ORDER BY 1
                """
            )
            names = tuple(r[0] for r in cur.fetchall() if r[0])
        return names or _SOURCES_FALLBACK
    except Exception:  # pragma: no cover - dashboard must not hard-fail
        log.exception("source list query failed — using fallback")
        return _SOURCES_FALLBACK

_DASHBOARD_DOMAIN_CATEGORIES = {
    "patching": "patching",
    "coverage": "compliance",
    "software": "software",
    "identity": "inventory",
    "lifecycle": "inventory",
    "data_quality": "inventory",
}

_DASHBOARD_STATE_LABELS = {
    "needs_action": "Needs action",
    "review": "Review",
    "monitor": "Monitor",
    "on_track": "On track",
    "delayed": "Data delayed",
    "unavailable": "Data unavailable",
}

_DASHBOARD_PRIORITY_LABELS = {
    "immediate": "Act now",
    "soon": "Review next",
    "routine": "Monitor",
    "none": "No current concerns",
}

_DASHBOARD_STATE_PRIORITY = {
    "needs_action": 3,
    "review": 2,
    "monitor": 1,
    "on_track": 0,
    "delayed": 0,
    "unavailable": 0,
}

_CLIENT_DOMAIN_LABELS = {
    "patching": "Patching",
    "coverage": "Compliance",
    "software": "Software",
    "identity": "Inventory",
    "lifecycle": "Inventory",
    "data_quality": "Inventory",
}


def _empty_issue_stats() -> dict:
    return {"severities": {}, "types": {}, "subjects": {}, "total": 0, "new": 0}


def _issue_state_from_stats(
    stats: dict, *, has_data: bool = True, data_delayed: bool = False
) -> tuple[str, str, str]:
    issue_state = _dashboard_issue_state(stats["severities"])
    display_state = _dashboard_display_state(
        issue_state, has_data=has_data, data_delayed=data_delayed
    )
    return issue_state, display_state, _DASHBOARD_STATE_LABELS[display_state]


def _dashboard_issue_state(severity_counts: dict[str, int]) -> str:
    """Return an operational state without treating data freshness as health."""
    if severity_counts.get("critical", 0):
        return "needs_action"
    if severity_counts.get("high", 0):
        return "review"
    if (
        severity_counts.get("medium", 0)
        or severity_counts.get("low", 0)
        or severity_counts.get("info", 0)
    ):
        return "monitor"
    return "on_track"


def _dashboard_display_state(
    issue_state: str, *, has_data: bool = True, data_delayed: bool = False
) -> str:
    """Keep delayed/unavailable data distinct without hiding known problems."""
    if not has_data:
        return "unavailable"
    if data_delayed and issue_state == "on_track":
        return "delayed"
    return issue_state


def _dashboard_priority(domains: list[dict]) -> tuple[str, str]:
    """Derive client priority and a short, human-readable reason."""
    contributing = [
        domain for domain in domains if _DASHBOARD_STATE_PRIORITY[domain["issue_state"]] > 0
    ]
    if not contributing:
        return "none", ""

    highest = max(_DASHBOARD_STATE_PRIORITY[domain["issue_state"]] for domain in contributing)
    priority = {3: "immediate", 2: "soon", 1: "routine"}[highest]
    names = [domain["name"] for domain in contributing]
    match names:
        case [name]:
            reason = name
        case [first, second]:
            reason = f"{first} and {second}"
        case [first, *others]:
            reason = f"{first} + {len(others)} more areas"
        case []:  # Defensive only; contributing is known to be non-empty.
            reason = ""
    return priority, reason


@require_GET
@transaction.non_atomic_requests
def healthz(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


@login_required
def home(request: HttpRequest) -> HttpResponse:  # noqa: PLR0912, PLR0915
    now = timezone.now()
    device_policy = get_device_status_policy()
    active_device_days = device_policy["active_device_days"]
    source_delay_hours = device_policy["source_delay_hours"]
    yesterday = now - timedelta(hours=24)
    stale_before = now - timedelta(hours=source_delay_hours)
    clients = list(
        Client.objects.filter(tenant_id=1, deleted_at__isnull=True).order_by("display_name")
    )

    # One grouped device query supplies all client counts and the global,
    # mutually-exclusive device mix. Retired devices remain visible as
    # secondary context but never inflate the active total.
    device_counts: dict = {}
    device_mix = {"workstations": 0, "servers": 0, "virtual": 0, "other": 0}
    retired_devices = 0
    device_rollup = (
        Device.objects.filter(tenant_id=1, deleted_at__isnull=True)
        .values("client_id", "lifecycle_status", "device_role", "device_type")
        .annotate(n=Count("id"))
    )
    for row in device_rollup:
        count = row["n"]
        if row["lifecycle_status"] == Device.LifecycleStatus.RETIRED:
            retired_devices += count
            continue
        client_id = row["client_id"]
        device_counts[client_id] = device_counts.get(client_id, 0) + count
        if row["device_type"] == Device.DeviceType.VM:
            device_mix["virtual"] += count
        elif row["device_role"] == "server":
            device_mix["servers"] += count
        elif row["device_role"] == "workstation":
            device_mix["workstations"] += count
        else:
            device_mix["other"] += count
    total_devices = sum(device_counts.values())
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            f"""
            SELECT COUNT(*)::int
            FROM operations.v_device
            WHERE tenant_id = 1
              AND lifecycle_status <> 'retired'
              AND last_contact_at >= NOW() - INTERVAL '{active_device_days} days'
            """
        )
        active_devices = cur.fetchone()[0]

    # Aggregate active, unsnoozed issues by client/domain/type/severity. This
    # replaces filtered joins repeated for every dashboard metric and keeps the
    # query count independent of the number of clients.
    issue_rows = (
        Finding.objects.filter(
            tenant_id=1,
            client_id__isnull=False,
            status__in=_FINDING_ACTIVE_STATUSES,
            finding_type__category__name__in=_DASHBOARD_DOMAIN_CATEGORIES,
        )
        .filter(Q(snoozed_until__isnull=True) | Q(snoozed_until__lt=now))
        .values(
            "client_id",
            "finding_type__category__name",
            "finding_type__name",
            "severity",
        )
        .annotate(
            n=Count("id"),
            subjects=Count("subject_id", distinct=True),
            new=Count("id", filter=Q(first_seen_at__gte=yesterday)),
        )
    )
    client_domain_stats: dict = {}
    global_domain_stats = {
        name: {"severities": {}, "types": {}, "subjects": {}, "total": 0, "new_total": 0}
        for name in ("patching", "compliance", "software", "inventory")
    }
    global_category_counts: dict[str, int] = {}
    for row in issue_rows:
        category_name = row["finding_type__category__name"]
        domain_name = _DASHBOARD_DOMAIN_CATEGORIES[category_name]
        global_category_counts[category_name] = (
            global_category_counts.get(category_name, 0) + row["n"]
        )
        client_stats = client_domain_stats.setdefault(row["client_id"], {}).setdefault(
            domain_name,
            {"severities": {}, "types": {}, "subjects": {}, "total": 0, "new_total": 0},
        )
        for stats in (client_stats, global_domain_stats[domain_name]):
            severity = row["severity"]
            type_name = row["finding_type__name"]
            stats["severities"][severity] = stats["severities"].get(severity, 0) + row["n"]
            stats["types"][type_name] = stats["types"].get(type_name, 0) + row["n"]
            stats["subjects"][type_name] = stats["subjects"].get(type_name, 0) + row["subjects"]
            stats["total"] += row["n"]
            stats["new_total"] += row["new"]

    patching_by_client: dict = {}
    source_rows: dict = {}
    recent_patch_activity = {"installed": 0, "failed": 0}
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """
            SELECT client_id,
                   COUNT(*)::int,
                   COUNT(*) FILTER (
                       WHERE effective_patching_scope = 'Included'
                   )::int
            FROM operations.v_device
            WHERE tenant_id = 1 AND lifecycle_status != 'retired'
            GROUP BY client_id
            """
        )
        patching_by_client = {
            row[0]: {"total": row[1], "included": row[2]} for row in cur.fetchall()
        }

        # Shared derived state: never aggregate raw observation history during
        # an interactive Dashboard request.
        cur.execute(
            """
            SELECT platform, last_observed_at, last_run_ok, last_success_at
            FROM operations.source_health_current
            WHERE tenant_id = 1
            """
        )
        source_rows = {
            row[0]: {
                "observed_at": row[1],
                "run_ok": row[2],
                "success_at": row[3],
            }
            for row in cur.fetchall()
        }

        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE LOWER(status) = 'installed')::int,
                COUNT(*) FILTER (WHERE LOWER(status) = 'failed')::int
            FROM ninja_patches.patch_facts
            WHERE fact_type = 'install_outcome' AND installed_at >= %s
            """,
            [yesterday],
        )
        installed, failed = cur.fetchone()
        recent_patch_activity = {"installed": installed, "failed": failed}

    registered_sources = _registered_sources()
    source_health = []
    stale_sources: list[str] = []
    for source_name in registered_sources:
        source = source_rows.get(source_name, {})
        observed_at = source.get("observed_at")
        stale = observed_at is None or observed_at < stale_before or source.get("run_ok") is False
        source_health.append({"name": source_name, "updated_at": observed_at, "stale": stale})
        if stale:
            stale_sources.append(source_name)
    sources_ok = len(registered_sources) - len(stale_sources)
    source_health_by_name = {source["name"]: source for source in source_health}
    observed_updates = [source["updated_at"] for source in source_health if source["updated_at"]]
    dashboard_updated_at = max(observed_updates, default=None)

    client_sources: dict = {}
    for client_id, source_name in ClientSourceLink.objects.filter(tenant_id=1).values_list(
        "client_id", "source__name"
    ):
        client_sources.setdefault(client_id, set()).add(source_name)

    pending_merges_by_client = {
        row["client_id"]: row["n"]
        for row in MergeCandidate.objects.filter(
            tenant_id=1, status=MergeCandidate.Status.OPEN, client_id__isnull=False
        )
        .values("client_id")
        .annotate(n=Count("id"))
    }
    pending_merges = sum(pending_merges_by_client.values())
    if pending_merges:
        global_inventory = global_domain_stats["inventory"]
        global_inventory["severities"]["medium"] = (
            global_inventory["severities"].get("medium", 0) + pending_merges
        )
        global_inventory["types"]["merge_candidate"] = pending_merges
        global_inventory["total"] += pending_merges

    software_catalog_titles = (
        SoftwareCatalog.objects.filter(Q(tenant_id=1) | Q(tenant_id__isnull=True))
        .values("canonical_name")
        .distinct()
        .count()
    )
    software_decision_rows = list(
        SoftwareDecision.objects.filter(tenant_id=1).values("client_id").annotate(n=Count("id"))
    )
    software_decisions_by_client = {
        row["client_id"]: row["n"] for row in software_decision_rows if row["client_id"] is not None
    }
    software_decisions_total = sum(row["n"] for row in software_decision_rows)

    def _stats(client_id, domain_name: str) -> dict:
        return client_domain_stats.get(client_id, {}).get(
            domain_name,
            {"severities": {}, "types": {}, "subjects": {}, "total": 0, "new_total": 0},
        )

    def _count(stats: dict, type_name: str, *, subjects: bool = False) -> int:
        bucket = "subjects" if subjects else "types"
        return stats[bucket].get(type_name, 0)

    def _state(
        stats: dict, *, has_data: bool = True, data_delayed: bool = False
    ) -> tuple[str, str]:
        issue_state = _dashboard_issue_state(stats["severities"])
        display_state = _dashboard_display_state(
            issue_state, has_data=has_data, data_delayed=data_delayed
        )
        return issue_state, display_state

    def _percent(numerator: int, denominator: int) -> int:
        return round((numerator / denominator) * 100) if denominator else 0

    ninja_health = source_health_by_name.get("Ninja", {"stale": True, "updated_at": None})
    any_source_delayed = bool(stale_sources)
    patch_total = sum(row["total"] for row in patching_by_client.values())
    patch_included = sum(row["included"] for row in patching_by_client.values())
    compliance_stats = global_domain_stats["compliance"]
    missing_devices = _count(compliance_stats, "missing_required_platform", subjects=True)
    compliance_covered = max(total_devices - missing_devices, 0)

    domain_summaries = []
    global_specs = [
        {
            "key": "patching",
            "name": "Patching",
            "description": "Device updates and restart readiness",
            "value": f"{_percent(patch_included, patch_total)}%",
            "value_label": "included for updates",
            "has_data": patch_total > 0,
            "delayed": ninja_health["stale"],
            "updated_at": ninja_health["updated_at"],
            "href": reverse("patching_queue"),
            "facts": [
                {
                    "label": f"{_count(global_domain_stats['patching'], 'patching_stalled')} stalled",
                    "href": f"{reverse('patching_queue')}?type=patching_stalled",
                },
                {
                    "label": f"{_count(global_domain_stats['patching'], 'device_never_patched')} never patched",
                    "href": f"{reverse('patching_queue')}?type=device_never_patched",
                },
                {
                    "label": f"{_count(global_domain_stats['patching'], 'reboot_pending')} awaiting restart",
                    "href": f"{reverse('patching_queue')}?type=reboot_pending",
                },
            ],
        },
        {
            "key": "compliance",
            "name": "Compliance",
            "description": "Required controls and reporting",
            "value": f"{_percent(compliance_covered, total_devices)}%",
            "value_label": "devices covered",
            "has_data": total_devices > 0,
            "delayed": any_source_delayed,
            "updated_at": min(observed_updates, default=None),
            "href": f"{reverse('findings_queue')}?category=coverage",
            "facts": [
                {
                    "label": f"{_count(compliance_stats, 'missing_required_platform')} missing",
                    "href": f"{reverse('findings_queue')}?type=missing_required_platform",
                },
                {
                    "label": f"{_count(compliance_stats, 'stale_required_platform')} not reporting",
                    "href": f"{reverse('findings_queue')}?type=stale_required_platform",
                },
                {
                    "label": f"{compliance_stats['total']} need review",
                    "href": f"{reverse('findings_queue')}?category=coverage",
                },
            ],
        },
        {
            "key": "software",
            "name": "Software",
            "description": "Applications, classification, and review",
            "value": f"{software_catalog_titles:,}",
            "value_label": "applications classified",
            "has_data": ninja_health["updated_at"] is not None,
            "delayed": ninja_health["stale"],
            "updated_at": ninja_health["updated_at"],
            "href": reverse("software_page"),
            "facts": [
                {
                    "label": f"{global_domain_stats['software']['new_total']} new review items",
                    "href": f"{reverse('findings_queue')}?category=software",
                },
                {
                    "label": f"{global_domain_stats['software']['total']} need review",
                    "href": f"{reverse('findings_queue')}?category=software",
                },
                {
                    "label": f"{software_decisions_total} decisions recorded",
                    "href": reverse("software_decisions_queue"),
                },
            ],
        },
        {
            "key": "inventory",
            "name": "Inventory",
            "description": "Devices, ownership, and data quality",
            "value": f"{total_devices:,}",
            "value_label": "managed devices",
            "has_data": total_devices > 0,
            "delayed": any_source_delayed,
            "updated_at": dashboard_updated_at,
            "href": reverse("devices_page"),
            "facts": [
                {
                    "label": f"{global_category_counts.get('identity', 0)} identity reviews",
                    "href": f"{reverse('findings_queue')}?category=identity",
                },
                {
                    "label": f"{global_category_counts.get('lifecycle', 0)} lifecycle reviews",
                    "href": f"{reverse('findings_queue')}?category=lifecycle",
                },
                {
                    "label": f"{global_category_counts.get('data_quality', 0)} data-quality reviews",
                    "href": f"{reverse('findings_queue')}?category=data_quality",
                },
                {
                    "label": f"{pending_merges} possible duplicates",
                    "href": reverse("merge_candidates_queue"),
                },
            ],
        },
    ]
    for spec in global_specs:
        issue_state, display_state = _state(
            global_domain_stats[spec["key"]],
            has_data=spec["has_data"],
            data_delayed=spec["delayed"],
        )
        spec["issue_state"] = issue_state
        spec["state"] = display_state
        spec["state_label"] = _DASHBOARD_STATE_LABELS[display_state]
        domain_summaries.append(spec)

    client_rows = []
    priority_counts = {"immediate": 0, "soon": 0, "routine": 0, "none": 0}
    for client in clients:
        client_id = client.id
        devices = device_counts.get(client_id, 0)
        patching = patching_by_client.get(client_id, {"total": 0, "included": 0})
        linked_sources = sorted(client_sources.get(client_id, set()))
        linked_health = [
            source_health_by_name[name] for name in linked_sources if name in source_health_by_name
        ]
        delayed_links = [source["name"] for source in linked_health if source["stale"]]
        if not linked_health:
            data_status = "unavailable"
            data_label = "Data unavailable"
            data_detail = "No active data connection"
            data_sort = 1
        elif delayed_links:
            data_status = "delayed"
            data_label = (
                f"{delayed_links[0]} delayed"
                if len(delayed_links) == 1
                else f"{len(delayed_links)} connections delayed"
            )
            data_detail = (
                "Other connections current" if len(delayed_links) < len(linked_health) else ""
            )
            data_sort = 2
        else:
            data_status = "current"
            data_label = "Current"
            data_detail = f"All {len(linked_health)} connections updated"
            data_sort = 0

        patch_stats = _stats(client_id, "patching")
        compliance = _stats(client_id, "compliance")
        software_stats = _stats(client_id, "software")
        inventory = _stats(client_id, "inventory")
        pending_client_merges = pending_merges_by_client.get(client_id, 0)
        if pending_client_merges:
            inventory["severities"]["medium"] = (
                inventory["severities"].get("medium", 0) + pending_client_merges
            )
            inventory["types"]["merge_candidate"] = pending_client_merges
            inventory["total"] += pending_client_merges
        missing = _count(compliance, "missing_required_platform", subjects=True)
        compliance_covered_client = max(devices - missing, 0)
        inventory_issues = inventory["total"]

        domain_specs = [
            {
                "key": "patching",
                "name": "Patching",
                "stats": patch_stats,
                "has_data": patching["total"] > 0,
                "delayed": ninja_health["stale"] and "Ninja" in linked_sources,
                "detail": (
                    f"{_percent(patching['included'], patching['total'])}% included"
                    f" · {_count(patch_stats, 'patching_stalled')} stalled"
                ),
                "href": f"{reverse('patching_queue')}?client={client.slug}",
            },
            {
                "key": "compliance",
                "name": "Compliance",
                "stats": compliance,
                "has_data": devices > 0 and bool(linked_health),
                "delayed": bool(delayed_links),
                "detail": (
                    f"{_percent(compliance_covered_client, devices)}% covered"
                    f" · {missing} missing"
                ),
                "href": f"{reverse('findings_queue')}?client={client.slug}&category=coverage",
            },
            {
                "key": "software",
                "name": "Software",
                "stats": software_stats,
                "has_data": "Ninja" in linked_sources,
                "delayed": ninja_health["stale"] and "Ninja" in linked_sources,
                "detail": (
                    f"{software_stats['total']} to review"
                    f" · {software_decisions_by_client.get(client_id, 0)} decisions"
                ),
                "href": reverse("org_software", kwargs={"org_slug": client.slug}),
            },
            {
                "key": "inventory",
                "name": "Inventory",
                "stats": inventory,
                "has_data": devices > 0,
                "delayed": bool(delayed_links),
                "detail": f"{devices:,} devices · {inventory_issues} to review",
                "href": reverse("org_devices", kwargs={"org_slug": client.slug}),
            },
        ]
        domains = []
        for domain in domain_specs:
            issue_state, display_state = _state(
                domain["stats"],
                has_data=domain["has_data"],
                data_delayed=domain["delayed"],
            )
            domain["issue_state"] = issue_state
            domain["state"] = display_state
            domain["state_label"] = _DASHBOARD_STATE_LABELS[display_state]
            domain["contributes"] = _DASHBOARD_STATE_PRIORITY[issue_state] > 0
            domains.append(domain)

        priority, priority_reason = _dashboard_priority(domains)
        priority_counts[priority] += 1
        client_rows.append(
            {
                "client": client,
                "devices": devices,
                "priority": priority,
                "priority_label": _DASHBOARD_PRIORITY_LABELS[priority],
                "priority_reason": priority_reason,
                "domains": domains,
                "data_status": data_status,
                "data_label": data_label,
                "data_detail": data_detail,
                "data_sort": data_sort,
                "source_updates": linked_health,
            }
        )

    priority_order = {"immediate": 0, "soon": 1, "routine": 2, "none": 3}
    client_rows.sort(
        key=lambda row: (priority_order[row["priority"]], row["client"].display_name.lower())
    )

    return render(
        request,
        "home.html",
        {
            "total_devices": total_devices,
            "active_devices": active_devices,
            "active_device_days": active_device_days,
            "retired_devices": retired_devices,
            "device_mix": device_mix,
            "total_clients": len(clients),
            "clients_connected": sum(1 for client in clients if client_sources.get(client.id)),
            "domain_summaries": domain_summaries,
            "client_rows": client_rows,
            "priority_counts": priority_counts,
            "attention_count": priority_counts["immediate"] + priority_counts["soon"],
            "source_health": source_health,
            "sources_ok": sources_ok,
            "sources_total": len(registered_sources),
            "stale_sources": stale_sources,
            "dashboard_updated_at": dashboard_updated_at,
            "recent_activity": {
                "patch_installed": recent_patch_activity["installed"],
                "patch_failed": recent_patch_activity["failed"],
                "software_new": global_domain_stats["software"]["new_total"],
            },
            "initial_view": request.GET.get("view", "all"),
        },
    )


def _type_summary_from_counts(counts: dict[str, int]) -> list[tuple[str, str, int]]:
    """(type_value, type_label, count) for device types present in a count map."""
    return [
        (device_type, label, counts.get(device_type, 0))
        for device_type, label in Device.DeviceType.choices
        if counts.get(device_type, 0) > 0
    ]


def _type_summary(devices: list) -> list[tuple[str, str, int]]:
    counts: dict[str, int] = {}
    for d in devices:
        counts[d.device_type] = counts.get(d.device_type, 0) + 1
    return _type_summary_from_counts(counts)


@login_required
def org_index(request: HttpRequest, org_slug: str) -> HttpResponse:
    """Summary hub for a client or the fleet."""
    device_policy = get_device_status_policy()
    active_device_days = device_policy["active_device_days"]
    ctx: dict = {}
    if getattr(request, "current_client", None):
        client = request.current_client
        devices = list(
            Device.objects.filter(tenant_id=1, client=client, deleted_at__isnull=True).only(
                "device_type"
            )
        )
        ctx["device_count"] = len(devices)
        ctx["type_summary"] = _type_summary(devices)
        ctx["client_links"] = list(
            client.source_links.select_related("source").order_by("source__name")
        )
        ctx["policy_count"] = ClientPolicy.objects.filter(tenant_id=1, client=client).count()
        ctx["policy_categories"] = list(
            ClientPolicy.objects.filter(tenant_id=1, client=client)
            .values_list("category", flat=True)
            .order_by("category")
        )

        _PLATFORM_SEVERITY = {
            "Ninja": "critical",
            "SentinelOne": "critical",
            "ScreenConnect": "high",
            "LogMeIn": "high",
        }
        with transaction.atomic():
            with connection.cursor() as cur:
                cur.execute("SET LOCAL operations.tenant_id = 1")

                # Total devices per scope. Device type is form factor only;
                # coverage applicability comes from requirements/entity_type.
                cur.execute(
                    f"""
                    SELECT od.device_role AS scope, COUNT(*)::int
                    FROM operations.devices od
                    WHERE od.tenant_id = 1 AND od.client_id = %s AND od.deleted_at IS NULL
                      AND od.lifecycle_status != 'retired'
                    GROUP BY 1
                    """,
                    [str(client.id)],
                )
                scope_totals = dict(cur.fetchall())  # {'server': N, 'workstation': M, ...}
                total_all = sum(scope_totals.values())

                # Presence per platform per scope.
                cur.execute(
                    """
                    SELECT ap.platform, ap.entity_type, od.device_role AS scope,
                           COUNT(DISTINCT ap.device_id)::int AS present,
                           MAX(ap.last_observed_at) AS last_seen
                    FROM operations.device_agent_presence_current ap
                    JOIN operations.devices od
                         ON od.id = ap.device_id AND od.deleted_at IS NULL
                    WHERE ap.tenant_id = 1 AND ap.client_id = %s
                      AND ap.last_observed_at > NOW() - INTERVAL '{active_device_days} days'
                      AND od.lifecycle_status != 'retired'
                    GROUP BY 1, 2, 3
                    """,
                    [str(client.id)],
                )
                presence_rows = cur.fetchall()

                # Deduplicated requirements: client-specific beats global;
                # suppress 'all' when per-scope reqs exist for same platform.
                cur.execute(
                    """
                    WITH deduped AS (
                        SELECT DISTINCT ON (platform, entity_type, device_scope)
                            platform, entity_type, device_scope, severity
                        FROM operations.coverage_requirements
                        WHERE tenant_id = %s AND enabled = TRUE
                          AND (client_id = %s OR client_id IS NULL)
                        ORDER BY platform, entity_type, device_scope,
                                 (client_id IS NULL)
                    )
                    SELECT platform, entity_type, device_scope, severity
                    FROM deduped r
                    WHERE device_scope != 'all'
                       OR NOT EXISTS (
                           SELECT 1 FROM deduped r2
                           WHERE r2.platform = r.platform
                             AND r2.entity_type = r.entity_type
                             AND r2.device_scope != 'all'
                       )
                    ORDER BY platform, device_scope
                    """,
                    [1, str(client.id)],
                )
                req_rows = cur.fetchall()

                cur.execute(
                    """
                    SELECT COUNT(DISTINCT canonical_name)::int
                    FROM operations.software_installations_current
                    WHERE tenant_id = 1 AND client_id = %s AND deleted_at IS NULL
                    """,
                    [str(client.id)],
                )
                ctx["software_count"] = cur.fetchone()[0]

        # Build lookup: (platform, entity_type, scope) → {present, last_seen}
        presence_map: dict = {}
        for platform, etype, scope, present, last_seen in presence_rows:
            presence_map[(platform, etype, scope)] = {
                "present": present,
                "last_seen": last_seen,
            }

        def _scope_total(scope: str) -> int:
            if scope == "all":
                return total_all
            return scope_totals.get(scope, 0)

        def _scope_present(platform: str, etype: str, scope: str):
            if scope == "all":
                count = sum(
                    v["present"]
                    for (p, e, _), v in presence_map.items()
                    if p == platform and e == etype
                )
                last = max(
                    (
                        v["last_seen"]
                        for (p, e, _), v in presence_map.items()
                        if p == platform and e == etype and v["last_seen"]
                    ),
                    default=None,
                )
                return count, last
            v = presence_map.get((platform, etype, scope), {})
            return v.get("present", 0), v.get("last_seen")

        platform_coverage: dict = {}
        for platform, etype, scope, severity in req_rows:
            present, last_seen = _scope_present(platform, etype, scope)
            total = _scope_total(scope)
            entry = platform_coverage.setdefault(
                platform,
                {
                    "severity": _PLATFORM_SEVERITY.get(platform, severity),
                    "scopes": {},
                },
            )
            scope_label = "all devices" if scope == "all" else scope + "s"
            entry["scopes"][scope_label] = {
                "total": total,
                "present": present,
                "gap": max(0, total - present),
                "last_seen": last_seen,
                "role": "" if scope == "all" else scope,
                "entity_type": etype,
            }
        ctx["platform_coverage"] = platform_coverage
        ctx["active_finding_count"] = Finding.objects.filter(
            tenant_id=1, client=client, status__in=_FINDING_ACTIVE_STATUSES
        ).count()

        # ── Client scoreboard extensions ──
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")

            # Devices online/offline + patch-scope for this client.
            cur.execute(
                f"""
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE is_online_any) AS online,
                   COUNT(*) FILTER (WHERE NOT is_online_any) AS offline,
                   COUNT(*) FILTER (WHERE device_role = 'server') AS servers,
                   COUNT(*) FILTER (WHERE device_role = 'workstation') AS workstations,
                   COUNT(*) FILTER (WHERE effective_patching_scope = 'Included') AS in_patch_scope,
                   COUNT(*) FILTER (WHERE lifecycle_status <> 'retired'
                                     AND last_contact_at >= NOW() - INTERVAL '{active_device_days} days') AS active,
                   COUNT(*) FILTER (WHERE last_contact_at IS NULL
                                        OR last_contact_at < NOW() - INTERVAL '{active_device_days} days') AS stale
                FROM operations.v_device
                WHERE tenant_id = 1 AND client_id = %s
            """,
                [str(client.id)],
            )
            r = cur.fetchone()
            ctx["dev_overview"] = {
                "total": r[0],
                "online": r[1],
                "offline": r[2],
                "servers": r[3],
                "workstations": r[4],
                "in_patch_scope": r[5],
                "active": r[6],
                "stale": r[7],
            }

            # Severity breakdown of open findings for this client.
            cur.execute(
                """
                SELECT severity, COUNT(*)::int
                FROM operations.findings
                WHERE tenant_id = 1 AND client_id = %s
                  AND status IN ('open', 'acknowledged', 'investigating')
                GROUP BY severity
                """,
                [str(client.id)],
            )
            sev = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
            for s, c in cur.fetchall():
                sev[s] = c
            ctx["finding_severity"] = sev
            ctx["severe_count"] = sev["critical"] + sev["high"]

            # Top attention: severe/high open findings, most recent first.
            cur.execute(
                """
                SELECT f.id, f.severity, ft.name AS ftype,
                       COALESCE(f.finding_details->>'title',
                                f.finding_details->>'summary') AS title,
                       f.last_detected_at,
                       d.id AS device_id, d.canonical_hostname
                FROM operations.findings f
                JOIN operations.finding_types ft ON ft.id = f.finding_type_id
                LEFT JOIN operations.devices d
                  ON f.subject_type = 'device'
                 AND d.tenant_id = f.tenant_id
                 AND d.id = f.subject_id
                WHERE f.tenant_id = 1
                  -- Software findings carry no client_id; this client is
                  -- reached through the installation link instead.
                  AND (f.client_id = %s
                       OR f.id IN (SELECT e.finding_id
                                     FROM operations.v_device_software_exposure e
                                    WHERE e.tenant_id = 1 AND e.client_id = %s))
                  AND f.status IN ('open', 'acknowledged', 'investigating')
                  AND f.severity IN ('critical', 'high')
                ORDER BY CASE f.severity WHEN 'critical' THEN 0 ELSE 1 END,
                         f.last_detected_at DESC NULLS LAST
                LIMIT 15
                """,
                [str(client.id), str(client.id)],
            )
            ctx["attention_findings"] = [
                {
                    "id": row[0],
                    "severity": row[1],
                    "ftype": row[2],
                    "title": row[3],
                    "last_detected_at": row[4],
                    "device_id": row[5],
                    "hostname": row[6],
                }
                for row in cur.fetchall()
            ]

            # Offline offenders — top 10 most-severe or longest-offline.
            cur.execute(
                """
                SELECT v.device_id, v.canonical_hostname, v.device_role, v.os_group,
                       v.last_contact_at,
                       COALESCE((
                           SELECT COUNT(*)::int FROM operations.findings f
                           WHERE f.tenant_id = 1
                             AND f.subject_type = 'device'
                             AND f.subject_id = v.device_id
                             AND f.status IN ('open', 'acknowledged', 'investigating')
                             AND f.severity IN ('critical', 'high')
                       ), 0)
                       -- Software findings are no longer device subjects, so
                       -- they are inherited through the installation link.
                       -- Without this the count silently drops them.
                       + COALESCE((
                           SELECT COUNT(DISTINCT e.finding_id)::int
                           FROM operations.v_device_software_exposure e
                           WHERE e.tenant_id = 1
                             AND e.device_id = v.device_id
                             AND e.status IN ('open', 'acknowledged', 'investigating')
                             AND e.severity IN ('critical', 'high')
                       ), 0) AS severe
                FROM operations.v_device v
                WHERE v.tenant_id = 1 AND v.client_id = %s
                  AND NOT v.is_online_any
                ORDER BY severe DESC, v.last_contact_at ASC NULLS FIRST
                LIMIT 10
                """,
                [str(client.id)],
            )
            ctx["offender_devices"] = [
                {
                    "id": row[0],
                    "hostname": row[1],
                    "role": row[2],
                    "os_group": row[3],
                    "last_contact_at": row[4],
                    "severe": row[5],
                }
                for row in cur.fetchall()
            ]

            # Decision coverage is intentionally reported directly. Counting
            # every installed title with no matching global/client decision
            # required a large correlated anti-join on every overview render.
            cur.execute(
                """
                SELECT COUNT(*)::int
                FROM operations.software_decisions
                WHERE tenant_id = 1 AND (client_id IS NULL OR client_id = %s)
                """,
                [str(client.id)],
            )
            ctx["software_decisions"] = cur.fetchone()[0]

            # Findings opened in the last 24h.
            cur.execute(
                """
                SELECT COUNT(*)::int
                FROM operations.findings
                WHERE tenant_id = 1 AND client_id = %s
                  AND first_seen_at > NOW() - INTERVAL '24 hours'
                """,
                [str(client.id)],
            )
            ctx["new_24h"] = cur.fetchone()[0]

        # Traffic-light health for the client header.
        if sev["critical"] > 0:
            ctx["client_health"] = "red"
            ctx["client_bucket"] = "critical"
        elif sev["high"] > 0:
            ctx["client_health"] = "amber"
            ctx["client_bucket"] = "degrading"
        elif ctx["dev_overview"]["total"] == 0:
            ctx["client_health"] = "grey"
            ctx["client_bucket"] = "no_data"
        else:
            ctx["client_health"] = "green"
            ctx["client_bucket"] = "healthy"
        ctx.update(build_client_workspace(client, ctx, device_policy=device_policy))
    else:
        # All-clients fleet view.
        clients_with_counts = list(
            Client.objects.filter(tenant_id=1, deleted_at__isnull=True)
            .select_related("requirement_profile")
            .prefetch_related(
                Prefetch(
                    "source_links",
                    queryset=ClientSourceLink.objects.select_related("source").order_by("source__name"),
                )
            )
            .annotate(
                device_count=Count(
                    "devices",
                    filter=Q(devices__deleted_at__isnull=True),
                )
            )
            .order_by("-device_count", "display_name")
        )
        for c in clients_with_counts:
            # Shared sources carry one link per platform group — dedupe for display.
            c.source_names = list(dict.fromkeys(l.source.name for l in c.source_links.all()))
        fleet_type_counts = {
            row["device_type"]: row["count"]
            for row in Device.objects.filter(tenant_id=1, deleted_at__isnull=True)
            .values("device_type")
            .annotate(count=Count("id"))
        }
        # Clients actually observed per platform — client_links row counts are
        # meaningless here (per-client SC instances have one link total).
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                """
                SELECT platform, COUNT(DISTINCT client_id)
                FROM operations.device_agent_presence_current
                WHERE client_id IS NOT NULL
                  AND entity_type LIKE 'agent.%'
                GROUP BY platform
                ORDER BY platform
                """
            )
            source_coverage = [{"name": r[0], "client_count": int(r[1])} for r in cur.fetchall()]
        ctx["clients_with_counts"] = clients_with_counts
        ctx["all_device_count"] = sum(c.device_count for c in clients_with_counts)
        ctx["all_client_count"] = len(clients_with_counts)
        ctx["fleet_type_summary"] = _type_summary_from_counts(fleet_type_counts)
        ctx["source_coverage"] = source_coverage
        ctx["open_finding_count"] = Finding.objects.filter(
            tenant_id=1, status__in=_FINDING_ACTIVE_STATUSES
        ).count()
        ctx.update(build_client_directory(clients_with_counts))
    return render(request, "org_index.html", ctx)


@login_required
def org_devices(request: HttpRequest, org_slug: str) -> HttpResponse:
    """Device list for a specific client with server-side search/filter."""
    client = _get_client_by_slug(org_slug)
    active_device_days = get_device_status_policy()["active_device_days"]
    base_qs = Device.objects.filter(tenant_id=1, client=client, deleted_at__isnull=True)
    type_counts = {
        row["device_type"]: row["count"]
        for row in base_qs.values("device_type").annotate(count=Count("id"))
    }
    total_count = sum(type_counts.values())

    search_query = request.GET.get("q", "").strip()
    active_type = request.GET.get("type", "").strip()
    active_role = request.GET.get("role", "").strip()
    missing_platform = request.GET.get("missing", "").strip()
    missing_entity_type = request.GET.get("entity_type", "agent.rmm").strip() or "agent.rmm"
    valid_types = {value for value, _label in Device.DeviceType.choices}

    devices_qs = base_qs
    if search_query:
        devices_qs = devices_qs.filter(
            Q(canonical_hostname__icontains=search_query)
            | Q(canonical_serial__icontains=search_query)
        )
    if active_type in valid_types:
        devices_qs = devices_qs.filter(device_type=active_type)
    else:
        active_type = ""
    if active_role in ("server", "workstation", "unknown"):
        devices_qs = devices_qs.filter(device_role=active_role)
    else:
        active_role = ""
    if missing_platform in _registered_sources():
        # Coverage-gap drilldown for the requirement's entity type/platform.
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                f"""
                SELECT DISTINCT device_id
                FROM operations.device_agent_presence_current
                WHERE tenant_id = 1 AND client_id = %s AND platform = %s
                  AND entity_type = %s
                  AND last_observed_at > NOW() - INTERVAL '{active_device_days} days'
                """,
                [str(client.id), missing_platform, missing_entity_type],
            )
            present_ids = [r[0] for r in cur.fetchall()]
        devices_qs = devices_qs.exclude(id__in=present_ids).exclude(
            lifecycle_status=Device.LifecycleStatus.RETIRED
        )
    else:
        missing_platform = ""

    devices_qs = devices_qs.order_by("canonical_hostname").only(
        "id",
        "canonical_hostname",
        "canonical_serial",
        "device_type",
        "device_role",
    )
    if wants_csv(request):
        return csv_response(
            devices_qs,
            columns=[
                ("Hostname", "canonical_hostname"),
                ("Serial", "canonical_serial"),
                ("Type", "device_type"),
                ("Role", "device_role"),
                ("Device ID", lambda d: str(d.id)),
            ],
            filename_stem=f"{org_slug}_devices",
        )
    paginator = Paginator(devices_qs, DEVICE_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    page_query = request.GET.copy()
    page_query.pop("page", None)
    type_query = request.GET.copy()
    type_query.pop("page", None)
    type_query.pop("type", None)

    return render(
        request,
        "org_devices.html",
        {
            "client": client,
            "devices": page_obj.object_list,
            "page_obj": page_obj,
            "paginator": paginator,
            "device_count": total_count,
            "filtered_count": paginator.count,
            "type_summary": _type_summary_from_counts(type_counts),
            "active_type": active_type,
            "active_role": active_role,
            "missing_platform": missing_platform,
            "missing_entity_type": missing_entity_type,
            "search_query": search_query,
            "page_query": page_query.urlencode(),
            "type_query": type_query.urlencode(),
            "page_size": DEVICE_PAGE_SIZE,
        },
    )


@login_required
def org_policies(request: HttpRequest, org_slug: str) -> HttpResponse:
    client = _get_client_by_slug(org_slug)
    policies = list(ClientPolicy.objects.filter(tenant_id=1, client=client).order_by("category"))
    return render(
        request,
        "org_policies.html",
        {"client": client, "policies": policies},
    )


# ── Raw snapshots on Device Detail (Identity & raw tab) ──────────────
#
# Cross-source field comparison uses `canonical_data` — the normalized
# per-source projection the writer emits. Every source rewrites the same
# concepts (hostname, os_name, serial_number, macs, is_online, ...) into
# canonical_data with identical key names, so the matrix can compare
# values directly across sources. Rendering priority:
#
#   1. Canonical fields, grouped by category, values shown per source
#      with disagreement highlight.
#   2. Per-source native (raw_data) fields the source uses but that are
#      not part of the canonical projection.
#   3. Full raw JSON payload under an inner collapse, for the long tail.

_RAW_FIELD_CATEGORIES: list[tuple[str, set[str]]] = [
    (
        "Identity",
        {
            "hostname",
            "hostnamefqdn",
            "host",
            "name",
            "displayname",
            "systemname",
            "computername",
            "netbiosname",
            "dnsname",
        },
    ),
    (
        "Serial & IDs",
        {
            "id",
            "uuid",
            "vmuuid",
            "deviceid",
            "agentid",
            "endpointid",
            "serial",
            "serialnumber",
            "sn",
            "assettag",
            "assetid",
            "productcode",
        },
    ),
    (
        "Network",
        {
            "mac",
            "macs",
            "macaddress",
            "macaddresses",
            "ip",
            "ipaddress",
            "ipaddresses",
            "publicip",
            "privateip",
            "externalip",
            "internalip",
            "gateway",
            "subnet",
        },
    ),
    (
        "Operating system",
        {
            "os",
            "osname",
            "osfamily",
            "osversion",
            "osrevision",
            "osarch",
            "osarchitecture",
            "osbuildnumber",
            "osreleaseid",
            "platform",
            "kernelversion",
            "domain",
            "domainrole",
        },
    ),
    (
        "Hardware",
        {
            "cpu",
            "cpuid",
            "cpucount",
            "model",
            "manufacturer",
            "chassistype",
            "totalmemorybytes",
            "memory",
            "isvirtualmachine",
            "isvm",
            "vmtype",
        },
    ),
    (
        "Presence & state",
        {
            "ishostonline",
            "isonline",
            "isactive",
            "offline",
            "lastseen",
            "lastseenat",
            "lastcontact",
            "lastcontactat",
            "lastactive",
            "lastactivetime",
            "hoststatechangedate",
            "lastloggedinuser",
            "lastuser",
            "needsreboot",
            "maintenancestatus",
            "state",
            "powerstate",
            "lastboottimeat",
        },
    ),
    (
        "Enrollment & grouping",
        {
            "groupid",
            "groupname",
            "organizationid",
            "organization",
            "locationid",
            "location",
            "policyid",
            "policyname",
            "rolepolicyid",
            "nodeclass",
            "approvalstatus",
            "tags",
            "site",
            "siteid",
            "tenantid",
            "entitytype",
            "devicerole",
            "parentninjaid",
        },
    ),
]
_RAW_CATEGORY_ORDER = [name for name, _ in _RAW_FIELD_CATEGORIES] + ["Other"]


def _raw_field_category(field_name: str) -> str:
    norm = field_name.lower().replace("_", "").replace("-", "")
    for cat, keys in _RAW_FIELD_CATEGORIES:
        if norm in keys:
            return cat
    return "Other"


def _raw_value_display(value) -> tuple[str, bool]:
    """Return (display_string, is_nested).

    - Scalar → its string form.
    - `None` → em dash.
    - Empty list / dict → em dash (avoids `[]` / `{}` clutter that hides
      that the field is present-but-empty).
    - Non-empty list of scalars → comma-joined, so MACs and tags render
      as readable values instead of JSON.
    - Nested dict / list of dicts → pretty JSON string, `is_nested=True`
      so the template can hide-by-default or format differently.
    """
    if value is None:
        return "—", False
    if isinstance(value, list):
        if not value:
            return "—", False
        if all(not isinstance(v, (dict, list)) for v in value):
            return ", ".join("" if v is None else str(v) for v in value), False
        try:
            return json.dumps(value, sort_keys=True, default=str), True
        except (TypeError, ValueError):
            return str(value), True
    if isinstance(value, dict):
        if not value:
            return "—", False
        try:
            return json.dumps(value, sort_keys=True, default=str), True
        except (TypeError, ValueError):
            return str(value), True
    if isinstance(value, bool):
        return "yes" if value else "no", False
    return str(value), False


def _raw_json_object(value) -> dict:
    """Return a JSON object for the raw-snapshot display surface.

    psycopg normally decodes JSONB objects to dictionaries, but deployments
    with a text loader can yield their JSON text instead. The display surface
    only compares object keys, so scalar, list, and invalid values are safely
    treated as empty objects.
    """
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _build_raw_snapshot_view(device, links):
    """Build the legacy identity shape from safe observation metadata.

    Returns (per_source_snapshots, canonical_by_category, source_specific).

    - `canonical_by_category` — the field matrix, driven by `canonical_data`
      because every source rewrites the same concepts into the same key
      names there. Fields shown for every source that reports on the
      device; values grouped so agreement collapses and disagreement is
      surfaced with a highlight.
    - `source_specific` — for each source snapshot, the fields in
      `raw_data` that are NOT already in canonical_data. That's the
      source-native long tail. Plus the full raw JSON under a
      collapse.

    Raw and canonical payload reads moved to the audited E5 reveal route.
    This compatibility helper now receives only explicitly safe metadata and
    remains until the typed Device identity surface is fully retired.
    """
    snapshots: list[dict] = []
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """
            SELECT platform, entity_type, observed_at,
                   jsonb_build_object('hostname', canonical_hostname),
                   '{}'::jsonb
            FROM operations.v_entity_observation_admin_metadata
            WHERE tenant_id = %s AND device_id = %s AND active = TRUE
            ORDER BY platform, entity_type
            """,
            [1, str(device.id)],
        )
        rows = [
            (
                platform,
                entity_type,
                observed_at,
                _raw_json_object(canonical_data),
                _raw_json_object(raw_data),
            )
            for platform, entity_type, observed_at, canonical_data, raw_data in cur.fetchall()
        ]

        for platform, entity_type, observed_at, canonical_data, raw_data in rows:
            canonical = canonical_data
            raw_payload = raw_data
            fallback_note = None
            try:
                pretty = json.dumps(raw_payload, indent=2, sort_keys=True, default=str)
            except (TypeError, ValueError):
                pretty = str(raw_payload)
            snapshots.append(
                {
                    "platform": platform,
                    "entity_type": entity_type,
                    "observed_at": observed_at,
                    "canonical_data": canonical,
                    "raw_data": raw_payload,
                    "pretty": pretty,
                    "fallback_note": fallback_note,
                    "source_label": f"{platform} ({entity_type})",
                }
            )

    # ── Canonical field matrix (cross-source comparison) ────────────
    #
    # `canonical_data` uses the same field names across sources, so we
    # can compare values directly. Every canonical field appears — even
    # if only one source reports it — because operators want to see the
    # whole normalized picture, not just what happens to overlap.
    canonical_appearances: dict[str, list[tuple[str, str, bool]]] = {}
    for snap in snapshots:
        if not isinstance(snap["canonical_data"], dict):
            continue
        for field, value in snap["canonical_data"].items():
            display, is_nested = _raw_value_display(value)
            canonical_appearances.setdefault(field, []).append(
                (snap["source_label"], display, is_nested)
            )

    canonical_rows: list[dict] = []
    for field, appearances in canonical_appearances.items():
        groups: dict[str, list[str]] = {}
        any_nested = False
        for src, disp, is_nested in appearances:
            groups.setdefault(disp, []).append(src)
            any_nested = any_nested or is_nested
        value_groups = [
            {"value": v, "sources": srcs}
            for v, srcs in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        ]
        canonical_rows.append(
            {
                "field": field,
                "category": _raw_field_category(field),
                "value_groups": value_groups,
                "differs": len(value_groups) > 1,
                "single_source": len(appearances) == 1,
                "is_nested": any_nested,
            }
        )

    by_cat: dict[str, list[dict]] = {}
    for f in canonical_rows:
        by_cat.setdefault(f["category"], []).append(f)
    for lst in by_cat.values():
        lst.sort(key=lambda f: f["field"].lower())
    canonical_by_category = [(cat, by_cat[cat]) for cat in _RAW_CATEGORY_ORDER if cat in by_cat]

    # ── Per-source collected fields ─────────────────────────────────
    #
    # Keep every source-native field available in its collapsed reference
    # panel. The combined record above is a convenience, not a lossy filter.
    source_specific = []
    for snap in snapshots:
        extras: list[dict] = []
        if isinstance(snap["raw_data"], dict):
            for field, value in snap["raw_data"].items():
                display, is_nested = _raw_value_display(value)
                extras.append(
                    {
                        "field": field,
                        "category": _raw_field_category(field),
                        "value": display,
                        "is_nested": is_nested,
                    }
                )
        extras.sort(
            key=lambda f: (
                _RAW_CATEGORY_ORDER.index(f["category"]),
                f["field"].lower(),
            )
        )
        source_specific.append(
            {
                "source_label": snap["source_label"],
                "platform": snap["platform"],
                "entity_type": snap["entity_type"],
                "observed_at": snap["observed_at"],
                "extras": extras,
                "pretty": snap["pretty"],
                "fallback_note": snap["fallback_note"],
            }
        )

    conflicts = [field for field in canonical_rows if field["differs"]]
    identity_summary = {
        "source_count": len(snapshots),
        "field_count": len(canonical_rows),
        "conflicts": conflicts,
        "latest_observed_at": max(
            (snapshot["observed_at"] for snapshot in snapshots if snapshot["observed_at"]),
            default=None,
        ),
    }
    return snapshots, canonical_by_category, source_specific, identity_summary


@login_required
def device_detail(request: HttpRequest, org_slug: str, device_id: str) -> HttpResponse:
    device = get_object_or_404(
        Device.objects.select_related("client"),
        tenant_id=1,
        id=device_id,
        client__slug=org_slug,
        deleted_at__isnull=True,
    )
    links = list(device.source_links.select_related("source").order_by("source__name"))

    # Software findings are subjects on the title or release, so they no longer
    # carry this device's id. The device inherits them through the installation
    # link; without this second set, a device page stops reporting that it runs
    # vulnerable or end-of-life software.
    with transaction.atomic(), connection.cursor() as _cur:
        _cur.execute("SET LOCAL operations.tenant_id = 1")
        _cur.execute(
            """
            SELECT DISTINCT finding_id
              FROM operations.v_device_software_exposure
             WHERE tenant_id = 1 AND device_id = %s
            """,
            [str(device.id)],
        )
        exposed_finding_ids = [row[0] for row in _cur.fetchall()]

    active_findings = list(
        Finding.objects.filter(
            Q(subject_type=Finding.SubjectType.DEVICE, subject_id=device.id)
            | Q(id__in=exposed_finding_ids),
            tenant_id=1,
            status__in=_FINDING_ACTIVE_STATUSES,
        )
        .select_related("finding_type")
        .order_by("severity", "-last_seen_at")[:50]
    )

    agent_presence = []
    software_rows = []
    patching = None
    windows_servicing = None
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                """
                SELECT platform, entity_type,
                       MAX(last_observed_at) AS last_seen,
                       MAX(last_contact_at)  AS last_contact
                FROM operations.device_agent_presence_current
                WHERE tenant_id = %s AND device_id = %s
                GROUP BY platform, entity_type
                ORDER BY platform
                """,
                [1, str(device.id)],
            )
            agent_presence = cur.fetchall()

            cur.execute(
                """
                SELECT canonical_name, publisher, version,
                       install_date, last_observed_at, install_location
                FROM operations.software_installations_current
                WHERE tenant_id = %s AND device_id = %s AND deleted_at IS NULL
                ORDER BY canonical_name
                LIMIT 300
                """,
                [1, str(device.id)],
            )
            software_rows = cur.fetchall()

            cur.execute(
                """
                SELECT support_state, product_name, cycle, release_label,
                       os_name, os_build_number, os_release_id,
                       active_support_ends_on, security_support_ends_on,
                       extended_security_ends_on,
                       extended_security_available, classification_reason,
                       evidence_source, evaluated_at
                FROM operations.device_windows_servicing_current
                WHERE tenant_id = %s AND device_id = %s
                """,
                [1, str(device.id)],
            )
            servicing_row = cur.fetchone()
            if servicing_row:
                windows_servicing = {
                    "support_state": servicing_row[0],
                    "product_name": servicing_row[1],
                    "cycle": servicing_row[2],
                    "release_label": servicing_row[3],
                    "os_name": servicing_row[4],
                    "os_build_number": servicing_row[5],
                    "os_release_id": servicing_row[6],
                    "active_support_ends_on": servicing_row[7],
                    "security_support_ends_on": servicing_row[8],
                    "extended_security_ends_on": servicing_row[9],
                    "extended_security_available": servicing_row[10],
                    "classification_reason": servicing_row[11],
                    "evidence_source": servicing_row[12],
                    "evaluated_at": servicing_row[13],
                }

            # Patching context: effective scope + session state from
            # v_device (Track O), plus per-device patch signal from
            # ninja_patches.device_patch_signal joined via the source link.
            cur.execute(
                """
                SELECT effective_patching_scope,
                       patching_scope_derived,
                       patching_scope_reason,
                       patching_scope_override,
                       patching_scope_override_reason,
                       needs_reboot,
                       last_boot_at,
                       is_online_any,
                       online_sources,
                       last_contact_at
                FROM operations.v_device
                WHERE tenant_id = %s AND device_id = %s
                """,
                [1, str(device.id)],
            )
            row = cur.fetchone()
            if row:
                patching = {
                    "effective_scope": row[0],
                    "derived_scope": row[1],
                    "scope_reason": row[2],
                    "override_scope": row[3],
                    "override_reason": row[4],
                    "needs_reboot": row[5],
                    "last_boot_at": row[6],
                    "is_online_any": row[7],
                    "online_sources": row[8] or [],
                    "last_contact_at": row[9],
                }

                # Patch signal from ninja_patches — one row per Ninja
                # device_id. Ops device may have >1 Ninja link; pick
                # the freshest signal.
                cur.execute(
                    """
                    SELECT dps.ever_installed,
                           dps.last_seen_at,
                           dps.install_attempts
                    FROM operations.v_device_source_link dl
                    JOIN operations.sources s
                      ON s.id = dl.source_id AND s.name = 'Ninja'
                    JOIN ninja_patches.device_patch_signal dps
                      ON dps.device_id = dl.external_id::int
                    WHERE dl.device_id = %s AND dl.tenant_id = %s
                    ORDER BY dps.last_seen_at DESC NULLS LAST
                    LIMIT 1
                    """,
                    [str(device.id), 1],
                )
                sig = cur.fetchone()
                if sig:
                    patching["ever_installed"] = sig[0]
                    patching["last_patch_installed_at"] = sig[1]
                    patching["install_attempts"] = sig[2]
                else:
                    patching["ever_installed"] = None
                    patching["last_patch_installed_at"] = None
                    patching["install_attempts"] = 0

            # Exemptions dict {entity_type: reason} from operator decisions.
            cur.execute(
                """
                SELECT value FROM operations.device_operator_decisions
                WHERE tenant_id = 1 AND device_id = %s AND dimension = 'exemptions'
                """,
                [str(device.id)],
            )
            row_ex = cur.fetchone()
            exemptions = row_ex[0] if row_ex and isinstance(row_ex[0], dict) else {}

            # Entity types the operator can pick from — distinct across
            # any coverage requirement active for this tenant.
            cur.execute(
                """
                SELECT DISTINCT entity_type
                FROM operations.coverage_requirements
                WHERE tenant_id = 1 AND enabled = TRUE
                ORDER BY entity_type
                """
            )
            entity_type_choices = [r[0] for r in cur.fetchall()]

    # ── Extras for 5-tab layout ──
    active_tab = request.GET.get("tab") or "overview"
    if active_tab not in ("overview", "sources", "activity", "software", "identity"):
        active_tab = "overview"

    # Software decisions map — key by canonical_name, prefer per-client
    # over global.
    software_titles = [row[0] for row in software_rows]
    software_publishers = [row[1] for row in software_rows if row[1]]
    decisions_map: dict = {}
    if software_titles:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            # Mirrors _resolve_decision in ingest/software_findings.py:
            # device > client > global, across BOTH title and publisher scope.
            #
            # The previous query filtered only on (client_id IS NULL OR
            # client_id = <this client>) and matched only canonical_name, which
            # was wrong twice. Device-scoped rows carry a client_id as well --
            # software_decision_create sets client = device.client -- so a
            # decision scoped to one device appeared on every other device of
            # that client, labeled "client". And an approve_publisher row has
            # an empty canonical_name, so a title covered by a trusted
            # publisher rendered as "pending".
            cur.execute(
                """
                SELECT canonical_name, publisher, decision, client_id, device_id
                FROM operations.software_decisions
                WHERE tenant_id = 1
                  AND (device_id IS NULL OR device_id = %s)
                  AND (client_id IS NULL OR client_id = %s)
                  AND (canonical_name = ANY(%s) OR publisher = ANY(%s))
                """,
                [
                    str(device.id),
                    str(device.client_id),
                    software_titles,
                    software_publishers or [""],
                ],
            )
            rows = cur.fetchall()

    def _tier(client_id, device_id) -> int:
        """Specificity: device beats client beats global."""
        if device_id is not None:
            return 2
        if client_id is not None:
            return 1
        return 0

    if software_titles:
        # Title-scope decisions win over publisher-scope at the same tier, so
        # they are applied last and overwrite.
        by_publisher: dict = {}
        for name, publisher, decision, client_id, device_id in rows:
            entry = {
                "decision": decision,
                "client_id": client_id,
                "device_id": device_id,
                "tier": _tier(client_id, device_id),
            }
            if name:
                prev = decisions_map.get(name)
                if not prev or entry["tier"] >= prev["tier"]:
                    decisions_map[name] = entry
            elif publisher:
                prev = by_publisher.get(publisher)
                if not prev or entry["tier"] >= prev["tier"]:
                    by_publisher[publisher] = entry
        # Publisher decisions apply to every title from that publisher that has
        # no more specific title-scope decision of its own.
        for row in software_rows:
            name, publisher = row[0], row[1]
            pub_entry = by_publisher.get(publisher) if publisher else None
            if pub_entry and (
                name not in decisions_map
                or pub_entry["tier"] > decisions_map[name]["tier"]
            ):
                decisions_map[name] = pub_entry

    software_view = [
        {
            "name": r[0],
            "publisher": r[1],
            "version": r[2],
            "install_date": r[3],
            "last_observed_at": r[4],
            "install_location": r[5],
            "decision": (decisions_map.get(r[0]) or {}).get("decision"),
            "decision_scope": (
                None
                if r[0] not in decisions_map
                else (
                    "device"
                    if decisions_map[r[0]]["device_id"] is not None
                    else (
                        "client"
                        if decisions_map[r[0]]["client_id"] is not None
                        else "global"
                    )
                )
            ),
        }
        for r in software_rows
    ]

    # Aggregate open-issue counts (for header + Overview snapshot).
    sev_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for f in active_findings:
        sev_counts[f.severity] = sev_counts.get(f.severity, 0) + 1
    severe_open = sev_counts["critical"] + sev_counts["high"]
    if severe_open > 0:
        device_health = "red"
    elif patching and not patching.get("is_online_any"):
        device_health = "amber"
    else:
        device_health = "green"

    # Activity events (unified timeline).
    activity: list = []
    for f in active_findings:
        activity.append(
            {
                "kind": "issue_open",
                "at": f.first_seen_at,
                "severity": f.severity,
                "label": f.finding_type.name,
                "status": f.get_status_display(),
                "finding_id": f.id,
            }
        )
        if f.last_reviewed_at:
            activity.append(
                {
                    "kind": "issue_reviewed",
                    "at": f.last_reviewed_at,
                    "severity": f.severity,
                    "label": f.finding_type.name,
                    "status": f.get_status_display(),
                    "finding_id": f.id,
                }
            )
    if patching:
        if patching.get("last_boot_at"):
            activity.append(
                {
                    "kind": "reboot",
                    "at": patching["last_boot_at"],
                    "label": "Device booted",
                    "severity": None,
                }
            )
        if patching.get("last_patch_installed_at"):
            activity.append(
                {
                    "kind": "patch",
                    "at": patching["last_patch_installed_at"],
                    "label": "Patch installed",
                    "severity": None,
                }
            )
    # Ninja activity feed — only when the Activity tab is active, to
    # avoid an extra query on hot paths. Requires a Ninja device_link
    # (any device without one just falls back to the finding-derived
    # timeline).
    if active_tab == "activity":
        ninja_external_id = None
        for link in links:
            if link.source.name.lower() == "ninja":
                ninja_external_id = link.external_id
                break
        if ninja_external_id:
            try:
                nid = int(ninja_external_id)
            except (TypeError, ValueError):
                nid = None
            if nid is not None:
                with transaction.atomic(), connection.cursor() as cur:
                    cur.execute("SET LOCAL operations.tenant_id = 1")
                    cur.execute(
                        """
                        SELECT activity_time, activity_type, source_name,
                               severity, subject, message, data, ingested_at
                        FROM ninja_activities.activities
                        WHERE device_id = %s
                        ORDER BY activity_time DESC
                        LIMIT 100
                        """,
                        [nid],
                    )
                    for at, atype, sname, sev, subj, msg, raw_data, ingested_at in cur.fetchall():
                        activity.append(
                            {
                                "kind": "ninja_event",
                                "at": at,
                                "severity": (sev or "").lower() or None,
                                "label": subj or atype or "Ninja event",
                                "status": msg or atype,
                                "source": sname,
                                "collected_at": ingested_at,
                                "raw_data": json.dumps(
                                    raw_data, indent=2, sort_keys=True, default=str
                                ),
                            }
                        )

                    # Patch facts are Ninja's retained evidence of patch state
                    # and install outcomes.  They answer a different question
                    # from the generic activity feed, so keep both in the one
                    # device timeline and preserve the original payload.
                    cur.execute(
                        """
                        SELECT pf.fact_type, pf.status, pf.severity,
                               pf.kb_number, pf.name, pf.type,
                               pf.installed_at, pf.ninja_observed_at,
                               pf.last_observed_at, pf.data
                        FROM ninja_patches.patch_facts pf
                        WHERE pf.device_id = %s
                        ORDER BY COALESCE(pf.installed_at, pf.ninja_observed_at,
                                          pf.last_observed_at) DESC NULLS LAST
                        LIMIT 100
                        """,
                        [nid],
                    )
                    for (
                        fact_type,
                        status,
                        severity,
                        kb_number,
                        name,
                        patch_type,
                        installed_at,
                        ninja_observed_at,
                        last_observed_at,
                        raw_data,
                    ) in cur.fetchall():
                        event_at = installed_at or ninja_observed_at or last_observed_at
                        patch_label = name or kb_number or "Patch record"
                        activity.append(
                            {
                                "kind": "patch",
                                "at": event_at,
                                "severity": (severity or "").lower() or None,
                                "label": patch_label,
                                "status": status,
                                "source": "Ninja patch data",
                                "detail": " · ".join(
                                    part
                                    for part in (
                                        fact_type.replace("_", " "),
                                        kb_number,
                                        patch_type,
                                    )
                                    if part
                                ),
                                "collected_at": last_observed_at,
                                "raw_data": json.dumps(
                                    raw_data, indent=2, sort_keys=True, default=str
                                ),
                            }
                        )

    activity.sort(key=lambda e: (e["at"] or timezone.now()), reverse=True)
    activity = activity[:100]

    # Raw evidence is never fetched on GET. It is available only through the
    # permission-checked, audited POST reveal on the generic entity surface.
    raw_snapshots: list[dict] = []
    raw_canonical_by_category: list[tuple[str, list[dict]]] = []
    raw_source_specific: list[dict] = []
    raw_identity_summary: dict = {}

    return render(
        request,
        "device_detail.html",
        {
            "device": device,
            "links": links,
            "active_findings": active_findings,
            "agent_presence": agent_presence,
            "software_rows": software_view,
            "patching": patching,
            "windows_servicing": windows_servicing,
            "active_tab": active_tab,
            "sev_counts": sev_counts,
            "severe_open": severe_open,
            "device_health": device_health,
            "activity": activity,
            "exemptions": exemptions,
            "entity_type_choices": entity_type_choices,
            "raw_snapshots": raw_snapshots,
            "raw_canonical_by_category": raw_canonical_by_category,
            "raw_source_specific": raw_source_specific,
            "raw_identity_summary": raw_identity_summary,
            "can_view_entity_evidence": bool(
                device.entity_id
                and (
                    request.user.is_superuser
                    or request.user.has_perm("operations.manage_catalog")
                )
            ),
        },
    )


@login_required
@require_POST
def device_patch_scope_set(request: HttpRequest, org_slug: str, device_id: str) -> HttpResponse:
    """Operator override of a device's patching scope."""
    device = get_object_or_404(
        Device,
        tenant_id=1,
        id=device_id,
        client__slug=org_slug,
        deleted_at__isnull=True,
    )
    scope = (request.POST.get("scope") or "").strip()
    if scope not in (DevicePatchingOverride.Scope.INCLUDED, DevicePatchingOverride.Scope.EXCLUDED):
        messages.warning(request, "Pick a scope value.")
        return redirect("device_detail", org_slug=org_slug, device_id=device_id)
    reason = (request.POST.get("reason") or "").strip()
    DevicePatchingOverride.objects.update_or_create(
        tenant_id=1,
        device=device,
        defaults={"scope": scope, "reason": reason, "set_by": request.user.username or ""},
    )
    messages.info(request, f"Patch scope override set to {scope}.")
    return redirect("device_detail", org_slug=org_slug, device_id=device_id)


@login_required
@require_POST
def device_exemption_add(request: HttpRequest, org_slug: str, device_id: str) -> HttpResponse:
    """Add or update an exemption key on the device's exemptions dict."""
    device = get_object_or_404(
        Device,
        tenant_id=1,
        id=device_id,
        client__slug=org_slug,
        deleted_at__isnull=True,
    )
    entity_type = (request.POST.get("entity_type") or "").strip()
    reason = (request.POST.get("reason") or "").strip()
    if not entity_type or not reason:
        messages.warning(request, "Both entity type and reason are required.")
        return redirect("device_detail", org_slug=org_slug, device_id=device_id)
    row, _ = DeviceOperatorDecision.objects.get_or_create(
        tenant_id=1,
        device=device,
        dimension="exemptions",
        defaults={"value": {}, "reason": "", "set_by": request.user.username or ""},
    )
    current = row.value if isinstance(row.value, dict) else {}
    current[entity_type] = reason
    row.value = current
    row.set_by = request.user.username or ""
    row.save(update_fields=["value", "set_by", "set_at"])
    messages.info(request, f"Exempted from {entity_type}.")
    return redirect("device_detail", org_slug=org_slug, device_id=device_id)


@login_required
@require_POST
def device_exemption_clear(request: HttpRequest, org_slug: str, device_id: str) -> HttpResponse:
    device = get_object_or_404(
        Device,
        tenant_id=1,
        id=device_id,
        client__slug=org_slug,
        deleted_at__isnull=True,
    )
    entity_type = (request.POST.get("entity_type") or "").strip()
    try:
        row = DeviceOperatorDecision.objects.get(
            tenant_id=1,
            device=device,
            dimension="exemptions",
        )
    except DeviceOperatorDecision.DoesNotExist:
        return redirect("device_detail", org_slug=org_slug, device_id=device_id)
    current = row.value if isinstance(row.value, dict) else {}
    current.pop(entity_type, None)
    if current:
        row.value = current
        row.save(update_fields=["value", "set_at"])
    else:
        row.delete()
    messages.info(request, f"Exemption cleared for {entity_type}.")
    return redirect("device_detail", org_slug=org_slug, device_id=device_id)


@login_required
@require_POST
def device_patch_scope_clear(request: HttpRequest, org_slug: str, device_id: str) -> HttpResponse:
    device = get_object_or_404(
        Device,
        tenant_id=1,
        id=device_id,
        client__slug=org_slug,
        deleted_at__isnull=True,
    )
    DevicePatchingOverride.objects.filter(tenant_id=1, device=device).delete()
    messages.info(request, "Patch scope override removed — reverted to derived scope.")
    return redirect("device_detail", org_slug=org_slug, device_id=device_id)


@login_required
def client_switch(request: HttpRequest) -> HttpResponse:
    slug = request.GET.get("slug", "all")
    return redirect("org_index", org_slug=slug)


@login_required
def search(request: HttpRequest) -> HttpResponse:
    """Fleet-wide search — hostname / serial / client name / slug.

    - Unique device match → redirect straight to device_detail.
    - Unique client match → redirect to client's org_index page.
    - Ambiguous or empty → render a results page.
    """
    q = (request.GET.get("q") or "").strip()
    if not q:
        return render(request, "search_results.html", {"q": "", "devices": [], "clients": []})

    devices = list(
        Device.objects.filter(
            tenant_id=1,
            deleted_at__isnull=True,
        )
        .filter(Q(canonical_hostname__icontains=q) | Q(canonical_serial__icontains=q))
        .select_related("client")
        .order_by("canonical_hostname")[:100]
    )

    clients = list(
        Client.objects.filter(
            tenant_id=1,
            deleted_at__isnull=True,
        )
        .filter(Q(display_name__icontains=q) | Q(slug__icontains=q))
        .order_by("display_name")[:100]
    )

    # Unambiguous matches → redirect straight there.
    if len(devices) == 1 and not clients:
        d = devices[0]
        if d.client:
            return redirect("device_detail", org_slug=d.client.slug, device_id=d.id)
    if len(clients) == 1 and not devices:
        return redirect("org_index", org_slug=clients[0].slug)

    return render(
        request,
        "search_results.html",
        {
            "q": q,
            "devices": devices,
            "clients": clients,
        },
    )


@login_required
@transaction.atomic
def findings_queue(request: HttpRequest) -> HttpResponse:
    """Entity findings review page."""
    with connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")

    status_filter = request.GET.get("status", "active")
    severity_filter = request.GET.get("severity", "")
    type_filter = request.GET.get("type", "")
    category_filter = request.GET.get("category", "")
    confidence_filter = request.GET.get("confidence", "")
    client_filter = request.GET.get("client", "")
    platform_filter = request.GET.get("platform", "")
    online_filter = request.GET.get("online", "")
    subject_id_filter = (request.GET.get("subject_id") or "").strip()
    q_filter = (request.GET.get("q") or "").strip()

    # Source names come from operations.sources (admin-editable
    # reference data) — never hardcoded in code.
    source_names = list(Source.objects.order_by("name").values_list("name", flat=True))
    source_names_set = set(source_names)

    qs = Finding.objects.filter(tenant_id=1).select_related(
        "finding_type",
        "finding_type__category",
        "client",
        "owner",
    )

    show_snoozed = request.GET.get("snoozed") == "1"
    if status_filter == "active":
        qs = qs.filter(status__in=_FINDING_ACTIVE_STATUSES)
    elif status_filter and status_filter != "all":
        qs = qs.filter(status=status_filter)
    # Hide snoozed issues by default; user can toggle to see them.
    if not show_snoozed and status_filter not in ("all",):
        qs = qs.filter(Q(snoozed_until__isnull=True) | Q(snoozed_until__lt=timezone.now()))
    status_scope_qs = qs

    if category_filter:
        qs = qs.filter(finding_type__category__name=category_filter)
    if type_filter:
        qs = qs.filter(finding_type__name=type_filter)
    if confidence_filter:
        qs = qs.filter(confidence=confidence_filter)
    if client_filter:
        qs = qs.filter(client__slug=client_filter)
    if platform_filter:
        qs = qs.filter(finding_details__platform=platform_filter)
    if subject_id_filter:
        # Filter to findings targeting a specific subject (device / client
        # / etc.). Used by Device Detail's "Issue → Issues page" clickthru.
        try:
            uuid.UUID(subject_id_filter)
        except (ValueError, TypeError):
            subject_id_filter = ""
        else:
            qs = qs.filter(subject_id=subject_id_filter)
    if q_filter:
        # Free-text match against canonical_name OR hostname in details
        qs = qs.filter(
            Q(finding_details__canonical_name__icontains=q_filter)
            | Q(finding_details__hostname__icontains=q_filter)
        )

    # Findings with a coalesced platform gap only belong in this queue when
    # the device is online. Applying the same predicate before aggregates and
    # row selection keeps every count and export aligned with the visible set.
    device_subject = Q(subject_type=Finding.SubjectType.DEVICE)
    coalesced_offline_q = (
        Q(finding_type__name__in=_COALESCED_OFFLINE_FINDING_TYPES)
        & device_subject
        & ~Q(subject_id__in=_online_device_ids())
    )
    status_scope_qs = status_scope_qs.exclude(coalesced_offline_q)
    qs = qs.exclude(coalesced_offline_q)

    # Online is a device-state filter. Software findings are unscoped facts,
    # not offline devices, and are therefore excluded when this filter is set.
    if online_filter == "online":
        qs = qs.filter(device_subject, subject_id__in=_online_device_ids())
    elif online_filter == "offline":
        qs = qs.filter(device_subject).exclude(subject_id__in=_online_device_ids())
    elif online_filter in source_names_set:
        qs = qs.filter(
            device_subject,
            subject_id__in=_online_device_ids(online_filter),
        )

    # Software-policy candidates have their own review workflow. Severity
    # tiles stay focused on actionable findings, rather than treating a large
    # low-severity decision backlog as an incident count.
    severity_qs = qs.exclude(finding_type__name__in=_SOFTWARE_POLICY_CANDIDATE_TYPES)
    if severity_filter:
        qs = qs.filter(severity=severity_filter)

    policy_qs = qs.filter(finding_type__name__in=_SOFTWARE_POLICY_CANDIDATE_TYPES)
    actionable_qs = qs.exclude(finding_type__name__in=_SOFTWARE_POLICY_CANDIDATE_TYPES)

    # Tile counts and the headline are computed before the display slice from
    # the fully filtered queryset, so they remain exact beyond 500 rows.
    severity_tile_counts = {
        row["severity"]: row["n"]
        for row in severity_qs.values("severity").annotate(n=Count("id"))
    }
    total_matching = qs.count()
    actionable_matching = actionable_qs.count()
    policy_matching = policy_qs.count()
    affected_devices = _affected_device_rows(actionable_qs)
    affected_client_count = len({row["client"] for row in affected_devices if row["client"]})
    status_scope_total = status_scope_qs.count()
    status_scope_actionable_total = status_scope_qs.exclude(
        finding_type__name__in=_SOFTWARE_POLICY_CANDIDATE_TYPES
    ).count()
    status_scope_policy_total = status_scope_qs.filter(
        finding_type__name__in=_SOFTWARE_POLICY_CANDIDATE_TYPES
    ).count()
    fleet_device_total = Device.objects.filter(tenant_id=1, deleted_at__isnull=True).count()
    fleet_client_total = Client.objects.filter(tenant_id=1, deleted_at__isnull=True).count()
    status_scope_label = "all" if status_filter == "all" else status_filter.replace("_", " ")

    def scope_card(label: str, count: int, total: int, total_label: str, note: str) -> dict:
        """Build a labeled filtered-count fraction for the Issues summary."""
        percentage = f"{(100 * count / total):.1f}%" if total else "0%"
        return {
            "label": label,
            "count": count,
            "total": total,
            "total_label": total_label,
            "percentage": percentage,
            "note": note,
        }

    result_scope_cards = [
        scope_card(
            "Findings",
            total_matching,
            status_scope_total,
            f"{status_scope_label} findings",
            "matching the active filters",
        ),
        scope_card(
            "Actionable",
            actionable_matching,
            status_scope_actionable_total,
            f"{status_scope_label} actionable findings",
            "incident or remediation work",
        ),
        scope_card(
            "Devices",
            len(affected_devices),
            fleet_device_total,
            "fleet devices",
            "affected by actionable findings",
        ),
        scope_card(
            "Clients",
            affected_client_count,
            fleet_client_total,
            "fleet clients",
            "with affected devices",
        ),
        scope_card(
            "Policy review",
            policy_matching,
            status_scope_policy_total,
            f"{status_scope_label} policy candidates",
            "software decision candidates",
        ),
    ]

    if request.GET.get("format") == "devices_csv":
        return csv_response(
            affected_devices,
            columns=[
                ("Hostname", "hostname"),
                ("Client", "client"),
                ("Operating system", "os_name"),
                ("OS release", "os_release_id"),
                ("OS build", "os_build_number"),
                ("Finding types", "finding_types"),
                ("Device ID", "device_id"),
            ],
            filename_stem="affected_devices",
        )

    # Prebuild severity tiles — each is a dict the template renders
    # directly (avoids needing a custom dict-lookup template filter).
    # Clicking a tile TOGGLES that severity in the filter set.
    severity_tiles = []
    for sev, label in Finding.Severity.choices:
        params = request.GET.copy()
        params.pop("page", None)
        is_active = severity_filter == sev
        if is_active:
            params.pop("severity", None)  # click again to clear
        else:
            params["severity"] = sev
        severity_tiles.append(
            {
                "value": sev,
                "label": label,
                "count": severity_tile_counts.get(sev, 0),
                "href": "?" + params.urlencode() if params else "?",
                "active": is_active,
            }
        )

    _SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    # The screen intentionally stays bounded so it remains responsive, but an
    # explicit CSV is a report of the complete filtered set. Keeping its input
    # uncapped makes its row count agree with the headline rather than silently
    # truncating at the screen limit.
    findings = sorted(
        qs if wants_csv(request) else actionable_qs[:500],
        key=lambda f: (
            _SEVERITY_ORDER.get(f.severity, 9),
            -(f.last_detected_at or f.last_seen_at).timestamp(),
        ),
    )
    policy_findings = sorted(
        policy_qs[:100],
        key=lambda f: (-(f.last_detected_at or f.last_seen_at).timestamp(), f.id),
    )

    # Per-device map of platforms whose latest source-reported state is online.
    # Freshness is deliberately separate from this state and remains available
    # on the device detail surface.
    all_display_findings = [*findings, *policy_findings]
    subject_ids = [f.subject_id for f in all_display_findings if f.subject_id]
    online_map: dict[str, list[str]] = {}
    if subject_ids:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                """
                SELECT device_id::text, online_sources
                FROM operations.device_session_current
                WHERE device_id = ANY(%s::uuid[])
                  AND array_length(online_sources, 1) > 0
                """,
                ([str(sid) for sid in subject_ids],),
            )
            for did, sources in cur.fetchall():
                online_map[did] = list(sources or [])

    # Build a per-finding detail string for the inline column.
    _DAYS_KEYS = ("days_since_last_seen", "days_offline")

    def _detail_string(finding: Finding) -> str:
        d = finding.finding_details or {}
        name = finding.finding_type.name
        if name == "missing_required_platform":
            return f"missing {d.get('platform', '?')}"
        if name == "stale_required_platform":
            hours = d.get("gap_age_hours") or d.get("gap_hours")
            return f"stale {d.get('platform', '?')}" + (f" · {int(hours)}h" if hours else "")
        if name == "device_unenrolled":
            ps = d.get("power_state") or "unknown"
            days = d.get("days_since_last_seen")
            via = d.get("observed_via") or "tracked"
            return f"{ps}" + (f" · {days}d" if days is not None else "") + f" · via {via}"
        if name in ("device_offline", "device_long_offline"):
            since = (
                d.get("fully_offline_since") or d.get("last_contact_at") or d.get("last_seen_at")
            )
            last_src = d.get("last_seen_source")
            base = f"fully offline since {since[:10]}" if since else "no source has contact"
            return f"{base} (last: {last_src})" if last_src else base
        if name == "device_role_conflict":
            return f"{d.get('previous_role', '?')} → {d.get('new_role', '?')}"
        if name.startswith("windows_servicing_"):
            os_name = d.get("os_name")
            build = d.get("os_build_number") or d.get("build_number") or "?"
            cycle = d.get("cycle")
            end = d.get("security_support_ends_on")
            pieces = [os_name] if os_name else []
            pieces.append(f"build {build}")
            if cycle:
                pieces.append(cycle)
            if end:
                pieces.append(f"support ended {end}" if name.endswith("_eol") else f"ends {end}")
            return " · ".join(pieces)
        if name in (
            "unauthorized_av",
            "unauthorized_rmm",
            "unauthorized_remote_access",
            "suspicious_name",
            "install_path_suspicious",
            "eol_runtime",
        ):
            cn = d.get("canonical_name") or ""
            pub = d.get("publisher") or ""
            pieces = [cn]
            if pub:
                pieces.append(f"({pub})")
            loc = d.get("location") or d.get("install_path")
            if loc:
                pieces.append(f"@ {loc}")
            return " ".join(pieces) if cn else (d.get("reason") or "")
        if name == "multi_av_conflict":
            avs = d.get("av_products") or []
            return ", ".join(avs) if avs else "multiple AV products"
        if name == "rare_recent":
            n = d.get("fleet_device_count") or d.get("machine_count")
            days = d.get("first_seen_days")
            cn = d.get("canonical_name") or ""
            pieces = [cn] if cn else []
            if n is not None:
                pieces.append(f"on {n} machine{'s' if n != 1 else ''}")
            if days is not None:
                pieces.append(f"first seen {days}d ago")
            return " · ".join(pieces) if pieces else "rare install"
        if name == "whitelist_suggestion":
            devices = d.get("fleet_device_count")
            threshold = d.get("threshold")
            if devices is not None and threshold is not None:
                return f"installed on {devices} devices (review threshold {threshold})"
            if devices is not None:
                return f"installed on {devices} devices; no decision recorded"
            return d.get("reason") or "widespread software with no decision"
        if name == "vulnerable_software":
            pieces = [d.get("reason") or "matched vulnerability intelligence"]
            if d.get("worst_cvss") is not None:
                pieces.append(f"CVSS {d['worst_cvss']}")
            if kev := d.get("kev_cves"):
                pieces.append(f"KEV: {', '.join(kev[:3])}")
            elif high := d.get("high_cves"):
                pieces.append(f"high CVEs: {', '.join(high[:3])}")
            return " · ".join(pieces)
        if name == "known_malicious_hint":
            hits = d.get("threat_hit_count")
            return (
                f"{hits} community threat-intel hit{'s' if hits != 1 else ''}"
                if hits is not None
                else (d.get("reason") or "community threat-intel accumulation")
            )
        # Fallback: platform if present, else empty
        return d.get("platform") or ""

    # Add device context to device-subject findings. Software and client
    # findings have no single device OS, so their context remains blank.
    device_subject_ids = {
        f.subject_id
        for f in all_display_findings
        if f.subject_type == Finding.SubjectType.DEVICE and f.subject_id
    }
    device_context_by_id: dict = {}
    if device_subject_ids:
        device_context_by_id = {
            device_id: {"hostname": hostname, "os_name": os_name}
            for device_id, hostname, os_name in Device.objects.filter(
                tenant_id=1,
                id__in=device_subject_ids,
            ).values_list("id", "canonical_hostname", "os_name")
        }

    windows_context_by_device_id: dict[str, dict[str, str]] = {}
    if device_subject_ids:
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT device_id::text, os_name, os_release_id, os_build_number
                FROM operations.device_windows_servicing_current
                WHERE tenant_id = 1 AND device_id = ANY(%s::uuid[])
                """,
                ([str(device_id) for device_id in device_subject_ids],),
            )
            windows_context_by_device_id = {
                device_id: {
                    "os_name": os_name or "",
                    "os_release_id": os_release_id or "",
                    "os_build_number": os_build_number or "",
                }
                for device_id, os_name, os_release_id, os_build_number in cur.fetchall()
            }

    def _device_context(finding: Finding) -> dict[str, str]:
        if finding.subject_type != Finding.SubjectType.DEVICE:
            return {}
        current = windows_context_by_device_id.get(str(finding.subject_id), {})
        device = device_context_by_id.get(finding.subject_id, {})
        details = finding.finding_details or {}
        return {
            "hostname": device.get("hostname") or details.get("hostname", ""),
            "os_name": details.get("os_name") or current.get("os_name") or device.get("os_name", ""),
            "os_release_id": details.get("os_release_id") or current.get("os_release_id", ""),
            "os_build_number": details.get("os_build_number")
            or details.get("build_number")
            or current.get("os_build_number", ""),
        }

    def _subject_display_name(f: Finding) -> str | None:
        return _device_context(f).get("hostname") or None

    def _display_row(f: Finding) -> dict:
        details = f.finding_details or {}
        device_context = _device_context(f)
        online_sources = online_map.get(str(f.subject_id)) if f.subject_id else None
        subject_label = ""
        subject_url = ""
        context_parts: list[str] = []

        if f.subject_type == Finding.SubjectType.DEVICE:
            subject_label = device_context.get("hostname") or "(unnamed device)"
            if f.client and f.subject_id:
                subject_url = reverse(
                    "device_detail",
                    kwargs={"org_slug": f.client.slug, "device_id": f.subject_id},
                )
            if f.client:
                context_parts.append(f.client.display_name)
            os_parts = [
                device_context.get("os_name", ""),
                device_context.get("os_release_id", ""),
                device_context.get("os_build_number", ""),
            ]
            if os_text := " ".join(part for part in os_parts if part):
                context_parts.append(os_text)
            if online_sources:
                context_parts.append("online via " + ", ".join(online_sources))
            elif online_sources is not None:
                context_parts.append("offline")
        elif f.subject_type == Finding.SubjectType.CLIENT:
            subject_label = f.client.display_name if f.client else "(unnamed client)"
            if f.client:
                subject_url = reverse("org_index", kwargs={"org_slug": f.client.slug})
                context_parts.append("client-wide")
        elif f.subject_type in (
            Finding.SubjectType.SOFTWARE_PRODUCT,
            Finding.SubjectType.SOFTWARE_VERSION,
        ):
            subject_label = details.get("canonical_name") or "(unnamed software)"
            if subject_label and subject_label != "(unnamed software)":
                subject_url = reverse("software_detail", kwargs={"name": subject_label})
            if publisher := details.get("publisher"):
                context_parts.append(publisher)
            context_parts.append(
                "software release"
                if f.subject_type == Finding.SubjectType.SOFTWARE_VERSION
                else "software title"
            )
        else:
            subject_label = f.get_subject_type_display()
            context_parts.append("platform or source context")

        return {
            "f": f,
            "detail": _detail_string(f),
            "online_sources": online_sources,
            "subject_hostname": _subject_display_name(f),
            "device_context": device_context,
            "subject_label": subject_label,
            "subject_url": subject_url,
            "context": " · ".join(context_parts),
            "canonical_name": details.get("canonical_name", ""),
            "publisher": details.get("publisher", ""),
            "fleet_device_count": details.get("fleet_device_count"),
            "threshold": details.get("threshold"),
        }

    findings_with_detail = [_display_row(f) for f in findings]
    policy_rows = [_display_row(f) for f in policy_findings]

    if wants_csv(request):
        return csv_response(
            findings_with_detail,
            columns=[
                ("Severity", lambda r: r["f"].severity),
                ("Type", lambda r: r["f"].finding_type.name),
                (
                    "Category",
                    lambda r: (
                        r["f"].finding_type.category.name if r["f"].finding_type.category else ""
                    ),
                ),
                ("Client", lambda r: (r["f"].client.display_name if r["f"].client else "")),
                ("Subject type", lambda r: r["f"].subject_type),
                ("Subject id", lambda r: str(r["f"].subject_id) if r["f"].subject_id else ""),
                (
                    "Hostname",
                    lambda r: r.get("subject_hostname")
                    or (r["f"].finding_details or {}).get("hostname", ""),
                ),
                (
                    "Operating system",
                    lambda r: r["device_context"].get("os_name", ""),
                ),
                (
                    "OS release",
                    lambda r: r["device_context"].get("os_release_id", ""),
                ),
                (
                    "OS build",
                    lambda r: r["device_context"].get("os_build_number", ""),
                ),
                (
                    "Lifecycle cycle",
                    lambda r: (r["f"].finding_details or {}).get("cycle", ""),
                ),
                (
                    "Security support ends",
                    lambda r: (r["f"].finding_details or {}).get(
                        "security_support_ends_on", ""
                    ),
                ),
                ("Detail", "detail"),
                ("Online sources", "online_sources"),
                ("Status", lambda r: r["f"].status),
                ("Confidence", lambda r: r["f"].confidence),
                ("First seen", lambda r: r["f"].first_seen_at),
                ("Last seen", lambda r: r["f"].last_seen_at),
                ("Last detected", lambda r: r["f"].last_detected_at),
                ("Snoozed until", lambda r: r["f"].snoozed_until),
                ("Owner", lambda r: (r["f"].owner.username if r["f"].owner else "")),
            ],
            filename_stem="findings",
        )

    paginator = Paginator(findings_with_detail, 50)
    page = paginator.get_page(request.GET.get("page"))

    # Type dropdown cascades: if category selected, only show types in it.
    ft_qs = FindingType.objects.select_related("category").order_by("name")
    if category_filter:
        ft_qs = ft_qs.filter(category__name=category_filter)
    categories = list(FindingCategory.objects.order_by("display_order", "name"))
    finding_type_groups = _finding_type_groups(categories, list(ft_qs))
    clients = Client.objects.filter(tenant_id=1, deleted_at__isnull=True).order_by("display_name")

    page_query = request.GET.copy()
    page_query.pop("page", None)
    page_query.pop("format", None)

    return render(
        request,
        "findings_queue.html",
        {
            "page_obj": page,
            "findings": page.object_list,
            "finding_type_groups": finding_type_groups,
            "categories": categories,
            "clients": clients,
            "status_choices": Finding.Status.choices,
            "severity_choices": Finding.Severity.choices,
            "confidence_choices": Finding.Confidence.choices,
            "platform_choices": [(name, name) for name in source_names],
            "online_choices": (
                [("online", "Online (any source)"), ("offline", "Offline (no source)")]
                + [(name, f"via {name}") for name in source_names]
            ),
            "active_status": status_filter,
            "active_severity": severity_filter,
            "active_type": type_filter,
            "active_category": category_filter,
            "active_platform": platform_filter,
            "active_online": online_filter,
            "active_q": q_filter,
            "active_confidence": confidence_filter,
            "active_client": client_filter,
            "show_snoozed": show_snoozed,
            "severity_tiles": severity_tiles,
            "total_matching": total_matching,
            "actionable_matching": actionable_matching,
            "policy_matching": policy_matching,
            "result_scope_cards": result_scope_cards,
            "policy_rows": policy_rows,
            "policy_rows_truncated": policy_matching > len(policy_rows),
            "affected_device_count": len(affected_devices),
            "page_query": page_query.urlencode(),
        },
    )


def _policy_candidate_state_action_blocked(request: HttpRequest, finding: Finding) -> bool:
    """Keep recommendation state separate from the SoftwareDecision workflow."""
    if finding.finding_type.name not in _SOFTWARE_POLICY_CANDIDATE_TYPES:
        return False
    messages.info(
        request,
        "This is a software policy candidate. Review it through Software Decisions; "
        "a global, client, or device decision is the authoritative action.",
    )
    return True


@login_required
@require_POST
def finding_acknowledge(request: HttpRequest, finding_id: str) -> HttpResponse:
    """Acknowledge an entity finding."""
    finding = get_object_or_404(
        Finding.objects.select_related("finding_type"), id=finding_id, tenant_id=1
    )
    if _policy_candidate_state_action_blocked(request, finding):
        return redirect(request.POST.get("next") or "findings_queue")
    if finding.status == Finding.Status.OPEN:
        finding.status = Finding.Status.ACKNOWLEDGED
        fields = ["status"]
        if finding.acknowledged_at is None:
            finding.acknowledged_at = timezone.now()
            fields.append("acknowledged_at")
        finding.save(update_fields=fields)
    return redirect(request.POST.get("next") or "findings_queue")


@login_required
@require_POST
def finding_resolve(request: HttpRequest, finding_id: str) -> HttpResponse:
    finding = get_object_or_404(
        Finding.objects.select_related("finding_type"), id=finding_id, tenant_id=1
    )
    if _policy_candidate_state_action_blocked(request, finding):
        return redirect(request.POST.get("next") or "findings_queue")
    if finding.status != Finding.Status.RESOLVED:
        finding.status = Finding.Status.RESOLVED
        finding.closed_at = finding.closed_at or timezone.now()
        finding.save(update_fields=["status", "closed_at"])
    return redirect(request.POST.get("next") or "findings_queue")


@login_required
@require_POST
def finding_snooze(request: HttpRequest, finding_id: str) -> HttpResponse:
    """Snooze an issue for N days (default 7)."""
    finding = get_object_or_404(
        Finding.objects.select_related("finding_type"), id=finding_id, tenant_id=1
    )
    if _policy_candidate_state_action_blocked(request, finding):
        return redirect(request.POST.get("next") or "findings_queue")
    try:
        days = int(request.POST.get("days") or 7)
    except ValueError:
        days = 7
    days = max(1, min(days, 90))
    finding.snoozed_until = timezone.now() + timedelta(days=days)
    finding.save(update_fields=["snoozed_until"])
    messages.info(request, f"Snoozed for {days} day{'s' if days != 1 else ''}.")
    return redirect(request.POST.get("next") or "findings_queue")


@login_required
@require_POST
def finding_suppress(request: HttpRequest, finding_id: str) -> HttpResponse:
    """Create a SuppressionRule matching this finding's subject."""
    finding = get_object_or_404(
        Finding.objects.select_related("finding_type"),
        id=finding_id,
        tenant_id=1,
    )
    if _policy_candidate_state_action_blocked(request, finding):
        return redirect(request.POST.get("next") or "findings_queue")
    reason = (request.POST.get("reason") or "").strip() or "Suppressed from Issues"
    expires_days = request.POST.get("expires_days")
    expires_at = None
    if expires_days:
        try:
            expires_at = timezone.now() + timedelta(days=max(1, min(int(expires_days), 365)))
        except ValueError:
            expires_at = None

    SuppressionRule.objects.create(
        tenant_id=1,
        finding_type=finding.finding_type,
        subject_match={
            "subject_type": finding.subject_type,
            "subject_id": str(finding.subject_id),
        },
        reason=reason,
        expires_at=expires_at,
        created_by=request.user,
    )
    now = timezone.now()
    finding.status = Finding.Status.SUPPRESSED
    finding.closed_at = finding.closed_at or now
    finding.save(update_fields=["status", "closed_at"])
    messages.info(request, "Issue suppressed.")
    return redirect(request.POST.get("next") or "findings_queue")


@login_required
@require_POST
def findings_bulk_action(request: HttpRequest) -> HttpResponse:
    """Apply one action across multiple selected findings."""
    ids = request.POST.getlist("ids")
    action = (request.POST.get("action") or "").strip()
    if not ids or action not in ("ack", "resolve", "snooze"):
        messages.warning(request, "Pick an action and at least one issue.")
        return redirect(request.POST.get("next") or "findings_queue")

    now = timezone.now()
    qs = Finding.objects.filter(tenant_id=1, id__in=ids)
    policy_count = qs.filter(
        finding_type__name__in=_SOFTWARE_POLICY_CANDIDATE_TYPES
    ).count()
    qs = qs.exclude(finding_type__name__in=_SOFTWARE_POLICY_CANDIDATE_TYPES)
    if not qs.exists():
        messages.info(
            request,
            "Software policy candidates are reviewed through Software Decisions; "
            "no issue-state action was applied.",
        )
        return redirect(request.POST.get("next") or "findings_queue")
    if action == "ack":
        # First-time ack sets acknowledged_at; reack (rare) leaves the
        # original stamp so MTTA stays honest.
        touched = qs.filter(status=Finding.Status.OPEN, acknowledged_at__isnull=True).update(
            status=Finding.Status.ACKNOWLEDGED,
            acknowledged_at=now,
        )
        touched += qs.filter(status=Finding.Status.OPEN, acknowledged_at__isnull=False).update(
            status=Finding.Status.ACKNOWLEDGED,
        )
        message = f"Acknowledged {touched} issue{'s' if touched != 1 else ''}."
    elif action == "resolve":
        touched = qs.exclude(status=Finding.Status.RESOLVED).update(
            status=Finding.Status.RESOLVED,
            closed_at=now,
        )
        message = f"Resolved {touched} issue{'s' if touched != 1 else ''}."
    elif action == "snooze":
        try:
            days = int(request.POST.get("days") or 7)
        except ValueError:
            days = 7
        days = max(1, min(days, 90))
        until = timezone.now() + timedelta(days=days)
        touched = qs.update(snoozed_until=until)
        message = f"Snoozed {touched} for {days} day{'s' if days != 1 else ''}."
    if policy_count:
        message += (
            f" Skipped {policy_count} software policy candidate"
            f"{'s' if policy_count != 1 else ''}."
        )
    messages.info(request, message)
    return redirect(request.POST.get("next") or "findings_queue")


# ─────────────────────────────────────────────────────────────────────
# Software fleet page — the whole software ecosystem across the fleet:
# inventory, catalog classification, decisions, and issues as ONE
# facet (not the whole story).
# ─────────────────────────────────────────────────────────────────────


def _software_page_data(request: HttpRequest) -> dict:
    """Compute the full data set shared by the Software Overview and
    Products list views. Returns a context dict ready for render().
    Both views render different templates from the same data.
    """
    q_filter = (request.GET.get("q") or "").strip()
    decision_filter = request.GET.get("decision", "")  # approved|rejected|pending|any
    category_filter = request.GET.get("category", "")  # av|rmm|remote_access|...|uncategorized
    safety_filter = request.GET.get("safety", "")      # high|medium|low|clean
    publisher_filter = (request.GET.get("publisher") or "").strip()
    flagged_filter = request.GET.get("flagged", "").strip().lower() in ("1", "true", "yes", "on")
    min_devices = request.GET.get("min_devices", "").strip()
    try:
        min_devices_int = int(min_devices) if min_devices else 0
    except ValueError:
        min_devices_int = 0

    # Intel layer availability probe — used to gate risk queries.
    intel_available = False
    try:
        with connection.cursor() as pcur:
            pcur.execute("SELECT to_regclass('operations.v_software_safety')")
            (regclass,) = pcur.fetchone()
            intel_available = regclass is not None
    except Exception:
        intel_available = False
    if not intel_available and safety_filter:
        safety_filter = ""

    # Fetch v_software_safety ONCE up front. Everything downstream —
    # per-title risk map, high-risk count, distribution, this-week
    # highlights, AND the ?safety=<band> filter — is derived from this
    # single snapshot.
    #
    # The comment here used to justify this by "the view is a multi-CTE join
    # that costs ~700-900 ms per evaluation". That is no longer true: it has
    # since been materialized, and the full unbounded fetch measures 19 ms
    # against production. Fetching once is still right — one round trip beats
    # six — but it is not the page's cost center, and chasing it would have
    # been wasted effort.
    all_safety_rows: list[tuple] = []
    if intel_available:
        try:
            with transaction.atomic(), connection.cursor() as sc:
                sc.execute("SET LOCAL operations.tenant_id = 1")
                sc.execute(
                    """
                    SELECT canonical_name, safety_score, safety_band,
                           cve_count, kev_count, osint_hits
                    FROM operations.v_software_safety
                    WHERE tenant_id = 1
                    """
                )
                all_safety_rows = list(sc.fetchall())
        except Exception:
            all_safety_rows = []

    # If a risk-band filter is set, resolve the matching canonical set
    # up front so the main title-rollup query can filter with a cheap
    # ANY() against that fixed list instead of a per-row EXISTS on the
    # view (which timed out on fleets with tens of thousands of titles).
    safety_filter_names: list[str] = []
    if safety_filter in ("high", "medium", "low", "clean", "unknown"):
        safety_filter_names = [
            r[0] for r in all_safety_rows if r[2] == safety_filter
        ]
        if not safety_filter_names:
            # No products in that band. Force the main query to return
            # zero title rows without scanning the whole fleet.
            safety_filter_names = ["\x00__no_match__\x00"]

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")

        cur.execute(
            """
            SELECT COUNT(*) FROM operations.software_catalog
            WHERE tenant_id = 1 OR tenant_id IS NULL
            """
        )
        (categorized_titles,) = cur.fetchone()

        # Decisions rollup
        cur.execute(
            """
            SELECT decision, COUNT(*) FROM operations.software_decisions
            WHERE tenant_id = 1 GROUP BY decision
            """
        )
        decision_counts = {row[0]: row[1] for row in cur.fetchall()}

        # Category breakdown (from catalog rows)
        cur.execute(
            """
            SELECT jsonb_array_elements_text(categories) AS category,
                   COUNT(DISTINCT canonical_name) AS titles
            FROM operations.software_catalog
            WHERE tenant_id = 1 OR tenant_id IS NULL
            GROUP BY category
            ORDER BY titles DESC
            """
        )
        category_rows = cur.fetchall()

        # Titles-across-the-fleet aggregate. One row per canonical
        # product with rollup counts. Filter by name, category,
        # decision.
        where_clauses = ["sic.tenant_id = 1"]
        params: list = []
        if q_filter:
            where_clauses.append("(sic.canonical_name ILIKE %s OR sic.publisher ILIKE %s)")
            params.extend([f"%{q_filter}%", f"%{q_filter}%"])
        if publisher_filter:
            where_clauses.append("sic.publisher ILIKE %s")
            params.append(f"%{publisher_filter}%")
        if flagged_filter:
            # Products with at least one open classifier finding — the
            # "needs decision" set. Same signal the retired Decisions
            # queue surfaced, now available as a filter on Products.
            where_clauses.append(
                "EXISTS (SELECT 1 FROM operations.findings f "
                " JOIN operations.finding_types ft ON ft.id = f.finding_type_id "
                " WHERE f.tenant_id = 1 "
                "   AND f.status IN ('open', 'acknowledged') "
                "   AND ft.source_module = 'platform.software_findings' "
                "   AND f.finding_details->>'canonical_name' = sic.canonical_name)"
            )
        if category_filter == "uncategorized":
            where_clauses.append(
                "NOT EXISTS (SELECT 1 FROM operations.software_catalog cat "
                " WHERE cat.canonical_name = sic.canonical_name "
                "   AND (cat.tenant_id = sic.tenant_id OR cat.tenant_id IS NULL))"
            )
        elif category_filter:
            where_clauses.append(
                "EXISTS (SELECT 1 FROM operations.software_catalog cat "
                " WHERE cat.canonical_name = sic.canonical_name "
                "   AND (cat.tenant_id = sic.tenant_id OR cat.tenant_id IS NULL) "
                "   AND cat.categories ? %s)"
            )
            params.append(category_filter)
        if decision_filter == "approved":
            where_clauses.append(
                "(EXISTS (SELECT 1 FROM operations.software_decisions sd "
                " WHERE sd.tenant_id = sic.tenant_id "
                "   AND sd.canonical_name = sic.canonical_name "
                "   AND sd.decision IN ('approve','approve_publisher'))"
                " OR EXISTS (SELECT 1 FROM operations.software_decisions sd "
                " WHERE sd.tenant_id = sic.tenant_id "
                "   AND sd.publisher <> '' "
                "   AND LOWER(sd.publisher) = LOWER(COALESCE(sic.publisher, '')) "
                "   AND sd.decision IN ('approve','approve_publisher')))"
            )
        elif decision_filter == "rejected":
            where_clauses.append(
                "(EXISTS (SELECT 1 FROM operations.software_decisions sd "
                " WHERE sd.tenant_id = sic.tenant_id "
                "   AND sd.canonical_name = sic.canonical_name "
                "   AND sd.decision = 'reject')"
                " OR EXISTS (SELECT 1 FROM operations.software_decisions sd "
                " WHERE sd.tenant_id = sic.tenant_id "
                "   AND sd.publisher <> '' "
                "   AND LOWER(sd.publisher) = LOWER(COALESCE(sic.publisher, '')) "
                "   AND sd.decision = 'reject'))"
            )
        elif decision_filter == "pending":
            where_clauses.append(
                "NOT EXISTS (SELECT 1 FROM operations.software_decisions sd "
                " WHERE sd.tenant_id = sic.tenant_id "
                "   AND (sd.canonical_name = sic.canonical_name "
                "        OR (sd.publisher <> '' "
                "            AND LOWER(sd.publisher) = LOWER(COALESCE(sic.publisher, '')))))"
            )
        if safety_filter_names:
            # Filter to the pre-computed canonical set for this risk
            # band — avoids re-evaluating v_software_safety per row.
            where_clauses.append("sic.canonical_name = ANY(%s::text[])")
            params.append(safety_filter_names)

        where_sql = " AND ".join(where_clauses)
        cur.execute(
            f"""
            WITH totals AS (
                SELECT COALESCE(SUM(installations), 0)::bigint AS installations,
                       COUNT(*)::bigint AS unique_titles
                FROM operations.software_title_current
                WHERE tenant_id = 1
            ),
            filtered AS (
                SELECT sic.canonical_name,
                       sic.publisher,
                       sic.device_count,
                       sic.client_count,
                       sic.latest_install AS last_install,
                   (SELECT array_agg(DISTINCT cat_name)
                    FROM operations.software_catalog cat,
                         jsonb_array_elements_text(cat.categories) AS cat_name
                    WHERE cat.canonical_name = sic.canonical_name
                      AND (cat.tenant_id = sic.tenant_id OR cat.tenant_id IS NULL)
                   ) AS categories,
                   (SELECT MIN(sd.decision)
                    FROM operations.software_decisions sd
                    WHERE sd.tenant_id = sic.tenant_id
                      AND sd.canonical_name = sic.canonical_name
                   ) AS decision
                FROM operations.software_title_current sic
                WHERE {where_sql}
                  AND sic.device_count >= {min_devices_int}
                ORDER BY sic.device_count DESC, sic.canonical_name
                LIMIT 500
            )
            SELECT filtered.canonical_name,
                   filtered.publisher,
                   filtered.device_count,
                   filtered.client_count,
                   filtered.last_install,
                   filtered.categories,
                   filtered.decision,
                   totals.installations,
                   totals.unique_titles
            FROM totals
            LEFT JOIN filtered ON TRUE
            """,
            params,
        )
        software_rows = cur.fetchall()
        installations = software_rows[0][7]
        unique_titles = software_rows[0][8]
        title_rows = [row[:7] for row in software_rows if row[0] is not None]

        canonical_names = [row[0] for row in title_rows]

        # Recent installations — last 24h, first-seen
        cur.execute(
            """
            SELECT sic.canonical_name, sic.publisher, c.display_name AS client,
                   sic.first_observed_at
            FROM operations.software_installations_current sic
            JOIN operations.clients c ON c.id = sic.client_id
            WHERE sic.tenant_id = 1 AND sic.deleted_at IS NULL
              AND sic.first_observed_at >= NOW() - INTERVAL '24 hours'
            ORDER BY sic.first_observed_at DESC
            LIMIT 10
            """
        )
        recent_installs = cur.fetchall()

    # v_software_safety was already fetched once at the top of the
    # request. Reuse ``all_safety_rows`` for all downstream aggregates.
    safety_by_title: dict[str, dict] = {}
    shown_set = {c for c in canonical_names}
    high_risk_titles = 0
    risk_distribution = {"high": 0, "medium": 0, "low": 0, "clean": 0, "unknown": 0}
    for cn, score, band, cve_count, kev_count, osint_hits in all_safety_rows:
        if band in risk_distribution:
            risk_distribution[band] += 1
        if band == "high":
            high_risk_titles += 1
        if cn in shown_set:
            safety_by_title[cn] = {
                "score": score, "band": band,
                "cve_count": cve_count, "kev_count": kev_count,
                "osint_hits": osint_hits,
            }

    # Risk distribution + this-week highlights + workflow aggregates.
    this_week: dict = {"new_products": 0, "new_high_risk": 0, "top_new_product": None}
    workflow_state: dict = {
        "publishers_undecided": 0,
        "tech_checklist_devices": 0,
        "user_risk_users": 0,
    }
    try:
        with transaction.atomic(), connection.cursor() as sc:
            sc.execute("SET LOCAL operations.tenant_id = 1")
            sc.execute(
                """
                SELECT canonical_name
                FROM operations.software_title_current
                WHERE tenant_id = 1
                  AND latest_install >= NOW() - INTERVAL '7 days'
                """
            )
            new_products_set = {row[0] for row in sc.fetchall()}
            this_week["new_products"] = len(new_products_set)
            sc.execute(
                """
                SELECT canonical_name, device_count AS devices
                FROM operations.software_title_current
                WHERE tenant_id = 1
                  AND latest_install >= NOW() - INTERVAL '7 days'
                ORDER BY device_count DESC, canonical_name LIMIT 1
                """
            )
            row = sc.fetchone()
            if row:
                this_week["top_new_product"] = {"name": row[0], "devices": row[1]}
        # Derive new-high-risk from the safety snapshot rather than a
        # separate view scan.
        this_week["new_high_risk"] = sum(
            1 for r in all_safety_rows
            if r[2] == "high" and r[0] in new_products_set
        )
    except Exception:
        pass

    try:
        with transaction.atomic(), connection.cursor() as sc:
            sc.execute("SET LOCAL operations.tenant_id = 1")
            # Publishers with at least one fleet install and no
            # global publisher-scope decision.
            sc.execute(
                """
                SELECT COUNT(DISTINCT LOWER(sic.publisher))::int
                FROM operations.software_title_current sic
                WHERE sic.tenant_id = 1
                  AND COALESCE(sic.publisher, '') <> ''
                  AND NOT EXISTS (
                      SELECT 1 FROM operations.software_decisions sd
                      WHERE sd.tenant_id = 1
                        AND sd.publisher <> ''
                        AND sd.client_id IS NULL AND sd.device_id IS NULL
                        AND LOWER(sd.publisher) = LOWER(sic.publisher)
                  )
                """
            )
            (workflow_state["publishers_undecided"],) = sc.fetchone()
    except Exception:
        pass

    try:
        with transaction.atomic(), connection.cursor() as sc:
            sc.execute("SET LOCAL operations.tenant_id = 1")
            sc.execute(
                """
                -- Software findings are subjects on the title or release now,
                -- so the affected devices come from the exposure view rather
                -- than from subject_id.
                SELECT COUNT(DISTINCT e.device_id)::int
                FROM operations.v_device_software_exposure e
                WHERE e.tenant_id = 1
                  AND e.status IN ('open','acknowledged')
                  AND e.finding_type <> 'whitelist_suggestion'
                """
            )
            (workflow_state["tech_checklist_devices"],) = sc.fetchone()
    except Exception:
        pass

    # Software issues count (Finding table). Split whitelist_suggestion
    # out of "issues" — it's a review candidate, not a problem.
    software_open_qs = Finding.objects.filter(
        tenant_id=1,
        status__in=_FINDING_ACTIVE_STATUSES,
        finding_type__category__name="software",
    )
    software_issues = software_open_qs.exclude(
        finding_type__name="whitelist_suggestion"
    ).count()
    # Resolve the registry id before the distinct JSON aggregate.  Filtering
    # through the category/type joins made PostgreSQL abandon the existing
    # partial expression index on `finding_details -> 'canonical_name'`; on
    # production that aggregate then exceeded Gunicorn's 30-second timeout and
    # made the Products page return 500.  The direct predicate is equivalent
    # (the type is itself a software finding) and uses
    # idx_findings_type_canonical.
    whitelist_type_id = (
        FindingType.objects.filter(name="whitelist_suggestion")
        .values_list("id", flat=True)
        .first()
    )
    whitelist_suggestions = (
        Finding.objects.filter(
            tenant_id=1,
            status__in=_FINDING_ACTIVE_STATUSES,
            finding_type_id=whitelist_type_id,
        )
        .values("finding_details__canonical_name")
        .distinct()
        .count()
        if whitelist_type_id is not None
        else 0
    )

    # Product-level decision counts. A publisher-scope decision applies
    # to every product from that publisher, so the raw
    # SoftwareDecision row count is wrong. Count DISTINCT canonical_names
    # that have EITHER a title-scope decision or a matching publisher-
    # scope decision at global scope.
    approved_titles = rejected_titles = investigate_titles = 0
    try:
        with transaction.atomic(), connection.cursor() as sc:
            sc.execute("SET LOCAL operations.tenant_id = 1")
            sc.execute(
                """
                -- Pre-aggregate the decisions, then join. This was three
                -- correlated EXISTS subqueries evaluated per title, i.e.
                -- 20,631 x 3 scans of software_decisions: 1,484 ms measured
                -- against production. Aggregating first and hash-joining the
                -- result measures 83 ms for the same three numbers.
                WITH scoped AS (
                    SELECT canonical_name, LOWER(publisher) AS pub, decision
                    FROM operations.software_decisions
                    WHERE tenant_id = 1 AND client_id IS NULL AND device_id IS NULL
                      AND decision IN ('approve','approve_publisher','reject','investigate')
                ), by_name AS (
                    SELECT canonical_name,
                           BOOL_OR(decision IN ('approve','approve_publisher')) AS appr,
                           BOOL_OR(decision = 'reject') AS rej,
                           BOOL_OR(decision = 'investigate') AS inv
                    FROM scoped WHERE canonical_name <> '' GROUP BY 1
                ), by_pub AS (
                    SELECT pub,
                           BOOL_OR(decision IN ('approve','approve_publisher')) AS appr,
                           BOOL_OR(decision = 'reject') AS rej,
                           BOOL_OR(decision = 'investigate') AS inv
                    FROM scoped WHERE pub <> '' GROUP BY 1
                )
                SELECT
                    COUNT(DISTINCT sic.canonical_name)
                        FILTER (WHERE COALESCE(n.appr, FALSE) OR COALESCE(p.appr, FALSE)) AS approved,
                    COUNT(DISTINCT sic.canonical_name)
                        FILTER (WHERE COALESCE(n.rej, FALSE) OR COALESCE(p.rej, FALSE)) AS rejected,
                    COUNT(DISTINCT sic.canonical_name)
                        FILTER (WHERE COALESCE(n.inv, FALSE) OR COALESCE(p.inv, FALSE)) AS investigating
                FROM operations.software_title_current sic
                LEFT JOIN by_name n ON n.canonical_name = sic.canonical_name
                LEFT JOIN by_pub  p ON p.pub = LOWER(COALESCE(sic.publisher, ''))
                WHERE sic.tenant_id = 1
                """
            )
            row = sc.fetchone() or (0, 0, 0)
            approved_titles = row[0] or 0
            rejected_titles = row[1] or 0
            investigate_titles = row[2] or 0
    except Exception:
        # Fall back to raw counts if the join fails somehow.
        approved_titles = decision_counts.get("approve", 0)
        rejected_titles = decision_counts.get("reject", 0)
        investigate_titles = decision_counts.get("investigate", 0)
    pending_decisions = unique_titles - approved_titles - rejected_titles - investigate_titles
    if pending_decisions < 0:
        pending_decisions = 0

    titles = []
    for row in title_rows:
        canonical = row[0]
        safety = safety_by_title.get(canonical, {})
        titles.append({
            "canonical_name": canonical,
            "publisher": row[1] or "",
            "device_count": row[2],
            "client_count": row[3],
            "last_install": row[4],
            "categories": row[5] or [],
            "decision": row[6],
            "safety_score": safety.get("score"),
            "safety_band": safety.get("band", ""),
            "safety_cve_count": safety.get("cve_count", 0),
            "safety_kev_count": safety.get("kev_count", 0),
            "safety_osint_hits": safety.get("osint_hits", 0),
        })

    return {
        "installations": installations,
        "unique_titles": unique_titles,
        "categorized_titles": categorized_titles,
        "uncategorized_titles": unique_titles - categorized_titles
        if unique_titles > categorized_titles
        else 0,
        "approved_titles": approved_titles,
        "rejected_titles": rejected_titles,
        "investigate_titles": investigate_titles,
        "pending_decisions": pending_decisions,
        "software_issues": software_issues,
        "whitelist_suggestions": whitelist_suggestions,
        "high_risk_titles": high_risk_titles,
        "category_rows": category_rows,
        "titles": titles,
        "recent_installs": recent_installs,
        "active_q": q_filter,
        "active_category": category_filter,
        "active_decision": decision_filter,
        "active_safety": safety_filter,
        "active_publisher": publisher_filter,
        "active_min_devices": min_devices_int,
        "active_flagged": flagged_filter,
        "decision_choices": SoftwareDecision.Decision.choices,
        "risk_distribution": risk_distribution,
        "this_week": this_week,
        "workflow_state": workflow_state,
    }


@login_required
def software_page(request: HttpRequest) -> HttpResponse:
    """Software Overview — dashboard tiles + workflows + distribution
    + recent installs. The full products list lives under Products
    (see software_products)."""
    ctx = _software_page_data(request)
    if wants_csv(request):
        # CSV export on Overview yields the top products the dashboard
        # dashboards summarize; keep parity with the previous behavior.
        return csv_response(
            ctx["titles"],
            columns=[
                ("Canonical name", "canonical_name"),
                ("Publisher", "publisher"),
                ("Device count", "device_count"),
                ("Client count", "client_count"),
                ("Last install", "last_install"),
                ("Categories", "categories"),
                ("Decision", "decision"),
            ],
            filename_stem="software",
        )
    ctx["software_tab"] = "overview"
    return render(request, "software_page.html", ctx)


@login_required
def software_products(request: HttpRequest) -> HttpResponse:
    """Software Products — the full products list with per-column
    filters (search / publisher / min_devices / risk / decision /
    category)."""
    ctx = _software_page_data(request)
    if wants_csv(request):
        return csv_response(
            ctx["titles"],
            columns=[
                ("Product", "canonical_name"),
                ("Publisher", "publisher"),
                ("Devices", "device_count"),
                ("Clients", "client_count"),
                ("Last install", "last_install"),
                ("Categories", "categories"),
                ("Decision", "decision"),
                ("Risk band", "safety_band"),
                ("Risk score", "safety_score"),
            ],
            filename_stem="software_products",
        )
    ctx["software_tab"] = "products"
    return render(request, "software_products.html", ctx)


# ─────────────────────────────────────────────────────────────────────
# Software title detail — per-canonical drill-through from /software/.
# Anchors row-level decisions, version breakdown, per-device install list,
# publisher facts, catalog metadata, related findings, and decision history.
# Case-insensitive canonical_name lookup; URL slug carries the display form.
# ─────────────────────────────────────────────────────────────────────


@login_required
def software_detail(request: HttpRequest, name: str) -> HttpResponse:
    canonical_name = name.strip()
    if not canonical_name:
        return redirect("software_page")

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")

        # Fleet-wide install rollup for this title.
        cur.execute(
            """
            SELECT COUNT(*)                             AS installations,
                   COUNT(DISTINCT sic.device_id)        AS devices,
                   COUNT(DISTINCT sic.client_id)        AS clients,
                   MIN(sic.first_observed_at)           AS first_observed,
                   MAX(sic.last_observed_at)            AS last_observed,
                   MAX(sic.first_observed_at)           AS latest_install
            FROM operations.software_installations_current sic
            WHERE sic.tenant_id = 1
              AND sic.deleted_at IS NULL
              AND sic.stale_since IS NULL
              AND LOWER(sic.canonical_name) = LOWER(%s)
            """,
            [canonical_name],
        )
        row = cur.fetchone()
        installations, devices, clients, first_observed, last_observed, latest_install = row

        if not installations:
            # Fall back to any historical row (deleted / stale) so an
            # operator following a stale finding link still lands somewhere.
            cur.execute(
                """
                SELECT canonical_name FROM operations.software_installations_current
                WHERE tenant_id = 1 AND LOWER(canonical_name) = LOWER(%s)
                LIMIT 1
                """,
                [canonical_name],
            )
            r = cur.fetchone()
            if not r:
                messages.warning(
                    request,
                    f"No installations recorded for “{canonical_name}”.",
                )
                return redirect("software_page")
            canonical_name = r[0]

        # Preserve the display form the installations table uses.
        cur.execute(
            """
            SELECT canonical_name FROM operations.software_installations_current
            WHERE tenant_id = 1 AND LOWER(canonical_name) = LOWER(%s)
            LIMIT 1
            """,
            [canonical_name],
        )
        r = cur.fetchone()
        if r:
            canonical_name = r[0]

        # Publisher facts — every distinct publisher the fleet observed for
        # this title, with per-publisher install counts. Multiple publishers
        # for the same canonical_name usually indicate a rename / catalog
        # merge and are worth surfacing.
        cur.execute(
            """
            SELECT COALESCE(NULLIF(publisher, ''), '(unknown)') AS publisher,
                   COUNT(*)::int AS installs,
                   COUNT(DISTINCT device_id)::int AS devices
            FROM operations.software_installations_current
            WHERE tenant_id = 1 AND deleted_at IS NULL AND stale_since IS NULL
              AND LOWER(canonical_name) = LOWER(%s)
            GROUP BY 1
            ORDER BY installs DESC
            """,
            [canonical_name],
        )
        publisher_rows = [
            {"publisher": row[0], "installs": row[1], "devices": row[2]}
            for row in cur.fetchall()
        ]

        # Version breakdown — one row per distinct version.
        cur.execute(
            """
            SELECT COALESCE(NULLIF(version, ''), '(unknown)') AS version,
                   COUNT(*)::int AS installs,
                   COUNT(DISTINCT device_id)::int AS devices,
                   COUNT(DISTINCT client_id)::int AS clients,
                   MAX(last_observed_at) AS last_observed
            FROM operations.software_installations_current
            WHERE tenant_id = 1 AND deleted_at IS NULL AND stale_since IS NULL
              AND LOWER(canonical_name) = LOWER(%s)
            GROUP BY 1
            ORDER BY installs DESC, version
            """,
            [canonical_name],
        )
        version_rows = [
            {
                "version": row[0],
                "installs": row[1],
                "devices": row[2],
                "clients": row[3],
                "last_observed": row[4],
            }
            for row in cur.fetchall()
        ]

        # Install-location breakdown.
        cur.execute(
            """
            SELECT COALESCE(NULLIF(install_location, ''), '(unknown)') AS location,
                   COUNT(*)::int AS installs
            FROM operations.software_installations_current
            WHERE tenant_id = 1 AND deleted_at IS NULL AND stale_since IS NULL
              AND LOWER(canonical_name) = LOWER(%s)
            GROUP BY 1
            ORDER BY installs DESC
            LIMIT 20
            """,
            [canonical_name],
        )
        location_rows = [
            {"location": row[0], "installs": row[1]} for row in cur.fetchall()
        ]

        # Per-device install list — bounded so a mega-title doesn't OOM.
        cur.execute(
            """
            SELECT sic.device_id, sic.client_id, c.slug, c.display_name,
                   d.canonical_hostname, d.device_role, d.os_group,
                   sic.version, sic.install_location, sic.install_date,
                   sic.first_observed_at, sic.last_observed_at
            FROM operations.software_installations_current sic
            JOIN operations.clients c ON c.id = sic.client_id
            JOIN operations.devices d ON d.id = sic.device_id
            WHERE sic.tenant_id = 1
              AND sic.deleted_at IS NULL
              AND sic.stale_since IS NULL
              AND LOWER(sic.canonical_name) = LOWER(%s)
            ORDER BY c.display_name, d.canonical_hostname
            LIMIT 500
            """,
            [canonical_name],
        )
        install_rows = [
            {
                "device_id": row[0],
                "client_id": row[1],
                "client_slug": row[2],
                "client_name": row[3],
                "hostname": row[4],
                "device_role": row[5],
                "os_group": row[6],
                "version": row[7] or "",
                "install_location": row[8] or "",
                "install_date": row[9],
                "first_observed": row[10],
                "last_observed": row[11],
            }
            for row in cur.fetchall()
        ]

    # Safety intel — composite score + matched CVEs + OSINT signals.
    safety_summary: dict = {}
    matched_cves: list[dict] = []
    osint_rows: list[dict] = []
    catalog_tags: list[str] = []
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """
            SELECT safety_score, safety_band,
                   cve_count, kev_count, osint_hits, publisher_osint_hits,
                   max_cvss, max_epss,
                   title_approved, title_rejected,
                   publisher_approved, publisher_rejected
            FROM operations.v_software_safety
            WHERE tenant_id = 1 AND LOWER(canonical_name) = LOWER(%s)
            """,
            [canonical_name],
        )
        row = cur.fetchone()
        if row:
            safety_summary = {
                "score": row[0], "band": row[1],
                "cve_count": row[2], "kev_count": row[3],
                "osint_hits": row[4], "publisher_osint_hits": row[5],
                "max_cvss": row[6], "max_epss": row[7],
                "title_approved": row[8], "title_rejected": row[9],
                "publisher_approved": row[10], "publisher_rejected": row[11],
            }
        cur.execute(
            """
            SELECT c.cve_id, c.severity, c.cvss_v3, c.epss_score, c.kev_flag,
                   c.kev_added_at, c.description, cm.confidence, cm.match_kind
            FROM operations.cve_match cm
            JOIN intel.cves c ON c.cve_id = cm.cve_id
            WHERE cm.tenant_id = 1 AND LOWER(cm.canonical_name) = LOWER(%s)
            ORDER BY c.kev_flag DESC, c.cvss_v3 DESC NULLS LAST, c.epss_score DESC NULLS LAST
            LIMIT 100
            """,
            [canonical_name],
        )
        for r in cur.fetchall():
            matched_cves.append({
                "cve_id": r[0], "severity": r[1], "cvss_v3": r[2],
                "epss_score": r[3], "kev_flag": r[4], "kev_added_at": r[5],
                "description": (r[6] or "")[:400],
                "confidence": r[7], "match_kind": r[8],
            })
        cur.execute(
            """
            SELECT source, signal_type, severity, details, observed_at
            FROM operations.safety_signal
            WHERE tenant_id = 1
              AND (LOWER(canonical_name) = LOWER(%s)
                   OR (publisher <> ''
                       AND LOWER(publisher) IN (
                           SELECT LOWER(publisher)
                           FROM operations.software_installations_current
                           WHERE tenant_id = 1
                             AND LOWER(canonical_name) = LOWER(%s)
                             AND publisher <> ''
                           LIMIT 5
                       )))
            ORDER BY severity DESC, observed_at DESC
            LIMIT 50
            """,
            [canonical_name, canonical_name],
        )
        for r in cur.fetchall():
            osint_rows.append({
                "source": r[0], "signal_type": r[1], "severity": r[2],
                "details": r[3], "observed_at": r[4],
            })

    # Catalog metadata — categories, publisher hint, EOL, notes.
    catalog_entry = (
        SoftwareCatalog.objects.filter(canonical_name__iexact=canonical_name)
        .filter(Q(tenant_id=1) | Q(tenant__isnull=True))
        .order_by("tenant_id")
        .first()
    )
    # Pull tags from winget/chocolatey safety_signal into a merged
    # categorization list. Operator-set catalog_entry.categories still wins.
    for row in osint_rows:
        details = row["details"]
        if (
            row["source"] in ("winget", "chocolatey")
            and row["signal_type"] == "category"
            and isinstance(details, dict)
        ):
            for tag in details.get("tags", []) or []:
                if tag and tag not in catalog_tags:
                    catalog_tags.append(str(tag))

    # Decision history — every scope for this canonical.
    decision_rows = list(
        SoftwareDecision.objects.filter(
            tenant_id=1, canonical_name__iexact=canonical_name
        )
        .select_related("client", "device", "decided_by")
        .order_by("-decided_at", "-id")
    )
    global_decision = next(
        (d for d in decision_rows if d.client_id is None and d.device_id is None),
        None,
    )
    client_decisions = [d for d in decision_rows if d.client_id and not d.device_id]
    device_decisions = [d for d in decision_rows if d.device_id]
    decision_scope_clients, decision_scope_devices = _decision_scope_targets(install_rows)

    # Global capability evidence belongs to stable product identities, not the
    # display title. The catalog can hold more than one identity for a title,
    # so retain that distinction in the review surface rather than guessing.
    capability_schema_ready = capability_evidence.schema_ready()
    capability_product_uuids = capability_evidence.products_for_title(canonical_name)
    capability_by_product = capability_evidence.effective_for_products(capability_product_uuids)
    capability_product_rows = [
        {"product_uuid": product_uuid, "rows": capability_by_product.get(product_uuid, [])}
        for product_uuid in capability_product_uuids
    ]
    can_curate_capability = request.user.has_perm(capability_evidence.CURATOR_PERMISSION)
    # Authorizing a product is a different decision from settling what it is,
    # so it carries its own permission and its own control.
    can_authorize_software = request.user.has_perm("core.authorize_software_product")
    # `decision_scope_clients` carries slugs, but an authorization is written
    # against the client UUID, so resolve them rather than letting the form
    # post an empty scope and silently authorize every client.
    authorization_clients = list(
        Client.objects.filter(
            tenant_id=1,
            deleted_at__isnull=True,
            slug__in=[row["slug"] for row in decision_scope_clients],
        )
        .order_by("display_name")
        .values("id", "display_name")
    )

    # Related active findings that name this title.
    related_findings = list(
        Finding.objects.filter(
            tenant_id=1,
            status__in=_FINDING_ACTIVE_STATUSES,
            finding_details__canonical_name__iexact=canonical_name,
        )
        .select_related("finding_type", "client")
        .order_by("-last_detected_at", "-last_seen_at")[:50]
    )

    return render(
        request,
        "software_detail.html",
        {
            "canonical_name": canonical_name,
            "catalog_entry": catalog_entry,
            "installations": installations,
            "device_count": devices,
            "client_count": clients,
            "first_observed": first_observed,
            "last_observed": last_observed,
            "latest_install": latest_install,
            "publishers": publisher_rows,
            "versions": version_rows,
            "locations": location_rows,
            "install_rows": install_rows,
            "global_decision": global_decision,
            "decision_scope_clients": decision_scope_clients,
            "decision_scope_devices": decision_scope_devices,
            "capability_schema_ready": capability_schema_ready,
            "capability_product_rows": capability_product_rows,
            "can_curate_capability": can_curate_capability,
            "can_authorize_software": can_authorize_software,
            "authorization_clients": authorization_clients,
            "client_decisions": client_decisions,
            "device_decisions": device_decisions,
            "related_findings": related_findings,
            "decision_choices": SoftwareDecision.Decision.choices,
            "back_url": request.META.get("HTTP_REFERER") or reverse("software_page"),
            "safety_summary": safety_summary,
            "matched_cves": matched_cves,
            "osint_rows": osint_rows,
            "catalog_tags": catalog_tags,
            "software_tab": "overview",
        },
    )


@login_required
@require_POST
@transaction.atomic
def software_capability_decide(request: HttpRequest) -> HttpResponse:
    """Confirm or reject global capability truth for one product identity."""
    if not request.user.has_perm(capability_evidence.CURATOR_PERMISSION):
        messages.error(request, "Platform-curator permission is required for capability decisions.")
        return redirect(_safe_next(request, "software_page"))

    product_uuid = (request.POST.get("product_uuid") or "").strip()
    capability = (request.POST.get("capability") or "").strip()
    decision = (request.POST.get("decision") or "").strip()
    rationale = (request.POST.get("rationale") or "").strip()
    if decision not in {"confirm", "reject"} or not product_uuid or not capability:
        messages.error(request, "A product identity, capability, and confirm or reject decision are required.")
        return redirect(_safe_next(request, "software_page"))
    try:
        product_id = uuid.UUID(product_uuid)
    except ValueError:
        messages.error(request, "Invalid product identity.")
        return redirect(_safe_next(request, "software_page"))

    polarity = decision == "confirm"
    try:
        # The nested transaction contains a rejected foreign-key/check input
        # without poisoning the request transaction or its audit path.
        with transaction.atomic():
            capability_evidence.confirm(
                str(product_id), capability, polarity, request.user.get_username(), rationale
            )
    except (capability_evidence.CapabilitySchemaUnavailable, IntegrityError, ValueError) as exc:
        messages.error(request, str(exc))
        return redirect(_safe_next(request, "software_page"))

    AuditLog.objects.create(
        tenant_id=1,
        actor=request.user,
        actor_kind=AuditLog.ActorKind.USER,
        source=AuditLog.Source.UI,
        action="software_capability.confirm" if polarity else "software_capability.reject",
        entity_type="catalog.product_capability",
        entity_id=product_id,
        before_state={},
        after_state={
            "product_uuid": str(product_id),
            "capability": capability,
            "polarity": polarity,
            "rationale": rationale,
        },
        ip_address=request.META.get("REMOTE_ADDR") or None,
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:2000],
    )
    messages.success(
        request,
        f"Capability {'confirmed' if polarity else 'rejected'} for the selected product identity.",
    )
    return redirect(_safe_next(request, "software_page"))


@login_required
@require_POST
@transaction.atomic
def software_product_authorize(request: HttpRequest) -> HttpResponse:
    """Permit or deny a product capability, globally or at one client.

    Distinct from `software_capability_decide`, which settles what a product
    *is*. This settles whether it is allowed here, and it is deliberately not a
    coverage requirement: requiring a platform states that a client must run
    it, which is a different claim from allowing it.
    """
    if not request.user.has_perm("core.authorize_software_product"):
        messages.error(request, "Authorization permission is required to permit or deny software.")
        return redirect(_safe_next(request, "software_page"))

    product_uuid = (request.POST.get("product_uuid") or "").strip()
    capability = (request.POST.get("capability") or "").strip()
    decision = (request.POST.get("decision") or "").strip()
    rationale = (request.POST.get("rationale") or "").strip()
    client_id = (request.POST.get("client_id") or "").strip()
    # No default polarity anywhere in the write path: an authorization must
    # state whether it permits or denies.
    if decision not in {"permit", "deny"} or not product_uuid or not capability:
        messages.error(request, "A product identity, capability, and permit or deny decision are required.")
        return redirect(_safe_next(request, "software_page"))
    if not rationale:
        messages.error(request, "A rationale is required so the authorization can be reviewed later.")
        return redirect(_safe_next(request, "software_page"))
    try:
        product_id = uuid.UUID(product_uuid)
        client_key = uuid.UUID(client_id) if client_id else None
    except ValueError:
        messages.error(request, "Invalid product or client identity.")
        return redirect(_safe_next(request, "software_page"))

    polarity = decision == "permit"
    try:
        with transaction.atomic():
            # Supersede rather than overwrite: the live row is withdrawn with a
            # reason and a new one inserted, so the change stays visible in
            # history instead of being erased.
            superseded = ProductAuthorization.objects.filter(
                tenant_id=1,
                client_id=client_key,
                product_uuid=product_id,
                capability=capability,
                withdrawn_at__isnull=True,
            ).update(
                withdrawn_at=timezone.now(),
                withdrawn_reason=f"superseded by a new {decision} decision",
            )
            ProductAuthorization.objects.create(
                tenant_id=1,
                client_id=client_key,
                product_uuid=product_id,
                capability=capability,
                polarity=polarity,
                rationale=rationale,
                authorized_by=request.user,
            )
    except (IntegrityError, ValueError) as exc:
        messages.error(request, str(exc))
        return redirect(_safe_next(request, "software_page"))

    AuditLog.objects.create(
        tenant_id=1,
        actor=request.user,
        actor_kind=AuditLog.ActorKind.USER,
        source=AuditLog.Source.UI,
        action=f"software_authorization.{decision}",
        entity_type="operations.product_authorization",
        entity_id=product_id,
        before_state={"superseded_rows": superseded},
        after_state={
            "product_uuid": str(product_id),
            "capability": capability,
            "client_id": str(client_key) if client_key else None,
            "polarity": polarity,
            "rationale": rationale,
        },
        ip_address=request.META.get("REMOTE_ADDR") or None,
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:2000],
    )
    scope = "this client" if client_key else "all clients"
    messages.success(
        request,
        f"Software {'permitted' if polarity else 'denied'} for {scope}.",
    )
    return redirect(_safe_next(request, "software_page"))


# ─────────────────────────────────────────────────────────────────────
# Software publisher rollup + per-publisher detail.
# Complements the per-title surfaces with a publisher-level view and
# publisher-scope decisions (SoftwareDecision.publisher, migration 0079).
# ─────────────────────────────────────────────────────────────────────


@login_required
def software_publishers(request: HttpRequest) -> HttpResponse:
    """List publishers with per-publisher install/product counts and
    current publisher-scope decision status. Supports filtering by name
    and by decision state (approved / rejected / pending)."""
    q_filter = (request.GET.get("q") or "").strip()
    decision_filter = (request.GET.get("decision") or "").strip().lower()

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")

        params: list = []
        extra_where = ""
        if q_filter:
            extra_where = "AND publisher ILIKE %s"
            params.append(f"%{q_filter}%")

        cur.execute(
            f"""
            SELECT COALESCE(NULLIF(publisher, ''), '(unknown)') AS publisher,
                   COUNT(*)::int AS installations,
                   COUNT(DISTINCT canonical_name)::int AS titles,
                   COUNT(DISTINCT device_id)::int AS devices,
                   COUNT(DISTINCT client_id)::int AS clients,
                   MAX(last_observed_at) AS last_observed
            FROM operations.software_installations_current
            WHERE tenant_id = 1
              AND deleted_at IS NULL
              AND stale_since IS NULL
              {extra_where}
            GROUP BY 1
            ORDER BY installations DESC, publisher
            LIMIT 500
            """,
            params,
        )
        rollup_rows = cur.fetchall()

    # Publisher-scope global decisions, keyed by lower(publisher).
    pub_decisions = {
        d.publisher.lower(): d
        for d in SoftwareDecision.objects.filter(
            tenant_id=1, client__isnull=True, device__isnull=True
        ).exclude(publisher="")
    }

    publishers = []
    for pub, installations, titles, devices, clients, last_observed in rollup_rows:
        dec = pub_decisions.get(pub.lower())
        publishers.append(
            {
                "publisher": pub,
                "installations": installations,
                "titles": titles,
                "devices": devices,
                "clients": clients,
                "last_observed": last_observed,
                "global_decision": dec.decision if dec else "",
                # PublisherCategory is retired as a competing capability path.
                # Product capability evidence appears on the title detail page,
                # where the stable product identity and its provenance are
                # visible; a publisher-wide label is too broad to be truth.
                "category": "",
            }
        )

    # Filter by decision state after computing all decisions.
    if decision_filter == "approved":
        publishers = [p for p in publishers if p["global_decision"] in ("approve", "approve_publisher")]
    elif decision_filter == "rejected":
        publishers = [p for p in publishers if p["global_decision"] == "reject"]
    elif decision_filter == "investigate":
        publishers = [p for p in publishers if p["global_decision"] == "investigate"]
    elif decision_filter == "pending":
        publishers = [p for p in publishers if not p["global_decision"]]

    if wants_csv(request):
        return csv_response(
            publishers,
            columns=[
                ("Publisher", "publisher"),
                ("Installations", "installations"),
                ("Products", "titles"),
                ("Devices", "devices"),
                ("Clients", "clients"),
                ("Last observed", "last_observed"),
                ("Global decision", "global_decision"),
            ],
            filename_stem="software_publishers",
        )

    return render(
        request,
        "software_publishers.html",
        {
            "publishers": publishers,
            "active_q": q_filter,
            "active_decision": decision_filter,
            "decision_choices": SoftwareDecision.Decision.choices,
            "software_tab": "publishers",
        },
    )


@login_required
def software_publisher_detail(request: HttpRequest, publisher: str) -> HttpResponse:
    """Per-publisher detail: titles under this publisher with per-title
    decision state, and inline publisher-scope decision action."""
    pub = publisher.strip()
    if not pub:
        return redirect("software_publishers")

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")

        # Preserve the display-form of the publisher.
        cur.execute(
            """
            SELECT publisher FROM operations.software_installations_current
            WHERE tenant_id = 1 AND deleted_at IS NULL AND stale_since IS NULL
              AND LOWER(publisher) = LOWER(%s)
            LIMIT 1
            """,
            [pub],
        )
        r = cur.fetchone()
        if r:
            pub = r[0] or pub

        # Rollup for the header tiles.
        cur.execute(
            """
            SELECT COUNT(*)::int AS installations,
                   COUNT(DISTINCT canonical_name)::int AS titles,
                   COUNT(DISTINCT device_id)::int AS devices,
                   COUNT(DISTINCT client_id)::int AS clients,
                   MIN(first_observed_at) AS first_observed,
                   MAX(last_observed_at) AS last_observed
            FROM operations.software_installations_current
            WHERE tenant_id = 1 AND deleted_at IS NULL AND stale_since IS NULL
              AND LOWER(publisher) = LOWER(%s)
            """,
            [pub],
        )
        installations, titles, devices, clients, first_observed, last_observed = (
            cur.fetchone()
        )

        # Titles under this publisher (bounded).
        cur.execute(
            """
            SELECT canonical_name,
                   COUNT(*)::int AS installs,
                   COUNT(DISTINCT device_id)::int AS device_count,
                   COUNT(DISTINCT client_id)::int AS client_count,
                   MAX(last_observed_at) AS last_observed
            FROM operations.software_installations_current
            WHERE tenant_id = 1 AND deleted_at IS NULL AND stale_since IS NULL
              AND LOWER(publisher) = LOWER(%s)
            GROUP BY canonical_name
            ORDER BY installs DESC, canonical_name
            LIMIT 500
            """,
            [pub],
        )
        title_rows_raw = cur.fetchall()

        # Scope targets are limited to current installations of this publisher.
        # A publisher-wide decision may only be narrowed to a client/device
        # that actually runs one of its products.
        cur.execute(
            """
            SELECT DISTINCT ON (sic.device_id)
                   sic.device_id, c.slug, c.display_name, d.canonical_hostname
              FROM operations.software_installations_current sic
              JOIN operations.clients c ON c.id = sic.client_id
              JOIN operations.devices d ON d.id = sic.device_id
             WHERE sic.tenant_id = 1 AND sic.deleted_at IS NULL
               AND sic.stale_since IS NULL
               AND LOWER(sic.publisher) = LOWER(%s)
             ORDER BY sic.device_id, c.display_name, d.canonical_hostname
             LIMIT 500
            """,
            [pub],
        )
        publisher_scope_rows = [
            {
                "device_id": row[0],
                "client_slug": row[1],
                "client_name": row[2],
                "hostname": row[3],
            }
            for row in cur.fetchall()
        ]

    canonical_names = [row[0] for row in title_rows_raw]
    title_decisions = {
        d.canonical_name.lower(): d
        for d in SoftwareDecision.objects.filter(
            tenant_id=1,
            client__isnull=True,
            device__isnull=True,
            canonical_name__in=canonical_names,
        )
    }
    title_rows = [
        {
            "canonical_name": row[0],
            "installs": row[1],
            "devices": row[2],
            "clients": row[3],
            "last_observed": row[4],
            "decision": (
                title_decisions[row[0].lower()].decision
                if row[0].lower() in title_decisions
                else ""
            ),
        }
        for row in title_rows_raw
    ]

    # Publisher-scope decisions (all tiers).
    pub_decision_rows = list(
        SoftwareDecision.objects.filter(tenant_id=1, publisher__iexact=pub)
        .select_related("client", "device", "decided_by")
        .order_by("-decided_at", "-id")
    )
    global_pub_decision = next(
        (d for d in pub_decision_rows if d.client_id is None and d.device_id is None),
        None,
    )
    client_pub_decisions = [
        d for d in pub_decision_rows if d.client_id and not d.device_id
    ]
    device_pub_decisions = [d for d in pub_decision_rows if d.device_id]
    decision_scope_clients, decision_scope_devices = _decision_scope_targets(
        publisher_scope_rows
    )

    return render(
        request,
        "software_publisher_detail.html",
        {
            "publisher": pub,
            "installations": installations,
            "title_count": titles,
            "device_count": devices,
            "client_count": clients,
            "first_observed": first_observed,
            "last_observed": last_observed,
            "title_rows": title_rows,
            "global_pub_decision": global_pub_decision,
            "decision_scope_clients": decision_scope_clients,
            "decision_scope_devices": decision_scope_devices,
            "client_pub_decisions": client_pub_decisions,
            "device_pub_decisions": device_pub_decisions,
            "decision_choices": SoftwareDecision.Decision.choices,
            "software_tab": "publishers",
        },
    )


# ─────────────────────────────────────────────────────────────────────
# User-risk view — per-user rollup of software checklist items on the
# device that user last logged into. Anchored on Ninja's
# lastLoggedInUser field, resolved via device_snapshots latest-per-device
# and canonical source links. Read-only.
# ─────────────────────────────────────────────────────────────────────


@login_required
def software_user_risk(request: HttpRequest) -> HttpResponse:
    client_slugs = [s for s in request.GET.getlist("client") if s]
    q_filter = (request.GET.get("q") or "").strip().lower()
    kind_filter = (request.GET.get("kind") or "").strip().lower()
    filtered_client_ids: list[str] = []
    if client_slugs:
        filtered_client_ids = [
            str(cid)
            for cid in Client.objects.filter(
                tenant_id=1, slug__in=client_slugs, deleted_at__isnull=True
            ).values_list("id", flat=True)
        ]

    client_where = ""
    client_params: list = []
    if filtered_client_ids:
        client_where = "AND d.client_id = ANY(%s::uuid[])"
        client_params.append(filtered_client_ids)
    elif client_slugs:
        client_where = "AND FALSE"

    sql = f"""
        WITH latest_user AS (
            SELECT ds.device_id AS ninja_device_id,
                   TRIM(ds.last_user) AS last_user,
                   ds.snapshot_at
            FROM operations.ninja_device_detail_current_shadow ds
            WHERE ds.last_user IS NOT NULL AND TRIM(ds.last_user) <> ''
        ),
        device_user AS (
            SELECT DISTINCT dl.device_id AS ops_device_id, lu.last_user, lu.snapshot_at
            FROM latest_user lu
            JOIN operations.v_device_source_link dl
              ON dl.external_id ~ '^\\d+$'
             AND dl.external_id::integer = lu.ninja_device_id
            JOIN operations.sources s ON s.id = dl.source_id
            WHERE dl.tenant_id = 1 AND LOWER(s.name) = 'ninja'
        ),
        finding_items AS (
            SELECT d.id AS device_id, d.client_id,
                   e.canonical_name,
                   e.finding_type AS kind
            FROM operations.v_device_software_exposure e
            JOIN operations.devices d ON d.id = e.device_id AND d.deleted_at IS NULL
            WHERE e.tenant_id = 1
              AND e.status IN ('open', 'acknowledged')
              AND e.finding_type <> 'whitelist_suggestion'
              {client_where}
        ),
        decision_items AS (
            SELECT d.id AS device_id, d.client_id,
                   sic.canonical_name,
                   ('decision_' || sd.decision) AS kind
            FROM operations.software_installations_current sic
            JOIN operations.devices d ON d.id = sic.device_id AND d.deleted_at IS NULL
            JOIN operations.software_decisions sd
              ON sd.tenant_id = sic.tenant_id
             AND sd.decision IN ('reject', 'investigate')
             AND (
                 (sd.canonical_name <> '' AND sd.canonical_name = sic.canonical_name)
              OR (sd.publisher <> ''
                  AND LOWER(sd.publisher) = LOWER(COALESCE(sic.publisher, '')))
             )
             AND (sd.device_id IS NULL OR sd.device_id = sic.device_id)
             AND (sd.client_id IS NULL OR sd.client_id = sic.client_id)
            WHERE sic.tenant_id = 1
              AND sic.deleted_at IS NULL
              AND sic.stale_since IS NULL
              {client_where}
        ),
        all_items AS (
            SELECT device_id, client_id, canonical_name, kind FROM finding_items
            UNION ALL
            SELECT device_id, client_id, canonical_name, kind FROM decision_items
        )
        SELECT du.last_user,
               d.id AS device_id,
               d.canonical_hostname,
               c.slug AS client_slug,
               c.display_name AS client_name,
               ai.canonical_name,
               ai.kind
        FROM device_user du
        JOIN operations.devices d ON d.id = du.ops_device_id AND d.deleted_at IS NULL
        JOIN operations.clients c ON c.id = d.client_id AND c.deleted_at IS NULL
        JOIN all_items ai ON ai.device_id = d.id
        WHERE d.tenant_id = 1
          {client_where}
        ORDER BY du.last_user, d.canonical_hostname, ai.kind, ai.canonical_name
    """

    # client_where appears 3× in the SQL — client_params must repeat.
    run_params = client_params * 3 if client_params else []

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(sql, run_params)
        rows = cur.fetchall()

    per_user: dict = {}
    for last_user, device_id, hostname, client_slug, client_name, canonical, kind in rows:
        entry = per_user.setdefault(
            last_user,
            {
                "last_user": last_user,
                "devices": {},
                "clients": set(),
                "item_count": 0,
                "item_keys": set(),
            },
        )
        item_key = (device_id, (canonical or "").lower(), kind)
        if item_key in entry["item_keys"]:
            continue
        entry["item_keys"].add(item_key)
        entry["item_count"] += 1
        entry["clients"].add(client_name)
        dev = entry["devices"].setdefault(
            device_id,
            {
                "device_id": device_id,
                "hostname": hostname,
                "client_slug": client_slug,
                "client_name": client_name,
                "items": [],
            },
        )
        dev["items"].append({"canonical_name": canonical or "", "kind": kind})

    users = []
    for entry in per_user.values():
        entry.pop("item_keys", None)
        entry["clients"] = sorted(entry["clients"])
        entry["device_list"] = sorted(
            entry["devices"].values(), key=lambda d: d["hostname"] or ""
        )
        entry.pop("devices", None)
        users.append(entry)
    users.sort(key=lambda u: (-u["item_count"], u["last_user"]))

    # Enrich items with category from SoftwareCatalog.
    all_ur_canonicals = {
        i["canonical_name"].lower()
        for u in users
        for d in u["device_list"]
        for i in d["items"]
        if i["canonical_name"]
    }
    ur_catalog_cats = {
        c.canonical_name.lower(): ", ".join(c.categories or [])
        for c in SoftwareCatalog.objects.filter(
            canonical_name__in=list(all_ur_canonicals)
        )
    } if all_ur_canonicals else {}
    for u in users:
        for d in u["device_list"]:
            for item in d["items"]:
                item["category"] = ur_catalog_cats.get(
                    (item["canonical_name"] or "").lower(), ""
                )

    # Apply user search and kind filter (post-fetch, small result set).
    if q_filter:
        users = [u for u in users if q_filter in (u["last_user"] or "").lower()]
    if kind_filter:
        for u in users:
            for d in u["device_list"]:
                d["items"] = [i for i in d["items"] if kind_filter in (i["kind"] or "").lower()]
            u["device_list"] = [d for d in u["device_list"] if d["items"]]
        users = [u for u in users if u["device_list"]]

    clients = Client.objects.filter(
        tenant_id=1, deleted_at__isnull=True
    ).order_by("display_name")

    if wants_csv(request):
        flat_rows: list[dict] = []
        for u in users:
            for d in u["device_list"]:
                for item in d["items"]:
                    flat_rows.append(
                        {
                            "user": u["last_user"],
                            "client": d["client_name"],
                            "hostname": d["hostname"],
                            "canonical_name": item["canonical_name"],
                            "kind": item["kind"],
                        }
                    )
        return csv_response(
            flat_rows,
            columns=[
                ("Last logged-in user", "user"),
                ("Client", "client"),
                ("Device", "hostname"),
                ("Title", "canonical_name"),
                ("Reason kind", "kind"),
            ],
            filename_stem="user_risk",
        )

    return render(
        request,
        "software_user_risk.html",
        {
            "users": users[:500],
            "user_count": len(users),
            "total_items": sum(u["item_count"] for u in users),
            "clients": clients,
            "active_clients": client_slugs,
            "active_q": q_filter,
            "active_kind": kind_filter,
            "software_tab": "user-risk",
        },
    )


# ─────────────────────────────────────────────────────────────────────
# Jobs — operator-facing catalog of every scheduled ingest / intel /
# evaluator / notifier job with last-run status and a "Run now" button
# that POSTs to the ingest container's /run/<slug> HTTP endpoint.
# ─────────────────────────────────────────────────────────────────────


_INGEST_BASE_URL = os.environ.get("INGEST_BASE_URL", "http://ingest:8090")

# Static catalog of jobs surfaced on /admin/jobs/. Each row maps to an
# existing /run/<slug> HTTP endpoint on the ingest container. Categories
# keep the UI groupable; last-run status is looked up per-category with
# a small helper query (intel jobs use intel_ingest_status; everything
# else uses run_log).
_JOB_CATALOG: list[dict] = [
    # Source ingest — Ninja patch cycle. status_key is a LIKE prefix
    # against run_log.kind so any per-instance source row surfaces.
    {"id": "patches",            "name": "Ninja source cycle",   "category": "source ingest", "endpoint": "run/patches",   "status_key": "source.Ninja",         "status_source": "run_log_like",  "description": "Full Ninja API pull: devices, activities, patches, custom fields, matviews."},
    {"id": "agent-observations", "name": "Agent observations",   "category": "source ingest", "endpoint": "run/agents",    "status_key": "source.",              "status_source": "run_log_like",  "description": "Fetch device inventory + agent presence from every source."},
    # Evaluators
    {"id": "software-classify",  "name": "Software classifier (+ auto-intel)", "category": "evaluators", "endpoint": "run/software-classify", "status_key": "software_classifier", "status_source": "run_log", "description": "Run intel matcher + catalog enrichers then the software finding classifier."},
    # Same underlying job as the entry above, minus the intel pre-steps, so it
    # writes the same run_log kind and is held out of "run all": firing both
    # would start two concurrent classifier passes over the same findings, and
    # nothing in ingest serializes them.
    {"id": "software-classify-only", "name": "Software classifier (no intel refresh)", "category": "evaluators", "endpoint": "run/software-classify-only", "status_key": "software_classifier", "status_source": "run_log", "run_all": False, "description": "Re-emit software findings from the intel already stored. The same path the scheduler runs; use it when the enriching job above would spend ~41 minutes on a matcher pass you do not need."},
    {"id": "patch-classify",     "name": "Patch classifier",     "category": "evaluators", "endpoint": "run/patch-classify",    "status_key": "patch_findings",   "status_source": "run_log", "description": "Emit patch findings from the current patch inventory."},
    {"id": "platform-evaluate",  "name": "Platform evaluator",   "category": "evaluators", "endpoint": "run/platform-evaluate", "status_key": "platform_evaluator", "status_source": "run_log", "description": "Refresh coverage, identity, and lifecycle findings."},
    {"id": "resolver",           "name": "Identity resolver",    "category": "evaluators", "endpoint": "run/resolver",          "status_key": "identity_resolver", "status_source": "run_log", "description": "Merge candidate resolver + layered-entity write path."},
    {"id": "parity-check",       "name": "Parity check",         "category": "evaluators", "endpoint": "run/parity-check",      "status_key": "parity_check",     "status_source": "run_log", "description": "Cross-check ingest state against derived operational reality."},
    # Intel connectors
    {"id": "intel-kev",          "name": "Intel: CISA KEV",           "category": "intel", "endpoint": "run/intel-kev",         "status_key": "cisa_kev",   "status_source": "intel", "description": "CISA Known Exploited Vulnerabilities feed (~1,200 CVEs)."},
    {"id": "intel-nvd",          "name": "Intel: NVD (CVE feed)",     "category": "intel", "endpoint": "run/intel-nvd",         "status_key": "nvd",        "status_source": "intel", "description": "NIST NVD v2 CVE delta pull."},
    {"id": "intel-cpe-dict",     "name": "Intel: CPE dictionary",     "category": "intel", "endpoint": "run/intel-cpe-dict",    "status_key": "cpe_dict",   "status_source": "intel", "description": "NIST CPE 2.3 vendor / product dictionary for CVE matching."},
    {"id": "intel-epss",         "name": "Intel: EPSS scores",        "category": "intel", "endpoint": "run/intel-epss",        "status_key": "epss",       "status_source": "intel", "description": "FIRST.org EPSS exploit-likelihood scores."},
    {"id": "intel-matcher",      "name": "Intel: title × CVE matcher","category": "intel", "endpoint": "run/intel-matcher",     "status_key": "matcher",    "status_source": "intel", "description": "Match installed products to CPE entries and populate cve_match."},
    {"id": "intel-winget",       "name": "Intel: Winget enrichment",  "category": "intel", "endpoint": "run/intel-winget",      "status_key": "winget",     "status_source": "intel", "description": "Per-product tags + publisher from Windows Package Manager."},
    {"id": "intel-chocolatey",   "name": "Intel: Chocolatey enrichment","category": "intel","endpoint": "run/intel-chocolatey", "status_key": "chocolatey", "status_source": "intel", "description": "Per-product tags from the Chocolatey community feed."},
    {"id": "intel-capability",   "name": "Intel: capability projection", "category": "intel", "endpoint": "run/intel-capability", "status_key": "capability_match", "status_source": "intel", "description": "Project vetted and candidate software capability evidence from catalog rules."},
    {"id": "intel-lolrmm",       "name": "Intel: LOLRMM corpus",       "category": "intel", "endpoint": "run/intel-lolrmm", "status_key": "lolrmm", "status_source": "intel", "description": "Refresh the LOLRMM corpus and exact one-to-one local product matches."},
    {"id": "intel-otx",          "name": "Intel: AlienVault OTX",     "category": "intel", "endpoint": "run/intel-otx",         "status_key": "otx",        "status_source": "intel", "description": "Community threat-intel pulses from OTX."},
    {"id": "intel-abusech",      "name": "Intel: abuse.ch",           "category": "intel", "endpoint": "run/intel-abusech",     "status_key": "abusech",    "status_source": "intel", "description": "MalwareBazaar + ThreatFox recent dump files."},
    # Notifications
    {"id": "notifications-dispatch", "name": "Notifications dispatch", "category": "notifications", "endpoint": "run/notifications/dispatch", "status_key": "notifications_dispatch", "status_source": "run_log", "description": "Deliver queued notifications."},
    {"id": "notifications-digest",   "name": "Notifications digest",   "category": "notifications", "endpoint": "run/notifications/digest",   "status_key": "notifications_digest",   "status_source": "run_log", "description": "Send scheduled digest routes."},
]

_JOB_INDEX = {j["id"]: j for j in _JOB_CATALOG}


@login_required
def admin_jobs(request: HttpRequest) -> HttpResponse:
    """List every schedulable job with last-run status and a run-now button."""
    category_filter = (request.GET.get("category") or "").strip().lower()
    status_filter = (request.GET.get("status") or "").strip().lower()

    intel_status: dict[str, dict] = {}
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        try:
            cur.execute(
                "SELECT connector, last_status, last_run_at, last_success_at,"
                " rows_touched, last_error FROM operations.intel_ingest_status"
            )
            for r in cur.fetchall():
                intel_status[r[0]] = {
                    "last_status": r[1] or "",
                    "last_run_at": r[2],
                    "last_success_at": r[3],
                    "rows_touched": r[4] or 0,
                    "last_error": (r[5] or "")[:200],
                }
        except Exception:
            intel_status = {}

    run_log_status: dict[str, dict] = {}
    recent_runs: list[dict] = []
    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                """
                SELECT DISTINCT ON (kind) kind, ok, started_at, ended_at, rows, error
                FROM operations.run_log
                ORDER BY kind, started_at DESC
                """
            )
            for r in cur.fetchall():
                run_log_status[r[0]] = {
                    "last_status": "ok" if r[1] else "failed",
                    "last_run_at": r[2],
                    "last_success_at": r[3] if r[1] else None,
                    "rows_touched": r[4] or 0,
                    "last_error": (r[5] or "")[:200],
                }
            # Aggregate recent activity for the panel at the bottom.
            cur.execute(
                """
                SELECT kind, ok, started_at, ended_at, rows, LEFT(COALESCE(error,''), 120)
                FROM operations.run_log
                ORDER BY started_at DESC
                LIMIT 25
                """
            )
            recent_runs = [
                {
                    "kind": r[0], "ok": r[1], "started_at": r[2],
                    "ended_at": r[3], "rows": r[4] or 0, "error": r[5],
                    "source": "run_log",
                }
                for r in cur.fetchall()
            ]
            # And the latest intel runs alongside.
            cur.execute(
                """
                SELECT connector, last_status, last_run_at, last_success_at,
                       rows_touched, LEFT(COALESCE(last_error,''), 120)
                FROM operations.intel_ingest_status
                ORDER BY last_run_at DESC NULLS LAST LIMIT 15
                """
            )
            for r in cur.fetchall():
                recent_runs.append({
                    "kind": r[0], "ok": r[1] == "ok",
                    "started_at": r[2], "ended_at": r[3],
                    "rows": r[4] or 0, "error": r[5],
                    "source": "intel",
                })
    except Exception:
        run_log_status = {}
        recent_runs = []
    recent_runs.sort(key=lambda r: r["started_at"] or now - timedelta(days=365), reverse=True)
    recent_runs = recent_runs[:25]

    def _lookup_run_log_like(prefix: str) -> dict:
        """Return the latest run_log entry whose kind starts with prefix."""
        best: dict = {}
        best_at = None
        for kind, data in run_log_status.items():
            if kind.startswith(prefix):
                at = data.get("last_run_at")
                if at and (best_at is None or at > best_at):
                    best = data
                    best_at = at
        return best

    # Dynamic per-source-instance rows — one entry per distinct
    # source.<Platform>[.<Instance>] kind we've ever seen. These aren't
    # in the static catalog because instance names come from data.
    dynamic_source_entries: list[dict] = []
    seen_source_kinds = [k for k in run_log_status.keys() if k.startswith("source.")]
    for kind in seen_source_kinds:
        instance = kind[len("source."):]
        dynamic_source_entries.append({
            "id": f"source-{instance.lower().replace('.', '-')}",
            "name": f"Source: {instance}",
            "category": "source ingest",
            "endpoint": "run/sources/enqueue",  # opens the ingest form
            "status_key": kind,
            "status_source": "run_log",
            "description": f"Ingest run history for {instance}.",
            "no_run_now": True,  # per-instance triggers go through the /run/sources/enqueue form
        })

    now = timezone.now()
    jobs = []
    categories = set()
    for entry in list(_JOB_CATALOG) + dynamic_source_entries:
        categories.add(entry["category"])
        source = entry["status_source"]
        if source == "intel":
            status = intel_status.get(entry["status_key"]) or {}
        elif source == "run_log_like":
            status = _lookup_run_log_like(entry["status_key"])
        else:
            status = run_log_status.get(entry["status_key"]) or {}
        last_run_at = status.get("last_run_at")
        last_success_at = status.get("last_success_at")
        state = "never_run"
        if status.get("last_status") == "ok":
            state = "ok"
        elif status.get("last_status"):
            state = status["last_status"]
        if last_run_at is not None:
            age = now - last_run_at
        else:
            age = None
        is_stale = last_success_at is None or (now - last_success_at) > timedelta(days=2)
        jobs.append({
            "id": entry["id"],
            "name": entry["name"],
            "category": entry["category"],
            "description": entry["description"],
            "state": state,
            "last_run_at": last_run_at,
            "last_success_at": last_success_at,
            "age": age,
            "rows_touched": status.get("rows_touched", 0),
            "last_error": status.get("last_error", ""),
            "is_stale": is_stale,
            "no_run_now": entry.get("no_run_now", False),
        })

    if category_filter:
        jobs = [j for j in jobs if j["category"] == category_filter]
    if status_filter == "never_run":
        jobs = [j for j in jobs if j["state"] == "never_run"]
    elif status_filter == "failed":
        jobs = [j for j in jobs if j["state"] not in ("ok", "never_run")]
    elif status_filter == "stale":
        jobs = [j for j in jobs if j["is_stale"] and j["state"] != "never_run"]
    elif status_filter == "ok":
        jobs = [j for j in jobs if j["state"] == "ok" and not j["is_stale"]]

    # Group by category so the template can render sections instead of
    # a flat list. Preserve catalog order within each group.
    jobs_by_category: dict[str, list[dict]] = {}
    for j in jobs:
        jobs_by_category.setdefault(j["category"], []).append(j)

    # Ingest exposes its on-demand org/device selector forms on
    # port 8090. Compute a browser-reachable URL for the operator by
    # rewriting the current host's port. Overridable via the
    # ``INGEST_PUBLIC_URL`` env var for setups where 8090 isn't the
    # public port (e.g. behind a reverse proxy).
    ingest_public_url = os.environ.get("INGEST_PUBLIC_URL", "").strip()
    if not ingest_public_url:
        host_no_port = request.get_host().split(":")[0]
        ingest_public_url = f"{request.scheme}://{host_no_port}:8090"

    return render(
        request,
        "admin_jobs.html",
        {
            "admin_group": "integrations",
            "admin_tab": "jobs",
            "jobs": jobs,
            "jobs_by_category": jobs_by_category,
            "categories": sorted(categories),
            "active_category": category_filter,
            "active_status": status_filter,
            "recent_runs": recent_runs,
            "ingest_public_url": ingest_public_url,
        },
    )


@login_required
@require_POST
def admin_jobs_run(request: HttpRequest, job_id: str) -> HttpResponse:
    entry = _JOB_INDEX.get(job_id)
    if not entry:
        messages.error(request, f"Unknown job '{job_id}'.")
        return redirect("admin_jobs")
    ok, note = _dispatch_job(entry)
    (messages.success if ok else messages.error)(request, f"{entry['name']} → {note}")
    return redirect(request.META.get("HTTP_REFERER") or reverse("admin_jobs"))


@login_required
@require_POST
def admin_jobs_run_all(request: HttpRequest) -> HttpResponse:
    """Fire every job in the catalog, or every job in a category if
    ``category`` is supplied on the POST body."""
    category = (request.POST.get("category") or "").strip().lower()
    targets = [
        j for j in _JOB_CATALOG
        if j.get("run_all", True) and (not category or j["category"] == category)
    ]
    if not targets:
        messages.warning(request, f"No jobs matched category '{category or 'all'}'.")
        return redirect(request.META.get("HTTP_REFERER") or reverse("admin_jobs"))
    fired = 0
    failed = 0
    for entry in targets:
        ok, _note = _dispatch_job(entry)
        if ok:
            fired += 1
        else:
            failed += 1
    scope = category or "all"
    if failed:
        messages.warning(
            request,
            f"Fired {fired} job(s) in '{scope}'; {failed} failed to dispatch — see the ingest log.",
        )
    else:
        messages.success(request, f"Fired {fired} job(s) in '{scope}'.")
    return redirect(request.META.get("HTTP_REFERER") or reverse("admin_jobs"))


def _dispatch_job(entry: dict) -> tuple[bool, str]:
    """POST to the ingest container's endpoint for a single job. Returns
    (ok, note) — note is a short summary for the toast / audit."""
    url = _INGEST_BASE_URL.rstrip("/") + "/" + entry["endpoint"]
    try:
        req = _urllib_request.Request(url, data=b"", method="POST")
        with _urllib_request.urlopen(req, timeout=10) as resp:
            body = resp.read(200).decode("utf-8", errors="replace").strip()
        return True, f"{resp.status} {body}"
    except HTTPError as exc:
        return False, f"HTTP {exc.code}: {exc.reason}"
    except URLError as exc:
        return False, f"network error: {exc.reason}"


# ─────────────────────────────────────────────────────────────────────
# On-demand external lookup — VirusTotal free-tier search per canonical
# title. Rate-limited to 10 lookups/hour/operator via title_intel_cache.
# Results cached for 48 h so re-clicks are free.
# ─────────────────────────────────────────────────────────────────────


_LOOKUP_SOURCES = ("virustotal",)  # metadefender / abusech require a hash we don't yet track
_LOOKUP_TTL = timedelta(hours=48)
_LOOKUP_PER_HOUR_CAP = 10


@login_required
@require_POST
def software_title_lookup(request: HttpRequest, name: str, source: str) -> HttpResponse:
    canonical_name = name.strip()
    if not canonical_name:
        return redirect("software_page")
    if source not in _LOOKUP_SOURCES:
        messages.error(request, f"Unknown lookup source '{source}'.")
        return redirect("software_detail", name=canonical_name)

    now = datetime.now(timezone.utc)
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """
            SELECT COUNT(*) FROM operations.title_intel_cache
             WHERE tenant_id = 1
               AND looked_up_by_id = %s
               AND looked_up_at > %s
            """,
            (request.user.id, now - timedelta(hours=1)),
        )
        (used,) = cur.fetchone()
        if used >= _LOOKUP_PER_HOUR_CAP:
            messages.error(
                request,
                f"Too many lookups this hour ({used}/{_LOOKUP_PER_HOUR_CAP}). "
                "Try again shortly — we cap this to protect the free-tier quota.",
            )
            return redirect("software_detail", name=canonical_name)

        # Cache hit inside TTL: reuse.
        cur.execute(
            """
            SELECT result_summary, looked_up_at
              FROM operations.title_intel_cache
             WHERE tenant_id = 1
               AND source = %s
               AND LOWER(canonical_name) = LOWER(%s)
               AND looked_up_at > %s
             ORDER BY looked_up_at DESC LIMIT 1
            """,
            (source, canonical_name, now - _LOOKUP_TTL),
        )
        cached = cur.fetchone()
        if cached:
            messages.info(
                request,
                f"Reusing cached {source} result from {cached[1]:%Y-%m-%d %H:%M}."
                f" Summary: {cached[0]}",
            )
            return redirect("software_detail", name=canonical_name)

    # Do the actual external call.
    try:
        result, summary = _do_lookup(source, canonical_name)
    except Exception as exc:
        messages.error(request, f"Lookup failed: {exc}")
        return redirect("software_detail", name=canonical_name)

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """
            INSERT INTO operations.title_intel_cache (
                tenant_id, canonical_name, source,
                looked_up_at, looked_up_by_id,
                result, result_summary
            ) VALUES (1, %s, %s, %s, %s, %s::jsonb, %s)
            """,
            (canonical_name, source, now, request.user.id,
             json.dumps(result), summary[:1000]),
        )
    _audit(request, "software.lookup", uuid.uuid4(), {}, {
        "canonical_name": canonical_name,
        "source": source,
        "summary": summary[:400],
    })
    messages.success(request, f"{source.title()} lookup complete: {summary}")
    return redirect("software_detail", name=canonical_name)


def _do_lookup(source: str, canonical_name: str) -> tuple[dict, str]:
    if source == "virustotal":
        return _lookup_virustotal(canonical_name)
    raise ValueError(source)


def _lookup_virustotal(canonical_name: str) -> tuple[dict, str]:
    api_key = os.environ.get("VT_API_KEY", "").strip()
    if not api_key:
        return {"error": "VT_API_KEY not configured"}, "no API key configured on server"
    qs = urlencode({"query": canonical_name[:120], "limit": 10})
    req = _urllib_request.Request(
        f"https://www.virustotal.com/api/v3/search?{qs}",
        headers={"x-apikey": api_key, "Accept": "application/json"},
    )
    try:
        with _urllib_request.urlopen(req, timeout=15) as resp:
            body = resp.read()
    except HTTPError as exc:
        if exc.code == 429:
            return {"error": "rate_limited"}, "VirusTotal rate-limited (free-tier daily cap)"
        if exc.code == 401:
            return {"error": "unauthorized"}, "VirusTotal rejected our key"
        return {"error": f"http_{exc.code}"}, f"VirusTotal returned HTTP {exc.code}"
    except URLError as exc:
        return {"error": "network"}, f"Network error contacting VirusTotal: {exc.reason}"
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except ValueError:
        return {"error": "bad_json"}, "VirusTotal returned unparseable JSON"
    data = payload.get("data") or []
    if not data:
        return payload, "no matching files or domains found"
    first = data[0]
    attrs = first.get("attributes") or {}
    stats = attrs.get("last_analysis_stats") or {}
    malicious = stats.get("malicious") or 0
    suspicious = stats.get("suspicious") or 0
    summary = (
        f"{len(data)} match(es); top hit "
        f"{first.get('id','?')[:40]} — {malicious} engines flagged as malicious, "
        f"{suspicious} suspicious"
    )
    return payload, summary


# ─────────────────────────────────────────────────────────────────────
# Tech Checklist — per-device curated cleanup list combining active
# software findings and reject/investigate decisions (title- or publisher-
# scope). Answers "what should the tech clean up on this device?"
# Optional ?client=<slug> filter for a per-client view.
# ─────────────────────────────────────────────────────────────────────


@login_required
def software_tech_checklist(request: HttpRequest) -> HttpResponse:
    client_slugs = [s for s in request.GET.getlist("client") if s]
    q_filter = (request.GET.get("q") or "").strip()
    role_filter = (request.GET.get("role") or "").strip().lower()
    os_filter = (request.GET.get("os") or "").strip()
    kind_filter = (request.GET.get("kind") or "").strip()
    filtered_client_ids: list[str] = []
    if client_slugs:
        filtered_client_ids = [
            str(cid)
            for cid in Client.objects.filter(
                tenant_id=1, slug__in=client_slugs, deleted_at__isnull=True
            ).values_list("id", flat=True)
        ]

    client_where = ""
    client_params: list = []
    if filtered_client_ids:
        client_where = "AND d.client_id = ANY(%s::uuid[])"
        client_params.append(filtered_client_ids)
    elif client_slugs:
        client_where = "AND FALSE"
    if role_filter in ("server", "workstation", "unknown"):
        client_where += " AND d.device_role = %s"
        client_params.append(role_filter)
    if os_filter:
        client_where += " AND d.os_group = %s"
        client_params.append(os_filter)

    findings_sql = f"""
        SELECT d.client_id, c.slug, c.display_name,
               d.id AS device_id, d.canonical_hostname,
               d.device_role, d.os_group,
               e.canonical_name,
               e.publisher,
               e.finding_details->>'reason'         AS reason,
               e.finding_type,
               e.severity
        FROM operations.v_device_software_exposure e
        JOIN operations.devices d ON d.id = e.device_id AND d.deleted_at IS NULL
        JOIN operations.clients c ON c.id = d.client_id AND c.deleted_at IS NULL
        WHERE e.tenant_id = 1
          AND e.status IN ('open', 'acknowledged')
          AND e.finding_type <> 'whitelist_suggestion'
          {client_where}
    """

    # Reject / investigate decisions that hit an active install on the
    # device (title-scope or publisher-scope). These may not have a
    # classifier finding (e.g. reject-only) but still belong on the
    # cleanup list.
    decisions_sql = f"""
        SELECT d.client_id, c.slug, c.display_name,
               d.id AS device_id, d.canonical_hostname,
               d.device_role, d.os_group,
               sic.canonical_name,
               sic.publisher,
               CASE sd.decision
                   WHEN 'reject' THEN 'operator rejected'
                   WHEN 'investigate' THEN 'operator flagged for investigation'
                   ELSE 'operator decision'
               END AS reason,
               ('decision_' || sd.decision) AS finding_type,
               'medium' AS severity
        FROM operations.software_installations_current sic
        JOIN operations.devices d ON d.id = sic.device_id AND d.deleted_at IS NULL
        JOIN operations.clients c ON c.id = d.client_id AND c.deleted_at IS NULL
        JOIN operations.software_decisions sd
          ON sd.tenant_id = sic.tenant_id
         AND sd.decision IN ('reject', 'investigate')
         AND (
              (sd.canonical_name <> '' AND sd.canonical_name = sic.canonical_name)
           OR (sd.publisher <> ''
               AND LOWER(sd.publisher) = LOWER(COALESCE(sic.publisher, '')))
         )
         AND (sd.device_id IS NULL OR sd.device_id = sic.device_id)
         AND (sd.client_id IS NULL OR sd.client_id = sic.client_id)
        WHERE sic.tenant_id = 1
          AND sic.deleted_at IS NULL
          AND sic.stale_since IS NULL
          {client_where}
    """

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(findings_sql, client_params)
        finding_rows = cur.fetchall()
        cur.execute(decisions_sql, client_params)
        decision_rows = cur.fetchall()

    per_device: dict = {}
    for row in list(finding_rows) + list(decision_rows):
        (
            client_id, slug, client_name, device_id, hostname,
            device_role, os_group, canonical, publisher, reason,
            finding_type, severity,
        ) = row
        entry = per_device.setdefault(
            device_id,
            {
                "device_id": device_id,
                "client_slug": slug,
                "client_name": client_name,
                "hostname": hostname,
                "device_role": device_role,
                "os_group": os_group,
                "items": [],
                "item_keys": set(),
            },
        )
        item_key = (finding_type, (canonical or "").lower())
        if item_key in entry["item_keys"]:
            continue
        entry["item_keys"].add(item_key)
        entry["items"].append(
            {
                "canonical_name": canonical or "",
                "publisher": publisher or "",
                "reason": reason or "",
                "finding_type": finding_type,
                "severity": severity,
            }
        )

    devices = []
    for entry in per_device.values():
        entry.pop("item_keys", None)
        entry["item_count"] = len(entry["items"])
        entry["items"].sort(key=lambda i: (i["finding_type"], i["canonical_name"]))
        devices.append(entry)
    devices.sort(
        key=lambda e: (-e["item_count"], e["client_name"], e["hostname"] or "")
    )

    # Enrich items with category from SoftwareCatalog (canonical lookup).
    all_canonicals = {
        i["canonical_name"].lower()
        for e in devices
        for i in e["items"]
        if i["canonical_name"]
    }
    catalog_cats = {
        c.canonical_name.lower(): ", ".join(c.categories or [])
        for c in SoftwareCatalog.objects.filter(
            canonical_name__in=list(all_canonicals)
        )
    } if all_canonicals else {}
    for entry in devices:
        for item in entry["items"]:
            item["category"] = catalog_cats.get((item["canonical_name"] or "").lower(), "")

    clients = Client.objects.filter(
        tenant_id=1, deleted_at__isnull=True
    ).order_by("display_name")

    if wants_csv(request):
        flat_rows: list[dict] = []
        for entry in devices:
            for item in entry["items"]:
                flat_rows.append(
                    {
                        "client": entry["client_name"],
                        "hostname": entry["hostname"],
                        "canonical_name": item["canonical_name"],
                        "publisher": item["publisher"],
                        "finding_type": item["finding_type"],
                        "reason": item["reason"],
                        "severity": item["severity"],
                    }
                )
        return csv_response(
            flat_rows,
            columns=[
                ("Client", "client"),
                ("Device", "hostname"),
                ("Title", "canonical_name"),
                ("Publisher", "publisher"),
                ("Reason kind", "finding_type"),
                ("Reason", "reason"),
                ("Severity", "severity"),
            ],
            filename_stem="tech_checklist",
        )

    # Post-fetch filtering for q + kind — filters that don't map
    # cleanly to the SQL join. Small candidate set → done in Python.
    def _match_row(entry: dict) -> bool:
        if q_filter:
            needle = q_filter.lower()
            if needle not in (entry["hostname"] or "").lower() and needle not in (entry["client_name"] or "").lower():
                if not any(
                    needle in (i.get("canonical_name") or "").lower()
                    or needle in (i.get("publisher") or "").lower()
                    for i in entry["items"]
                ):
                    return False
        if kind_filter:
            if not any(kind_filter in (i.get("finding_type") or "") for i in entry["items"]):
                return False
        return True
    if q_filter or kind_filter:
        devices = [d for d in devices if _match_row(d)]

    return render(
        request,
        "software_tech_checklist.html",
        {
            "devices": devices[:500],
            "device_count": len(devices),
            "total_items": sum(e["item_count"] for e in devices),
            "clients": clients,
            "active_clients": client_slugs,
            "active_q": q_filter,
            "active_role": role_filter,
            "active_os": os_filter,
            "active_kind": kind_filter,
            "software_tab": "checklist",
        },
    )


# ─────────────────────────────────────────────────────────────────────
# Devices fleet page — entity-first browse across every client.
# Parallels /software/ and /patching/ — overview cards + filter chips
# + main table. Per-client /orgs/<slug>/devices/ stays as-is for the
# scoped view.
# ─────────────────────────────────────────────────────────────────────


@login_required
def devices_page(request: HttpRequest) -> HttpResponse:
    device_policy = get_device_status_policy()
    active_device_days = device_policy["active_device_days"]
    source_delay_hours = device_policy["source_delay_hours"]
    q_filter = (request.GET.get("q") or "").strip()
    os_filter = request.GET.get("os", "")  # Windows | macOS | Linux | Other
    role_filter = request.GET.get("role", "")  # server | workstation | unknown
    online_filter = request.GET.get("online", "")  # online | offline
    state_filter = request.GET.get("state", "")  # active | not-reporting
    client_filter = request.GET.get("client", "")  # slug

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")

        # Overview — reads v_device to get session state + scope in one query
        cur.execute(
            f"""
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE is_online_any) AS online,
                   COUNT(*) FILTER (WHERE NOT is_online_any) AS offline,
                   COUNT(*) FILTER (WHERE device_role = 'server') AS servers,
                   COUNT(*) FILTER (WHERE device_role = 'workstation') AS workstations,
                   COUNT(*) FILTER (WHERE effective_patching_scope = 'Included') AS in_patch_scope,
                   COUNT(*) FILTER (WHERE lifecycle_status <> 'retired'
                                     AND last_contact_at >= NOW() - INTERVAL '{active_device_days} days') AS active,
                   COUNT(*) FILTER (WHERE last_contact_at IS NULL
                                    OR last_contact_at < NOW() - INTERVAL '{active_device_days} days') AS stale
            FROM operations.v_device
            WHERE tenant_id = 1
            """
        )
        row = cur.fetchone()
        overview = {
            "total": row[0],
            "online": row[1],
            "offline": row[2],
            "servers": row[3],
            "workstations": row[4],
            "in_patch_scope": row[5],
            "active": row[6],
            "stale": row[7],
        }

        cur.execute(
            """
            SELECT
              COUNT(DISTINCT f.subject_id) FILTER (WHERE fc.name = 'coverage')::int,
              COUNT(DISTINCT f.subject_id) FILTER (WHERE fc.name = 'identity')::int
            FROM operations.findings f
            JOIN operations.finding_types ft ON ft.id = f.finding_type_id
            JOIN operations.finding_categories fc ON fc.id = ft.category_id
            WHERE f.tenant_id = 1
              AND f.status IN ('open', 'acknowledged', 'investigating')
              AND f.subject_type = 'device'
            """
        )
        coverage_issues, identity_issues = cur.fetchone()
        cur.execute(
            f"""
            SELECT COUNT(*)::int
            FROM operations.source_health_current
            WHERE tenant_id = 1
              AND (last_run_ok = FALSE OR last_observed_at IS NULL
                   OR last_observed_at < NOW() - INTERVAL '{source_delay_hours} hours')
            """
        )
        delayed_sources = cur.fetchone()[0]

        # OS group breakdown for chip strip
        cur.execute(
            """
            SELECT os_group, COUNT(*) FROM operations.v_device
            WHERE tenant_id = 1 GROUP BY os_group ORDER BY COUNT(*) DESC
            """
        )
        os_rows = cur.fetchall()

        # Device table — v_device + client name. Apply filters.
        where = ["v.tenant_id = 1"]
        params: list = []
        if q_filter:
            where.append("(v.canonical_hostname ILIKE %s OR v.canonical_serial ILIKE %s)")
            params.extend([f"%{q_filter}%", f"%{q_filter}%"])
        if os_filter:
            where.append("v.os_group = %s")
            params.append(os_filter)
        if role_filter:
            where.append("v.device_role = %s")
            params.append(role_filter)
        if online_filter == "online":
            where.append("v.is_online_any")
        elif online_filter == "offline":
            where.append("NOT v.is_online_any")
        if state_filter == "active":
            where.append(
                f"v.lifecycle_status <> 'retired' AND v.last_contact_at >= NOW() - INTERVAL '{active_device_days} days'"
            )
        elif state_filter == "not-reporting":
            where.append(
                f"(v.last_contact_at IS NULL OR v.last_contact_at < NOW() - INTERVAL '{active_device_days} days')"
            )
        if client_filter:
            where.append(
                "v.client_id = (SELECT id FROM operations.clients WHERE slug = %s AND tenant_id = 1)"
            )
            params.append(client_filter)

        where_sql = " AND ".join(where)
        cur.execute(
            f"""
            SELECT v.device_id, v.canonical_hostname, v.canonical_serial,
                   v.device_role, v.os_group, v.os_name,
                   v.is_online_any, v.online_sources, v.last_contact_at,
                   v.effective_patching_scope,
                   c.display_name AS client_name, c.slug AS client_slug,
                   (SELECT COUNT(*) FROM operations.findings f
                    WHERE f.tenant_id = 1
                      AND f.subject_type = 'device'
                      AND f.subject_id = v.device_id
                      AND f.status IN ('open','acknowledged','investigating')
                      AND f.severity IN ('critical','high')
                   )
                   + (SELECT COUNT(DISTINCT e.finding_id)
                      FROM operations.v_device_software_exposure e
                      WHERE e.tenant_id = 1
                        AND e.device_id = v.device_id
                        AND e.status IN ('open','acknowledged','investigating')
                        AND e.severity IN ('critical','high')
                   ) AS severe_issues
            FROM operations.v_device v
            LEFT JOIN operations.clients c ON c.id = v.client_id
            WHERE {where_sql}
            ORDER BY v.canonical_hostname
            LIMIT 500
            """,
            params,
        )
        device_rows = cur.fetchall()

    devices = []
    for row in device_rows:
        (
            did,
            hostname,
            serial,
            role,
            os_group,
            os_name,
            is_online,
            online_sources,
            last_contact,
            scope,
            client_name,
            client_slug,
            severe,
        ) = row
        # Traffic-light health per row
        if severe and severe > 0:
            health = "red"
        elif not is_online:
            health = "amber"
        else:
            health = "green"
        if last_contact is None or last_contact < timezone.now() - timedelta(
            days=active_device_days
        ):
            state_label = "Not reporting"
        elif is_online:
            state_label = "Online"
        else:
            state_label = "Offline"
        devices.append(
            {
                "id": did,
                "hostname": hostname,
                "serial": serial or "",
                "role": role,
                "os_group": os_group,
                "os_name": os_name,
                "is_online": is_online,
                "online_sources": online_sources or [],
                "last_contact": last_contact,
                "scope": scope,
                "client_name": client_name,
                "client_slug": client_slug,
                "severe": severe or 0,
                "health": health,
                "state_label": state_label,
            }
        )

    clients = Client.objects.filter(
        tenant_id=1,
        deleted_at__isnull=True,
    ).order_by("display_name")

    if wants_csv(request):
        return csv_response(
            devices,
            columns=[
                ("Hostname", "hostname"),
                ("Client", "client_name"),
                ("Serial", "serial"),
                ("Role", "role"),
                ("OS group", "os_group"),
                ("OS name", "os_name"),
                ("Online", lambda r: "yes" if r["is_online"] else "no"),
                ("Online sources", "online_sources"),
                ("Last contact", "last_contact"),
                ("Patch scope", "scope"),
                ("Severe issues", "severe"),
                ("Device ID", lambda r: str(r["id"])),
            ],
            filename_stem="devices",
        )

    return render(
        request,
        "devices_page.html",
        {
            "overview": overview,
            "active_device_days": active_device_days,
            "os_rows": os_rows,
            "devices": devices,
            "clients": clients,
            "active_q": q_filter,
            "active_os": os_filter,
            "active_role": role_filter,
            "active_online": online_filter,
            "active_state": state_filter,
            "active_client": client_filter,
            "coverage_issues": coverage_issues,
            "identity_issues": identity_issues,
            "delayed_sources": delayed_sources,
        },
    )


# ─────────────────────────────────────────────────────────────────────
# Patching queue — dedicated surface for the 5 patching finding types
# emitted by ingest/patch_findings.py. Complements the general findings
# queue with per-type tiles + scope filter (only in-scope devices fire
# these findings, per Track O batch O5).
# ─────────────────────────────────────────────────────────────────────

_PATCHING_TYPES = (
    "device_never_patched",
    "patching_stalled",
    "reboot_pending",
    "patch_failing_repeatedly",
    "patch_approval_backlog",
)


@login_required
def patching_queue(request: HttpRequest) -> HttpResponse:
    """Patching triage queue — filter bar, device-population summary,
    5 finding-type tiles reflecting the current filter, filterable
    table.
    """

    device_policy = get_device_status_policy()
    active_device_days = device_policy["active_device_days"]
    patch_activity_days = device_policy["patch_activity_days"]

    # Multi-value filters accept BOTH native repeated params
    # (`?type=X&type=Y` — how HTML multi-select submits) AND
    # comma-separated values (`?type=X,Y` — convenient for
    # bookmarks). Empty segments dropped so `?type=` is unset.
    def _multi(key: str) -> list[str]:
        result: list[str] = []
        for raw in request.GET.getlist(key):
            for v in raw.split(","):
                if v:
                    result.append(v)
        return result

    type_filter = _multi("type")
    status_filter = request.GET.get("status", "active")
    client_filter = _multi("client")
    role_filter = request.GET.get("role", "")
    _ROLE_CHOICES = ("server", "workstation", "unknown")
    if role_filter and role_filter not in _ROLE_CHOICES:
        role_filter = ""

    # Resolve client slugs → ids for downstream population + drilldown
    # SQL. Multi-select supported (comma-separated).
    filtered_client_ids: list[str] = []
    if client_filter:
        filtered_client_ids = [
            str(cid)
            for cid in Client.objects.filter(
                tenant_id=1,
                slug__in=client_filter,
                deleted_at__isnull=True,
            ).values_list("id", flat=True)
        ]

    # Base Finding queryset for tiles and main table — everything
    # inherits status + client filters. Type filter applied only to
    # the main table (tiles remain per-type navigators).
    base_qs = Finding.objects.filter(
        tenant_id=1,
        finding_type__category__name="patching",
    )
    if status_filter == "active":
        base_qs = base_qs.filter(status__in=_FINDING_ACTIVE_STATUSES)
    elif status_filter and status_filter != "all":
        base_qs = base_qs.filter(status=status_filter)
    if filtered_client_ids:
        base_qs = base_qs.filter(client_id__in=filtered_client_ids)
    elif client_filter:
        # Client slug given but no match — return no rows to avoid
        # showing global counts under a mistyped slug.
        base_qs = base_qs.none()

    # Role filter: constrains device-subject findings to devices with
    # the chosen device_role. Client-subject findings (e.g.
    # patch_approval_backlog) are hidden when a role filter is set
    # since they aggregate across the client's whole fleet — mixing
    # them into a role view is misleading.
    if role_filter:
        role_device_ids = Device.objects.filter(
            tenant_id=1,
            device_role=role_filter,
            deleted_at__isnull=True,
        ).values("id")
        base_qs = base_qs.filter(
            subject_type=Finding.SubjectType.DEVICE,
            subject_id__in=role_device_ids,
        )

    # Per-type tile counts (respects status + client filters).
    tile_counts = {
        row["finding_type__name"]: row["cnt"]
        for row in (base_qs.values("finding_type__name").annotate(cnt=Count("id")))
    }

    def _type_tile_href(ftname: str) -> str:
        parts = [f"type={ftname}"]
        if client_filter:
            parts.append(f"client={','.join(client_filter)}")
        if status_filter != "active":
            parts.append(f"status={status_filter}")
        if role_filter:
            parts.append(f"role={role_filter}")
        return "?" + "&".join(parts)

    tiles = [
        {
            "label": ftname.replace("_", " "),
            "value": tile_counts.get(ftname, 0),
            "href": _type_tile_href(ftname),
        }
        for ftname in _PATCHING_TYPES
    ]

    # Device-population summary — how many devices exist in the
    # filtered slice, how many are in scope (Included). Reads
    # v_device (Track O). Scoped to client + role if filtered.
    pop_where = ["tenant_id = %s"]
    pop_params: list = [1]
    if filtered_client_ids:
        pop_where.append("client_id = ANY(%s::uuid[])")
        pop_params.append(filtered_client_ids)
    elif client_filter:
        # slug given but zero matches → force empty result
        pop_where.append("FALSE")
    if role_filter:
        pop_where.append("device_role = %s")
        pop_params.append(role_filter)
    pop_sql = (
        "SELECT COUNT(*) AS total,\n"
        "       COUNT(*) FILTER (WHERE effective_patching_scope = 'Included') AS in_scope,\n"
        "       COUNT(*) FILTER (WHERE effective_patching_scope = 'Excluded') AS excluded,\n"
        "       COUNT(*) FILTER (WHERE effective_patching_scope = 'Unmanaged') AS unmanaged\n"
        f"FROM operations.v_device WHERE {' AND '.join(pop_where)}"
    )
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(pop_sql, pop_params)
        pop_row = cur.fetchone() or (0, 0, 0, 0)
    population = {
        "total": pop_row[0],
        "in_scope": pop_row[1],
        "excluded": pop_row[2],
        "unmanaged": pop_row[3],
        "in_scope_pct": (round(100.0 * pop_row[1] / pop_row[0], 1) if pop_row[0] else 0.0),
    }

    # Status overview.  Keep the three ideas deliberately separate:
    # device freshness (active), patching policy (Included), and evidence of
    # patch work (a recent Ninja state observation or install outcome).
    posture_where = ["v.tenant_id = %s", "v.lifecycle_status <> 'retired'"]
    posture_params: list = [1]
    if filtered_client_ids:
        posture_where.append("v.client_id = ANY(%s::uuid[])")
        posture_params.append(filtered_client_ids)
    elif client_filter:
        posture_where.append("FALSE")
    if role_filter:
        posture_where.append("v.device_role = %s")
        posture_params.append(role_filter)
    posture_where_sql = " AND ".join(posture_where)

    posture_cte = f"""
        WITH scoped_devices AS (
            SELECT v.device_id, v.client_id, v.canonical_hostname,
                   v.device_role, v.os_group, v.last_contact_at,
                   v.needs_reboot, v.effective_patching_scope
            FROM operations.v_device v
            WHERE {posture_where_sql}
        ), ninja_links AS (
            SELECT DISTINCT dl.device_id, dl.external_id::integer AS ninja_device_id
            FROM operations.v_device_source_link dl
            JOIN operations.sources s ON s.id = dl.source_id
            WHERE dl.tenant_id = 1 AND LOWER(s.name) = 'ninja'
              AND dl.external_id ~ '^\\d+$'
        ), patch_signal AS (
            SELECT nl.device_id,
                   BOOL_OR(COALESCE(dps.ever_installed, FALSE)) AS ever_installed
            FROM ninja_links nl
            JOIN ninja_patches.device_patch_signal dps
              ON dps.device_id = nl.ninja_device_id
            GROUP BY nl.device_id
        ), patch_activity AS (
            -- Reads the device_patch_activity matview (sql migration 070)
            -- rather than re-aggregating ninja_patches.patch_facts at request
            -- time. A canonical device can be linked to multiple Ninja device
            -- ids, so take MAX across links.
            SELECT nl.device_id,
                   MAX(dpa.last_patch_activity_at) AS last_patch_activity_at
            FROM ninja_links nl
            JOIN ninja_patches.device_patch_activity dpa
              ON dpa.device_id = nl.ninja_device_id
            GROUP BY nl.device_id
        ), device_posture AS (
            SELECT sd.*, pa.last_patch_activity_at,
                   COALESCE(ps.ever_installed, FALSE) AS ever_installed,
                   sd.last_contact_at >= NOW() - INTERVAL '{active_device_days} days' AS is_active,
                   pa.last_patch_activity_at >= NOW() - INTERVAL '{patch_activity_days} days'
                       AS has_recent_patch_activity
            FROM scoped_devices sd
            LEFT JOIN patch_signal ps ON ps.device_id = sd.device_id
            LEFT JOIN patch_activity pa ON pa.device_id = sd.device_id
        )
    """
    # Single query returning the fleet totals row (GROUPING sentinel = 1) and
    # one row per client (sentinel = 0). Halves the CTE work vs. running the
    # rollup twice.
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            posture_cte
            + """
            SELECT dp.client_id, c.slug, c.display_name,
                   COUNT(*)::int AS total,
                   COUNT(*) FILTER (WHERE dp.is_active)::int AS active,
                   COUNT(*) FILTER (WHERE dp.is_active
                                     AND dp.effective_patching_scope = 'Included')::int AS active_in_scope,
                   COUNT(*) FILTER (WHERE dp.is_active
                                     AND dp.effective_patching_scope = 'Included'
                                     AND dp.has_recent_patch_activity)::int AS recent_activity,
                   COUNT(*) FILTER (WHERE dp.is_active
                                     AND dp.effective_patching_scope = 'Included'
                                     AND NOT dp.has_recent_patch_activity)::int AS quiet,
                   COUNT(*) FILTER (WHERE dp.is_active
                                     AND dp.effective_patching_scope = 'Included'
                                     AND NOT dp.ever_installed)::int AS never_patched,
                   COUNT(*) FILTER (WHERE dp.is_active
                                     AND dp.effective_patching_scope = 'Included'
                                     AND dp.needs_reboot)::int AS reboot_pending,
                   GROUPING(dp.client_id) AS is_total
            FROM device_posture dp
            LEFT JOIN operations.clients c
              ON c.id = dp.client_id AND c.deleted_at IS NULL
            GROUP BY GROUPING SETS ((), (dp.client_id, c.slug, c.display_name))
            ORDER BY is_total DESC,
                     quiet DESC, never_patched DESC, reboot_pending DESC,
                     c.display_name
            """,
            posture_params,
        )
        rollup_rows = cur.fetchall()

    patch_status = {
        "total": 0,
        "active": 0,
        "active_in_scope": 0,
        "recent_patch_activity": 0,
        "quiet_patch_data": 0,
        "never_patched": 0,
        "reboot_pending": 0,
    }
    client_posture: list[dict] = []
    for row in rollup_rows:
        (
            client_id,
            slug,
            name,
            total,
            active,
            active_in_scope,
            recent_activity,
            quiet,
            never_patched,
            reboot_pending,
            is_total,
        ) = row
        if is_total == 1:
            patch_status = {
                "total": total,
                "active": active,
                "active_in_scope": active_in_scope,
                "recent_patch_activity": recent_activity,
                "quiet_patch_data": quiet,
                "never_patched": never_patched,
                "reboot_pending": reboot_pending,
            }
        elif slug is not None:
            client_posture.append(
                {
                    "client_id": client_id,
                    "slug": slug,
                    "name": name,
                    "active": active,
                    "in_scope": active_in_scope,
                    "recent_activity": recent_activity,
                    "quiet": quiet,
                    "never_patched": never_patched,
                    "reboot_pending": reboot_pending,
                }
            )
    # Device population by scope (drilldown from the summary tiles).
    # Optional "scope" query param drills into a specific bucket.
    scope_filter = request.GET.get("scope", "")
    posture_filter = request.GET.get("posture", "")
    device_rows: list = []
    if scope_filter in ("Included", "Excluded", "Unmanaged", "Unknown") or posture_filter in (
        "active",
        "active-in-scope",
        "recent-activity",
        "quiet",
        "never-patched",
        "reboot-pending",
    ):
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            base_where = ["1=1"]
            if scope_filter:
                base_where.append("effective_patching_scope = %s")
            if posture_filter == "active":
                base_where.append("is_active")
            elif posture_filter == "active-in-scope":
                base_where.extend(("is_active", "effective_patching_scope = 'Included'"))
            elif posture_filter == "recent-activity":
                base_where.extend(
                    (
                        "is_active",
                        "effective_patching_scope = 'Included'",
                        "has_recent_patch_activity",
                    )
                )
            elif posture_filter == "quiet":
                base_where.extend(
                    (
                        "is_active",
                        "effective_patching_scope = 'Included'",
                        "NOT has_recent_patch_activity",
                    )
                )
            elif posture_filter == "never-patched":
                base_where.extend(
                    ("is_active", "effective_patching_scope = 'Included'", "NOT ever_installed")
                )
            elif posture_filter == "reboot-pending":
                base_where.extend(
                    ("is_active", "effective_patching_scope = 'Included'", "needs_reboot")
                )
            cur.execute(
                posture_cte
                + f"""
                SELECT device_id, canonical_hostname, client_id,
                       device_role, os_group,
                       NULL::text AS patching_scope_reason,
                       NULL::text AS patching_scope_override,
                       last_contact_at, last_patch_activity_at
                FROM device_posture
                WHERE {' AND '.join(base_where)}
                ORDER BY canonical_hostname
                LIMIT 500
                """,
                posture_params + ([scope_filter] if scope_filter else []),
            )
            device_rows = cur.fetchall()

    # Client-id → slug lookup, pre-compute clickthrough URL per device
    # row (template-side lookup would iterate all clients per row —
    # bad).
    if device_rows:
        client_slug_by_id = dict(Client.objects.filter(tenant_id=1).values_list("id", "slug"))
        from django.urls import reverse

        device_rows = [
            {
                "device_id": did,
                "hostname": hostname,
                "role": role,
                "os_group": os_group,
                "reason": reason,
                "override": override,
                "last_contact": last_contact,
                "last_patch_activity": last_patch_activity,
                "url": (
                    reverse(
                        "device_detail",
                        kwargs={
                            "org_slug": client_slug_by_id[cid],
                            "device_id": did,
                        },
                    )
                    if cid in client_slug_by_id
                    else None
                ),
                "activity_url": (
                    reverse(
                        "device_detail",
                        kwargs={
                            "org_slug": client_slug_by_id[cid],
                            "device_id": did,
                        },
                    )
                    + "?tab=activity"
                    if cid in client_slug_by_id
                    else None
                ),
            }
            for (
                did,
                hostname,
                cid,
                role,
                os_group,
                reason,
                override,
                last_contact,
                last_patch_activity,
            ) in device_rows
        ]

    # Main table query = base_qs + type filter
    qs = base_qs.select_related("finding_type", "client")
    if type_filter:
        qs = qs.filter(finding_type__name__in=type_filter)

    _SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    findings = sorted(
        qs[:500],
        key=lambda f: (
            _SEV_ORDER.get(f.severity, 9),
            -(f.last_detected_at or f.last_seen_at).timestamp(),
        ),
    )

    def _detail(finding: Finding) -> str:
        d = finding.finding_details or {}
        name = finding.finding_type.name
        if name == "device_never_patched":
            return "no INSTALLED patches on record"
        if name == "patching_stalled":
            ls = d.get("last_patch_seen_at")
            return f"last install {ls[:10]}" if ls else "no fresh scan (>35d)"
        if name == "reboot_pending":
            lb = d.get("last_boot_at")
            return f"last boot {lb[:10]}" if lb else "no boot recorded"
        if name == "patch_failing_repeatedly":
            kbs = d.get("failing_patches") or []
            return f"{len(kbs)} KB(s) failing"
        if name == "patch_approval_backlog":
            return f"{d.get('backlog_count', '?')} APPROVED uninstalled"
        return ""

    rows = [
        {
            "f": f,
            "detail": _detail(f),
            "subject_label": (
                (f.finding_details or {}).get("hostname")
                or (f.finding_details or {}).get("client_name")
                or str(f.subject_id)
            ),
        }
        for f in findings
    ]

    if wants_csv(request):
        return csv_response(
            rows,
            columns=[
                ("Severity", lambda r: r["f"].severity),
                ("Type", lambda r: r["f"].finding_type.name),
                ("Client", lambda r: (r["f"].client.display_name if r["f"].client else "")),
                ("Subject", "subject_label"),
                ("Detail", "detail"),
                ("Status", lambda r: r["f"].status),
                ("Confidence", lambda r: r["f"].confidence),
                ("First seen", lambda r: r["f"].first_seen_at),
                ("Last detected", lambda r: r["f"].last_detected_at),
            ],
            filename_stem="patching",
        )

    paginator = Paginator(rows, 50)
    page = paginator.get_page(request.GET.get("page"))

    clients = Client.objects.filter(tenant_id=1, deleted_at__isnull=True).order_by("display_name")

    page_query = request.GET.copy()
    page_query.pop("page", None)

    # Preserve current filters as query-string fragment for scope
    # drilldown links.
    filter_qs_parts = []
    if client_filter:
        filter_qs_parts.append(f"client={','.join(client_filter)}")
    if status_filter and status_filter != "active":
        filter_qs_parts.append(f"status={status_filter}")
    if role_filter:
        filter_qs_parts.append(f"role={role_filter}")
    filter_qs = "&".join(filter_qs_parts)

    # Population summary tiles (clickthrough drills into scope bucket).
    def _scope_href(bucket: str) -> str:
        parts = [f"scope={bucket}"]
        if filter_qs:
            parts.append(filter_qs)
        return "?" + "&".join(parts)

    population_tiles = [
        {"label": "Total devices", "value": population["total"]},
        {
            "label": "In scope (Included)",
            "value": population["in_scope"],
            "href": _scope_href("Included"),
        },
        {"label": "Excluded", "value": population["excluded"], "href": _scope_href("Excluded")},
        {"label": "Unmanaged", "value": population["unmanaged"], "href": _scope_href("Unmanaged")},
    ]

    return render(
        request,
        "patching_queue.html",
        {
            "tiles": tiles,
            "population_tiles": population_tiles,
            "page_obj": page,
            "rows": page.object_list,
            "patching_types": _PATCHING_TYPES,
            "clients": clients,
            "status_choices": Finding.Status.choices,
            "active_type": type_filter,
            "active_status": status_filter,
            "active_client": client_filter,
            "active_role": role_filter,
            "role_choices": _ROLE_CHOICES,
            "active_scope": scope_filter,
            "total_active": sum(tile_counts.values()),
            "population": population,
            "patch_status": patch_status,
            "client_posture": client_posture,
            "active_device_days": active_device_days,
            "patch_activity_days": patch_activity_days,
            "active_posture": posture_filter,
            "filter_qs": filter_qs,
            "device_rows": device_rows,
            "page_query": page_query.urlencode(),
        },
    )


@login_required
def findings_admin_health(request: HttpRequest) -> HttpResponse:
    """Admin/platform-health findings page."""
    status_filter = request.GET.get("status", "active")
    severity_filter = request.GET.get("severity", "")
    type_filter = request.GET.get("type", "")

    qs = AdminFinding.objects.filter(tenant_id=1).select_related("finding_type")

    if status_filter == "active":
        qs = qs.filter(status__in=["open", "acknowledged"])
    elif status_filter and status_filter != "all":
        qs = qs.filter(status=status_filter)

    if severity_filter:
        qs = qs.filter(severity=severity_filter)
    if type_filter:
        qs = qs.filter(finding_type__name=type_filter)

    qs = qs.order_by("-last_detected_at")[:200]

    finding_types = FindingType.objects.filter(finding_class="admin").order_by("name")

    return render(
        request,
        "findings_admin_health.html",
        {
            "admin_group": "integrations",
            "admin_tab": "ingest",
            "findings": qs,
            "finding_types": finding_types,
            "severity_choices": Finding.Severity.choices,
            "active_status": status_filter,
            "active_severity": severity_filter,
            "active_type": type_filter,
        },
    )


@login_required
@require_POST
def admin_finding_acknowledge(request: HttpRequest, finding_id: str) -> HttpResponse:
    """Acknowledge an admin finding."""
    finding = get_object_or_404(AdminFinding, id=finding_id, tenant_id=1)
    if finding.status == "open":
        finding.status = "acknowledged"
        finding.save(update_fields=["status"])
    return redirect("findings_admin_health")


@login_required
@require_POST
def admin_finding_apply_client_rename(request: HttpRequest, finding_id: str) -> HttpResponse:
    """Apply a source-observed client name to the canonical client.

    Completes the `client_name_conflict` workflow. Track C replaced the old
    `bootstrap_clients_from_ninja` auto-rename with "name drift = finding,
    never re-match" — an operator decides, rather than a source silently
    overwriting canonical state. The finding half was built; this apply half
    was not, which left the rename visible but unactionable.

    `slug` is deliberately untouched. The retired bootstrap command preserved
    it too, because the slug is in operator-facing URLs and churning it breaks
    saved links.
    """
    finding = get_object_or_404(AdminFinding, id=finding_id, tenant_id=1)
    if finding.finding_type.name != "client_name_conflict":
        messages.error(request, "That action only applies to client rename findings.")
        return redirect("findings_admin_health")

    ref = finding.subject_ref or {}
    observed_name = (ref.get("observed_name") or "").strip()
    client_id = ref.get("client_id")
    if not observed_name or not client_id:
        messages.error(
            request,
            "This finding is missing the observed name or client reference; "
            "cannot apply.",
        )
        return redirect("findings_admin_health")

    client = get_object_or_404(Client, id=client_id, tenant_id=1, deleted_at__isnull=True)
    previous_name = client.display_name
    if previous_name == observed_name:
        messages.info(request, f"{client.display_name} already carries that name.")
    else:
        client.display_name = observed_name
        client.save(update_fields=["display_name"])
        AuditLog.objects.create(
            tenant_id=1,
            actor=request.user if request.user.is_authenticated else None,
            actor_kind=AuditLog.ActorKind.USER,
            source=AuditLog.Source.UI,
            action="client.rename_from_source",
            entity_type="client",
            entity_id=client.id,
            before_state={"display_name": previous_name, "slug": client.slug},
            after_state={"display_name": observed_name, "slug": client.slug},
            ip_address=request.META.get("REMOTE_ADDR") or None,
            user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:2000],
        )
        messages.success(
            request,
            f"Renamed {previous_name} to {observed_name}. The URL is unchanged.",
        )

    # The next resolver pass would resolve this itself once the names agree;
    # closing it here keeps the queue honest in the meantime.
    finding.status = "resolved"
    finding.resolved_at = timezone.now()
    finding.save(update_fields=["status", "resolved_at"])
    return redirect("findings_admin_health")


# ── Patching visibility — Fleet Patch Evidence ─────────────────────────────


_PATCH_STATUS_CHOICES = [
    ("INSTALLED", "Installed"),
    ("FAILED", "Failed"),
    ("PENDING", "Pending"),
    ("APPROVED", "Approved"),
    ("REJECTED", "Rejected"),
    ("MANUAL", "Manual"),
    ("DELAYED", "Delayed"),
]

_PATCH_SEVERITY_CHOICES = [
    ("critical", "Critical"),
    ("important", "Important"),
    ("moderate", "Moderate"),
    ("optional", "Optional"),
    ("none", "Unspecified"),
    ("security", "Security"),
]

_PATCH_SEVERITY_VALUES = {
    "critical": ("CRITICAL",),
    "important": ("IMPORTANT",),
    "moderate": ("MODERATE",),
    "optional": ("OPTIONAL", "optional"),
    "none": ("NONE",),
    "security": ("security",),
}

_WINDOWS_11_COMPATIBILITY_CHOICES = [
    ("capable", "Capable"),
    ("not_capable", "Not capable"),
    ("undetermined", "Undetermined"),
    ("not_assessed", "Not assessed"),
]


@login_required
def patch_evidence_page(request: HttpRequest) -> HttpResponse:
    """Fleet-wide Patch Evidence — one row per (device, patch) with
    the current patch state joined to device / client metadata.

    Replaces the legacy `script-dev/ninja/Ninja-Patching-report.ps1`
    CSV report + Metabase's "Patch Evidence" dashboard. All data is
    already in the pipeline; this is the native operator surface.

    Filters:
      - status         current Ninja patch state
      - severity       current Ninja patch severity
      - client         org slug
      - online         Any / Online / Offline / source currently online
      - role           device role
      - os_group       operating-system group
      - win11          current Ninja Windows 11 compatibility result
      - q              free-text against patch name or KB number
    """
    status_filter = request.GET.get("status", "").strip().upper()
    severity_filter = request.GET.get("severity", "").strip().lower()
    client_filter = request.GET.get("client", "").strip()
    online_filter = request.GET.get("online", "").strip()
    role_filter = request.GET.get("role", "").strip()
    os_group_filter = request.GET.get("os_group", "").strip()
    win11_filter = request.GET.get("win11", "").strip()
    q_filter = (request.GET.get("q") or "").strip()

    role_choices = ("server", "workstation", "unknown")
    if role_filter not in role_choices:
        role_filter = ""
    if severity_filter not in _PATCH_SEVERITY_VALUES:
        severity_filter = ""
    if win11_filter not in {
        value for value, _label in _WINDOWS_11_COMPATIBILITY_CHOICES
    }:
        win11_filter = ""

    source_names = list(Source.objects.order_by("name").values_list("name", flat=True))
    source_names_set = set(source_names)
    if online_filter not in {"", "online", "offline"} | source_names_set:
        online_filter = ""
    os_group_choices = list(
        Device.objects.filter(tenant_id=1, deleted_at__isnull=True)
        .exclude(os_group="")
        .order_by("os_group")
        .values_list("os_group", flat=True)
        .distinct()
    )
    if os_group_filter not in os_group_choices:
        os_group_filter = ""

    where = ["1=1"]
    params: list = []
    if status_filter:
        where.append("cps.status = %s")
        params.append(status_filter)
    if severity_filter:
        where.append("cps.severity = ANY(%s)")
        params.append(list(_PATCH_SEVERITY_VALUES[severity_filter]))
    if client_filter:
        where.append("c.slug = %s")
        params.append(client_filter)
    if role_filter:
        where.append("d.device_role = %s")
        params.append(role_filter)
    if os_group_filter:
        where.append("d.os_group = %s")
        params.append(os_group_filter)
    if online_filter == "online":
        where.append("COALESCE(cardinality(dsc.online_sources), 0) > 0")
    elif online_filter == "offline":
        where.append("COALESCE(cardinality(dsc.online_sources), 0) = 0")
    elif online_filter:
        where.append("%s = ANY(dsc.online_sources)")
        params.append(online_filter)
    if win11_filter == "capable":
        where.append("w11.value_text = 'Capable'")
    elif win11_filter == "not_capable":
        where.append("w11.value_text LIKE '[Alert] Not Capable%'")
    elif win11_filter == "undetermined":
        where.append("w11.value_text LIKE '[Error] Undetermined%'")
    elif win11_filter == "not_assessed":
        where.append("w11.entity_id IS NULL")
    if q_filter:
        where.append("(cps.patch_name ILIKE %s OR cps.kb_number ILIKE %s)")
        params.extend([f"%{q_filter}%", f"%{q_filter}%"])
    where_sql = " AND ".join(where)
    has_explicit_filter = bool(
        status_filter
        or severity_filter
        or client_filter
        or online_filter
        or role_filter
        or os_group_filter
        or win11_filter
        or q_filter
    )
    patch_state_source = "ninja_patches.current_patch_state cps"
    if not has_explicit_filter:
        patch_state_source = """
            (
                SELECT *
                FROM ninja_patches.current_patch_state
                ORDER BY last_observed_at DESC NULLS LAST
                LIMIT 1000
            ) cps
        """
    evidence_from_sql = f"""
        FROM {patch_state_source}
        JOIN operations.v_device_source_link dl
          ON dl.external_id = cps.device_id::text
         AND dl.source_id = (SELECT id FROM operations.sources WHERE name = 'Ninja' LIMIT 1)
         AND dl.tenant_id = 1
        JOIN operations.devices d
          ON d.id = dl.device_id AND d.deleted_at IS NULL
        JOIN operations.clients c
          ON c.id = d.client_id AND c.deleted_at IS NULL
        LEFT JOIN operations.device_session_current dsc
          ON dsc.tenant_id = 1 AND dsc.device_id = d.id
        LEFT JOIN (
            SELECT DISTINCT ON (entity_id)
                   entity_id,
                   value_text
            FROM ninja_core.custom_field_values
            WHERE entity_type = 'DEVICE'
              AND field_name = 'w11Compatible'
            ORDER BY entity_id, last_observed_at DESC
        ) w11
          ON w11.entity_id = cps.device_id
    """

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        # Overview counts by status (fleet-wide, ignoring filters).
        cur.execute(
            """
            SELECT status, COUNT(*)::int
            FROM ninja_patches.current_patch_state
            GROUP BY status
            ORDER BY 1
            """
        )
        status_counts = dict(cur.fetchall())

        # Counts are deliberately computed from the same filtered relation as
        # the table (before its display limit), so cards explain the exact
        # scope currently being reviewed.
        cur.execute(
            f"""
            SELECT COUNT(*)::int,
                   COUNT(DISTINCT d.id)::int,
                   COUNT(DISTINCT c.id)::int,
                   COUNT(DISTINCT d.id) FILTER (
                       WHERE COALESCE(cardinality(dsc.online_sources), 0) > 0
                   )::int
            {evidence_from_sql}
            WHERE {where_sql}
            """,
            params,
        )
        summary_row = cur.fetchone() or (0, 0, 0, 0)

        cur.execute(
            f"""
            SELECT
                d.id                       AS device_id,
                d.canonical_hostname       AS hostname,
                c.slug                     AS client_slug,
                c.display_name             AS client_name,
                d.device_role,
                d.os_group,
                d.os_name,
                COALESCE(dsc.online_sources, ARRAY[]::text[]) AS online_sources,
                cps.patch_name,
                cps.kb_number,
                cps.status,
                cps.severity,
                cps.installed_at,
                cps.last_observed_at,
                lio.status                 AS last_install_status,
                lio.installed_at           AS last_install_at
            {evidence_from_sql}
            LEFT JOIN ninja_patches.latest_install_outcome lio
              ON lio.device_id = cps.device_id AND lio.patch_uid = cps.patch_uid
            WHERE {where_sql}
            ORDER BY
                CASE UPPER(cps.severity)
                    WHEN 'CRITICAL'    THEN 0
                    WHEN 'IMPORTANT'   THEN 1
                    WHEN 'MODERATE'    THEN 2
                    WHEN 'OPTIONAL'    THEN 3
                    ELSE 5
                END,
                cps.last_observed_at DESC NULLS LAST,
                c.display_name,
                d.canonical_hostname,
                cps.patch_name
            LIMIT 1000
            """,
            params,
        )
        rows = cur.fetchall()

    summary_counts = {
        "patch_rows": summary_row[0],
        "devices": summary_row[1],
        "clients": summary_row[2],
        "online_devices": summary_row[3],
    }

    columns = [
        "device_id",
        "hostname",
        "client_slug",
        "client_name",
        "device_role",
        "os_group",
        "os_name",
        "online_sources",
        "patch_name",
        "kb_number",
        "status",
        "severity",
        "installed_at",
        "last_observed_at",
        "last_install_status",
        "last_install_at",
    ]
    patch_rows = [dict(zip(columns, r, strict=True)) for r in rows]

    if wants_csv(request):
        return csv_response(
            patch_rows,
            columns=[
                ("Client", "client_name"),
                ("Hostname", "hostname"),
                ("Role", "device_role"),
                ("OS group", "os_group"),
                ("OS name", "os_name"),
                ("Online sources", "online_sources"),
                ("KB", "kb_number"),
                ("Patch", "patch_name"),
                ("Status", "status"),
                ("Severity", "severity"),
                ("Installed at", "installed_at"),
                ("Last observed", "last_observed_at"),
                ("Last install status", "last_install_status"),
                ("Last install at", "last_install_at"),
            ],
            filename_stem="patch_evidence",
        )

    clients = list(
        Client.objects.filter(tenant_id=1, deleted_at__isnull=True)
        .order_by("display_name")
        .values("slug", "display_name")
    )

    return render(
        request,
        "patch_evidence.html",
        {
            "rows": patch_rows,
            "row_count": len(patch_rows),
            "is_recent_slice": not has_explicit_filter,
            "summary_counts": summary_counts,
            "status_counts": status_counts,
            "clients": clients,
            "status_choices": _PATCH_STATUS_CHOICES,
            "severity_choices": _PATCH_SEVERITY_CHOICES,
            "online_choices": [("online", "Online (any source)"), ("offline", "Offline")]
            + [(name, f"via {name}") for name in source_names],
            "role_choices": role_choices,
            "os_group_choices": os_group_choices,
            "win11_compatibility_choices": _WINDOWS_11_COMPATIBILITY_CHOICES,
            "active_status": status_filter,
            "active_severity": severity_filter,
            "active_client": client_filter,
            "active_online": online_filter,
            "active_role": role_filter,
            "active_os_group": os_group_filter,
            "active_win11": win11_filter,
            "active_q": q_filter,
        },
    )


@login_required
def patch_trends_page(request: HttpRequest) -> HttpResponse:
    """Per-day install / failure trend view over `ninja_patches.patch_facts`.

    Closes the Metabase "Patch Trends" dashboard GAP. Optional client
    filter narrows to one org.

    Range is `?days=` (default 30, capped at 180). Each row =
    (day, client_scope) with install + failure counts. CSV export via
    the standard `?format=csv`.
    """
    try:
        days = int(request.GET.get("days") or 30)
    except ValueError:
        days = 30
    days = max(1, min(180, days))

    client_filter = (request.GET.get("client") or "").strip()

    where = [
        "pf.fact_type = 'install_outcome'",
        "pf.installed_at > NOW() - (%s::text || ' days')::interval",
    ]
    params: list = [str(days)]
    if client_filter:
        # Constrain by the client this Ninja device_id resolves to.
        where.append(
            "EXISTS (SELECT 1 FROM operations.v_device_source_link dl "
            "JOIN operations.devices d ON d.id = dl.device_id "
            "JOIN operations.clients c ON c.id = d.client_id "
            "WHERE dl.tenant_id = 1 "
            "  AND dl.source_id = (SELECT id FROM operations.sources WHERE name='Ninja' LIMIT 1) "
            "  AND dl.external_id = pf.device_id::text "
            "  AND c.slug = %s)"
        )
        params.append(client_filter)

    where_sql = " AND ".join(where)

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            f"""
            SELECT
                date_trunc('day', pf.installed_at)::date AS day,
                COUNT(*) FILTER (WHERE pf.status = 'Installed')::int AS installs,
                COUNT(*) FILTER (WHERE pf.status = 'Failed')::int    AS failures,
                COUNT(*)::int                                        AS total,
                COUNT(DISTINCT pf.device_id)::int                    AS devices_touched
            FROM ninja_patches.patch_facts pf
            WHERE {where_sql}
            GROUP BY 1
            ORDER BY 1 DESC
            """,
            params,
        )
        rows = cur.fetchall()

    trend_rows = [
        {
            "day": day,
            "installs": installs,
            "failures": failures,
            "total": total,
            "devices_touched": devices_touched,
            "fail_pct": round(100.0 * failures / total, 1) if total else 0.0,
        }
        for day, installs, failures, total, devices_touched in rows
    ]

    totals = {
        "installs": sum(r["installs"] for r in trend_rows),
        "failures": sum(r["failures"] for r in trend_rows),
        "total": sum(r["total"] for r in trend_rows),
        "devices_touched": sum(r["devices_touched"] for r in trend_rows),
    }
    totals["fail_pct"] = (
        round(100.0 * totals["failures"] / totals["total"], 1) if totals["total"] else 0.0
    )

    if wants_csv(request):
        return csv_response(
            trend_rows,
            columns=[
                ("Day", "day"),
                ("Installs", "installs"),
                ("Failures", "failures"),
                ("Total attempts", "total"),
                ("Devices touched", "devices_touched"),
                ("Failure %", "fail_pct"),
            ],
            filename_stem="patch_trends",
        )

    clients = list(
        Client.objects.filter(tenant_id=1, deleted_at__isnull=True)
        .order_by("display_name")
        .values("slug", "display_name")
    )

    # Max value in the range — drives inline bar widths in the template.
    max_total = max((r["total"] for r in trend_rows), default=0) or 1

    return render(
        request,
        "patch_trends.html",
        {
            "rows": trend_rows,
            "totals": totals,
            "days": days,
            "active_client": client_filter,
            "clients": clients,
            "max_total": max_total,
        },
    )


@login_required
def patch_activity_search_page(request: HttpRequest) -> HttpResponse:
    """Free-text search across recent Ninja patch install outcomes.

    Each result retains Ninja's event time, Operations collection time, and
    source payload so an operator can inspect the evidence behind a status.

    Query params: `q` (patch name or KB), `days` (default 30, capped
    180), `status` (Installed/Failed/...), `client` (slug). CSV export
    via the standard `?format=csv`.
    """
    q_filter = (request.GET.get("q") or "").strip()
    try:
        days = int(request.GET.get("days") or 30)
    except ValueError:
        days = 30
    days = max(1, min(180, days))
    status_filter = (request.GET.get("status") or "").strip()
    client_filter = (request.GET.get("client") or "").strip()

    where = [
        "pf.fact_type = 'install_outcome'",
        "pf.installed_at > NOW() - (%s::text || ' days')::interval",
    ]
    params: list = [str(days)]
    if q_filter:
        where.append("(pf.name ILIKE %s OR pf.kb_number ILIKE %s)")
        params.extend([f"%{q_filter}%", f"%{q_filter}%"])
    if status_filter:
        where.append("pf.status = %s")
        params.append(status_filter)
    if client_filter:
        where.append("c.slug = %s")
        params.append(client_filter)
    where_sql = " AND ".join(where)

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            f"""
            SELECT
                pf.installed_at,
                pf.status,
                pf.severity,
                pf.kb_number,
                pf.name,
                pf.fact_type,
                pf.ninja_observed_at,
                pf.last_observed_at,
                pf.data,
                d.id                     AS device_id,
                d.canonical_hostname     AS hostname,
                c.slug                   AS client_slug,
                c.display_name           AS client_name
            FROM ninja_patches.patch_facts pf
            JOIN operations.v_device_source_link dl
              ON dl.external_id = pf.device_id::text
             AND dl.source_id = (SELECT id FROM operations.sources WHERE name='Ninja' LIMIT 1)
             AND dl.tenant_id = 1
            JOIN operations.devices d
              ON d.id = dl.device_id AND d.deleted_at IS NULL
            JOIN operations.clients c
              ON c.id = d.client_id AND c.deleted_at IS NULL
            WHERE {where_sql}
            ORDER BY pf.installed_at DESC NULLS LAST
            LIMIT 500
            """,
            params,
        )
        rows = cur.fetchall()

        # Patch facts are structured patch evidence. Ninja's activity feed is
        # the accompanying source event trail, so expose both in one search
        # rather than making an operator leave Operations for the message
        # Ninja reported.
        ninja_activity_rows = []
        if not status_filter:
            activity_where = [
                "a.activity_time > NOW() - (%s::text || ' days')::interval",
            ]
            activity_params: list = [str(days)]
            if q_filter:
                activity_where.append("(a.subject ILIKE %s OR a.message ILIKE %s)")
                activity_params.extend([f"%{q_filter}%", f"%{q_filter}%"])
            if client_filter:
                activity_where.append("c.slug = %s")
                activity_params.append(client_filter)
            cur.execute(
                f"""
                SELECT a.activity_time, NULL::text AS status, a.severity,
                       NULL::text AS kb_number, a.subject AS name,
                       a.activity_type AS fact_type, a.activity_time AS ninja_observed_at,
                       a.ingested_at AS last_observed_at, a.data,
                       d.id AS device_id, d.canonical_hostname AS hostname,
                       c.slug AS client_slug, c.display_name AS client_name
                FROM ninja_activities.activities a
                JOIN operations.v_device_source_link dl
                  ON dl.external_id = a.device_id::text
                 AND dl.tenant_id = 1
                JOIN operations.sources s
                  ON s.id = dl.source_id AND LOWER(s.name) = 'ninja'
                JOIN operations.devices d
                  ON d.id = dl.device_id AND d.deleted_at IS NULL
                JOIN operations.clients c
                  ON c.id = d.client_id AND c.deleted_at IS NULL
                WHERE {' AND '.join(activity_where)}
                ORDER BY a.activity_time DESC
                LIMIT 500
                """,
                activity_params,
            )
            ninja_activity_rows = cur.fetchall()

    cols = [
        "installed_at",
        "status",
        "severity",
        "kb_number",
        "name",
        "fact_type",
        "ninja_observed_at",
        "last_observed_at",
        "raw_data",
        "device_id",
        "hostname",
        "client_slug",
        "client_name",
    ]
    activity = [dict(zip(cols, r, strict=True)) for r in rows]
    activity.extend(dict(zip(cols, r, strict=True)) for r in ninja_activity_rows)
    for row in activity:
        row["raw_data"] = json.dumps(row["raw_data"], indent=2, sort_keys=True, default=str)
        row["event_at"] = row["installed_at"] or row["ninja_observed_at"] or row["last_observed_at"]
    activity.sort(key=lambda row: row["event_at"] or timezone.now(), reverse=True)
    activity = activity[:500]

    if wants_csv(request):
        return csv_response(
            activity,
            columns=[
                ("Installed at", "installed_at"),
                ("Status", "status"),
                ("Severity", "severity"),
                ("KB", "kb_number"),
                ("Patch", "name"),
                ("Ninja event time", "ninja_observed_at"),
                ("Collected", "last_observed_at"),
                ("Client", "client_name"),
                ("Hostname", "hostname"),
            ],
            filename_stem="patch_activity",
        )

    clients = list(
        Client.objects.filter(tenant_id=1, deleted_at__isnull=True)
        .order_by("display_name")
        .values("slug", "display_name")
    )

    return render(
        request,
        "patch_activity.html",
        {
            "rows": activity,
            "row_count": len(activity),
            "days": days,
            "clients": clients,
            "status_choices": _PATCH_STATUS_CHOICES,
            "active_q": q_filter,
            "active_status": status_filter,
            "active_client": client_filter,
        },
    )


def _get_client_by_slug(slug: str) -> Client:
    return get_object_or_404(Client, tenant_id=1, slug=slug, deleted_at__isnull=True)


@login_required
def client_policy_new(request: HttpRequest, org_slug: str) -> HttpResponse:
    client = _get_client_by_slug(org_slug)
    if request.method == "POST":
        form = ClientPolicyForm(request.POST)
        if form.is_valid():
            policy = form.save(commit=False)
            policy.tenant_id = 1
            policy.client = client
            try:
                policy.save()
            except Exception as exc:
                form.add_error("category", f"Could not save: {exc}")
            else:
                messages.success(request, f"Policy '{policy.category}' created.")
                return redirect("org_index", org_slug=org_slug)
    else:
        form = ClientPolicyForm()
    return render(
        request,
        "client_policy_form.html",
        {"form": form, "client": client, "mode": "new"},
    )


@login_required
def client_policy_edit(request: HttpRequest, org_slug: str, policy_id: str) -> HttpResponse:
    client = _get_client_by_slug(org_slug)
    policy = get_object_or_404(ClientPolicy, tenant_id=1, client=client, id=policy_id)
    if request.method == "POST":
        form = ClientPolicyForm(request.POST, instance=policy)
        if form.is_valid():
            form.save()
            messages.success(request, f"Policy '{policy.category}' updated.")
            return redirect("org_index", org_slug=org_slug)
    else:
        form = ClientPolicyForm(instance=policy)
    return render(
        request,
        "client_policy_form.html",
        {"form": form, "client": client, "policy": policy, "mode": "edit"},
    )


@login_required
@require_POST
def client_policy_delete(request: HttpRequest, org_slug: str, policy_id: str) -> HttpResponse:
    client = _get_client_by_slug(org_slug)
    policy = get_object_or_404(ClientPolicy, tenant_id=1, client=client, id=policy_id)
    category = policy.category
    policy.delete()
    messages.success(request, f"Policy '{category}' deleted.")
    return redirect("org_index", org_slug=org_slug)


@login_required
def merge_candidates_queue(request: HttpRequest) -> HttpResponse:
    """Cross-source merge candidate review queue.

    The docstring here used to read "Empty until multi-source ingest lands."
    Multi-source ingest landed long ago; what was missing was a producer, so
    the queue stayed empty and nobody questioned it. `resolver`'s
    `project_merge_candidates` now reconciles proposals against current device
    collisions each cycle.
    """
    status_filter = request.GET.get("status", MergeCandidate.Status.OPEN)
    entity_filter = request.GET.get("entity", "")
    # `key` lets an identity_conflict finding link straight to its own
    # proposal. The finding's condition_key and the candidate's canonical_key
    # are the same string by construction, so the two surfaces address one
    # collision.
    key_filter = request.GET.get("key", "").strip()

    qs = MergeCandidate.objects.filter(tenant_id=1).select_related("client")

    if status_filter and status_filter != "all":
        qs = qs.filter(status=status_filter)
    if entity_filter:
        qs = qs.filter(entity_type=entity_filter)
    if key_filter:
        qs = qs.filter(canonical_key=key_filter)

    qs = qs.order_by("-confidence", "canonical_key")[:200]

    entity_types = (
        MergeCandidate.objects.filter(tenant_id=1).values_list("entity_type", flat=True).distinct()
    )

    if wants_csv(request):
        return csv_response(
            list(qs),
            # `created_at`, `resolved_at` and `resolved_by` were listed here
            # but are not fields on MergeCandidate. `csv_export._resolve`
            # defaults missing attributes to "", so they did not raise — they
            # emitted three permanently blank columns. Invisible while the
            # queue was empty; wrong as soon as it held rows.
            columns=[
                ("Entity type", "entity_type"),
                ("Canonical key", "canonical_key"),
                ("Client", lambda r: (r.client.display_name if r.client else "")),
                ("Members", lambda r: len(r.member_snapshots or [])),
                ("Match reason", "match_reason"),
                ("Confidence", "confidence"),
                ("Status", "status"),
            ],
            filename_stem="merge_candidates",
        )

    return render(
        request,
        "merge_candidates_queue.html",
        {
            "admin_group": "review",
            "admin_tab": "merges",
            "candidates": qs,
            "key_filter": key_filter,
            "status_choices": MergeCandidate.Status.choices,
            "entity_types": sorted(set(entity_types)),
            "active_status": status_filter,
            "active_entity": entity_filter,
        },
    )


_SW_PAGE_SIZE = 100


@login_required
def org_software(request: HttpRequest, org_slug: str) -> HttpResponse:
    client = _get_client_by_slug(org_slug)
    search = request.GET.get("q", "").strip()
    active_publishers = request.GET.getlist("publisher")
    page = max(1, int(request.GET.get("page", 1) or 1))

    base_params: list = [1, str(client.id)]
    base_where = "tenant_id = %s AND client_id = %s AND deleted_at IS NULL"
    extra_where = ""
    extra_params: list = []

    if search:
        extra_where += " AND canonical_name ILIKE %s"
        extra_params.append(f"%{search}%")
    if active_publishers:
        placeholders = ",".join(["%s"] * len(active_publishers))
        extra_where += f" AND publisher IN ({placeholders})"
        extra_params.extend(active_publishers)

    full_where = base_where + extra_where
    all_params = base_params + extra_params

    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")

            cur.execute(
                f"""
                SELECT publisher
                FROM operations.software_installations_current
                WHERE {base_where}
                  AND publisher IS NOT NULL AND publisher <> ''
                GROUP BY publisher
                ORDER BY publisher
                """,
                base_params,
            )
            publishers = [row[0] for row in cur.fetchall()]

            cur.execute(
                f"""
                SELECT count(DISTINCT (canonical_name, COALESCE(publisher, '')))
                FROM operations.software_installations_current
                WHERE {full_where}
                """,
                all_params,
            )
            total = cur.fetchone()[0]

            offset = (page - 1) * _SW_PAGE_SIZE
            cur.execute(
                f"""
                SELECT
                    canonical_name,
                    publisher,
                    string_agg(DISTINCT version, ', ' ORDER BY version)
                        FILTER (WHERE version IS NOT NULL AND version <> '') AS versions,
                    count(DISTINCT device_id) AS device_count,
                    min(install_date)          AS first_installed,
                    max(last_observed_at)      AS last_seen,
                    string_agg(DISTINCT install_location, E'\\n')
                        FILTER (WHERE install_location IS NOT NULL AND install_location <> '') AS locations
                FROM operations.software_installations_current
                WHERE {full_where}
                GROUP BY canonical_name, publisher
                ORDER BY canonical_name
                LIMIT %s OFFSET %s
                """,
                all_params + [_SW_PAGE_SIZE, offset],
            )
            rows = cur.fetchall()

    # Attach decision + finding count to each row so templates don't
    # need dict-key lookups.
    decisions_map = {
        d.canonical_name: d.decision
        for d in SoftwareDecision.objects.filter(tenant_id=1, client=client)
    }
    # Per-canonical-name open finding counts scoped to THIS client's devices.
    findings_map: dict[str, int] = {}
    if rows:
        canonical_names = [row[0] for row in rows]
        with transaction.atomic(), connection.cursor() as cur2:
            cur2.execute("SET LOCAL operations.tenant_id = 1")
            cur2.execute(
                """
                -- Software findings carry no client_id and no device subject
                -- now, so "how many of this client's devices does this title
                -- affect" comes from the exposure view. Filtering on
                -- f.client_id here returned 0 for every title.
                SELECT e.canonical_name, COUNT(DISTINCT e.device_id)
                FROM operations.v_device_software_exposure e
                WHERE e.tenant_id = 1
                  AND e.client_id = %s
                  AND e.status IN ('open', 'acknowledged')
                  AND e.canonical_name = ANY(%s::text[])
                GROUP BY 1
                """,
                (client.id, canonical_names),
            )
            findings_map = {name: count for name, count in cur2.fetchall()}
    rows = [row + (decisions_map.get(row[0], ""), findings_map.get(row[0], 0)) for row in rows]

    num_pages = max(1, (total + _SW_PAGE_SIZE - 1) // _SW_PAGE_SIZE)

    page_query_parts = [f"publisher={p}" for p in active_publishers]
    if search:
        page_query_parts.append(f"q={search}")
    page_query = "&".join(page_query_parts)

    if wants_csv(request):
        return csv_response(
            rows,
            columns=[
                ("Canonical name", lambda r: r[0]),
                ("Publisher", lambda r: r[1] or ""),
                ("Device count", lambda r: r[2]),
                ("First installed", lambda r: r[3]),
                ("Last seen", lambda r: r[4]),
                ("Locations", lambda r: r[5] or ""),
                ("Decision", lambda r: r[6]),
                ("Open findings", lambda r: r[7]),
            ],
            filename_stem=f"{org_slug}_software",
        )

    return render(
        request,
        "org_software.html",
        {
            "client": client,
            "rows": rows,
            "total": total,
            "publishers": publishers,
            "active_publishers": active_publishers,
            "search_query": search,
            "decision_choices": SoftwareDecision.Decision.choices,
            "page": page,
            "num_pages": num_pages,
            "page_size": _SW_PAGE_SIZE,
            "page_query": page_query,
            "has_previous": page > 1,
            "has_next": page < num_pages,
            "previous_page": page - 1,
            "next_page": page + 1,
        },
    )


@login_required
def org_software_devices(request: HttpRequest, org_slug: str) -> HttpResponse:
    """Devices that have a specific software installed."""
    client = _get_client_by_slug(org_slug)
    sw_name = request.GET.get("name", "").strip()
    sw_publisher = request.GET.get("publisher", "").strip()
    if not sw_name:
        return redirect("org_software", org_slug=org_slug)

    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            params: list = [1, str(client.id), sw_name]
            pub_clause = ""
            if sw_publisher:
                pub_clause = " AND s.publisher = %s"
                params.append(sw_publisher)
            cur.execute(
                f"""
                SELECT d.id, d.canonical_hostname, d.canonical_serial, d.device_type,
                       s.version, s.install_date, s.install_location, s.last_observed_at
                FROM operations.software_installations_current s
                JOIN operations.devices d
                     ON d.id = s.device_id AND d.tenant_id = s.tenant_id
                WHERE s.tenant_id = %s
                  AND s.client_id = %s
                  AND s.canonical_name = %s
                  AND s.deleted_at IS NULL{pub_clause}
                ORDER BY d.canonical_hostname
                """,
                params,
            )
            device_rows = cur.fetchall()

    if wants_csv(request):
        return csv_response(
            device_rows,
            columns=[
                ("Device ID", lambda r: str(r[0])),
                ("Hostname", lambda r: r[1]),
                ("Serial", lambda r: r[2] or ""),
                ("Device type", lambda r: r[3]),
                ("Version", lambda r: r[4] or ""),
                ("Install date", lambda r: r[5]),
                ("Install path", lambda r: r[6] or ""),
                ("Last observed", lambda r: r[7]),
            ],
            filename_stem=f"{org_slug}_{sw_name}_devices",
        )

    return render(
        request,
        "org_software_devices.html",
        {
            "client": client,
            "sw_name": sw_name,
            "sw_publisher": sw_publisher,
            "device_rows": device_rows,
        },
    )


@login_required
@require_POST
def org_software_decide(request: HttpRequest, org_slug: str) -> HttpResponse:
    """Record approve/reject/investigate decision for a software entry."""
    from django.utils import timezone

    client = _get_client_by_slug(org_slug)
    sw_name = request.POST.get("canonical_name", "").strip()
    decision = request.POST.get("decision", "").strip()
    if not sw_name or decision not in SoftwareDecision.Decision.values:
        return redirect("org_software", org_slug=org_slug)

    SoftwareDecision.objects.update_or_create(
        tenant_id=1,
        client=client,
        # device must be part of the lookup, not just the scope intent: without
        # it a client decision matches — and overwrites — an existing
        # device-scoped row for the same client and title.
        device=None,
        canonical_name=sw_name,
        publisher="",
        defaults={
            "decision": decision,
            "decided_by": request.user,
            "decided_at": timezone.now(),
        },
    )
    # Follow only a relative ``next``; an unvalidated one (and HTTP_REFERER,
    # which is attacker-settable) is an open redirect.
    nxt = request.POST.get("next") or ""
    if nxt.startswith("/") and not nxt.startswith("//"):
        return redirect(nxt)
    return redirect("org_software", org_slug=org_slug)


# ── Compliance / fleet coverage page ─────────────────────────────────────────

_SEV_RANK = (
    "CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END"
)


@login_required
def fleet_coverage(request: HttpRequest) -> HttpResponse:
    """Compliance page: active missing-agent findings per client × platform."""
    client_filter = request.GET.get("client", "")
    platform_filter = request.GET.get("platform", "")
    conf_filter = request.GET.get("confidence", "")

    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")

            # Active missing-required-platform findings grouped by client + platform
            cur.execute(
                """
                SELECT
                    c.display_name,
                    c.slug,
                    f.finding_details->>'platform'    AS platform,
                    f.severity,
                    COUNT(*)::int                     AS total,
                    COUNT(*) FILTER (WHERE f.confidence = 'confirmed')::int  AS confirmed,
                    COUNT(*) FILTER (WHERE f.confidence = 'probable')::int   AS probable,
                    MIN(f.first_seen_at)              AS oldest_at
                FROM operations.findings f
                JOIN operations.clients c ON c.id = f.client_id
                JOIN operations.finding_types ft ON ft.id = f.finding_type_id
                WHERE f.tenant_id = 1
                  AND ft.name = 'missing_required_platform'
                  AND f.status IN ('open', 'acknowledged', 'investigating')
                  AND (%(client)s = '' OR c.slug = %(client)s)
                  AND (%(platform)s = '' OR f.finding_details->>'platform' = %(platform)s)
                  AND (%(confidence)s = '' OR f.confidence = %(confidence)s)
                GROUP BY c.display_name, c.slug, f.finding_details->>'platform', f.severity
                ORDER BY
                    CASE f.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                    COUNT(*) DESC,
                    c.display_name,
                    f.finding_details->>'platform'
            """,
                {"client": client_filter, "platform": platform_filter, "confidence": conf_filter},
            )
            rows = cur.fetchall()

            # Devices missing from Ninja per client (secondary signal)
            cur.execute("""
                SELECT c.display_name, c.slug, COUNT(*)::int
                FROM operations.findings f
                JOIN operations.clients c ON c.id = f.client_id
                JOIN operations.finding_types ft ON ft.id = f.finding_type_id
                WHERE f.tenant_id = 1
                  AND ft.name = 'device_missing_from_source'
                  AND f.status IN ('open', 'acknowledged', 'investigating')
                GROUP BY c.display_name, c.slug
                ORDER BY COUNT(*) DESC, c.display_name
            """)
            missing_rows = cur.fetchall()

            # Available platforms for filter dropdown
            cur.execute("""
                SELECT DISTINCT f.finding_details->>'platform'
                FROM operations.findings f
                JOIN operations.finding_types ft ON ft.id = f.finding_type_id
                WHERE f.tenant_id = 1 AND ft.name = 'missing_required_platform'
                  AND f.status IN ('open', 'acknowledged', 'investigating')
                  AND (f.finding_details->>'platform') IS NOT NULL
                ORDER BY 1
            """)
            platforms = [r[0] for r in cur.fetchall()]

            # Client list for filter dropdown
            cur.execute("""
                SELECT DISTINCT c.display_name, c.slug
                FROM operations.findings f
                JOIN operations.clients c ON c.id = f.client_id
                JOIN operations.finding_types ft ON ft.id = f.finding_type_id
                WHERE f.tenant_id = 1 AND ft.name = 'missing_required_platform'
                  AND f.status IN ('open', 'acknowledged', 'investigating')
                ORDER BY c.display_name
            """)
            filter_clients = [{"name": r[0], "slug": r[1]} for r in cur.fetchall()]

    gap_rows = [
        {
            "client_name": r[0],
            "client_slug": r[1],
            "platform": r[2],
            "severity": r[3],
            "total": r[4],
            "confirmed": r[5],
            "probable": r[6],
            "oldest_at": r[7],
        }
        for r in rows
    ]
    missing_devices = [
        {"client_name": r[0], "client_slug": r[1], "count": r[2]} for r in missing_rows
    ]

    clients_affected = len({r["client_slug"] for r in gap_rows})
    total_gaps = sum(r["total"] for r in gap_rows)
    critical_count = sum(r["total"] for r in gap_rows if r["severity"] == "critical")

    if wants_csv(request):
        return csv_response(
            gap_rows,
            columns=[
                ("Client", "client_name"),
                ("Platform", "platform"),
                ("Severity", "severity"),
                ("Total", "total"),
                ("Confirmed", "confirmed"),
                ("Probable", "probable"),
                ("Oldest at", "oldest_at"),
            ],
            filename_stem="fleet_coverage_gaps",
        )

    return render(
        request,
        "coverage.html",
        {
            "admin_group": "integrations",
            "admin_tab": "coverage",
            "gap_rows": gap_rows,
            "missing_devices": missing_devices,
            "clients_affected": clients_affected,
            "total_gaps": total_gaps,
            "critical_count": critical_count,
            "platforms": platforms,
            "filter_clients": filter_clients,
            "client_filter": client_filter,
            "platform_filter": platform_filter,
            "conf_filter": conf_filter,
        },
    )


# ── Source ingest status page ─────────────────────────────────────────────────


@login_required
def sources_status(request: HttpRequest) -> HttpResponse:
    """Registry-driven source-instance health and row-based entity counts."""
    tenant_id = int(getattr(request, "tenant_id", 1))
    with transaction.atomic():  # noqa: SIM117 -- matches existing transaction/GUC pattern
        with connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = %s", (tenant_id,))
            cur.execute(
                """
                SELECT id, source_name, client_display_name, enabled, run_platform,
                       last_observed_at, current_record_count, active_record_count,
                       last_run_ok, last_run_ended_at, last_run_rows,
                       last_run_error, last_success_at, last_success_rows
                  FROM operations.v_source_instance_health
                 WHERE tenant_id = %s
                 ORDER BY source_name, client_display_name NULLS FIRST, id
                """,
                (tenant_id,),
            )
            health_rows = cur.fetchall()
            cur.execute(
                """
                SELECT source_instance_id, entity_type, entity_class,
                       current_count, active_count, withdrawn_count, last_seen_at
                  FROM operations.v_source_instance_entity_counts
                 WHERE tenant_id = %s
                 ORDER BY source_instance_id, entity_class, entity_type
                """,
                (tenant_id,),
            )
            counts_by_instance: dict = {}
            for row in cur.fetchall():
                counts_by_instance.setdefault(row[0], []).append(
                    {
                        "entity_type": row[1],
                        "entity_class": row[2],
                        "current_count": row[3],
                        "active_count": row[4],
                        "withdrawn_count": row[5],
                        "last_seen_at": row[6],
                    }
                )

            # Currently pending or processing (manual demand queue)
            cur.execute(
                """
                SELECT df, status, queued_at, started_at
                  FROM operations.source_run_queue
                 WHERE status IN ('pending', 'processing')
                """
            )
            active = {r[0]: r for r in cur.fetchall()}

            # Recent run history — every recorded source run
            cur.execute("""
                SELECT substring(kind FROM 8), ok, started_at, ended_at, rows, error
                FROM operations.run_log
                WHERE tenant_id = %s AND kind LIKE 'source.%%'
                ORDER BY started_at DESC LIMIT 30
            """, (tenant_id,))
            recent_runs = [
                {
                    "source": r[0],
                    "status": "done" if r[1] else "failed",
                    "started_at": r[2],
                    "completed_at": r[3],
                    "rows_seen": r[4],
                    "error": r[5] or None,
                }
                for r in cur.fetchall()
            ]

    now = timezone.now()
    sources = []
    for row in health_rows:
        (
            source_instance_id,
            source_name,
            client_display_name,
            enabled,
            run_platform,
            last_observed,
            current_record_count,
            active_record_count,
            last_run_ok,
            last_run_ended_at,
            last_run_rows,
            last_run_error,
            last_success,
            last_success_rows,
        ) = row
        act = active.get(run_platform)
        last_fail = last_run_ended_at if last_run_ok is False else None
        last_error = (last_run_error or None) if last_run_ok is False else None
        is_stale = last_success is None or (now - last_success).total_seconds() > 8 * 3600
        sources.append(
            {
                "id": source_instance_id,
                "name": source_name,
                "client_name": client_display_name,
                "enabled": enabled,
                "run_platform": run_platform,
                "is_processing": bool(act and act[1] == "processing"),
                "has_pending": bool(act and act[1] == "pending"),
                "last_success": last_success,
                "last_failure": last_fail,
                "last_rows": last_success_rows if last_success_rows is not None else last_run_rows,
                "last_error": last_error,
                "last_observed": last_observed,
                "current_record_count": current_record_count,
                "active_record_count": active_record_count,
                "entity_counts": counts_by_instance.get(source_instance_id, []),
                "is_stale": is_stale,
            }
        )

    stale_count = sum(1 for s in sources if s["is_stale"] and not s["is_processing"])
    if wants_csv(request):
        return csv_response(
            sources,
            columns=[
                ("Source", "name"),
                ("Processing", lambda r: "yes" if r["is_processing"] else "no"),
                ("Pending", lambda r: "yes" if r["has_pending"] else "no"),
                ("Stale", lambda r: "yes" if r["is_stale"] else "no"),
                ("Last success", "last_success"),
                ("Last failure", "last_failure"),
                ("Last rows", "last_rows"),
                ("Last error", "last_error"),
                ("Last observed", "last_observed"),
                ("Current source records", "current_record_count"),
                ("Active source records", "active_record_count"),
            ],
            filename_stem="sources_status",
        )
    return render(
        request,
        "sources.html",
        {
            "admin_group": "integrations",
            "admin_tab": "sources",
            "sources": sources,
            "recent_runs": recent_runs,
            "stale_count": stale_count,
        },
    )


# ── Client candidates (Track C.4 evidence panel) ─────────────────────────────


@login_required
def client_candidates_queue(request: HttpRequest) -> HttpResponse:
    """Every unattached source group that resolved neither by id-link nor by
    name lands here. The operator accepts, maps, excludes, or fixes.
    """
    status_filter = request.GET.get("status", "open")
    qs = ClientCandidate.objects.filter(tenant_id=1)
    if status_filter != "all":
        qs = qs.filter(status=status_filter)
    candidates = list(qs.order_by("-seen_count", "display_name"))

    source_names = {s.id: s.name for s in Source.objects.all()}
    rows = []
    for c in candidates:
        refs = c.source_refs or []
        by_source: dict[str, int] = {}
        latest_seen = None
        for r in refs:
            sid = r.get("source_id")
            name = source_names.get(sid, "?") if sid else "?"
            by_source[name] = by_source.get(name, 0) + 1
            seen = r.get("observed_at")
            if seen and (latest_seen is None or seen > latest_seen):
                latest_seen = seen
        rows.append(
            {
                "candidate": c,
                "sources": sorted(by_source),
                "source_count": len(by_source),
                "latest_seen": latest_seen,
            }
        )

    counts = {
        row["status"]: row["n"]
        for row in ClientCandidate.objects.filter(tenant_id=1)
        .values("status")
        .annotate(n=Count("id"))
    }

    if wants_csv(request):
        return csv_response(
            rows,
            columns=[
                ("Display name", lambda r: r["candidate"].display_name),
                ("Status", lambda r: r["candidate"].status),
                ("Seen count", lambda r: r["candidate"].seen_count),
                ("Source count", "source_count"),
                ("Sources", "sources"),
                ("Latest seen", "latest_seen"),
                ("Candidate ID", lambda r: str(r["candidate"].id)),
            ],
            filename_stem="client_candidates",
        )

    return render(
        request,
        "client_candidates_queue.html",
        {
            "admin_group": "review",
            "admin_tab": "clients",
            "rows": rows,
            "active_status": status_filter,
            "counts": counts,
            "status_choices": ClientCandidate.Status.choices,
        },
    )


@login_required
def client_candidate_detail(request: HttpRequest, candidate_id) -> HttpResponse:
    """Full evidence for one candidate: source records, sample devices,
    device-overlap signal, fuzzy suggestions."""
    from difflib import get_close_matches

    candidate = get_object_or_404(ClientCandidate, id=candidate_id, tenant_id=1)
    refs = candidate.source_refs or []

    source_names = {s.id: s.name for s in Source.objects.all()}
    external_ids = [r.get("external_id") for r in refs if r.get("external_id")]

    per_source = []
    device_overlap: dict[str, dict] = {}
    sample_devices: list[dict] = []

    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")

            for ref in refs:
                sid = ref.get("source_id")
                ext_id = ref.get("external_id")
                if not (sid and ext_id):
                    continue
                cur.execute(
                    """
                    SELECT MIN(effective_from), MAX(COALESCE(effective_to, effective_from)), COUNT(*)
                    FROM operations.entity_observation_history eo
                    JOIN operations.source_bindings sb
                         ON sb.id = eo.source_binding_id
                    JOIN operations.source_instances si
                         ON si.id = sb.source_instance_id
                    WHERE eo.tenant_id = 1
                      AND eo.entity_type = 'org'
                      AND eo.entity_key = %s
                      AND si.source_id = %s
                    """,
                    (ext_id, sid),
                )
                first_seen, last_seen, run_count = cur.fetchone()

                cur.execute(
                    """
                    SELECT MAX((material_data->>'device_count')::int)
                    FROM operations.entity_observation_history eo
                    JOIN operations.source_bindings sb
                         ON sb.id = eo.source_binding_id
                    JOIN operations.source_instances si
                         ON si.id = sb.source_instance_id
                    WHERE eo.tenant_id = 1
                      AND eo.entity_type = 'org'
                      AND eo.entity_key = %s
                      AND si.source_id = %s
                    """,
                    (ext_id, sid),
                )
                (device_count,) = cur.fetchone()

                per_source.append(
                    {
                        "source": source_names.get(sid, "?"),
                        "external_id": ext_id,
                        "external_name": ref.get("external_name") or "",
                        "first_seen": first_seen,
                        "last_seen": last_seen,
                        "run_count": run_count,
                        "device_count": device_count or 0,
                    }
                )

            # Sample devices seen inside these groups AND client overlap.
            if external_ids:
                cur.execute(
                    """
                    SELECT DISTINCT ON (eo.entity_key, eo.platform)
                        eo.platform,
                        eo.canonical_hostname AS hostname,
                        eo.device_id,
                        d.client_id,
                        c.display_name
                    FROM operations.v_entity_observation_admin_metadata eo
                    LEFT JOIN operations.devices d
                        ON d.id = eo.device_id AND d.deleted_at IS NULL
                    LEFT JOIN operations.clients c
                        ON c.id = d.client_id
                    WHERE eo.tenant_id = 1
                      AND eo.active = TRUE
                      AND eo.entity_type <> 'org'
                      AND eo.platform_group_id = ANY(%s)
                    ORDER BY eo.entity_key, eo.platform, eo.observed_at DESC
                    LIMIT 25
                    """,
                    (external_ids,),
                )
                for platform, hostname, device_id, cid, cname in cur.fetchall():
                    sample_devices.append(
                        {
                            "platform": platform,
                            "hostname": hostname or "—",
                            "resolved_client_id": cid,
                            "resolved_client_name": cname or "",
                        }
                    )
                    if cid and cname:
                        overlap = device_overlap.setdefault(
                            str(cid),
                            {
                                "client_id": str(cid),
                                "display_name": cname,
                                "device_count": 0,
                            },
                        )
                        overlap["device_count"] += 1

    # Fuzzy suggestions against known client display names + aliases.
    known_names: dict[str, tuple] = {}
    for c in Client.objects.filter(tenant_id=1, deleted_at__isnull=True):
        known_names[c.display_name] = ("client", c.id, c.display_name)
    for a in ClientNameAlias.objects.filter(tenant_id=1, enabled=True).select_related("client"):
        known_names[a.alias] = ("alias", a.client_id, a.client.display_name)
    fuzzy = []
    if candidate.display_name:
        matches = get_close_matches(
            candidate.display_name, list(known_names.keys()), n=5, cutoff=0.6
        )
        for m in matches:
            kind, cid, cname = known_names[m]
            fuzzy.append({"match": m, "kind": kind, "client_id": cid, "client_name": cname})

    all_clients = list(
        Client.objects.filter(tenant_id=1, deleted_at__isnull=True).order_by("display_name")
    )
    profiles = list(RequirementProfile.objects.filter(tenant_id=1).order_by("name"))
    default_profile = next((p for p in profiles if p.is_tenant_default), None)

    return render(
        request,
        "client_candidate_detail.html",
        {
            "admin_group": "review",
            "admin_tab": "clients",
            "candidate": candidate,
            "per_source": per_source,
            "sample_devices": sample_devices,
            "device_overlap": sorted(device_overlap.values(), key=lambda x: -x["device_count"]),
            "fuzzy": fuzzy,
            "all_clients": all_clients,
            "profiles": profiles,
            "default_profile": default_profile,
        },
    )


# ── Candidate actions (Track C.4) — all audited ─────────────────────────────


def _audit(request, action: str, entity_id, before, after) -> None:
    AuditLog.objects.create(
        tenant_id=1,
        actor=request.user if request.user.is_authenticated else None,
        actor_kind=AuditLog.ActorKind.USER,
        source=AuditLog.Source.UI,
        action=action,
        entity_type="client_candidate",
        entity_id=entity_id,
        before_state=before,
        after_state=after,
        ip_address=request.META.get("REMOTE_ADDR") or None,
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:2000],
    )


def _attach_group_to_client(
    cur,
    source_id: int,
    external_id: str,
    client_id,
) -> None:
    """Backfill org + device observations for this group to a client.

    Mirrors client_resolver._attach_group. The client_link INSERT that used to
    open this function is retired with migration 0123: setting client_id on the
    observations below is the attachment, and the link is derived from that
    evidence by sync_entity_source_links_from_observations() at the next
    collection boundary. The `external_name` and `reason` parameters went with
    it — both existed only to populate the link row.
    """
    cur.execute(
        """
        UPDATE operations.entity_observation_current eo
        SET client_id = %s
        FROM operations.v_entity_observation_admin_metadata observation,
             operations.source_bindings sb, operations.source_instances si
        WHERE eo.observation_id = observation.observation_id
          AND observation.source_binding_id = sb.id
          AND sb.source_instance_id = si.id
          AND si.source_id = %s
          AND observation.tenant_id = 1
          AND observation.entity_type = 'org'
          AND observation.entity_key = %s
          AND observation.client_id IS NULL
        """,
        (client_id, source_id, external_id),
    )
    cur.execute(
        """
        UPDATE operations.entity_observation_current eo
        SET client_id = %s
        FROM operations.v_entity_observation_admin_metadata observation,
             operations.source_bindings sb, operations.source_instances si
        WHERE eo.observation_id = observation.observation_id
          AND observation.source_binding_id = sb.id
          AND sb.source_instance_id = si.id
          AND si.source_id = %s
          AND observation.tenant_id = 1
          AND observation.entity_type <> 'org'
          AND observation.client_id IS NULL
          AND observation.platform_group_id = %s
        """,
        (client_id, source_id, external_id),
    )
    cur.execute(
        """
        DELETE FROM operations.unmatched_source_groups
        WHERE tenant_id = 1 AND source_id = %s AND external_id = %s
        """,
        (source_id, external_id),
    )

    # Auto-resolve client_unattached_group findings for every binding
    # of this source that pointed at this external_id. The resolver
    # keys condition_key on source_binding_id, so we enumerate bindings.
    import hashlib

    cur.execute(
        """
        SELECT sb.id FROM operations.source_bindings sb
        JOIN operations.source_instances si ON si.id = sb.source_instance_id
        WHERE si.source_id = %s AND si.tenant_id = 1
        """,
        (source_id,),
    )
    binding_ids = [row[0] for row in cur.fetchall()]
    for bid in binding_ids:
        raw = f"client_resolver:{bid}:{external_id}"
        ckey = hashlib.sha256(raw.encode()).hexdigest()[:64]
        cur.execute(
            """
            UPDATE operations.admin_findings af
            SET status = 'resolved', resolved_at = NOW()
            FROM operations.finding_types ft
            WHERE af.finding_type_id = ft.id
              AND ft.name = 'client_unattached_group'
              AND af.tenant_id = 1
              AND af.condition_key = %s
              AND af.status IN ('open', 'acknowledged')
            """,
            (ckey,),
        )


def _resolve_finding_for_group(cur, source_binding_id, external_id: str) -> None:
    """Close any client_unattached_group admin finding for a now-attached group."""
    import hashlib

    raw = f"client_resolver:{source_binding_id}:{external_id}"
    condition_key = hashlib.sha256(raw.encode()).hexdigest()[:64]
    cur.execute(
        """
        UPDATE operations.admin_findings af
        SET status = 'resolved', resolved_at = NOW()
        FROM operations.finding_types ft
        WHERE af.finding_type_id = ft.id
          AND ft.name = 'client_unattached_group'
          AND af.tenant_id = 1
          AND af.condition_key = %s
          AND af.status IN ('open', 'acknowledged')
        """,
        (condition_key,),
    )


@login_required
@require_POST
@transaction.atomic
def client_candidate_accept(request, candidate_id) -> HttpResponse:
    """Create a new client from the candidate, attach every contributing
    source group, mint an alias row, and instantiate the requirement
    profile as per-client coverage_requirements."""
    candidate = get_object_or_404(
        ClientCandidate,
        id=candidate_id,
        tenant_id=1,
        status="open",
    )
    display_name = (request.POST.get("display_name") or candidate.display_name or "").strip()
    if not display_name:
        messages.error(request, "Display name required.")
        return redirect("client_candidate_detail", candidate_id=candidate.id)
    profile_id = request.POST.get("profile_id") or None
    profile = None
    if profile_id:
        profile = get_object_or_404(RequirementProfile, id=profile_id, tenant_id=1)
    else:
        profile = RequirementProfile.objects.filter(
            tenant_id=1,
            is_tenant_default=True,
        ).first()

    base_slug = slugify(display_name)[:110] or "client"
    slug = base_slug
    suffix = 1
    while Client.objects.filter(tenant_id=1, slug=slug).exists():
        suffix += 1
        slug = f"{base_slug}-{suffix}"

    client = Client.objects.create(
        tenant_id=1,
        slug=slug,
        display_name=display_name,
        requirement_profile=profile,
        created_reason=f"candidate.accept:{candidate.id}",
    )

    ClientNameAlias.objects.update_or_create(
        tenant_id=1,
        normalized_name=candidate.normalized_name,
        defaults={
            "client": client,
            "alias": display_name,
            "tier": ClientNameAlias.Tier.MANUAL,
            "enabled": True,
            "created_by": request.user.get_username(),
            "created_reason": f"accept candidate {candidate.id}",
        },
    )

    with connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        for ref in candidate.source_refs or []:
            sid = ref.get("source_id")
            ext_id = ref.get("external_id")
            if not (sid and ext_id):
                continue
            _attach_group_to_client(cur, sid, ext_id, client.id)

    # Profile is source of truth per BLUEPRINT C.6 — assigning
    # client.requirement_profile above is sufficient. No per-client
    # CoverageRequirement instantiation.

    candidate.status = ClientCandidate.Status.ACCEPTED
    candidate.resolved_client = client
    candidate.resolved_at = timezone.now()
    candidate.resolved_by = request.user.get_username()
    candidate.resolved_reason = "accepted → new client"
    candidate.save()

    _audit(
        request,
        "client_candidate.accept",
        candidate.id,
        {"normalized_name": candidate.normalized_name, "status": "open"},
        {
            "status": "accepted",
            "client_id": str(client.id),
            "display_name": display_name,
            "profile_id": str(profile.id) if profile else None,
        },
    )
    messages.success(request, f"Accepted — created client “{display_name}”.")
    return redirect("client_candidates_queue")


@login_required
@require_POST
@transaction.atomic
def client_candidate_map(request, candidate_id) -> HttpResponse:
    """Map candidate's source groups to an existing client."""
    candidate = get_object_or_404(
        ClientCandidate,
        id=candidate_id,
        tenant_id=1,
        status="open",
    )
    target_id = request.POST.get("client_id")
    if not target_id:
        messages.error(request, "Choose a client to map into.")
        return redirect("client_candidate_detail", candidate_id=candidate.id)
    target = get_object_or_404(Client, id=target_id, tenant_id=1, deleted_at__isnull=True)

    ClientNameAlias.objects.update_or_create(
        tenant_id=1,
        normalized_name=candidate.normalized_name,
        defaults={
            "client": target,
            "alias": candidate.display_name or candidate.normalized_name,
            "tier": ClientNameAlias.Tier.MANUAL,
            "enabled": True,
            "created_by": request.user.get_username(),
            "created_reason": f"map candidate {candidate.id} → {target.slug}",
        },
    )

    with connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        for ref in candidate.source_refs or []:
            sid = ref.get("source_id")
            ext_id = ref.get("external_id")
            if not (sid and ext_id):
                continue
            _attach_group_to_client(cur, sid, ext_id, target.id)

    candidate.status = ClientCandidate.Status.MAPPED
    candidate.resolved_client = target
    candidate.resolved_at = timezone.now()
    candidate.resolved_by = request.user.get_username()
    candidate.resolved_reason = f"mapped → {target.display_name}"
    candidate.save()

    _audit(
        request,
        "client_candidate.map",
        candidate.id,
        {"normalized_name": candidate.normalized_name, "status": "open"},
        {"status": "mapped", "client_id": str(target.id)},
    )
    messages.success(request, f"Mapped candidate to “{target.display_name}”.")
    return redirect("client_candidates_queue")


@login_required
@require_POST
@transaction.atomic
def client_candidate_exclude(request, candidate_id) -> HttpResponse:
    """Add the candidate's normalized name to client_org_excludes."""
    candidate = get_object_or_404(
        ClientCandidate,
        id=candidate_id,
        tenant_id=1,
        status="open",
    )
    reason = (request.POST.get("reason") or "").strip() or "excluded from candidate view"
    ClientOrgExclude.objects.get_or_create(
        tenant_id=1,
        normalized_name=candidate.normalized_name,
        defaults={
            "reason": reason[:240],
            "created_by": request.user.get_username(),
            "enabled": True,
        },
    )
    candidate.status = ClientCandidate.Status.EXCLUDED
    candidate.resolved_at = timezone.now()
    candidate.resolved_by = request.user.get_username()
    candidate.resolved_reason = reason[:240]
    candidate.save()

    _audit(
        request,
        "client_candidate.exclude",
        candidate.id,
        {"normalized_name": candidate.normalized_name, "status": "open"},
        {"status": "excluded", "reason": reason},
    )
    messages.success(request, "Candidate excluded.")
    return redirect("client_candidates_queue")


@login_required
@require_POST
def client_candidate_fix(request, candidate_id) -> HttpResponse:
    """Record an operator note — candidate stays open and re-resolves
    when the source is fixed."""
    candidate = get_object_or_404(
        ClientCandidate,
        id=candidate_id,
        tenant_id=1,
        status="open",
    )
    note = (request.POST.get("note") or "").strip()
    if not note:
        messages.error(request, "A note is required for fix-at-source.")
        return redirect("client_candidate_detail", candidate_id=candidate.id)
    _audit(
        request,
        "client_candidate.fix_at_source",
        candidate.id,
        {"normalized_name": candidate.normalized_name, "status": "open"},
        {"status": "open", "note": note},
    )
    messages.success(request, "Note recorded — candidate remains open.")
    return redirect("client_candidate_detail", candidate_id=candidate.id)


# ── Software findings review (Track 3.3) ────────────────────────────────


@login_required
def software_decisions_queue(request: HttpRequest) -> HttpResponse:
    """Review queue: software with open findings that need a decision.

    Grouped by canonical_name; each row shows category, fleet-wide
    device count, and (if a decision exists) the current disposition.
    Actions POST to `/software/decisions/<id>/decide` — global,
    per-client, or per-device scope.
    """
    category_filter = request.GET.get("category", "")
    q_filter = (request.GET.get("q") or "").strip().lower()
    decision_filter = (request.GET.get("decision") or "").strip().lower()
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                """
                SELECT
                    f.finding_details->>'canonical_name' AS canonical,
                    COALESCE(MAX(f.finding_details->>'publisher'), '') AS publisher,
                    f.finding_details->>'category' AS category,
                    MIN(sc.categories::text) AS catalog_categories,
                    -- How many devices run this title. subject_id is the
                    -- product or release now, so counting it would report 1
                    -- per title -- and this column drives the queue's ordering.
                    --
                    -- Counted from installations rather than from the exposure
                    -- view: this queue is where whitelist_suggestion is
                    -- decided, and that type deliberately does not fan out to
                    -- devices (migration 084). Installations are also what this
                    -- number has always meant -- "how many machines run this" --
                    -- and it stays correct for every type on the queue.
                    COUNT(DISTINCT sic.device_id) AS device_count,
                    MAX(f.last_seen_at) AS latest
                FROM operations.findings f
                JOIN operations.finding_types ft
                  ON ft.id = f.finding_type_id
                LEFT JOIN operations.software_installations_current sic
                  ON sic.tenant_id = f.tenant_id
                 AND sic.canonical_name = f.finding_details->>'canonical_name'
                 AND sic.stale_since IS NULL
                 AND sic.deleted_at IS NULL
                LEFT JOIN operations.software_catalog sc
                  ON LOWER(sc.canonical_name) = LOWER(f.finding_details->>'canonical_name')
                 AND (sc.tenant_id IS NULL OR sc.tenant_id = f.tenant_id)
                WHERE f.tenant_id = 1
                  AND f.status IN ('open', 'acknowledged')
                  AND ft.source_module = 'platform.software_findings'
                  AND f.finding_details->>'canonical_name' IS NOT NULL
                GROUP BY 1, 3
                ORDER BY device_count DESC, canonical
                LIMIT 500
                """,
            )
            rows = cur.fetchall()

    # Attach existing decision (global scope) to each row — either a
    # title-scope decision on the canonical, or a publisher-scope
    # decision on the observed publisher.
    canonical_names = [r[0] for r in rows if r[0]]
    publisher_names = list({r[1] for r in rows if r[1]})
    title_dec_map = {
        d.canonical_name.lower(): d
        for d in SoftwareDecision.objects.filter(
            tenant_id=1, canonical_name__in=canonical_names,
            client__isnull=True, device__isnull=True,
        ).exclude(canonical_name="")
    }
    pub_dec_map = {
        d.publisher.lower(): d
        for d in SoftwareDecision.objects.filter(
            tenant_id=1, publisher__in=publisher_names,
            client__isnull=True, device__isnull=True,
        ).exclude(publisher="")
    }
    display_rows = []
    for canonical, publisher, category, catalog_cats, device_count, latest in rows:
        title_dec = title_dec_map.get(canonical.lower()) if canonical else None
        pub_dec = pub_dec_map.get(publisher.lower()) if publisher else None
        display_rows.append(
            {
                "canonical": canonical,
                "publisher": publisher or "",
                "category": category or (catalog_cats or ""),
                "device_count": device_count,
                "latest": latest,
                "global_decision": title_dec.decision if title_dec else "",
                "publisher_decision": pub_dec.decision if pub_dec else "",
            }
        )

    if category_filter:
        display_rows = [r for r in display_rows if category_filter in (r["category"] or "")]
    if q_filter:
        display_rows = [
            r for r in display_rows
            if q_filter in (r["canonical"] or "").lower()
            or q_filter in (r["publisher"] or "").lower()
        ]
    if decision_filter == "pending":
        display_rows = [r for r in display_rows if not r["global_decision"] and not r["publisher_decision"]]
    elif decision_filter in ("approve", "reject", "investigate", "approve_publisher"):
        display_rows = [
            r for r in display_rows
            if r["global_decision"] == decision_filter or r["publisher_decision"] == decision_filter
        ]

    categories_seen = sorted({r["category"] for r in display_rows if r["category"]})

    if wants_csv(request):
        return csv_response(
            display_rows,
            columns=[
                ("Product", "canonical"),
                ("Publisher", "publisher"),
                ("Category", "category"),
                ("Device count", "device_count"),
                ("Latest seen", "latest"),
                ("Product decision", "global_decision"),
                ("Publisher decision", "publisher_decision"),
            ],
            filename_stem="software_decisions",
        )

    return render(
        request,
        "software_decisions.html",
        {
            "admin_group": "review",
            "admin_tab": "software",
            "rows": display_rows,
            "categories": categories_seen,
            "active_category": category_filter,
            "active_q": q_filter,
            "active_decision": decision_filter,
            "decision_choices": SoftwareDecision.Decision.choices,
            "software_tab": "decisions",
        },
    )


@login_required
def software_decision_log(request: HttpRequest) -> HttpResponse:
    """Chronological log of every SoftwareDecision — the complement to
    the pending queue. Answers "what have I decided recently?".
    Filters: scope, decision, publisher / product substring, date."""
    scope_filter = (request.GET.get("scope") or "").strip().lower()
    decision_filter = (request.GET.get("decision") or "").strip().lower()
    q_filter = (request.GET.get("q") or "").strip()

    qs = SoftwareDecision.objects.filter(tenant_id=1).select_related(
        "client", "device", "decided_by"
    )
    if scope_filter == "global":
        qs = qs.filter(client__isnull=True, device__isnull=True)
    elif scope_filter == "client":
        qs = qs.filter(client__isnull=False, device__isnull=True)
    elif scope_filter == "device":
        qs = qs.filter(device__isnull=False)
    elif scope_filter == "publisher":
        qs = qs.exclude(publisher="")
    elif scope_filter == "product":
        qs = qs.exclude(canonical_name="")
    if decision_filter in ("approve", "approve_publisher", "reject", "investigate"):
        qs = qs.filter(decision=decision_filter)
    if q_filter:
        qs = qs.filter(
            Q(canonical_name__icontains=q_filter)
            | Q(publisher__icontains=q_filter)
            | Q(reason__icontains=q_filter)
        )
    qs = qs.order_by("-decided_at", "-id")[:500]

    rows = [
        {
            "id": d.id,
            "decision": d.decision,
            "canonical_name": d.canonical_name,
            "publisher": d.publisher,
            "scope_label": (
                "device" if d.device_id
                else "client" if d.client_id
                else "global"
            ),
            "target_label": (
                d.canonical_name
                or (f"publisher: {d.publisher}" if d.publisher else "?")
            ),
            "client": d.client.display_name if d.client else None,
            "device_id": d.device_id,
            "decided_by": d.decided_by.username if d.decided_by else None,
            "decided_at": d.decided_at,
            "reason": (d.reason or "")[:200],
        }
        for d in qs
    ]

    if wants_csv(request):
        return csv_response(
            rows,
            columns=[
                ("Decided at", "decided_at"),
                ("Decision", "decision"),
                ("Product", "canonical_name"),
                ("Publisher", "publisher"),
                ("Scope", "scope_label"),
                ("Client", "client"),
                ("Decided by", "decided_by"),
                ("Reason", "reason"),
            ],
            filename_stem="software_decision_log",
        )

    return render(
        request,
        "software_decision_log.html",
        {
            "rows": rows,
            "active_scope": scope_filter,
            "active_decision": decision_filter,
            "active_q": q_filter,
            "software_tab": "decisions",
        },
    )


def _refresh_software_risk_matview() -> None:
    """Best-effort REFRESH MATERIALIZED VIEW on ``v_software_safety``.
    Called after any operator decision write so the software UI shows
    the updated band immediately. Never raises to the caller — the
    write itself is what matters; the refresh is a courtesy."""
    try:
        with connection.cursor() as cur:
            cur.execute("REFRESH MATERIALIZED VIEW operations.v_software_safety")
    except Exception:
        pass


@login_required
@require_POST
@transaction.atomic
def software_decision_bulk(request: HttpRequest) -> HttpResponse:
    """Apply a single decision to a set of canonical names or publishers.

    Form fields:
      * canonical_name — repeated (from checkbox list); optional
      * publisher      — repeated; optional
      * decision       — one of SoftwareDecision.Decision.values
      * scope          — must be ``global``. Narrower scopes are rejected
                          rather than silently written as global; use
                          ``software_decision_create`` for those.
      * next           — return URL
    """
    decision = (request.POST.get("decision") or "").strip()
    if decision not in dict(SoftwareDecision.Decision.choices):
        messages.error(request, "Pick a decision before applying.")
        return redirect(_safe_next(request, "software_decisions_queue"))

    scope = (request.POST.get("scope") or "global").strip()
    if scope != "global":
        messages.error(
            request,
            f"Bulk apply only writes global decisions; got scope '{scope}'. "
            "Use the per-row action for a client or device decision.",
        )
        return redirect(_safe_next(request, "software_decisions_queue"))

    canonical_names = [n for n in request.POST.getlist("canonical_name") if n.strip()]
    publishers      = [p for p in request.POST.getlist("publisher")      if p.strip()]
    if not canonical_names and not publishers:
        messages.error(request, "Select at least one product or publisher.")
        return redirect(_safe_next(request, "software_decisions_queue"))

    created, updated = 0, 0
    for name in canonical_names:
        obj, was_created = SoftwareDecision.objects.update_or_create(
            tenant_id=1, canonical_name=name.strip(), publisher="",
            client=None, device=None,
            defaults={
                "decision": decision, "reason": "",
                "decided_by": request.user, "decided_at": timezone.now(),
            },
        )
        _audit(request, "software_decision.bulk_set", obj.id, {},
               {"canonical_name": name.strip(), "scope": "global", "decision": decision})
        created += int(was_created)
        updated += int(not was_created)
    for pub in publishers:
        obj, was_created = SoftwareDecision.objects.update_or_create(
            tenant_id=1, canonical_name="", publisher=pub.strip(),
            client=None, device=None,
            defaults={
                "decision": decision, "reason": "",
                "decided_by": request.user, "decided_at": timezone.now(),
            },
        )
        _audit(request, "software_decision.bulk_set", obj.id, {},
               {"publisher": pub.strip(), "scope": "global", "decision": decision})
        created += int(was_created)
        updated += int(not was_created)
    messages.success(
        request,
        f"{decision}: {created} new, {updated} updated across "
        f"{len(canonical_names)} product(s) + {len(publishers)} publisher(s).",
    )
    _refresh_software_risk_matview()
    return redirect(_safe_next(request, "software_decisions_queue"))


def _safe_next(request: HttpRequest, fallback_url_name: str) -> str:
    """Return the operator-supplied ``next`` if it's a relative URL,
    otherwise reverse ``fallback_url_name``."""
    nxt = request.POST.get("next") or ""
    if nxt.startswith("/") and not nxt.startswith("//"):
        return nxt
    return reverse(fallback_url_name)


def _decision_scope_targets(install_rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Distinct client/device choices for one title or publisher's current installs."""
    clients: dict[str, dict] = {}
    devices: dict[str, dict] = {}
    for row in install_rows:
        client_slug = row.get("client_slug") or ""
        if client_slug:
            clients.setdefault(
                client_slug,
                {"slug": client_slug, "name": row.get("client_name") or client_slug},
            )
        device_id = str(row.get("device_id") or "")
        if device_id:
            devices.setdefault(
                device_id,
                {
                    "id": device_id,
                    "hostname": row.get("hostname") or device_id,
                    "client_name": row.get("client_name") or "",
                },
            )
    return (
        sorted(clients.values(), key=lambda row: (row["name"].lower(), row["slug"])),
        sorted(devices.values(), key=lambda row: (row["client_name"].lower(), row["hostname"].lower())),
    )


@login_required
@require_POST
@transaction.atomic
def software_decision_create(request: HttpRequest) -> HttpResponse:
    """Create or update a SoftwareDecision at the requested scope
    (global / per-client / per-device). Match key is either a
    canonical_name (title-scope) or a publisher (publisher-scope, applies
    to every title from that publisher). Audited."""
    canonical_name = (request.POST.get("canonical_name") or "").strip()
    publisher = (request.POST.get("publisher") or "").strip()
    decision = (request.POST.get("decision") or "").strip()
    scope = request.POST.get("scope") or "global"
    client_slug = request.POST.get("client_slug") or ""
    device_id_str = request.POST.get("device_id") or ""
    reason = (request.POST.get("reason") or "").strip()

    if decision not in dict(SoftwareDecision.Decision.choices):
        messages.error(request, "A valid decision is required.")
        return redirect("software_decisions_queue")
    if bool(canonical_name) == bool(publisher):
        messages.error(
            request, "Provide exactly one of canonical_name or publisher."
        )
        return redirect("software_decisions_queue")

    if scope not in {"global", "client", "device"}:
        messages.error(request, "Choose global, client, or device scope.")
        return redirect(_safe_next(request, "software_decisions_queue"))

    client = None
    device = None
    if scope == "client":
        if not client_slug:
            messages.error(request, "Choose a client for a client-scoped decision.")
            return redirect(_safe_next(request, "software_decisions_queue"))
        client = get_object_or_404(Client, slug=client_slug, tenant_id=1)
    elif scope == "device":
        if not device_id_str:
            messages.error(request, "Choose a device for a device-scoped decision.")
            return redirect(_safe_next(request, "software_decisions_queue"))
        device = get_object_or_404(Device, id=device_id_str, tenant_id=1)
        client = device.client
    # scope == "global": both remain None.

    if scope != "global":
        target_column, target_value = (
            ("client_id", client.id) if scope == "client" else ("device_id", device.id)
        )
        match_column, match_value = (
            ("canonical_name", canonical_name) if canonical_name else ("publisher", publisher)
        )
        with connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                f"""
                SELECT EXISTS (
                    SELECT 1
                      FROM operations.software_installations_current
                     WHERE tenant_id = 1 AND deleted_at IS NULL AND stale_since IS NULL
                       AND {target_column} = %s
                       AND LOWER({match_column}) = LOWER(%s)
                )
                """,
                (target_value, match_value),
            )
            if not cur.fetchone()[0]:
                messages.error(
                    request,
                    "The selected scope has no current installation of this software.",
                )
                return redirect(_safe_next(request, "software_decisions_queue"))

    obj, created = SoftwareDecision.objects.update_or_create(
        tenant_id=1,
        canonical_name=canonical_name,
        publisher=publisher,
        client=client,
        device=device,
        defaults={
            "decision": decision,
            "reason": reason,
            "decided_by": request.user,
            "decided_at": timezone.now(),
        },
    )
    match_key = canonical_name or f"publisher:{publisher}"
    _audit(
        request,
        "software_decision.set",
        obj.id,
        {},
        {
            "canonical_name": canonical_name,
            "publisher": publisher,
            "scope": scope,
            "client_id": str(client.id) if client else None,
            "device_id": str(device.id) if device else None,
            "decision": decision,
        },
    )
    messages.success(
        request,
        f"{decision} recorded for {match_key} ({scope})."
        + (" Created." if created else " Updated."),
    )
    _refresh_software_risk_matview()
    next_url = request.POST.get("next") or ""
    # Only follow relative URLs to avoid open-redirects.
    if next_url.startswith("/") and not next_url.startswith("//"):
        return redirect(next_url)
    return redirect("software_decisions_queue")


# ── Device merge helper (called by device_merge view) ───────────────────


def _merge_devices(cur, survivor_id, loser_id: str, reason: str) -> dict:
    """Cascade merge: re-point every reference from loser → survivor,
    tombstone loser. Returns a summary dict of what was moved."""
    counts = {}
    # 1. Source links are no longer repointed here.
    #
    #    This step used to UPDATE and DELETE `operations.device_links`, which
    #    migration 0121 retired. Writing `entity_source_links` in its place was
    #    considered and rejected: that table is derived state, maintained by
    #    sync_entity_source_links_from_observations(), which also closes and
    #    reopens the matching `entity_source_link_history` interval. A bare
    #    entity_id UPDATE here would repoint the current row and leave the open
    #    history interval attributing the link to the tombstoned device, losing
    #    the record of when and why attachment moved. Reproducing that SCD-2
    #    handling here would be a second copy of the logic, and calling the sync
    #    function directly would mean granting the web app EXECUTE on a
    #    SECURITY DEFINER function owned by a superuser.
    #
    #    Moving the observations in step 2 is the authoritative action: the
    #    links are derived from exactly that evidence, so the next sync
    #    repoints them with correct history. This is the ADR-0012 rule the whole
    #    retirement enforces — a producer moves evidence, derived state follows.
    counts["source_links_converge_on_next_sync"] = True

    # 2. entity_observations
    cur.execute(
        """
        UPDATE operations.entity_observation_current observation
           SET device_id = %s
          FROM operations.v_entity_observation_admin_metadata metadata
         WHERE observation.observation_id = metadata.observation_id
           AND metadata.tenant_id = 1
           AND metadata.device_id = %s
        """,
        (survivor_id, loser_id),
    )
    counts["observations_moved"] = cur.rowcount

    # 3. findings — subject_id (only device-subject findings)
    cur.execute(
        """
        UPDATE operations.findings SET subject_id=%s
        WHERE tenant_id=1 AND subject_id=%s AND subject_type='device'
        """,
        (survivor_id, loser_id),
    )
    counts["findings_moved"] = cur.rowcount

    # 4. software_installations_current (composite PK includes device_id)
    cur.execute(
        """
        DELETE FROM operations.software_installations_current
        WHERE tenant_id=1 AND device_id=%s
        """,
        (loser_id,),
    )
    counts["software_rows_deleted"] = cur.rowcount

    # 5. Tombstone loser
    cur.execute(
        """
        UPDATE operations.devices
        SET deleted_at=NOW(), deleted_reason=%s
        WHERE tenant_id=1 AND id=%s
        """,
        (reason[:120], loser_id),
    )
    return counts


# ── Device merge (generic entity operation) ─────────────────────────────────


@login_required
def device_merge(
    request: HttpRequest, org_slug: str, device_id: str, target_id: str
) -> HttpResponse:
    """Merge two Devices in the same client. Generic device operation —
    not tied to any Finding type. Invokable from anywhere with two
    Device IDs (identity_conflict Finding evidence, admin manual link,
    future device-detail action, etc.).

    GET renders a side-by-side confirmation with a radio-button
    survivor selector (default suggests the Ninja-linked device, else
    the older by created_at). POST performs the merge and redirects to
    the survivor's detail page.
    """
    device_a = get_object_or_404(
        Device.objects.select_related("client"),
        tenant_id=1,
        id=device_id,
        client__slug=org_slug,
        deleted_at__isnull=True,
    )
    device_b = get_object_or_404(
        Device.objects.select_related("client"),
        tenant_id=1,
        id=target_id,
        deleted_at__isnull=True,
    )
    if device_a.client_id != device_b.client_id:
        messages.error(
            request,
            "Cross-client merges are not permitted — the two devices "
            "belong to different clients.",
        )
        return redirect("device_detail", org_slug=org_slug, device_id=device_id)
    if device_a.id == device_b.id:
        messages.error(request, "Cannot merge a device with itself.")
        return redirect("device_detail", org_slug=org_slug, device_id=device_id)

    if request.method == "POST":
        survivor_id = request.POST.get("survivor") or ""
        if survivor_id not in (str(device_a.id), str(device_b.id)):
            messages.error(request, "Pick a survivor.")
            return redirect(
                "device_merge",
                org_slug=org_slug,
                device_id=device_id,
                target_id=target_id,
            )
        if survivor_id == str(device_a.id):
            survivor, loser = device_a, device_b
        else:
            survivor, loser = device_b, device_a
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            counts = _merge_devices(cur, survivor.id, loser.id, "operator.merged")
        _audit(
            request,
            "device.merge",
            survivor.id,
            {"survivor_id": str(survivor.id), "loser_id": str(loser.id)},
            {"counts": counts},
        )
        messages.success(
            request,
            f"Merged {loser.canonical_hostname} into "
            f"{survivor.canonical_hostname}. "
            f"Moved {counts.get('observations_moved', 0)} observations and "
            f"{counts.get('findings_moved', 0)} findings. "
            "Source links follow the observations and update on the next "
            "collection cycle.",
        )
        return redirect(
            "device_detail",
            org_slug=survivor.client.slug,
            device_id=survivor.id,
        )

    # GET — default-survivor rule mirrors legacy identity_candidate_confirm:
    # Ninja-linked device wins, else older by created_at.
    with connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """
            SELECT dl.device_id FROM operations.v_device_source_link dl
            JOIN operations.sources s ON s.id = dl.source_id AND s.name = 'Ninja'
            WHERE dl.tenant_id = 1 AND dl.device_id IN (%s, %s)
            """,
            (device_a.id, device_b.id),
        )
        ninja_owners = {row[0] for row in cur.fetchall()}
    if device_a.id in ninja_owners and device_b.id not in ninja_owners:
        default_survivor = device_a
    elif device_b.id in ninja_owners and device_a.id not in ninja_owners:
        default_survivor = device_b
    else:
        default_survivor = device_a if device_a.created_at <= device_b.created_at else device_b
    return render(
        request,
        "device_merge.html",
        {
            "device_a": device_a,
            "device_b": device_b,
            "devices": [device_a, device_b],
            "default_survivor": default_survivor,
        },
    )


# ── Requirement profiles (Track C.6 admin knob) ─────────────────────────────


@login_required
def operations_admin_overview(request: HttpRequest) -> HttpResponse:
    """Operations Admin landing — one hub with every admin/operator
    surface grouped by workflow area. Counts are cheap; each tile is
    also a link."""
    now = timezone.now()

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """
            SELECT platform, last_observed_at, last_run_ok
            FROM operations.source_health_current
            WHERE tenant_id = 1
            """
        )
        source_health = cur.fetchall()
        cur.execute(
            """
            SELECT count(*)::integer, COALESCE(sum(conflict_count), 0)::integer
              FROM operations.v_entity_admin_summary
             WHERE tenant_id = 1 AND deleted_at IS NULL
            """
        )
        generic_entity_count, generic_conflict_count = cur.fetchone()
        cur.execute(
            """
            SELECT count(*) FILTER (WHERE status = 'pending')::integer,
                   count(*) FILTER (WHERE status = 'observed_only')::integer
              FROM operations.v_entity_candidate_admin
             WHERE tenant_id = 1
            """
        )
        generic_pending_candidates, generic_observed_candidates = cur.fetchone()
        cur.execute(
            "SELECT count(*)::integer FROM operations.v_source_instance_health WHERE tenant_id = 1"
        )
        generic_source_instance_count = cur.fetchone()[0]
    stale_sources = sum(
        observed_at is None or not run_ok or (now - observed_at).total_seconds() > 8 * 3600
        for _platform, observed_at, run_ok in source_health
    )

    # Intel connector status (optional — may not be present pre-migration).
    intel_ok = intel_failed = intel_never = 0
    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                "SELECT last_status FROM operations.intel_ingest_status"
            )
            for (status,) in cur.fetchall():
                if status == "ok":
                    intel_ok += 1
                elif status:
                    intel_failed += 1
                else:
                    intel_never += 1
        # Every connector we know about, minus what's recorded.
        intel_never += max(0, 9 - (intel_ok + intel_failed + intel_never))
    except Exception:
        intel_ok = intel_failed = intel_never = 0

    open_findings = Finding.objects.filter(
        tenant_id=1, status__in=_FINDING_ACTIVE_STATUSES
    ).count()
    software_findings_open = Finding.objects.filter(
        tenant_id=1, status__in=_FINDING_ACTIVE_STATUSES,
        finding_type__category__name="software",
    ).count()
    patching_findings_open = Finding.objects.filter(
        tenant_id=1, status__in=_FINDING_ACTIVE_STATUSES,
        finding_type__category__name="patching",
    ).count()
    software_decision_count = SoftwareDecision.objects.filter(tenant_id=1).count()
    classifier_rule_count = 0
    try:
        from .models import SoftwareClassifierRule
        classifier_rule_count = SoftwareClassifierRule.objects.filter(enabled=True).count()
    except Exception:
        classifier_rule_count = 0

    return render(
        request,
        "operations_admin_overview.html",
        {
            "admin_group": "overview",
            # Review counts
            "nav_pending_client_candidates": ClientCandidate.objects.filter(
                tenant_id=1, status="open"
            ).count(),
            "nav_pending_entity_candidates": generic_pending_candidates,
            "nav_pending_merges": MergeCandidate.objects.filter(
                tenant_id=1, status="open"
            ).count(),
            "nav_pending_software_decisions": Finding.objects.filter(
                tenant_id=1,
                status__in=_FINDING_ACTIVE_STATUSES,
                finding_type__category__name="software",
            ).count(),
            "open_findings": open_findings,
            "software_findings_open": software_findings_open,
            "patching_findings_open": patching_findings_open,
            # Software surface
            "software_decision_count": software_decision_count,
            "classifier_rule_count": classifier_rule_count,
            # Config counts
            "profile_count": RequirementProfile.objects.filter(tenant_id=1).count(),
            "profiles_without_clients": RequirementProfile.objects.filter(
                tenant_id=1, clients__isnull=True
            ).count(),
            "alert_rule_count": NotificationRule.objects.filter(tenant_id=1, enabled=True).count(),
            "suppression_count": SuppressionRule.objects.filter(tenant_id=1).count(),
            # Integrations
            "source_count": generic_source_instance_count,
            "stale_sources": stale_sources,
            "generic_entity_count": generic_entity_count,
            "generic_conflict_count": generic_conflict_count,
            "generic_observed_candidates": generic_observed_candidates,
            "admin_finding_count": AdminFinding.objects.filter(
                tenant_id=1, status__in=("open", "acknowledged")
            ).count(),
            "intel_ok": intel_ok,
            "intel_failed": intel_failed,
            "intel_never": intel_never,
        },
    )


@login_required
def requirement_profiles_list(request: HttpRequest) -> HttpResponse:
    profiles = list(
        RequirementProfile.objects.filter(tenant_id=1)
        .prefetch_related("items")
        .order_by("-is_tenant_default", "name")
    )
    rows = []
    for p in profiles:
        client_count = Client.objects.filter(
            tenant_id=1,
            requirement_profile=p,
            deleted_at__isnull=True,
        ).count()
        rows.append(
            {
                "profile": p,
                "items": list(p.items.all().order_by("device_scope", "entity_type", "platform")),
                "client_count": client_count,
            }
        )
    if wants_csv(request):
        return csv_response(
            rows,
            columns=[
                ("Name", lambda r: r["profile"].name),
                ("Is tenant default", lambda r: "yes" if r["profile"].is_tenant_default else "no"),
                ("Client count", "client_count"),
                ("Item count", lambda r: len(r["items"])),
                (
                    "Items",
                    lambda r: "; ".join(
                        f"{i.platform or ''}:{i.entity_type or ''}:{i.device_scope or ''}"
                        for i in r["items"]
                    ),
                ),
            ],
            filename_stem="requirement_profiles",
        )
    return render(
        request,
        "requirement_profiles.html",
        {
            "admin_group": "config",
            "admin_tab": "requirements",
            "rows": rows,
        },
    )


@login_required
@require_POST
@transaction.atomic
def client_profile_assign(request: HttpRequest, org_slug: str) -> HttpResponse:
    client = _get_client_by_slug(org_slug)
    profile_id = request.POST.get("profile_id") or ""
    prev_profile = client.requirement_profile_id
    if profile_id == "":
        client.requirement_profile = None
    else:
        profile = get_object_or_404(RequirementProfile, id=profile_id, tenant_id=1)
        client.requirement_profile = profile
    client.save(update_fields=["requirement_profile"])
    _audit(
        request,
        "client.requirement_profile.assign",
        client.id,
        {"requirement_profile_id": str(prev_profile) if prev_profile else None},
        {
            "requirement_profile_id": str(client.requirement_profile_id)
            if client.requirement_profile_id
            else None
        },
    )
    messages.success(
        request,
        f"Requirement profile for {client.display_name} set to "
        f"{client.requirement_profile.name if client.requirement_profile else '— global fallback —'}.",
    )
    return redirect("org_index", org_slug=client.slug)


def _client_service_requirement_rows(client: Client) -> list[dict]:
    """Return profile/global baseline services plus sparse client overrides."""
    profile_items = list(
        client.requirement_profile.items.select_related("agent").all()
        if client.requirement_profile_id
        else []
    )
    global_rows = list(
        CoverageRequirement.objects.filter(
            tenant_id=1, client__isnull=True, enabled=True
        ).select_related("agent")
        if not client.requirement_profile_id
        else []
    )
    overrides = {
        (row.agent_id, row.device_scope): row
        for row in CoverageRequirement.objects.filter(tenant_id=1, client=client).select_related(
            "agent"
        )
    }
    candidates: dict[tuple, dict] = {}
    for row in [*profile_items, *global_rows]:
        if row.agent_id is None:
            continue
        candidates[(row.agent_id, row.device_scope)] = {
            "agent": row.agent,
            "scope": row.device_scope,
            "baseline_required": True,
        }
    # Make every supported service independently configurable, even when it
    # is not part of the inherited baseline.
    for agent in Agent.objects.all().order_by("name"):
        candidates.setdefault(
            (agent.id, "all"),
            {"agent": agent, "scope": "all", "baseline_required": False},
        )
    for key, override in overrides.items():
        if key not in candidates and override.agent_id is not None:
            candidates[key] = {
                "agent": override.agent,
                "scope": override.device_scope,
                "baseline_required": False,
            }
    rows = []
    for key, item in candidates.items():
        override = overrides.get(key)
        if override is None:
            mode = "inherited"
            required = item["baseline_required"]
        else:
            mode = "required" if override.enabled else "not_required"
            required = override.enabled
        rows.append({**item, "mode": mode, "required": required})
    return sorted(rows, key=lambda row: (row["agent"].name.lower(), row["scope"]))


@login_required
@transaction.atomic
def client_requirements_config(request: HttpRequest, org_slug: str) -> HttpResponse:
    """Configure an inherited service baseline and per-client exceptions."""
    client = get_object_or_404(
        Client.objects.select_related("requirement_profile"),
        tenant_id=1,
        slug=org_slug,
        deleted_at__isnull=True,
    )
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "profile":
            profile_id = request.POST.get("profile_id") or ""
            before = client.requirement_profile_id
            client.requirement_profile = (
                get_object_or_404(RequirementProfile, id=profile_id, tenant_id=1)
                if profile_id
                else None
            )
            client.save(update_fields=["requirement_profile"])
            _audit(
                request,
                "client.requirement_profile.assign",
                client.id,
                {"requirement_profile_id": str(before) if before else None},
                {
                    "requirement_profile_id": str(client.requirement_profile_id)
                    if client.requirement_profile_id
                    else None
                },
            )
            messages.success(request, "Inherited service baseline updated.")
        elif action == "override":
            agent = get_object_or_404(Agent, id=request.POST.get("agent_id"))
            scope = request.POST.get("device_scope") or "all"
            mode = request.POST.get("mode")
            existing = CoverageRequirement.objects.filter(
                tenant_id=1, client=client, agent=agent, device_scope=scope
            ).first()
            before = {
                "mode": "required"
                if existing and existing.enabled
                else "not_required"
                if existing
                else "inherited"
            }
            if mode == "inherited":
                if existing:
                    existing.delete()
            elif mode in {"required", "not_required"}:
                defaults = {
                    "entity_type": agent.entity_type,
                    "platform": agent.name,
                    "enabled": mode == "required",
                }
                if existing:
                    for field, value in defaults.items():
                        setattr(existing, field, value)
                    existing.save(update_fields=[*defaults])
                else:
                    CoverageRequirement.objects.create(
                        tenant_id=1,
                        client=client,
                        agent=agent,
                        device_scope=scope,
                        **defaults,
                    )
            else:
                messages.error(request, "Choose Required, Not required, or Inherit.")
                return redirect("client_requirements_config", org_slug=client.slug)
            _audit(
                request,
                "client.coverage_requirement.override",
                client.id,
                {"agent": agent.name, "scope": scope, **before},
                {"agent": agent.name, "scope": scope, "mode": mode},
            )
            messages.success(request, f"{agent.name} requirement updated.")
        return redirect("client_requirements_config", org_slug=client.slug)

    return render(
        request,
        "client_requirements_config.html",
        {
            "client": client,
            "profiles": RequirementProfile.objects.filter(tenant_id=1).order_by(
                "-is_tenant_default", "name"
            ),
            "service_rows": _client_service_requirement_rows(client),
        },
    )


# ── Software classifier config (evaluator knobs, admin-editable) ────────

_CLASSIFIER_DEFAULTS = {
    "rare_recent_enabled": True,
    "rare_recent_max_age_days": 7,
    "rare_recent_max_devices": 2,
    "rare_recent_severity": "medium",
    "rare_recent_skip_categorized": True,
    "rare_recent_skip_decided": True,
}


@login_required
def classifier_config(request: HttpRequest) -> HttpResponse:
    row, _ = EvaluatorConfig.objects.get_or_create(
        tenant_id=1,
        evaluator_name="software_classifier",
        defaults={"config": {}, "updated_by": request.user},
    )
    stored = row.config if isinstance(row.config, dict) else {}
    effective = dict(_CLASSIFIER_DEFAULTS)
    effective.update(stored)

    if request.method == "POST":
        new_cfg: dict = {}

        def _bool(name: str) -> bool:
            return request.POST.get(name) == "on"

        def _int(name: str, lo: int, hi: int, fallback: int) -> int:
            try:
                v = int(request.POST.get(name) or fallback)
            except ValueError:
                v = fallback
            return max(lo, min(v, hi))

        new_cfg["rare_recent_enabled"] = _bool("rare_recent_enabled")
        new_cfg["rare_recent_skip_categorized"] = _bool("rare_recent_skip_categorized")
        new_cfg["rare_recent_skip_decided"] = _bool("rare_recent_skip_decided")
        new_cfg["rare_recent_max_age_days"] = _int(
            "rare_recent_max_age_days",
            1,
            90,
            7,
        )
        new_cfg["rare_recent_max_devices"] = _int(
            "rare_recent_max_devices",
            1,
            100,
            2,
        )
        sev = (request.POST.get("rare_recent_severity") or "medium").strip()
        if sev not in {"info", "low", "medium", "high", "critical"}:
            sev = "medium"
        new_cfg["rare_recent_severity"] = sev

        row.config = new_cfg
        row.updated_by = request.user
        row.save(update_fields=["config", "updated_by", "updated_at"])
        messages.info(request, "Classifier configuration saved.")
        return redirect("classifier_config")

    return render(
        request,
        "classifier_config.html",
        {
            "admin_group": "config",
            "admin_tab": "classifier",
            "effective": effective,
            "stored": stored,
            "defaults": _CLASSIFIER_DEFAULTS,
            "updated_at": row.updated_at,
            "updated_by": row.updated_by,
            "severity_choices": [
                ("info", "Info"),
                ("low", "Low"),
                ("medium", "Medium"),
                ("high", "High"),
                ("critical", "Critical"),
            ],
        },
    )


@login_required
def device_status_config(request: HttpRequest) -> HttpResponse:
    """Tenant-wide thresholds for estate and patching status."""
    row, _ = EvaluatorConfig.objects.get_or_create(
        tenant_id=1,
        evaluator_name=DEVICE_STATUS_POLICY_NAME,
        defaults={"config": {}, "updated_by": request.user},
    )
    stored = row.config if isinstance(row.config, dict) else {}
    effective = get_device_status_policy()

    if request.method == "POST":
        limits = {
            "active_device_days": (1, 90),
            "patch_activity_days": (1, 180),
            "reboot_pending_days": (1, 90),
            "repeated_failure_count": (1, 20),
            "approval_backlog_count": (1, 10_000),
            "source_delay_hours": (1, 168),
        }
        new_config = {}
        for key, (minimum, maximum) in limits.items():
            try:
                value = int(request.POST.get(key) or DEVICE_STATUS_DEFAULTS[key])
            except ValueError:
                value = DEVICE_STATUS_DEFAULTS[key]
            new_config[key] = max(minimum, min(value, maximum))
        before = row.config
        row.config = new_config
        row.updated_by = request.user
        row.save(update_fields=["config", "updated_by", "updated_at"])
        _audit(request, "device_status.policy.update", row.id, before, new_config)
        messages.success(request, "Device status and patching policy saved.")
        return redirect("device_status_config")

    return render(
        request,
        "device_status_config.html",
        {
            "admin_group": "config",
            "admin_tab": "device-status",
            "effective": effective,
            "stored": stored,
            "defaults": DEVICE_STATUS_DEFAULTS,
            "updated_at": row.updated_at,
            "updated_by": row.updated_by,
        },
    )


@login_required
@require_admin
@require_GET
def lifecycle_policy_status(request: HttpRequest) -> HttpResponse:
    """Read-only lifecycle policy and transition audit under Admin → System."""
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
        policies = list(
            EntityType.objects.order_by("name").values(
                "name", "is_identity_signal", "lifecycle_evidence_mode", "description"
            )
        )
        transitions = list(
            AuditLog.objects.filter(tenant_id=1, action="lifecycle.transition")
            .order_by("-occurred_at")
            .values("entity_id", "occurred_at", "before_state", "after_state")[:100]
        )
    return render(
        request,
        "lifecycle_policy_status.html",
        {
            "admin_group": "system",
            "admin_tab": "lifecycle",
            "policies": policies,
            "transitions": transitions,
        },
    )


# ── Notification dispatcher UI (Track 2.4) ──────────────────────────────


@login_required
def notification_rules_list(request: HttpRequest) -> HttpResponse:
    rules = list(
        NotificationRule.objects.filter(tenant_id=1)
        .select_related("finding_type", "route", "client")
        .order_by("finding_type__name", "client__display_name")
    )
    events = list(NotificationEvent.objects.filter(tenant_id=1).order_by("-sent_at")[:50])
    routes = list(NotificationRoute.objects.filter(tenant_id=1))
    if wants_csv(request):
        return csv_response(
            rules,
            columns=[
                ("Finding type", lambda r: r.finding_type.name),
                ("Client", lambda r: (r.client.display_name if r.client else "(any)")),
                ("Route", lambda r: (r.route.name if r.route else "")),
                ("Enabled", lambda r: "yes" if r.enabled else "no"),
                ("Min severity", "min_severity"),
                ("Created", "created_at"),
            ],
            filename_stem="notification_rules",
        )
    return render(
        request,
        "notification_rules.html",
        {
            "admin_group": "config",
            "admin_tab": "alerts",
            "rules": rules,
            "events": events,
            "routes": routes,
            "enabled_count": sum(1 for r in rules if r.enabled),
            "disabled_count": sum(1 for r in rules if not r.enabled),
        },
    )


@login_required
@require_POST
@transaction.atomic
def notification_rule_toggle(request: HttpRequest, rule_id) -> HttpResponse:
    rule = get_object_or_404(NotificationRule, id=rule_id, tenant_id=1)
    prev = rule.enabled
    rule.enabled = not prev
    rule.save(update_fields=["enabled"])
    _audit(
        request,
        "notification_rule.toggle",
        rule.id,
        {"enabled": prev},
        {"enabled": rule.enabled},
    )
    messages.success(
        request,
        f"Rule for {rule.finding_type.name} is now {'enabled' if rule.enabled else 'disabled'}.",
    )
    return redirect("notification_rules_list")


@login_required
def notification_suppressions_list(request: HttpRequest) -> HttpResponse:
    rows = list(
        SuppressionRule.objects.filter(tenant_id=1)
        .select_related("finding_type", "created_by")
        .order_by("-created_at")
    )
    if wants_csv(request):
        return csv_response(
            rows,
            columns=[
                ("Finding type", lambda r: r.finding_type.name),
                ("Subject type", "subject_type"),
                ("Subject key", "subject_key"),
                ("Reason", "reason"),
                ("Created", "created_at"),
                ("Created by", lambda r: (r.created_by.username if r.created_by else "")),
                ("Expires", "expires_at"),
            ],
            filename_stem="suppressions",
        )
    return render(
        request,
        "notification_suppressions.html",
        {
            "admin_group": "config",
            "admin_tab": "suppressions",
            "suppressions": rows,
        },
    )
