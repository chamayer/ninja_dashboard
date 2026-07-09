from __future__ import annotations

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import connection, transaction
from django.db.models import Count, Prefetch, Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .forms import ClientPolicyForm
from .models import (
    AdminFinding,
    Client,
    ClientLink,
    ClientPolicy,
    Device,
    Finding,
    FindingType,
    MergeCandidate,
    SoftwareDecision,
)

DEVICE_PAGE_SIZE = 100

_FINDING_ACTIVE_STATUSES = (
    Finding.Status.OPEN,
    Finding.Status.ACKNOWLEDGED,
    Finding.Status.INVESTIGATING,
)

_SOURCES = ("Ninja", "SentinelOne", "ScreenConnect", "LogMeIn")


@require_GET
@transaction.non_atomic_requests
def healthz(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


@login_required
def home(request: HttpRequest) -> HttpResponse:
    total_devices = Device.objects.filter(tenant_id=1, deleted_at__isnull=True).count()
    total_clients = Client.objects.filter(tenant_id=1, deleted_at__isnull=True).count()

    severity_counts = {
        row["severity"]: row["n"]
        for row in Finding.objects.filter(tenant_id=1, status__in=_FINDING_ACTIVE_STATUSES)
        .values("severity")
        .annotate(n=Count("id"))
    }
    total_active_findings = sum(severity_counts.values())

    yesterday = timezone.now() - timedelta(hours=24)
    recent_findings = list(
        Finding.objects.filter(
            tenant_id=1,
            status__in=_FINDING_ACTIVE_STATUSES,
            first_seen_at__gte=yesterday,
        )
        .select_related("finding_type", "client")
        .order_by("-first_seen_at")[:10]
    )

    device_counts = {
        row["client_id"]: row["n"]
        for row in Device.objects.filter(tenant_id=1, deleted_at__isnull=True)
        .values("client_id")
        .annotate(n=Count("id"))
    }

    clients = list(
        Client.objects.filter(tenant_id=1, deleted_at__isnull=True)
        .annotate(
            critical_findings=Count(
                "findings",
                filter=Q(findings__status__in=_FINDING_ACTIVE_STATUSES, findings__severity="critical"),
            ),
            high_findings=Count(
                "findings",
                filter=Q(findings__status__in=_FINDING_ACTIVE_STATUSES, findings__severity="high"),
            ),
            total_findings=Count(
                "findings",
                filter=Q(findings__status__in=_FINDING_ACTIVE_STATUSES),
            ),
        )
        .order_by("-critical_findings", "-high_findings", "display_name")
    )

    client_health = [
        {
            "client": c,
            "devices": device_counts.get(c.id, 0),
            "critical": c.critical_findings,
            "high": c.high_findings,
            "total": c.total_findings,
        }
        for c in clients
    ]

    # Source health: warn if any source has no successful run in 8 hours.
    stale_sources: list[str] = []
    eight_hours_ago = timezone.now() - timedelta(hours=8)
    with connection.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT ON (df)
                df, status, completed_at
            FROM operations.source_run_queue
            WHERE status = 'done'
            ORDER BY df, completed_at DESC
        """)
        last_success = {r[0]: r[2] for r in cur.fetchall()}
    for src in _SOURCES:
        ts = last_success.get(src)
        if ts is None or ts < eight_hours_ago:
            stale_sources.append(src)

    return render(
        request,
        "home.html",
        {
            "total_devices": total_devices,
            "total_clients": total_clients,
            "total_active_findings": total_active_findings,
            "severity_counts": severity_counts,
            "recent_findings": recent_findings,
            "client_health": client_health,
            "stale_sources": stale_sources,
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
    ctx: dict = {}
    if getattr(request, "current_client", None):
        client = request.current_client
        devices = list(
            Device.objects.filter(
                tenant_id=1, client=client, deleted_at__isnull=True
            ).only("device_type")
        )
        ctx["device_count"] = len(devices)
        ctx["type_summary"] = _type_summary(devices)
        ctx["client_links"] = list(
            client.links.select_related("source").order_by("source__name")
        )
        ctx["policy_count"] = ClientPolicy.objects.filter(
            tenant_id=1, client=client
        ).count()
        ctx["policy_categories"] = list(
            ClientPolicy.objects.filter(tenant_id=1, client=client)
            .values_list("category", flat=True)
            .order_by("category")
        )

        # node_class → server/workstation: mirrors infer_device_type() in normalize.py.
        # ninja_core.devices is the canonical source; no AC dependency.
        _SCOPE_SQL = """
            CASE
                WHEN nd.node_class LIKE '%%SERVER%%'     THEN 'server'
                WHEN nd.node_class LIKE '%%WORKSTATION%%' THEN 'workstation'
                WHEN nd.os_name ILIKE '%%server%%'       THEN 'server'
                ELSE 'workstation'
            END
        """
        _PLATFORM_SEVERITY = {
            "Ninja": "critical",
            "SentinelOne": "critical",
            "ScreenConnect": "high",
            "LogMeIn": "high",
        }
        with transaction.atomic():
            with connection.cursor() as cur:
                cur.execute("SET LOCAL operations.tenant_id = 1")

                # Total devices per scope for this client.
                cur.execute(
                    f"""
                    SELECT {_SCOPE_SQL} AS scope, COUNT(*)::int
                    FROM operations.devices od
                    JOIN operations.device_links dl
                         ON dl.device_id = od.id AND dl.missing_since IS NULL
                    JOIN operations.sources s
                         ON s.id = dl.source_id AND s.name = 'Ninja'
                    JOIN ninja_core.devices nd
                         ON nd.id = dl.external_id::bigint AND nd.is_current
                    WHERE od.tenant_id = 1 AND od.client_id = %s AND od.deleted_at IS NULL
                    GROUP BY 1
                    """,
                    [str(client.id)],
                )
                scope_totals = dict(cur.fetchall())  # {'server': N, 'workstation': M}
                total_all = sum(scope_totals.values())

                # Presence per platform per scope.
                # Each observed device is classified via its Ninja device_link
                # (Ninja is authoritative for device identity and node_class).
                cur.execute(
                    f"""
                    SELECT ap.platform, {_SCOPE_SQL} AS scope,
                           COUNT(DISTINCT ap.device_id)::int AS present,
                           MAX(ap.last_observed_at) AS last_seen
                    FROM operations.agent_presence_current ap
                    JOIN operations.device_links dl
                         ON dl.device_id = ap.device_id AND dl.missing_since IS NULL
                    JOIN operations.sources s
                         ON s.id = dl.source_id AND s.name = 'Ninja'
                    JOIN ninja_core.devices nd
                         ON nd.id = dl.external_id::bigint AND nd.is_current
                    WHERE ap.tenant_id = 1 AND ap.client_id = %s
                      AND ap.last_observed_at > NOW() - INTERVAL '7 days'
                    GROUP BY 1, 2
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

        # Build lookup: (platform, scope) → {present, last_seen}
        presence_map: dict = {}
        for platform, scope, present, last_seen in presence_rows:
            presence_map[(platform, scope)] = {"present": present, "last_seen": last_seen}

        def _scope_total(scope: str) -> int:
            if scope == "all":
                return total_all
            return scope_totals.get(scope, 0)

        def _scope_present(platform: str, scope: str):
            if scope == "all":
                count = sum(
                    v["present"] for (p, _), v in presence_map.items() if p == platform
                )
                last = max(
                    (v["last_seen"] for (p, _), v in presence_map.items()
                     if p == platform and v["last_seen"]),
                    default=None,
                )
                return count, last
            v = presence_map.get((platform, scope), {})
            return v.get("present", 0), v.get("last_seen")

        platform_coverage: dict = {}
        for platform, etype, scope, severity in req_rows:
            present, last_seen = _scope_present(platform, scope)
            total = _scope_total(scope)
            entry = platform_coverage.setdefault(platform, {
                "severity": _PLATFORM_SEVERITY.get(platform, severity),
                "scopes": {},
            })
            scope_label = "all devices" if scope == "all" else scope + "s"
            entry["scopes"][scope_label] = {
                "total":    total,
                "present":  present,
                "gap":      max(0, total - present),
                "last_seen": last_seen,
            }
        ctx["platform_coverage"] = platform_coverage
        ctx["active_finding_count"] = Finding.objects.filter(
            tenant_id=1, client=client, status__in=_FINDING_ACTIVE_STATUSES
        ).count()
    else:
        # All-clients fleet view.
        clients_with_counts = list(
            Client.objects.filter(tenant_id=1, deleted_at__isnull=True)
            .prefetch_related(
                Prefetch(
                    "links",
                    queryset=ClientLink.objects.select_related("source").order_by("source__name"),
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
            c.source_names = list(dict.fromkeys(l.source.name for l in c.links.all()))
        fleet_type_counts = {
            row["device_type"]: row["count"]
            for row in Device.objects.filter(tenant_id=1, deleted_at__isnull=True)
            .values("device_type")
            .annotate(count=Count("id"))
        }
        source_coverage = list(
            ClientLink.objects.filter(tenant_id=1)
            .values("source__name")
            .annotate(client_count=Count("client_id", distinct=True))
            .order_by("source__name")
        )
        ctx["clients_with_counts"] = clients_with_counts
        ctx["all_device_count"] = sum(c.device_count for c in clients_with_counts)
        ctx["all_client_count"] = len(clients_with_counts)
        ctx["fleet_type_summary"] = _type_summary_from_counts(fleet_type_counts)
        ctx["source_coverage"] = source_coverage
        ctx["open_finding_count"] = Finding.objects.filter(
            tenant_id=1, status__in=_FINDING_ACTIVE_STATUSES
        ).count()
    return render(request, "org_index.html", ctx)


@login_required
def org_devices(request: HttpRequest, org_slug: str) -> HttpResponse:
    """Device list for a specific client with server-side search/filter."""
    client = _get_client_by_slug(org_slug)
    base_qs = Device.objects.filter(
        tenant_id=1, client=client, deleted_at__isnull=True
    )
    type_counts = {
        row["device_type"]: row["count"]
        for row in base_qs.values("device_type").annotate(count=Count("id"))
    }
    total_count = sum(type_counts.values())

    search_query = request.GET.get("q", "").strip()
    active_type = request.GET.get("type", "").strip()
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

    devices_qs = devices_qs.order_by("canonical_hostname").only(
        "id",
        "canonical_hostname",
        "canonical_serial",
        "device_type",
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
            "search_query": search_query,
            "page_query": page_query.urlencode(),
            "type_query": type_query.urlencode(),
            "page_size": DEVICE_PAGE_SIZE,
        },
    )


@login_required
def org_policies(request: HttpRequest, org_slug: str) -> HttpResponse:
    client = _get_client_by_slug(org_slug)
    policies = list(
        ClientPolicy.objects.filter(tenant_id=1, client=client).order_by("category")
    )
    return render(
        request,
        "org_policies.html",
        {"client": client, "policies": policies},
    )


@login_required
def device_detail(request: HttpRequest, org_slug: str, device_id: str) -> HttpResponse:
    device = get_object_or_404(
        Device.objects.select_related("client"),
        tenant_id=1,
        id=device_id,
        client__slug=org_slug,
        deleted_at__isnull=True,
    )
    links = list(device.links.select_related("source").order_by("source__name"))

    active_findings = list(
        Finding.objects.filter(
            tenant_id=1,
            subject_type=Finding.SubjectType.DEVICE,
            subject_id=device.id,
            status__in=_FINDING_ACTIVE_STATUSES,
        )
        .select_related("finding_type")
        .order_by("severity", "-last_seen_at")[:50]
    )

    agent_presence = []
    software_rows = []
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                """
                SELECT platform, entity_type, MAX(last_observed_at) AS last_seen
                FROM operations.agent_presence_current
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

    return render(
        request,
        "device_detail.html",
        {
            "device": device,
            "links": links,
            "active_findings": active_findings,
            "agent_presence": agent_presence,
            "software_rows": software_rows,
        },
    )


@login_required
def client_switch(request: HttpRequest) -> HttpResponse:
    slug = request.GET.get("slug", "all")
    return redirect("org_index", org_slug=slug)


@login_required
def findings_queue(request: HttpRequest) -> HttpResponse:
    """Entity findings review page."""
    status_filter = request.GET.get("status", "active")
    severity_filter = request.GET.get("severity", "")
    type_filter = request.GET.get("type", "")
    confidence_filter = request.GET.get("confidence", "")
    client_filter = request.GET.get("client", "")

    qs = Finding.objects.filter(tenant_id=1).select_related("finding_type", "client", "owner")

    if status_filter == "active":
        qs = qs.filter(status__in=_FINDING_ACTIVE_STATUSES)
    elif status_filter and status_filter != "all":
        qs = qs.filter(status=status_filter)

    if severity_filter:
        qs = qs.filter(severity=severity_filter)
    if type_filter:
        qs = qs.filter(finding_type__name=type_filter)
    if confidence_filter:
        qs = qs.filter(confidence=confidence_filter)
    if client_filter:
        qs = qs.filter(client__slug=client_filter)

    _SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    findings = sorted(qs[:500], key=lambda f: (_SEVERITY_ORDER.get(f.severity, 9), -(f.last_detected_at or f.last_seen_at).timestamp()))

    paginator = Paginator(findings, 50)
    page = paginator.get_page(request.GET.get("page"))

    finding_types = FindingType.objects.order_by("name")
    clients = Client.objects.filter(tenant_id=1, deleted_at__isnull=True).order_by("display_name")

    return render(
        request,
        "findings_queue.html",
        {
            "page_obj": page,
            "findings": page.object_list,
            "finding_types": finding_types,
            "clients": clients,
            "status_choices": Finding.Status.choices,
            "severity_choices": Finding.Severity.choices,
            "confidence_choices": Finding.Confidence.choices,
            "active_status": status_filter,
            "active_severity": severity_filter,
            "active_type": type_filter,
            "active_confidence": confidence_filter,
            "active_client": client_filter,
        },
    )


@login_required
@require_POST
def finding_acknowledge(request: HttpRequest, finding_id: str) -> HttpResponse:
    """Acknowledge an entity finding."""
    finding = get_object_or_404(Finding, id=finding_id, tenant_id=1)
    if finding.status == Finding.Status.OPEN:
        finding.status = Finding.Status.ACKNOWLEDGED
        finding.save(update_fields=["status"])
    return redirect("findings_queue")


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


def _get_client_by_slug(slug: str) -> Client:
    return get_object_or_404(
        Client, tenant_id=1, slug=slug, deleted_at__isnull=True
    )


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
    """Cross-source merge candidate review queue. Empty until multi-source ingest lands."""
    status_filter = request.GET.get("status", MergeCandidate.Status.OPEN)
    entity_filter = request.GET.get("entity", "")

    qs = MergeCandidate.objects.filter(tenant_id=1).select_related("client")

    if status_filter and status_filter != "all":
        qs = qs.filter(status=status_filter)
    if entity_filter:
        qs = qs.filter(entity_type=entity_filter)

    qs = qs.order_by("-confidence", "canonical_key")[:200]

    entity_types = (
        MergeCandidate.objects.filter(tenant_id=1)
        .values_list("entity_type", flat=True)
        .distinct()
    )

    return render(
        request,
        "merge_candidates_queue.html",
        {
            "candidates": qs,
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

    # Attach decision to each row so templates don't need dict-key lookup
    decisions_map = {
        d.canonical_name: d.decision
        for d in SoftwareDecision.objects.filter(tenant_id=1, client=client)
    }
    rows = [row + (decisions_map.get(row[0], ""),) for row in rows]

    num_pages = max(1, (total + _SW_PAGE_SIZE - 1) // _SW_PAGE_SIZE)

    page_query_parts = [f"publisher={p}" for p in active_publishers]
    if search:
        page_query_parts.append(f"q={search}")
    page_query = "&".join(page_query_parts)

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
        canonical_name=sw_name,
        defaults={
            "decision": decision,
            "decided_by": request.user,
            "decided_at": timezone.now(),
        },
    )
    return redirect(request.POST.get("next") or request.META.get("HTTP_REFERER") or
                    f"/orgs/{org_slug}/software/")


# ── Compliance / fleet coverage page ─────────────────────────────────────────

_SEV_RANK = "CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END"


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
            cur.execute("""
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
            """, {"client": client_filter, "platform": platform_filter, "confidence": conf_filter})
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
            "client_name": r[0], "client_slug": r[1],
            "platform": r[2], "severity": r[3],
            "total": r[4], "confirmed": r[5], "probable": r[6],
            "oldest_at": r[7],
        }
        for r in rows
    ]
    missing_devices = [
        {"client_name": r[0], "client_slug": r[1], "count": r[2]}
        for r in missing_rows
    ]

    clients_affected = len({r["client_slug"] for r in gap_rows})
    total_gaps = sum(r["total"] for r in gap_rows)
    critical_count = sum(r["total"] for r in gap_rows if r["severity"] == "critical")

    return render(request, "coverage.html", {
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
    })


# ── Source ingest status page ─────────────────────────────────────────────────


@login_required
def sources_status(request: HttpRequest) -> HttpResponse:
    """Source ingest run status and last observation timestamps."""
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")

            # Last completed run per source
            cur.execute("""
                SELECT DISTINCT ON (df)
                    df, status, completed_at, rows_seen, error, started_at, queued_at
                FROM operations.source_run_queue
                WHERE status IN ('done', 'failed')
                ORDER BY df, completed_at DESC
            """)
            last_run = {r[0]: r for r in cur.fetchall()}

            # Currently pending or processing
            cur.execute("""
                SELECT df, status, queued_at, started_at
                FROM operations.source_run_queue
                WHERE status IN ('pending', 'processing')
            """)
            active = {r[0]: r for r in cur.fetchall()}

            # Last observation per platform from entity_observations
            cur.execute("""
                SELECT platform, MAX(observed_at) AS last_observed
                FROM operations.entity_observations
                WHERE entity_type LIKE 'agent.%%'
                GROUP BY platform
            """)
            last_obs = {r[0]: r[1] for r in cur.fetchall()}

            # Recent run history
            cur.execute("""
                SELECT id, df, status, queued_at, started_at, completed_at,
                       rows_seen, error
                FROM operations.source_run_queue
                ORDER BY queued_at DESC LIMIT 30
            """)
            recent_cols = ["id", "source", "status", "queued_at", "started_at",
                           "completed_at", "rows_seen", "error"]
            recent_runs = [dict(zip(recent_cols, r)) for r in cur.fetchall()]

    now = timezone.now()
    sources = []
    for source in _SOURCES:
        run = last_run.get(source)
        act = active.get(source)
        last_success = run[2] if run and run[1] == "done" else None
        last_fail = run[2] if run and run[1] == "failed" else None
        last_error = run[4] if run and run[1] == "failed" else None
        is_stale = last_success is None or (now - last_success).total_seconds() > 8 * 3600
        sources.append({
            "name":          source,
            "is_processing": bool(act and act[1] == "processing"),
            "has_pending":   bool(act and act[1] == "pending"),
            "last_success":  last_success,
            "last_failure":  last_fail,
            "last_rows":     run[3] if run and run[1] == "done" else None,
            "last_error":    last_error,
            "last_observed": last_obs.get(source),
            "is_stale":      is_stale,
        })

    stale_count = sum(1 for s in sources if s["is_stale"] and not s["is_processing"])
    return render(request, "sources.html", {
        "sources": sources,
        "recent_runs": recent_runs,
        "stale_count": stale_count,
    })
