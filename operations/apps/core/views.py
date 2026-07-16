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
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_POST

from .forms import ClientPolicyForm
from .models import (
    AdminFinding,
    AuditLog,
    Client,
    ClientCandidate,
    ClientLink,
    ClientNameAlias,
    ClientOrgExclude,
    ClientPolicy,
    Device,
    Finding,
    FindingCategory,
    FindingType,
    IdentityCandidate,
    MergeCandidate,
    NotificationEvent,
    NotificationRoute,
    NotificationRule,
    RequirementProfile,
    SoftwareCatalog,
    SoftwareClassifierRule,
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

_SOURCES = ("Ninja", "SentinelOne", "ScreenConnect", "LogMeIn")


@require_GET
@transaction.non_atomic_requests
def healthz(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


@login_required
def home(request: HttpRequest) -> HttpResponse:
    total_devices = Device.objects.filter(tenant_id=1, deleted_at__isnull=True).count()
    total_clients = Client.objects.filter(tenant_id=1, deleted_at__isnull=True).count()

    # Overall severity breakdown (retained for the critical banner).
    severity_counts = {
        row["severity"]: row["n"]
        for row in Finding.objects.filter(tenant_id=1, status__in=_FINDING_ACTIVE_STATUSES)
        .values("severity")
        .annotate(n=Count("id"))
    }
    total_active_findings = sum(severity_counts.values())

    # Per-category open finding counts. Powers the domain summary
    # cards (Patching / Software / Coverage / Health).
    category_counts = {
        row["finding_type__category__name"]: row["n"]
        for row in Finding.objects.filter(
            tenant_id=1, status__in=_FINDING_ACTIVE_STATUSES,
        )
        .values("finding_type__category__name")
        .annotate(n=Count("id"))
    }

    # Coverage split: Missing (agent never installed — actionable
    # gap) vs Stale (agent installed but not checking in — mixed
    # bag, includes offline devices which are unactionable).
    coverage_split = {
        row["finding_type__name"]: row["n"]
        for row in Finding.objects.filter(
            tenant_id=1,
            status__in=_FINDING_ACTIVE_STATUSES,
            finding_type__name__in=[
                "missing_required_platform",
                "stale_required_platform",
            ],
        )
        .values("finding_type__name")
        .annotate(n=Count("id"))
    }
    coverage_missing = coverage_split.get("missing_required_platform", 0)
    coverage_stale = coverage_split.get("stale_required_platform", 0)

    # Patching population from v_device (Track O).
    patching_pop = {"total": 0, "in_scope": 0}
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE effective_patching_scope = 'Included') AS in_scope
            FROM operations.v_device
            WHERE tenant_id = 1
            """
        )
        row = cur.fetchone()
        if row:
            patching_pop["total"] = row[0]
            patching_pop["in_scope"] = row[1]

    # Reviews pending across all three queues.
    reviews_pending = {
        "client_candidates": ClientCandidate.objects.filter(
            tenant_id=1, status=ClientCandidate.Status.OPEN,
        ).count(),
        "identity_candidates": IdentityCandidate.objects.filter(
            tenant_id=1, status="pending",
        ).count(),
        "merge_candidates": MergeCandidate.objects.filter(
            tenant_id=1, status="pending",
        ).count(),
    }
    reviews_pending["total"] = sum(reviews_pending.values())

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

    # ── Clients on fire — SEVERE issues in ≥2 domains ───────────
    # Genuine signal only: critical OR high severity in ≥2 of
    # patching / software / coverage. Medium-severity software
    # noise (~11k rare_recent) would otherwise flag every client
    # trivially — "on fire" needs to mean something.
    on_fire = []
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT f.client_id,
                   COUNT(DISTINCT ft.category_id) AS domain_count,
                   COUNT(*) AS severe_count
            FROM operations.findings f
            JOIN operations.finding_types ft ON ft.id = f.finding_type_id
            JOIN operations.finding_categories fc ON fc.id = ft.category_id
            WHERE f.tenant_id = 1
              AND f.status IN ('open', 'acknowledged', 'investigating')
              AND f.severity IN ('critical', 'high')
              AND fc.name IN ('patching', 'software', 'coverage')
              AND f.client_id IS NOT NULL
            GROUP BY f.client_id
            HAVING COUNT(DISTINCT ft.category_id) >= 2
            ORDER BY domain_count DESC, severe_count DESC
            LIMIT 30
            """
        )
        on_fire_rows = cur.fetchall()
    if on_fire_rows:
        client_lookup = {
            c.id: c for c in Client.objects.filter(
                tenant_id=1,
                id__in=[r[0] for r in on_fire_rows],
            )
        }
        for cid, domain_count, severe_count in on_fire_rows:
            c = client_lookup.get(cid)
            if c:
                on_fire.append({
                    "client": c,
                    "domain_count": domain_count,
                    "severe_count": severe_count,
                })

    # ── Client portfolio with health traffic light ──────────────
    client_q = (request.GET.get("client_q") or "").strip()
    view_filter = request.GET.get("view", "all")  # all | attention | healthy | no_data
    clients_qs = (
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
            medium_findings=Count(
                "findings",
                filter=Q(findings__status__in=_FINDING_ACTIVE_STATUSES, findings__severity="medium"),
            ),
            total_findings=Count(
                "findings",
                filter=Q(findings__status__in=_FINDING_ACTIVE_STATUSES),
            ),
            missing_agents=Count(
                "findings",
                filter=Q(
                    findings__status__in=_FINDING_ACTIVE_STATUSES,
                    findings__finding_type__name="missing_required_platform",
                ),
            ),
        )
        .order_by("-critical_findings", "-high_findings", "display_name")
    )
    if client_q:
        clients_qs = clients_qs.filter(display_name__icontains=client_q)

    def _health(devices: int, crit: int, high: int) -> str:
        """Traffic-light health per client — operational rollup."""
        if devices == 0:
            return "no_data"
        if crit > 0:
            return "red"
        if high > 0:
            return "amber"
        return "green"

    client_portfolio_all = []
    for c in clients_qs:
        devs = device_counts.get(c.id, 0)
        health = _health(devs, c.critical_findings, c.high_findings)
        client_portfolio_all.append({
            "client": c,
            "devices": devs,
            "critical": c.critical_findings,
            "high": c.high_findings,
            "medium": c.medium_findings,
            "total": c.total_findings,
            "missing_agents": c.missing_agents,
            "health": health,
        })

    # Counts for the filter chips (before view filter is applied).
    health_counts = {"red": 0, "amber": 0, "green": 0, "no_data": 0}
    for row in client_portfolio_all:
        health_counts[row["health"]] += 1
    attention_count = health_counts["red"] + health_counts["amber"]

    if view_filter == "attention":
        client_portfolio_all = [
            r for r in client_portfolio_all if r["health"] in ("red", "amber")
        ]
    elif view_filter == "healthy":
        client_portfolio_all = [r for r in client_portfolio_all if r["health"] == "green"]
    elif view_filter == "no_data":
        client_portfolio_all = [r for r in client_portfolio_all if r["health"] == "no_data"]

    client_health_paginator = Paginator(client_portfolio_all, 25)
    client_health_page = client_health_paginator.get_page(request.GET.get("client_page"))

    # Source health: fresh if the source has produced at least one
    # entity_observations row in the last 8 hours. Reads live data
    # (not the retired source_run_queue, whose completed_at is
    # frozen at legacy-retirement time).
    stale_sources: list[str] = []
    source_health = []
    eight_hours_ago = timezone.now() - timedelta(hours=8)
    with connection.cursor() as cur:
        cur.execute("""
            SELECT platform, MAX(observed_at) AS latest
            FROM operations.entity_observations
            WHERE tenant_id = 1
            GROUP BY platform
        """)
        latest_obs = {r[0]: r[1] for r in cur.fetchall()}
    for src in _SOURCES:
        ts = latest_obs.get(src)
        is_stale = ts is None or ts < eight_hours_ago
        source_health.append({"name": src, "last_success": ts, "stale": is_stale})
        if is_stale:
            stale_sources.append(src)
    sources_ok = sum(1 for s in source_health if not s["stale"])

    return render(
        request,
        "home.html",
        {
            "total_devices": total_devices,
            "total_clients": total_clients,
            "total_active_findings": total_active_findings,
            "severity_counts": severity_counts,
            "category_counts": category_counts,
            "coverage_missing": coverage_missing,
            "coverage_stale": coverage_stale,
            "patching_pop": patching_pop,
            "reviews_pending": reviews_pending,
            "source_health": source_health,
            "sources_ok": sources_ok,
            "sources_total": len(_SOURCES),
            "recent_findings": recent_findings,
            "client_health": client_health_page.object_list,
            "client_health_page": client_health_page,
            "client_health_total": len(client_portfolio_all),
            "client_q": client_q,
            "health_counts": health_counts,
            "attention_count": attention_count,
            "active_view": view_filter,
            "on_fire": on_fire,
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
                    """
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
                    FROM operations.agent_presence_current ap
                    JOIN operations.devices od
                         ON od.id = ap.device_id AND od.deleted_at IS NULL
                    WHERE ap.tenant_id = 1 AND ap.client_id = %s
                      AND ap.last_observed_at > NOW() - INTERVAL '7 days'
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
                "present": present, "last_seen": last_seen,
            }

        def _scope_total(scope: str) -> int:
            if scope == "all":
                return total_all
            return scope_totals.get(scope, 0)

        def _scope_present(platform: str, etype: str, scope: str):
            if scope == "all":
                count = sum(
                    v["present"] for (p, e, _), v in presence_map.items()
                    if p == platform and e == etype
                )
                last = max(
                    (v["last_seen"] for (p, e, _), v in presence_map.items()
                     if p == platform and e == etype and v["last_seen"]),
                    default=None,
                )
                return count, last
            v = presence_map.get((platform, etype, scope), {})
            return v.get("present", 0), v.get("last_seen")

        platform_coverage: dict = {}
        for platform, etype, scope, severity in req_rows:
            present, last_seen = _scope_present(platform, etype, scope)
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
                "role":     "" if scope == "all" else scope,
                "entity_type": etype,
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
        # Clients actually observed per platform — client_links row counts are
        # meaningless here (per-client SC instances have one link total).
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                """
                SELECT platform, COUNT(DISTINCT client_id)
                FROM operations.agent_presence_current
                WHERE client_id IS NOT NULL
                  AND entity_type LIKE 'agent.%'
                GROUP BY platform
                ORDER BY platform
                """
            )
            source_coverage = [
                {"name": r[0], "client_count": int(r[1])} for r in cur.fetchall()
            ]
        ctx["clients_with_counts"] = clients_with_counts
        ctx["all_device_count"] = sum(c.device_count for c in clients_with_counts)
        ctx["all_client_count"] = len(clients_with_counts)
        ctx["fleet_type_summary"] = _type_summary_from_counts(fleet_type_counts)
        ctx["source_coverage"] = source_coverage
        ctx["open_finding_count"] = Finding.objects.filter(
            tenant_id=1, status__in=_FINDING_ACTIVE_STATUSES
        ).count()
    ctx["all_profiles"] = list(
        RequirementProfile.objects.filter(tenant_id=1).order_by(
            "-is_tenant_default", "name"
        )
    )
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
    if missing_platform in _SOURCES:
        # Coverage-gap drilldown for the requirement's entity type/platform.
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                """
                SELECT DISTINCT device_id
                FROM operations.agent_presence_current
                WHERE tenant_id = 1 AND client_id = %s AND platform = %s
                  AND entity_type = %s
                  AND last_observed_at > NOW() - INTERVAL '7 days'
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
    patching = None
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                """
                SELECT platform, entity_type,
                       MAX(last_observed_at) AS last_seen,
                       MAX(last_contact_at)  AS last_contact
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

            # Patching context: effective scope + session state from
            # v_device (Track O), plus per-device patch signal from
            # ninja_patches.device_patch_signal joined via device_links.
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
                    FROM operations.device_links dl
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

    return render(
        request,
        "device_detail.html",
        {
            "device": device,
            "links": links,
            "active_findings": active_findings,
            "agent_presence": agent_presence,
            "software_rows": software_rows,
            "patching": patching,
        },
    )


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
        return render(request, "search_results.html",
                      {"q": "", "devices": [], "clients": []})

    devices = list(
        Device.objects.filter(
            tenant_id=1,
            deleted_at__isnull=True,
        )
        .filter(
            Q(canonical_hostname__icontains=q)
            | Q(canonical_serial__icontains=q)
        )
        .select_related("client")
        .order_by("canonical_hostname")[:100]
    )

    clients = list(
        Client.objects.filter(
            tenant_id=1,
            deleted_at__isnull=True,
        )
        .filter(
            Q(display_name__icontains=q)
            | Q(slug__icontains=q)
        )
        .order_by("display_name")[:100]
    )

    # Unambiguous matches → redirect straight there.
    if len(devices) == 1 and not clients:
        d = devices[0]
        if d.client:
            return redirect("device_detail",
                            org_slug=d.client.slug, device_id=d.id)
    if len(clients) == 1 and not devices:
        return redirect("org_index", org_slug=clients[0].slug)

    return render(request, "search_results.html", {
        "q": q,
        "devices": devices,
        "clients": clients,
    })


@login_required
def findings_queue(request: HttpRequest) -> HttpResponse:
    """Entity findings review page."""
    status_filter = request.GET.get("status", "active")
    severity_filter = request.GET.get("severity", "")
    type_filter = request.GET.get("type", "")
    category_filter = request.GET.get("category", "")
    confidence_filter = request.GET.get("confidence", "")
    client_filter = request.GET.get("client", "")
    platform_filter = request.GET.get("platform", "")
    online_filter = request.GET.get("online", "")
    q_filter = (request.GET.get("q") or "").strip()

    # Source names come from operations.sources (admin-editable
    # reference data) — never hardcoded in code.
    source_names = list(
        Source.objects.order_by("name").values_list("name", flat=True)
    )
    source_names_set = set(source_names)

    qs = Finding.objects.filter(tenant_id=1).select_related(
        "finding_type", "finding_type__category", "client", "owner",
    )

    if status_filter == "active":
        qs = qs.filter(status__in=_FINDING_ACTIVE_STATUSES)
    elif status_filter and status_filter != "all":
        qs = qs.filter(status=status_filter)

    if severity_filter:
        qs = qs.filter(severity=severity_filter)
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
    if q_filter:
        # Free-text match against canonical_name OR hostname in details
        qs = qs.filter(
            Q(finding_details__canonical_name__icontains=q_filter)
            | Q(finding_details__hostname__icontains=q_filter)
        )

    # Tile counts — computed BEFORE the [:500] slice so tiles show
    # true matching totals across all filters (severity, category,
    # client, etc.). Counts respect ALL current filters — including
    # severity itself, so if severity is set the tiles reflect only
    # that severity's slice (works as expected — you filter down,
    # tiles narrow).
    severity_tile_counts = {
        row["severity"]: row["n"]
        for row in qs.values("severity").annotate(n=Count("id"))
    }
    total_matching = sum(severity_tile_counts.values())

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
        severity_tiles.append({
            "value": sev,
            "label": label,
            "count": severity_tile_counts.get(sev, 0),
            "href": "?" + params.urlencode() if params else "?",
            "active": is_active,
        })

    _SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    findings = sorted(qs[:500], key=lambda f: (_SEVERITY_ORDER.get(f.severity, 9), -(f.last_detected_at or f.last_seen_at).timestamp()))

    # Per-device map of platforms currently in contact:
    #   device_id → sorted list of platform names (empty = offline).
    # Read from device_session_current (Track O batch O1) — the matview
    # pre-aggregates per-source "in contact within 24h" and the vm.guest
    # power_state='poweredon' signal, refreshed on every ingest cycle
    # (~hourly). Consumer used to compute this inline off
    # agent_presence_current.
    subject_ids = [f.subject_id for f in findings if f.subject_id]
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

    # Coalesce noise: for a device with no source in contact, suppress
    # missing/stale_required_platform findings from the queue — they
    # aren't actionable while the device isn't reachable. Findings still
    # exist and appear on the device detail page.
    _COALESCED_TYPES = {"missing_required_platform", "stale_required_platform"}
    findings = [
        f for f in findings
        if not (
            f.finding_type.name in _COALESCED_TYPES
            and f.subject_id
            and not online_map.get(str(f.subject_id))
        )
    ]

    # Online filter: "" any, "online" any source in contact, "offline"
    # none, or a specific source name to filter to devices reached by
    # that source right now.
    if online_filter == "online":
        findings = [f for f in findings if online_map.get(str(f.subject_id))]
    elif online_filter == "offline":
        findings = [f for f in findings if f.subject_id and not online_map.get(str(f.subject_id))]
    elif online_filter in source_names_set:
        findings = [
            f for f in findings
            if f.subject_id and online_filter in online_map.get(str(f.subject_id), [])
        ]

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
            lc = d.get("last_contact_at") or d.get("last_seen_at")
            return f"no source has contact since {lc[:10]}" if lc else "no source has contact"
        if name == "device_role_conflict":
            return f"{d.get('previous_role', '?')} → {d.get('new_role', '?')}"
        # Fallback: platform if present, else empty
        return d.get("platform") or ""

    findings_with_detail = [
        {
            "f": f,
            "detail": _detail_string(f),
            "online_sources": online_map.get(str(f.subject_id)) if f.subject_id else None,
        }
        for f in findings
    ]

    paginator = Paginator(findings_with_detail, 50)
    page = paginator.get_page(request.GET.get("page"))

    # Type dropdown cascades: if category selected, only show types in it.
    ft_qs = FindingType.objects.select_related("category").order_by("name")
    if category_filter:
        ft_qs = ft_qs.filter(category__name=category_filter)
    finding_types = list(ft_qs)
    categories = list(FindingCategory.objects.order_by("display_order", "name"))
    clients = Client.objects.filter(tenant_id=1, deleted_at__isnull=True).order_by("display_name")

    page_query = request.GET.copy()
    page_query.pop("page", None)

    return render(
        request,
        "findings_queue.html",
        {
            "page_obj": page,
            "findings": page.object_list,
            "finding_types": finding_types,
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
            "severity_tiles": severity_tiles,
            "total_matching": total_matching,
            "page_query": page_query.urlencode(),
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
            str(cid) for cid in Client.objects.filter(
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
        for row in (
            base_qs.values("finding_type__name").annotate(cnt=Count("id"))
        )
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
        "in_scope_pct": (
            round(100.0 * pop_row[1] / pop_row[0], 1) if pop_row[0] else 0.0
        ),
    }

    # Device population by scope (drilldown from the summary tiles).
    # Optional "scope" query param drills into a specific bucket.
    scope_filter = request.GET.get("scope", "")
    device_rows: list = []
    if scope_filter in ("Included", "Excluded", "Unmanaged", "Unknown"):
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            base_where = "tenant_id = %s AND effective_patching_scope = %s"
            params: list = [1, scope_filter]
            if filtered_client_ids:
                base_where += " AND client_id = ANY(%s::uuid[])"
                params.append(filtered_client_ids)
            elif client_filter:
                base_where += " AND FALSE"
            if role_filter:
                base_where += " AND device_role = %s"
                params.append(role_filter)
            cur.execute(
                f"""
                SELECT device_id, canonical_hostname, client_id,
                       device_role, os_group,
                       patching_scope_reason,
                       patching_scope_override,
                       last_contact_at
                FROM operations.v_device
                WHERE {base_where}
                ORDER BY canonical_hostname
                LIMIT 500
                """,
                params,
            )
            device_rows = cur.fetchall()

    # Client-id → slug lookup, pre-compute clickthrough URL per device
    # row (template-side lookup would iterate all clients per row —
    # bad).
    if device_rows:
        client_slug_by_id = dict(
            Client.objects.filter(tenant_id=1).values_list("id", "slug")
        )
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
                "url": (
                    reverse("device_detail", kwargs={
                        "org_slug": client_slug_by_id[cid],
                        "device_id": did,
                    })
                    if cid in client_slug_by_id else None
                ),
            }
            for (did, hostname, cid, role, os_group, reason, override,
                 last_contact) in device_rows
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

    paginator = Paginator(rows, 50)
    page = paginator.get_page(request.GET.get("page"))

    clients = (
        Client.objects.filter(tenant_id=1, deleted_at__isnull=True)
        .order_by("display_name")
    )

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
        {"label": "Total devices",  "value": population["total"]},
        {"label": "In scope (Included)", "value": population["in_scope"],
         "href": _scope_href("Included")},
        {"label": "Excluded",       "value": population["excluded"],
         "href": _scope_href("Excluded")},
        {"label": "Unmanaged",      "value": population["unmanaged"],
         "href": _scope_href("Unmanaged")},
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
                SELECT f.finding_details->>'canonical_name', COUNT(DISTINCT f.subject_id)
                FROM operations.findings f
                JOIN operations.finding_types ft ON ft.id = f.finding_type_id
                WHERE f.tenant_id = 1
                  AND f.client_id = %s
                  AND f.status IN ('open', 'acknowledged')
                  AND ft.source_module = 'platform.software_findings'
                  AND f.finding_details->>'canonical_name' = ANY(%s::text[])
                GROUP BY 1
                """,
                (client.id, canonical_names),
            )
            findings_map = {name: count for name, count in cur2.fetchall()}
    rows = [
        row + (decisions_map.get(row[0], ""), findings_map.get(row[0], 0))
        for row in rows
    ]

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
    """Source ingest run status and last observation timestamps.

    Run status comes from operations.run_log (kind 'source.<platform>[...]'),
    which records every source run — scheduled and manual. The demand queue
    is only consulted for pending/processing indicators.
    """
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")

            # Latest run per platform (any outcome)
            cur.execute("""
                SELECT DISTINCT ON (split_part(kind, '.', 2))
                    split_part(kind, '.', 2), ok, ended_at, rows, error
                FROM operations.run_log
                WHERE kind LIKE 'source.%%'
                ORDER BY split_part(kind, '.', 2), started_at DESC
            """)
            last_run = {r[0]: r for r in cur.fetchall()}

            # Latest successful run per platform
            cur.execute("""
                SELECT DISTINCT ON (split_part(kind, '.', 2))
                    split_part(kind, '.', 2), ended_at, rows
                FROM operations.run_log
                WHERE kind LIKE 'source.%%' AND ok
                ORDER BY split_part(kind, '.', 2), started_at DESC
            """)
            last_ok = {r[0]: r for r in cur.fetchall()}

            # Currently pending or processing (manual demand queue)
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

            # Observed reach per platform
            cur.execute("""
                SELECT platform, COUNT(DISTINCT client_id), COUNT(DISTINCT device_id)
                FROM operations.agent_presence_current
                GROUP BY platform
            """)
            reach = {r[0]: (int(r[1]), int(r[2])) for r in cur.fetchall()}

            # Recent run history — every recorded source run
            cur.execute("""
                SELECT substring(kind FROM 8), ok, started_at, ended_at, rows, error
                FROM operations.run_log
                WHERE kind LIKE 'source.%%'
                ORDER BY started_at DESC LIMIT 30
            """)
            recent_runs = [
                {
                    "source":       r[0],
                    "status":       "done" if r[1] else "failed",
                    "started_at":   r[2],
                    "completed_at": r[3],
                    "rows_seen":    r[4],
                    "error":        r[5] or None,
                }
                for r in cur.fetchall()
            ]

    now = timezone.now()
    sources = []
    for source in _SOURCES:
        run = last_run.get(source)
        ok_run = last_ok.get(source)
        act = active.get(source)
        last_success = ok_run[1] if ok_run else None
        last_fail = run[2] if run and not run[1] else None
        last_error = (run[4] or None) if run and not run[1] else None
        is_stale = last_success is None or (now - last_success).total_seconds() > 8 * 3600
        sources.append({
            "name":          source,
            "is_processing": bool(act and act[1] == "processing"),
            "has_pending":   bool(act and act[1] == "pending"),
            "last_success":  last_success,
            "last_failure":  last_fail,
            "last_rows":     ok_run[2] if ok_run else None,
            "last_error":    last_error,
            "last_observed": last_obs.get(source),
            "client_count":  reach.get(source, (0, 0))[0],
            "device_count":  reach.get(source, (0, 0))[1],
            "is_stale":      is_stale,
        })

    stale_count = sum(1 for s in sources if s["is_stale"] and not s["is_processing"])
    return render(request, "sources.html", {
        "sources": sources,
        "recent_runs": recent_runs,
        "stale_count": stale_count,
    })


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
        rows.append({
            "candidate": c,
            "sources": sorted(by_source),
            "source_count": len(by_source),
            "latest_seen": latest_seen,
        })

    counts = {
        row["status"]: row["n"]
        for row in ClientCandidate.objects.filter(tenant_id=1)
        .values("status").annotate(n=Count("id"))
    }

    return render(request, "client_candidates_queue.html", {
        "rows": rows,
        "active_status": status_filter,
        "counts": counts,
        "status_choices": ClientCandidate.Status.choices,
    })


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
                    SELECT MIN(observed_at), MAX(observed_at), COUNT(*)
                    FROM operations.entity_observations eo
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
                    SELECT MAX((canonical_data->>'device_count')::int)
                    FROM operations.entity_observations eo
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

                per_source.append({
                    "source":       source_names.get(sid, "?"),
                    "external_id":  ext_id,
                    "external_name": ref.get("external_name") or "",
                    "first_seen":   first_seen,
                    "last_seen":    last_seen,
                    "run_count":    run_count,
                    "device_count": device_count or 0,
                })

            # Sample devices seen inside these groups AND client overlap.
            if external_ids:
                cur.execute(
                    """
                    SELECT DISTINCT ON (eo.entity_key, eo.platform)
                        eo.platform,
                        eo.canonical_data->>'hostname' AS hostname,
                        eo.device_id,
                        d.client_id,
                        c.display_name
                    FROM operations.entity_observations eo
                    LEFT JOIN operations.devices d
                        ON d.id = eo.device_id AND d.deleted_at IS NULL
                    LEFT JOIN operations.clients c
                        ON c.id = d.client_id
                    WHERE eo.tenant_id = 1
                      AND eo.entity_type <> 'org'
                      AND eo.canonical_data->>'platform_group_id' = ANY(%s)
                    ORDER BY eo.entity_key, eo.platform, eo.observed_at DESC
                    LIMIT 25
                    """,
                    (external_ids,),
                )
                for platform, hostname, device_id, cid, cname in cur.fetchall():
                    sample_devices.append({
                        "platform": platform,
                        "hostname": hostname or "—",
                        "resolved_client_id": cid,
                        "resolved_client_name": cname or "",
                    })
                    if cid and cname:
                        overlap = device_overlap.setdefault(str(cid), {
                            "client_id": str(cid),
                            "display_name": cname,
                            "device_count": 0,
                        })
                        overlap["device_count"] += 1

    # Fuzzy suggestions against known client display names + aliases.
    known_names: dict[str, tuple] = {}
    for c in Client.objects.filter(tenant_id=1, deleted_at__isnull=True):
        known_names[c.display_name] = ("client", c.id, c.display_name)
    for a in ClientNameAlias.objects.filter(tenant_id=1, enabled=True).select_related("client"):
        known_names[a.alias] = ("alias", a.client_id, a.client.display_name)
    fuzzy = []
    if candidate.display_name:
        matches = get_close_matches(candidate.display_name, list(known_names.keys()), n=5, cutoff=0.6)
        for m in matches:
            kind, cid, cname = known_names[m]
            fuzzy.append({"match": m, "kind": kind, "client_id": cid, "client_name": cname})

    all_clients = list(
        Client.objects.filter(tenant_id=1, deleted_at__isnull=True)
        .order_by("display_name")
    )
    profiles = list(RequirementProfile.objects.filter(tenant_id=1).order_by("name"))
    default_profile = next((p for p in profiles if p.is_tenant_default), None)

    return render(request, "client_candidate_detail.html", {
        "candidate": candidate,
        "per_source": per_source,
        "sample_devices": sample_devices,
        "device_overlap": sorted(
            device_overlap.values(), key=lambda x: -x["device_count"]
        ),
        "fuzzy": fuzzy,
        "all_clients": all_clients,
        "profiles": profiles,
        "default_profile": default_profile,
    })


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
    cur, source_id: int, external_id: str, external_name: str,
    client_id, reason: str,
) -> None:
    """Backfill org + device observations for this group to a client,
    and mint / update the client_link. Mirrors client_resolver._attach_group."""
    cur.execute(
        """
        INSERT INTO operations.client_links
            (id, version, tenant_id, client_id, source_id, external_id,
             external_name, created_at, created_reason)
        VALUES (gen_random_uuid(), 0, 1, %s, %s, %s, %s, NOW(), %s)
        ON CONFLICT (tenant_id, source_id, external_id)
        DO UPDATE SET external_name = EXCLUDED.external_name
        """,
        (client_id, source_id, external_id, external_name, reason),
    )
    cur.execute(
        """
        UPDATE operations.entity_observations eo
        SET client_id = %s
        FROM operations.source_bindings sb, operations.source_instances si
        WHERE eo.source_binding_id = sb.id
          AND sb.source_instance_id = si.id
          AND si.source_id = %s
          AND eo.tenant_id = 1
          AND eo.entity_type = 'org'
          AND eo.entity_key = %s
          AND eo.client_id IS NULL
        """,
        (client_id, source_id, external_id),
    )
    cur.execute(
        """
        UPDATE operations.entity_observations eo
        SET client_id = %s
        FROM operations.source_bindings sb, operations.source_instances si
        WHERE eo.source_binding_id = sb.id
          AND sb.source_instance_id = si.id
          AND si.source_id = %s
          AND eo.tenant_id = 1
          AND eo.entity_type <> 'org'
          AND eo.client_id IS NULL
          AND eo.canonical_data ->> 'platform_group_id' = %s
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
        ClientCandidate, id=candidate_id, tenant_id=1, status="open",
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
            tenant_id=1, is_tenant_default=True,
        ).first()

    base_slug = slugify(display_name)[:110] or "client"
    slug = base_slug
    suffix = 1
    while Client.objects.filter(tenant_id=1, slug=slug).exists():
        suffix += 1
        slug = f"{base_slug}-{suffix}"

    client = Client.objects.create(
        tenant_id=1, slug=slug, display_name=display_name,
        requirement_profile=profile,
        created_reason=f"candidate.accept:{candidate.id}",
    )

    ClientNameAlias.objects.update_or_create(
        tenant_id=1, normalized_name=candidate.normalized_name,
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
            _attach_group_to_client(
                cur, sid, ext_id, ref.get("external_name") or display_name,
                client.id, "candidate.accept",
            )

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
        request, "client_candidate.accept", candidate.id,
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
        ClientCandidate, id=candidate_id, tenant_id=1, status="open",
    )
    target_id = request.POST.get("client_id")
    if not target_id:
        messages.error(request, "Choose a client to map into.")
        return redirect("client_candidate_detail", candidate_id=candidate.id)
    target = get_object_or_404(Client, id=target_id, tenant_id=1, deleted_at__isnull=True)

    ClientNameAlias.objects.update_or_create(
        tenant_id=1, normalized_name=candidate.normalized_name,
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
            _attach_group_to_client(
                cur, sid, ext_id,
                ref.get("external_name") or target.display_name,
                target.id, "candidate.map",
            )

    candidate.status = ClientCandidate.Status.MAPPED
    candidate.resolved_client = target
    candidate.resolved_at = timezone.now()
    candidate.resolved_by = request.user.get_username()
    candidate.resolved_reason = f"mapped → {target.display_name}"
    candidate.save()

    _audit(
        request, "client_candidate.map", candidate.id,
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
        ClientCandidate, id=candidate_id, tenant_id=1, status="open",
    )
    reason = (request.POST.get("reason") or "").strip() or "excluded from candidate view"
    ClientOrgExclude.objects.get_or_create(
        tenant_id=1, normalized_name=candidate.normalized_name,
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
        request, "client_candidate.exclude", candidate.id,
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
        ClientCandidate, id=candidate_id, tenant_id=1, status="open",
    )
    note = (request.POST.get("note") or "").strip()
    if not note:
        messages.error(request, "A note is required for fix-at-source.")
        return redirect("client_candidate_detail", candidate_id=candidate.id)
    _audit(
        request, "client_candidate.fix_at_source", candidate.id,
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
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                """
                SELECT
                    f.finding_details->>'canonical_name' AS canonical,
                    f.finding_details->>'category' AS category,
                    MIN(sc.categories::text) AS catalog_categories,
                    COUNT(DISTINCT f.subject_id) AS device_count,
                    MAX(f.last_seen_at) AS latest
                FROM operations.findings f
                JOIN operations.finding_types ft
                  ON ft.id = f.finding_type_id
                LEFT JOIN operations.software_catalog sc
                  ON LOWER(sc.canonical_name) = LOWER(f.finding_details->>'canonical_name')
                 AND (sc.tenant_id IS NULL OR sc.tenant_id = f.tenant_id)
                WHERE f.tenant_id = 1
                  AND f.status IN ('open', 'acknowledged')
                  AND ft.source_module = 'platform.software_findings'
                  AND f.finding_details->>'canonical_name' IS NOT NULL
                GROUP BY 1, 2
                ORDER BY device_count DESC, canonical
                LIMIT 500
                """,
            )
            rows = cur.fetchall()

    # Attach existing decision (global scope) to each row
    canonical_names = [r[0] for r in rows if r[0]]
    dec_map = {
        (d.canonical_name.lower(), d.client_id, d.device_id): d
        for d in SoftwareDecision.objects.filter(
            tenant_id=1,
            canonical_name__in=canonical_names,
            client__isnull=True,
            device__isnull=True,
        )
    }
    display_rows = []
    for canonical, category, catalog_cats, device_count, latest in rows:
        dec = dec_map.get((canonical.lower(), None, None))
        display_rows.append({
            "canonical": canonical,
            "category": category or (catalog_cats or ""),
            "device_count": device_count,
            "latest": latest,
            "global_decision": dec.decision if dec else "",
        })

    if category_filter:
        display_rows = [r for r in display_rows if category_filter in (r["category"] or "")]

    categories_seen = sorted({r["category"] for r in display_rows if r["category"]})

    return render(request, "software_decisions.html", {
        "rows": display_rows,
        "categories": categories_seen,
        "active_category": category_filter,
        "decision_choices": SoftwareDecision.Decision.choices,
    })


@login_required
@require_POST
@transaction.atomic
def software_decision_create(request: HttpRequest) -> HttpResponse:
    """Create or update a SoftwareDecision at the requested scope
    (global / per-client / per-device). Audited."""
    canonical_name = (request.POST.get("canonical_name") or "").strip()
    decision = (request.POST.get("decision") or "").strip()
    scope = request.POST.get("scope") or "global"
    client_slug = request.POST.get("client_slug") or ""
    device_id_str = request.POST.get("device_id") or ""
    reason = (request.POST.get("reason") or "").strip()

    if not canonical_name or decision not in dict(SoftwareDecision.Decision.choices):
        messages.error(request, "canonical_name and a valid decision are required.")
        return redirect("software_decisions_queue")

    client = None
    device = None
    if scope == "client" and client_slug:
        client = get_object_or_404(Client, slug=client_slug, tenant_id=1)
    elif scope == "device" and device_id_str:
        device = get_object_or_404(Device, id=device_id_str, tenant_id=1)
        client = device.client
    # scope == "global": both remain None

    obj, created = SoftwareDecision.objects.update_or_create(
        tenant_id=1,
        canonical_name=canonical_name,
        client=client,
        device=device,
        defaults={
            "decision": decision,
            "reason": reason,
            "decided_by": request.user,
            "decided_at": timezone.now(),
        },
    )
    _audit(
        request, "software_decision.set", obj.id,
        {},
        {
            "canonical_name": canonical_name,
            "scope": scope,
            "client_id": str(client.id) if client else None,
            "device_id": str(device.id) if device else None,
            "decision": decision,
        },
    )
    messages.success(
        request,
        f"{decision} recorded for {canonical_name} ({scope})."
        + (" Created." if created else " Updated."),
    )
    return redirect("software_decisions_queue")


# ── Identity fidelity (Track 4) ─────────────────────────────────────────


@login_required
def identity_candidates_list(request: HttpRequest) -> HttpResponse:
    """Pending identity_candidates — ambiguous same-client hostname
    resolutions awaiting operator decision. Actions: confirm (merge) or
    reject. Full BLUEPRINT §4.2 workflow."""
    status_filter = request.GET.get("status", "pending")
    qs = IdentityCandidate.objects.filter(tenant_id=1).select_related(
        "device_a", "device_a__client", "device_b", "device_b__client",
    )
    if status_filter != "all":
        qs = qs.filter(status=status_filter)
    candidates = list(qs.order_by("-created_at")[:200])

    # Serial quality signal: devices minted with a placeholder serial —
    # per BLUEPRINT §4.1, these should be flagged.
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """
            SELECT d.id, d.canonical_hostname, d.canonical_serial,
                   c.display_name, c.slug,
                   (SELECT COUNT(*) FROM operations.devices d2
                    WHERE d2.canonical_serial = d.canonical_serial
                      AND d2.deleted_at IS NULL) AS serial_share_count
            FROM operations.devices d
            JOIN operations.clients c ON c.id = d.client_id
            WHERE d.tenant_id = 1 AND d.deleted_at IS NULL
              AND d.canonical_serial <> ''
              AND (
                LOWER(d.canonical_serial) IN (
                  'none','null','default string','system serial number',
                  'chassis serial number','n/a','na','unknown','invalid',
                  'not specified','not applicable','0','00000000','0123456789'
                )
                OR EXISTS(
                  SELECT 1 FROM operations.devices d3
                  WHERE d3.canonical_serial = d.canonical_serial
                    AND d3.id <> d.id AND d3.deleted_at IS NULL
                )
              )
            ORDER BY serial_share_count DESC, c.display_name, d.canonical_hostname
            LIMIT 50
            """,
        )
        serial_warnings = cur.fetchall()

        # Unmatched source groups — count only, for the summary card.
        cur.execute(
            "SELECT COUNT(*) FROM operations.unmatched_source_groups WHERE tenant_id=1"
        )
        (unmatched_groups_count,) = cur.fetchone()

    return render(request, "identity_review.html", {
        "candidates": candidates,
        "active_status": status_filter,
        "status_choices": [("pending", "Pending"), ("confirmed", "Confirmed"),
                          ("rejected", "Rejected"), ("all", "All")],
        "serial_warnings": serial_warnings,
        "unmatched_groups_count": unmatched_groups_count,
    })


def _merge_devices(cur, survivor_id, loser_id: str, reason: str) -> dict:
    """Cascade merge: re-point every reference from loser → survivor,
    tombstone loser. Returns a summary dict of what was moved."""
    counts = {}
    # 1. device_links — repoint if the survivor doesn't already have a
    #    link with the same (source, external_id). If it does, tombstone
    #    the loser's link.
    cur.execute(
        """
        UPDATE operations.device_links dl
        SET device_id = %s
        WHERE dl.tenant_id = 1
          AND dl.device_id = %s
          AND NOT EXISTS(
              SELECT 1 FROM operations.device_links dl2
              WHERE dl2.tenant_id = dl.tenant_id
                AND dl2.source_id = dl.source_id
                AND dl2.external_id = dl.external_id
                AND dl2.device_id = %s
          )
        """,
        (survivor_id, loser_id, survivor_id),
    )
    counts["device_links_moved"] = cur.rowcount
    cur.execute(
        "DELETE FROM operations.device_links WHERE tenant_id=1 AND device_id=%s",
        (loser_id,),
    )
    counts["device_links_deleted_dupes"] = cur.rowcount

    # 2. entity_observations
    cur.execute(
        "UPDATE operations.entity_observations SET device_id=%s WHERE tenant_id=1 AND device_id=%s",
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


@login_required
@require_POST
@transaction.atomic
def identity_candidate_confirm(request: HttpRequest, candidate_id) -> HttpResponse:
    """Confirm = merge. Survivor = the device with a Ninja link, else
    the older by created_at."""
    cand = get_object_or_404(
        IdentityCandidate, id=candidate_id, tenant_id=1, status="pending",
    )
    dev_a, dev_b = cand.device_a, cand.device_b

    # Survivor rule
    with connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """
            SELECT dl.device_id FROM operations.device_links dl
            JOIN operations.sources s ON s.id = dl.source_id AND s.name='Ninja'
            WHERE dl.tenant_id=1 AND dl.device_id IN (%s, %s)
            """,
            (dev_a.id, dev_b.id),
        )
        ninja_owners = {row[0] for row in cur.fetchall()}
    if dev_a.id in ninja_owners and dev_b.id not in ninja_owners:
        survivor, loser = dev_a, dev_b
    elif dev_b.id in ninja_owners and dev_a.id not in ninja_owners:
        survivor, loser = dev_b, dev_a
    else:
        # Same Ninja status → older wins
        survivor, loser = (dev_a, dev_b) if dev_a.created_at <= dev_b.created_at else (dev_b, dev_a)

    with connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        counts = _merge_devices(cur, survivor.id, loser.id, "operator.merged")

    cand.status = "confirmed"
    cand.resolved_at = timezone.now()
    cand.resolved_by = request.user.get_username()
    cand.save(update_fields=["status", "resolved_at", "resolved_by"])

    _audit(
        request, "identity_candidate.confirm", cand.id,
        {"status": "pending", "device_a": str(dev_a.id), "device_b": str(dev_b.id)},
        {
            "status": "confirmed", "survivor_id": str(survivor.id),
            "loser_id": str(loser.id), "counts": counts,
        },
    )
    messages.success(
        request,
        f"Merged {loser.canonical_hostname} into {survivor.canonical_hostname}. "
        f"Moved {counts.get('device_links_moved',0)} links, "
        f"{counts.get('observations_moved',0)} observations, "
        f"{counts.get('findings_moved',0)} findings.",
    )
    return redirect("identity_candidates_list")


@login_required
@require_POST
@transaction.atomic
def identity_candidate_reject(request: HttpRequest, candidate_id) -> HttpResponse:
    cand = get_object_or_404(
        IdentityCandidate, id=candidate_id, tenant_id=1, status="pending",
    )
    cand.status = "rejected"
    cand.resolved_at = timezone.now()
    cand.resolved_by = request.user.get_username()
    cand.save(update_fields=["status", "resolved_at", "resolved_by"])
    _audit(
        request, "identity_candidate.reject", cand.id,
        {"status": "pending"},
        {"status": "rejected"},
    )
    messages.success(request, "Candidate rejected — pair excluded from future creation.")
    return redirect("identity_candidates_list")


# ── Requirement profiles (Track C.6 admin knob) ─────────────────────────────


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
            tenant_id=1, requirement_profile=p, deleted_at__isnull=True,
        ).count()
        rows.append({
            "profile": p,
            "items": list(p.items.all().order_by("device_scope", "entity_type", "platform")),
            "client_count": client_count,
        })
    return render(request, "requirement_profiles.html", {"rows": rows})


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
        request, "client.requirement_profile.assign", client.id,
        {"requirement_profile_id": str(prev_profile) if prev_profile else None},
        {"requirement_profile_id": str(client.requirement_profile_id) if client.requirement_profile_id else None},
    )
    messages.success(
        request,
        f"Requirement profile for {client.display_name} set to "
        f"{client.requirement_profile.name if client.requirement_profile else '— global fallback —'}.",
    )
    return redirect("org_index", org_slug=client.slug)


# ── Notification dispatcher UI (Track 2.4) ──────────────────────────────


@login_required
def notification_rules_list(request: HttpRequest) -> HttpResponse:
    rules = list(
        NotificationRule.objects.filter(tenant_id=1)
        .select_related("finding_type", "route", "client")
        .order_by("finding_type__name", "client__display_name")
    )
    events = list(
        NotificationEvent.objects.filter(tenant_id=1)
        .order_by("-sent_at")[:50]
    )
    routes = list(NotificationRoute.objects.filter(tenant_id=1))
    return render(request, "notification_rules.html", {
        "rules": rules,
        "events": events,
        "routes": routes,
        "enabled_count": sum(1 for r in rules if r.enabled),
        "disabled_count": sum(1 for r in rules if not r.enabled),
    })


@login_required
@require_POST
@transaction.atomic
def notification_rule_toggle(request: HttpRequest, rule_id) -> HttpResponse:
    rule = get_object_or_404(NotificationRule, id=rule_id, tenant_id=1)
    prev = rule.enabled
    rule.enabled = not prev
    rule.save(update_fields=["enabled"])
    _audit(
        request, "notification_rule.toggle", rule.id,
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
    return render(request, "notification_suppressions.html", {"suppressions": rows})
