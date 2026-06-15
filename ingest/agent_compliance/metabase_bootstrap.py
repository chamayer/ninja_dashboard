"""Provision the Agent Compliance Metabase collection and dashboards.

This module builds the dashboard surface from scratch around a simple
human workflow:

* Today: what needs attention right now.
* Devices: device-level fixes and ignore/restore.
* Alerts: notification readiness and delivery history.
* Customers: customer names across platforms and customer-name review.
* Setup: requirements, alert enablement, routes, and sources.
* Health: source health and data confidence.
* Debug: raw leftovers and low-level troubleshooting.

No visible table field should contain a raw URL. Action cells are plain
labels, and the link target lives in the card visualization settings.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import httpx

from ingest import db
from ingest.config import settings

log = logging.getLogger(__name__)

ACTION_BASE_URL = settings.AGENT_COMPLIANCE_ACTION_BASE_URL.rstrip("/")
COLLECTION_NAME = "Agent Compliance"

DASH_TODAY = "Agent Compliance - Today"
DASH_DEVICES = "Agent Compliance - Devices"
DASH_DEVICE_DRILLDOWN = "Agent Compliance - Device drilldown"
DASH_ALERTS = "Agent Compliance - Alerts"
DASH_CUSTOMERS = "Agent Compliance - Customers"
DASH_SETUP = "Agent Compliance - Setup"
DASH_HEALTH = "Agent Compliance - Health"
DASH_DEBUG = "Agent Compliance - Debug"

# ── Devices dashboard parameter slugs + IDs ─────────────────────────
# These slugs also act as URL query keys for cross-card drill-through.
PARAM_CUSTOMER = "p_dev_customer"
PARAM_MISSING = "p_dev_missing"
PARAM_ONLINE_IN = "p_dev_online_in"
PARAM_STATE = "p_dev_state"
PARAM_AV_EXEMPT = "p_dev_av"
PARAM_OS_FAMILY = "p_dev_os_family"
PARAM_DEVICE_TYPE = "p_dev_device_type"

# Device drilldown — dashboard scoped to one (customer, host) pair.
PARAM_DD_CUSTOMER = "p_dd_customer"
PARAM_DD_HOST = "p_dd_host"

# Alerts dashboard.
PARAM_AL_CUSTOMER = "p_al_customer"
PARAM_AL_SEVERITY = "p_al_severity"
PARAM_AL_TYPE = "p_al_type"

# Customers dashboard.
PARAM_CU_REVIEW_NAME = "p_cu_review_name"

PLATFORM_VALUES = ["Ninja", "ScreenConnect", "SentinelOne", "LogMeIn"]
STATE_VALUES = ["Fix now", "Review", "Stale", "Ignored", "Good"]
AV_EXEMPT_VALUES = ["Yes", "No"]
OS_FAMILY_VALUES = [
    "Windows 11", "Windows 10", "Windows 8.1", "Windows 8", "Windows 7",
    "Windows (other)",
    "Windows Server 2025", "Windows Server 2022", "Windows Server 2019",
    "Windows Server 2016", "Windows Server 2012 R2", "Windows Server 2012",
    "Windows Server 2008 R2", "Windows Server 2008",
    "Windows Server (other)",
    "Unknown", "Other",
]
DEVICE_TYPE_VALUES = ["Workstation", "Server"]
SEVERITY_VALUES = ["critical", "high", "medium", "info"]
FINDING_TYPE_VALUES = [
    "missing_required_platform",
    "stale_required_platform",
    "cross_client_conflict",
    "source_failure",
]

NAV_ORDER = [DASH_TODAY, DASH_DEVICES, DASH_ALERTS, DASH_CUSTOMERS, DASH_SETUP, DASH_HEALTH, DASH_DEBUG]
NAV_LABELS = {
    DASH_TODAY: "Today",
    DASH_DEVICES: "Devices",
    DASH_ALERTS: "Alerts",
    DASH_CUSTOMERS: "Customers",
    DASH_SETUP: "Setup",
    DASH_HEALTH: "Health",
    DASH_DEBUG: "Debug",
}
NAV_HEIGHT = 2
SECTION_HEADER_HEIGHT = 1


def _card(
    key: str,
    name: str,
    display: str,
    query: str,
    row: int,
    col: int,
    size_x: int,
    size_y: int,
    click_behavior: dict[str, Any] | None = None,
    column_click_behaviors: dict[str, dict[str, Any]] | None = None,
    column_widths: dict[str, int] | None = None,
    template_tags: dict[str, dict[str, Any]] | None = None,
    param_mappings: dict[str, list[Any]] | None = None,
) -> dict[str, Any]:
    card = {
        "key": key,
        "name": name,
        "display": display,
        "query": query,
        "row": row,
        "col": col,
        "size_x": size_x,
        "size_y": size_y,
    }
    if click_behavior is not None:
        card["click_behavior"] = click_behavior
    if column_click_behaviors is not None:
        card["column_click_behaviors"] = column_click_behaviors
    if column_widths is not None:
        card["column_widths"] = column_widths
    if template_tags is not None:
        card["template_tags"] = template_tags
    if param_mappings is not None:
        card["param_mappings"] = param_mappings
    return card


def _dashboard_link(
    target: str, params: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Cell click navigates to a dashboard. With `params`, columns from
    the row are passed through as dashboard URL parameters — Metabase
    binds them to dashboard filters with matching slugs, so a click on
    `Missing=SentinelOne` opens Devices already scoped to that value."""
    spec: dict[str, Any] = {"target": target}
    if params:
        spec["params"] = params
    return spec


def _url_template(path: str, params: list[tuple[str, str]], confirm: bool = True) -> str:
    query = "&".join(f"{key}={{{{{field}}}}}" for key, field in params)
    if confirm:
        suffix = f"?{query}&confirm=1" if query else "?confirm=1"
    else:
        suffix = f"?{query}" if query else ""
    return f"{ACTION_BASE_URL}{path}{suffix}"


def _build_click_behavior_json(
    spec: dict[str, Any],
    dash_id_by_name: dict[str, int],
) -> dict[str, Any] | None:
    target = spec.get("target")
    if target:
        target_id = dash_id_by_name.get(target)
        if target_id is None:
            log.warning("Click behavior: unknown target dashboard %r", target)
            return None
        params = spec.get("params") or []
        if params:
            qs = "&".join(f"{key}={{{{{field}}}}}" for key, field in params)
            link = f"/dashboard/{target_id}?{qs}"
        else:
            link = f"/dashboard/{target_id}"
        return {
            "type": "link",
            "linkType": "url",
            "linkTemplate": link,
        }

    url_template = spec.get("url_template")
    if url_template:
        return {
            "type": "link",
            "linkType": "url",
            "linkTemplate": url_template,
        }
    return None


# ── Filter parameter helpers ────────────────────────────────────────

def _param_multiselect(
    pid: str, name: str, slug: str, values: list[str],
) -> dict[str, Any]:
    """Dashboard parameter widget: multi-select dropdown backed by a
    static value list. SQL clauses written as
    `[[AND col IN ({{slug}})]]` are skipped when nothing is selected
    and ORed across selections when one or more values are chosen."""
    return {
        "id": pid,
        "name": name,
        "slug": slug,
        "type": "category",
        "values_query_type": "list",
        "values_source_type": "static-list",
        "values_source_config": {"values": [[v] for v in values]},
        "isMultiSelect": True,
    }


def _tag(slug: str, display_name: str) -> dict[str, Any]:
    """Template tag declaration that goes inside `template-tags` on a
    native query. Slug is the placeholder used in SQL (`{{slug}}`)."""
    return {
        "id": f"tt_{slug}",
        "name": slug,
        "display-name": display_name,
        "type": "text",
    }


def _mapping(slug: str) -> list[Any]:
    """Target shape that binds a dashboard parameter to a card-level
    template tag. Same on every card that consumes the same slug."""
    return ["variable", ["template-tag", slug]]


def _fetch_customer_values() -> list[str]:
    """List of active customer names for the Customer dropdown. Mirrors
    the same filter as the customer-directory card so the dropdown
    stays consistent with what the dashboards actually show."""
    with db.transaction() as cur:
        cur.execute(
            """
            SELECT client_name
            FROM ninja_agent_compliance.clients
            WHERE enabled
              AND source NOT IN ('alignment', 'demoted')
              AND lower(trim(client_name)) NOT IN
                  ('default site', 'unknown', 'various', '.default')
            ORDER BY client_name
            """
        )
        return [r[0] for r in cur.fetchall() if r[0]]


def _param_text(pid: str, name: str, slug: str) -> dict[str, Any]:
    """Free-text dashboard parameter. Used for drilldown scoping where
    the value is passed via URL params from a row click (no dropdown
    population needed)."""
    return {
        "id": pid,
        "name": name,
        "slug": slug,
        "type": "category",
    }


def _build_devices_parameters() -> list[dict[str, Any]]:
    customer_values = _fetch_customer_values()
    return [
        _param_multiselect(PARAM_CUSTOMER, "Customer", "customer", customer_values),
        _param_multiselect(PARAM_MISSING, "Missing platform", "missing", PLATFORM_VALUES),
        _param_multiselect(PARAM_ONLINE_IN, "Online in", "online_in", PLATFORM_VALUES),
        _param_multiselect(PARAM_STATE, "State", "state", STATE_VALUES),
        _param_multiselect(PARAM_AV_EXEMPT, "NO AV", "av", AV_EXEMPT_VALUES),
        _param_multiselect(PARAM_OS_FAMILY, "OS family", "os_family", OS_FAMILY_VALUES),
        _param_multiselect(PARAM_DEVICE_TYPE, "Device type", "device_type", DEVICE_TYPE_VALUES),
    ]


# Template tags shared across every Devices card that consumes any
# filter. Cards opt into a subset via `param_mappings`; tags that
# aren't mapped are still declared but unused, which Metabase tolerates.
_DEVICES_FILTER_TAGS = {
    "customer": _tag("customer", "Customer"),
    "missing": _tag("missing", "Missing platform"),
    "online_in": _tag("online_in", "Online in"),
    "state": _tag("state", "State"),
    "av": _tag("av", "NO AV"),
    "os_family": _tag("os_family", "OS family"),
    "device_type": _tag("device_type", "Device type"),
}


def _build_drilldown_parameters() -> list[dict[str, Any]]:
    return [
        _param_text(PARAM_DD_CUSTOMER, "Customer", "customer"),
        _param_text(PARAM_DD_HOST, "Device", "host"),
    ]


_DRILLDOWN_FILTER_TAGS = {
    "customer": _tag("customer", "Customer"),
    "host": _tag("host", "Device"),
}


def _build_alerts_parameters() -> list[dict[str, Any]]:
    return [
        _param_multiselect(PARAM_AL_CUSTOMER, "Customer", "customer", _fetch_customer_values()),
        _param_multiselect(PARAM_AL_SEVERITY, "Severity", "severity", SEVERITY_VALUES),
        _param_multiselect(PARAM_AL_TYPE, "Finding type", "finding_type", FINDING_TYPE_VALUES),
    ]


def _build_customers_parameters() -> list[dict[str, Any]]:
    return [
        _param_text(PARAM_CU_REVIEW_NAME, "Name to review", "review_name"),
    ]


_CUSTOMERS_FILTER_TAGS = {
    "review_name": _tag("review_name", "Name to review"),
}


_ALERTS_FILTER_TAGS = {
    "customer": _tag("customer", "Customer"),
    "severity": _tag("severity", "Severity"),
    "finding_type": _tag("finding_type", "Finding type"),
}


_LEGACY_DASHBOARDS_UNUSED = [
    {
        "name": DASH_TODAY,
        "cards": [
            _card(
                "compliant_percent",
                "Compliant %",
                "scalar",
                """
                    SELECT ROUND(
                        COUNT(*) FILTER (WHERE is_compliant) * 100.0 / NULLIF(COUNT(*), 0),
                        1
                    ) AS "Compliant %"
                    FROM ninja_agent_compliance.v_compliance_matrix_current
                """,
                0, 0, 4, 4,
                click_behavior=_dashboard_link(DASH_DEVICES),
            ),
            _card(
                "devices_to_fix",
                "Devices to fix",
                "scalar",
                """
                    SELECT COUNT(*) AS "Devices to fix"
                    FROM ninja_agent_compliance.v_remediation_candidates
                """,
                0, 4, 4, 4,
                click_behavior=_dashboard_link(DASH_DEVICES),
            ),
            _card(
                "sources_down",
                "Source work",
                "scalar",
                """
                    SELECT COUNT(*) AS "Source work"
                    FROM ninja_agent_compliance.v_source_work_current
                """,
                0, 8, 4, 4,
                click_behavior=_dashboard_link(DASH_HEALTH),
            ),
            _card(
                "names_to_review",
                "Customer names to review",
                "scalar",
                """
                    SELECT COUNT(*) AS "Customer names to review"
                    FROM ninja_agent_compliance.v_org_candidates_current
                """,
                0, 12, 4, 4,
                click_behavior=_dashboard_link(DASH_CUSTOMERS),
            ),
            _card(
                "active_alerts",
                "Current findings",
                "scalar",
                """
                    SELECT COUNT(*) AS "Current findings"
                    FROM ninja_agent_compliance.v_active_findings
                """,
                0, 20, 4, 4,
                click_behavior=_dashboard_link(DASH_ALERTS),
            ),
            _card(
                "ignored_devices_count",
                "Ignored devices",
                "scalar",
                """
                    SELECT COUNT(*) AS "Ignored devices"
                    FROM ninja_agent_compliance.v_device_ignores_current
                """,
                0, 16, 4, 4,
                click_behavior=_dashboard_link(DASH_DEVICES),
            ),
            _card(
                "new_customers_found",
                "New customer names found",
                "table",
                """
                    SELECT
                        candidate_name AS "Customer name",
                        platform AS "Found in",
                        COALESCE(NULLIF(source_name, ''), 'Unknown') AS "Source",
                        COALESCE(TO_CHAR(last_seen_at, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "Last seen",
                        'Review' AS "Action"
                    FROM ninja_agent_compliance.v_org_candidates_current
                    ORDER BY last_seen_at DESC, candidate_name
                    LIMIT 15
                """,
                4, 0, 24, 6,
                column_click_behaviors={
                    "Action": _dashboard_link(DASH_CUSTOMERS),
                },
            ),
        ],
    },
    {
        "name": DASH_DEVICES,
        "parameters_builder": _build_devices_parameters,
        "section_headers": [
            {"row": 0,  "text": "### Triage"},
            {"row": 16, "text": "### Gap analysis"},
            {"row": 32, "text": "### Maintenance"},
            {"row": 40, "text": "### Full device list"},
        ],
        "cards": [
            _card(
                "device_queue",
                "Need action",
                "table",
                """
                    WITH queue AS (
                        SELECT
                            m.*,
                            ARRAY_REMOVE(ARRAY[
                                CASE WHEN m.ninja_online THEN 'Ninja' END,
                                CASE WHEN m.screenconnect_online THEN 'ScreenConnect' END,
                                CASE WHEN m.sentinelone_online THEN 'SentinelOne' END,
                                CASE WHEN m.logmein_online THEN 'LogMeIn' END
                            ], NULL) AS online_now,
                            GREATEST(
                                m.ninja_last_seen,
                                m.screenconnect_last_seen,
                                m.sentinelone_last_seen,
                                m.logmein_last_seen
                            ) AS last_seen_anywhere
                        FROM ninja_agent_compliance.compliance_matrix_current m
                        WHERE NOT m.is_unknown
                          -- Include both noncompliant and degraded-but-compliant rows.
                          AND (NOT m.is_compliant OR m.is_degraded)
                          AND NOT EXISTS (
                              SELECT 1
                              FROM ninja_agent_compliance.alert_suppressions s
                              WHERE s.enabled
                                AND (s.client_id IS NULL OR s.client_id = m.client_id)
                                AND (s.norm_name IS NULL OR s.norm_name = m.norm_name)
                                AND (s.expires_at IS NULL OR s.expires_at > now())
                          )
                    )
                    SELECT
                        client_name AS "Customer",
                        hostname AS "Device",
                        device_type AS "Type",
                        COALESCE(array_to_string(missing_required_platforms, ', '), 'None') AS "Need",
                        COALESCE(array_to_string(observed_platforms, ', '), '-') AS "Found in",
                        COALESCE(TO_CHAR(last_seen_anywhere, 'YYYY-MM-DD HH24:MI'), 'never') AS "Last seen",
                        CASE
                            WHEN is_degraded THEN 'Degraded'
                            WHEN is_stale THEN 'Stale'
                            ELSE 'Review'
                        END AS "State",
                        CASE WHEN s1_exempt THEN 'Yes' ELSE 'No' END AS "NO AV",
                        'Ignore' AS "Action"
                    FROM queue
                    WHERE 1=1
                      [[AND client_name IN ({{customer}})]]
                      [[AND EXISTS (
                          SELECT 1
                          FROM unnest(missing_required_platforms) AS missing_filter(platform)
                          WHERE missing_filter.platform IN ({{missing}})
                      )]]
                      [[AND EXISTS (
                          SELECT 1
                          FROM unnest(online_now) AS online_filter(platform)
                          WHERE online_filter.platform IN ({{online_in}})
                      )]]
                      [[AND (
                          CASE
                              WHEN is_degraded THEN 'Degraded'
                              WHEN is_stale THEN 'Stale'
                              ELSE 'Review'
                          END
                      ) IN ({{state}})]]
                      [[AND (CASE WHEN s1_exempt THEN 'Yes' ELSE 'No' END) IN ({{av}})]]
                    ORDER BY client_name, hostname
                    LIMIT 500
                """,
                0, 0, 24, 10,
                column_click_behaviors={
                    "Device": _dashboard_link(
                        DASH_DEVICE_DRILLDOWN,
                        params=[("customer", "Customer"), ("host", "Device")],
                    ),
                    "Action": {
                        "url_template": _url_template(
                            "/a/ig",
                            [("client", "Customer"), ("host", "Device")],
                        ),
                    },
                },
                template_tags={
                    "customer": _DEVICES_FILTER_TAGS["customer"],
                    "missing": _DEVICES_FILTER_TAGS["missing"],
                    "online_in": _DEVICES_FILTER_TAGS["online_in"],
                    "state": _DEVICES_FILTER_TAGS["state"],
                    "av": _DEVICES_FILTER_TAGS["av"],
                },
                param_mappings={
                    PARAM_CUSTOMER: _mapping("customer"),
                    PARAM_MISSING: _mapping("missing"),
                    PARAM_ONLINE_IN: _mapping("online_in"),
                    PARAM_STATE: _mapping("state"),
                    PARAM_AV_EXEMPT: _mapping("av"),
                },
            ),
            _card(
                "all_current_devices",
                "All current devices",
                "table",
                """
                    WITH devices AS (
                        SELECT
                            m.*,
                            ARRAY_REMOVE(ARRAY[
                                CASE WHEN m.ninja_online THEN 'Ninja' END,
                                CASE WHEN m.screenconnect_online THEN 'ScreenConnect' END,
                                CASE WHEN m.sentinelone_online THEN 'SentinelOne' END,
                                CASE WHEN m.logmein_online THEN 'LogMeIn' END
                            ], NULL) AS online_now,
                            GREATEST(
                                m.ninja_last_seen,
                                m.screenconnect_last_seen,
                                m.sentinelone_last_seen,
                                m.logmein_last_seen
                            ) AS last_seen_anywhere,
                            EXISTS (
                                SELECT 1
                                FROM ninja_agent_compliance.alert_suppressions s
                                WHERE s.enabled
                                  AND (s.client_id IS NULL OR s.client_id = m.client_id)
                                  AND (s.norm_name IS NULL OR s.norm_name = m.norm_name)
                                  AND (s.expires_at IS NULL OR s.expires_at > now())
                            ) AS ignored
                        FROM ninja_agent_compliance.compliance_matrix_current m
                    )
                    SELECT
                        client_name AS "Customer",
                        hostname AS "Device",
                        device_type AS "Type",
                        CASE
                            WHEN is_unknown THEN 'Unknown'
                            WHEN is_degraded THEN 'Degraded'
                            WHEN is_stale THEN 'Stale'
                            WHEN NOT is_compliant THEN 'Review'
                            ELSE 'Good'
                        END AS "State",
                        CASE WHEN ignored THEN 'Yes' ELSE 'No' END AS "Ignored",
                        CASE WHEN s1_exempt THEN 'Yes' ELSE 'No' END AS "NO AV",
                        COALESCE(array_to_string(missing_required_platforms, ', '), 'None') AS "Missing",
                        COALESCE(array_to_string(observed_platforms, ', '), '-') AS "Found in",
                        COALESCE(array_to_string(online_now, ', '), '-') AS "Online in",
                        COALESCE(TO_CHAR(last_seen_anywhere, 'YYYY-MM-DD HH24:MI'), 'never') AS "Last seen"
                    FROM devices
                    WHERE 1=1
                      [[AND client_name IN ({{customer}})]]
                      [[AND EXISTS (
                          SELECT 1
                          FROM unnest(missing_required_platforms) AS missing_filter(platform)
                          WHERE missing_filter.platform IN ({{missing}})
                      )]]
                      [[AND EXISTS (
                          SELECT 1
                          FROM unnest(online_now) AS online_filter(platform)
                          WHERE online_filter.platform IN ({{online_in}})
                      )]]
                      [[AND (
                          CASE
                              WHEN is_unknown THEN 'Unknown'
                              WHEN is_degraded THEN 'Degraded'
                              WHEN is_stale THEN 'Stale'
                              WHEN NOT is_compliant THEN 'Review'
                              ELSE 'Good'
                          END
                      ) IN ({{state}})]]
                      [[AND (CASE WHEN s1_exempt THEN 'Yes' ELSE 'No' END) IN ({{av}})]]
                    ORDER BY client_name, hostname
                    LIMIT 1000
                """,
                41, 0, 24, 8,
                column_click_behaviors={
                    "Device": _dashboard_link(
                        DASH_DEVICE_DRILLDOWN,
                        params=[("customer", "Customer"), ("host", "Device")],
                    ),
                },
                template_tags={
                    "customer": _DEVICES_FILTER_TAGS["customer"],
                    "missing": _DEVICES_FILTER_TAGS["missing"],
                    "online_in": _DEVICES_FILTER_TAGS["online_in"],
                    "state": _DEVICES_FILTER_TAGS["state"],
                    "av": _DEVICES_FILTER_TAGS["av"],
                },
                param_mappings={
                    PARAM_CUSTOMER: _mapping("customer"),
                    PARAM_MISSING: _mapping("missing"),
                    PARAM_ONLINE_IN: _mapping("online_in"),
                    PARAM_STATE: _mapping("state"),
                    PARAM_AV_EXEMPT: _mapping("av"),
                },
            ),
            _card(
                "active_gaps_summary",
                "Missing but online elsewhere",
                "table",
                """
                    WITH gaps AS (
                        SELECT
                            m.client_id,
                            m.client_name,
                            m.norm_name,
                            m.s1_exempt,
                            missing.platform AS missing_platform,
                            online.platform AS online_platform
                        FROM ninja_agent_compliance.v_compliance_matrix_current m
                        CROSS JOIN LATERAL unnest(m.missing_required_platforms) AS missing(platform)
                        JOIN LATERAL (
                            VALUES
                                ('Ninja', m.ninja_online),
                                ('ScreenConnect', m.screenconnect_online),
                                ('SentinelOne', m.sentinelone_online),
                                ('LogMeIn', m.logmein_online)
                        ) AS online(platform, is_online)
                          ON online.is_online IS TRUE
                         AND online.platform <> missing.platform
                        WHERE NOT m.is_stale
                          AND NOT m.is_unknown
                    )
                    SELECT
                        missing_platform AS "Missing",
                        online_platform AS "Online in",
                        COUNT(DISTINCT (client_id, norm_name)) AS "Devices"
                    FROM gaps
                    WHERE 1=1
                      [[AND client_name IN ({{customer}})]]
                      [[AND missing_platform IN ({{missing}})]]
                      [[AND online_platform IN ({{online_in}})]]
                      [[AND (CASE WHEN s1_exempt THEN 'Yes' ELSE 'No' END) IN ({{av}})]]
                      -- Default: hide exempt devices from S1-gap counts.
                      -- The user can override by selecting Yes in the AV exempt filter.
                      AND (
                          missing_platform <> 'SentinelOne'
                          OR NOT s1_exempt
                          [[OR (CASE WHEN s1_exempt THEN 'Yes' ELSE 'No' END) IN ({{av}})]]
                      )
                    GROUP BY missing_platform, online_platform
                    ORDER BY "Devices" DESC, missing_platform, online_platform
                    LIMIT 500
                """,
                16, 0, 12, 6,
                click_behavior=_dashboard_link(
                    DASH_DEVICES,
                    params=[("missing", "Missing"), ("online_in", "Online in")],
                ),
                template_tags={
                    "customer": _DEVICES_FILTER_TAGS["customer"],
                    "missing": _DEVICES_FILTER_TAGS["missing"],
                    "online_in": _DEVICES_FILTER_TAGS["online_in"],
                    "av": _DEVICES_FILTER_TAGS["av"],
                },
                param_mappings={
                    PARAM_CUSTOMER: _mapping("customer"),
                    PARAM_MISSING: _mapping("missing"),
                    PARAM_ONLINE_IN: _mapping("online_in"),
                    PARAM_AV_EXEMPT: _mapping("av"),
                },
            ),
            _card(
                "active_gaps_by_missing",
                "Active gaps by missing platform",
                "bar",
                """
                    WITH gaps AS (
                        SELECT DISTINCT
                            m.client_id,
                            m.client_name,
                            m.norm_name,
                            m.s1_exempt,
                            missing.platform AS missing_platform
                        FROM ninja_agent_compliance.v_compliance_matrix_current m
                        CROSS JOIN LATERAL unnest(m.missing_required_platforms) AS missing(platform)
                        JOIN LATERAL (
                            VALUES
                                ('Ninja', m.ninja_online),
                                ('ScreenConnect', m.screenconnect_online),
                                ('SentinelOne', m.sentinelone_online),
                                ('LogMeIn', m.logmein_online)
                        ) AS online(platform, is_online)
                          ON online.is_online IS TRUE
                         AND online.platform <> missing.platform
                        WHERE NOT m.is_stale
                          AND NOT m.is_unknown
                    )
                    SELECT
                        missing_platform AS "Missing",
                        COUNT(*) AS "Devices"
                    FROM gaps
                    WHERE 1=1
                      [[AND client_name IN ({{customer}})]]
                      [[AND missing_platform IN ({{missing}})]]
                      [[AND (CASE WHEN s1_exempt THEN 'Yes' ELSE 'No' END) IN ({{av}})]]
                      AND (
                          missing_platform <> 'SentinelOne'
                          OR NOT s1_exempt
                          [[OR (CASE WHEN s1_exempt THEN 'Yes' ELSE 'No' END) IN ({{av}})]]
                      )
                    GROUP BY missing_platform
                    ORDER BY "Devices" DESC
                """,
                16, 12, 12, 6,
                click_behavior=_dashboard_link(
                    DASH_DEVICES, params=[("missing", "Missing")],
                ),
                template_tags={
                    "customer": _DEVICES_FILTER_TAGS["customer"],
                    "missing": _DEVICES_FILTER_TAGS["missing"],
                    "av": _DEVICES_FILTER_TAGS["av"],
                },
                param_mappings={
                    PARAM_CUSTOMER: _mapping("customer"),
                    PARAM_MISSING: _mapping("missing"),
                    PARAM_AV_EXEMPT: _mapping("av"),
                },
            ),
            _card(
                "active_platform_gap_details",
                "Active platform gap details",
                "table",
                """
                    WITH gaps AS (
                        SELECT
                            m.client_name,
                            m.hostname,
                            m.device_type,
                            m.os_name,
                            m.s1_exempt,
                            m.required_platforms,
                            m.observed_platforms,
                            missing.platform AS missing_platform,
                            online.platform AS online_platform,
                            online.last_seen_at
                        FROM ninja_agent_compliance.v_compliance_matrix_current m
                        CROSS JOIN LATERAL unnest(m.missing_required_platforms) AS missing(platform)
                        JOIN LATERAL (
                            VALUES
                                ('Ninja', m.ninja_online, m.ninja_last_seen),
                                ('ScreenConnect', m.screenconnect_online, m.screenconnect_last_seen),
                                ('SentinelOne', m.sentinelone_online, m.sentinelone_last_seen),
                                ('LogMeIn', m.logmein_online, m.logmein_last_seen)
                        ) AS online(platform, is_online, last_seen_at)
                          ON online.is_online IS TRUE
                         AND online.platform <> missing.platform
                        WHERE NOT m.is_stale
                          AND NOT m.is_unknown
                    )
                    SELECT
                        client_name AS "Customer",
                        hostname AS "Device",
                        device_type AS "Type",
                        COALESCE(NULLIF(os_name, ''), '') AS "OS",
                        CASE WHEN s1_exempt THEN 'Yes' ELSE 'No' END AS "NO AV",
                        missing_platform AS "Missing",
                        online_platform AS "Online in",
                        COALESCE(TO_CHAR(last_seen_at, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "Last online",
                        COALESCE(array_to_string(required_platforms, ', '), '') AS "Required",
                        COALESCE(array_to_string(observed_platforms, ', '), '') AS "Found in",
                        'Ignore' AS "Action"
                    FROM gaps
                    WHERE 1=1
                      [[AND client_name IN ({{customer}})]]
                      [[AND missing_platform IN ({{missing}})]]
                      [[AND online_platform IN ({{online_in}})]]
                      [[AND (CASE WHEN s1_exempt THEN 'Yes' ELSE 'No' END) IN ({{av}})]]
                      AND (
                          missing_platform <> 'SentinelOne'
                          OR NOT s1_exempt
                          [[OR (CASE WHEN s1_exempt THEN 'Yes' ELSE 'No' END) IN ({{av}})]]
                      )
                    ORDER BY missing_platform, online_platform, client_name, hostname
                    LIMIT 500
                """,
                22, 0, 24, 10,
                column_click_behaviors={
                    "Device": _dashboard_link(
                        DASH_DEVICE_DRILLDOWN,
                        params=[("customer", "Customer"), ("host", "Device")],
                    ),
                    "Action": {
                        "url_template": _url_template(
                            "/a/ig",
                            [("client", "Customer"), ("host", "Device")],
                        ),
                    },
                },
                template_tags={
                    "customer": _DEVICES_FILTER_TAGS["customer"],
                    "missing": _DEVICES_FILTER_TAGS["missing"],
                    "online_in": _DEVICES_FILTER_TAGS["online_in"],
                    "av": _DEVICES_FILTER_TAGS["av"],
                },
                param_mappings={
                    PARAM_CUSTOMER: _mapping("customer"),
                    PARAM_MISSING: _mapping("missing"),
                    PARAM_ONLINE_IN: _mapping("online_in"),
                    PARAM_AV_EXEMPT: _mapping("av"),
                },
            ),
            _card(
                "stale_by_customer",
                "Stale devices by customer",
                "table",
                """
                    SELECT
                        client_name AS "Customer",
                        COUNT(*) AS "Stale devices",
                        COALESCE(
                            TO_CHAR(
                                MAX(GREATEST(
                                    ninja_last_seen,
                                    screenconnect_last_seen,
                                    sentinelone_last_seen,
                                    logmein_last_seen
                                )),
                                'YYYY-MM-DD HH24:MI'
                            ),
                            'Unknown'
                        ) AS "Last seen anywhere",
                        'Bulk ignore' AS "Action"
                    FROM ninja_agent_compliance.v_remediation_candidates
                    WHERE is_stale
                      AND norm_name IS NOT NULL
                      [[AND client_name IN ({{customer}})]]
                    GROUP BY client_name
                    HAVING COUNT(*) > 0
                    ORDER BY COUNT(*) DESC, client_name
                    LIMIT 100
                """,
                10, 0, 24, 6,
                column_click_behaviors={
                    "Action": {
                        "url_template": _url_template(
                            "/a/bs",
                            [("client", "Customer")],
                        ),
                    },
                },
                template_tags={
                    "customer": _DEVICES_FILTER_TAGS["customer"],
                },
                param_mappings={
                    PARAM_CUSTOMER: _mapping("customer"),
                },
            ),
            _card(
                "ignored_devices",
                "Ignored",
                "table",
                """
                    SELECT
                        client_name AS "Customer",
                        COALESCE(NULLIF(display_name, ''), norm_name) AS "Device",
                        COALESCE(NULLIF(reason, ''), 'Ignored') AS "Reason",
                        COALESCE(TO_CHAR(updated_at, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "Updated",
                        'Restore' AS "Action"
                    FROM ninja_agent_compliance.v_device_ignores_current
                    WHERE 1=1
                      [[AND client_name IN ({{customer}})]]
                    ORDER BY updated_at DESC, client_name, display_name
                    LIMIT 200
                """,
                32, 0, 24, 6,
                column_click_behaviors={
                    "Device": _dashboard_link(
                        DASH_DEVICE_DRILLDOWN,
                        params=[("customer", "Customer"), ("host", "Device")],
                    ),
                    "Action": {
                        "url_template": _url_template(
                            "/a/ui",
                            [("client", "Customer"), ("host", "Device")],
                        ),
                    },
                },
                template_tags={
                    "customer": _DEVICES_FILTER_TAGS["customer"],
                },
                param_mappings={
                    PARAM_CUSTOMER: _mapping("customer"),
                },
            ),
        ],
    },
    {
        "name": DASH_DEVICE_DRILLDOWN,
        "parameters_builder": _build_drilldown_parameters,
        "section_headers": [
            {"row": 0, "text": "### Compliance timeline"},
            {"row": 10, "text": "### Findings"},
            {"row": 16, "text": "### Alerts and suppressions"},
        ],
        "cards": [
            _card(
                "drilldown_matrix_timeline",
                "Per-run state",
                "table",
                """
                    SELECT
                        TO_CHAR(evaluated_at, 'YYYY-MM-DD HH24:MI') AS "Evaluated",
                        CASE WHEN is_compliant THEN 'Compliant' ELSE 'Noncompliant' END AS "State",
                        CASE WHEN is_stale THEN 'Yes' ELSE '' END AS "Stale",
                        CASE WHEN is_degraded THEN 'Yes' ELSE '' END AS "Degraded",
                        CASE
                            WHEN ninja_online THEN 'Online'
                            WHEN ninja_last_seen IS NOT NULL THEN 'Offline'
                            ELSE '—'
                        END AS "Ninja",
                        CASE
                            WHEN screenconnect_online THEN 'Online'
                            WHEN screenconnect_last_seen IS NOT NULL THEN 'Offline'
                            ELSE '—'
                        END AS "ScreenConnect",
                        CASE
                            WHEN sentinelone_online THEN 'Online'
                            WHEN sentinelone_last_seen IS NOT NULL THEN 'Offline'
                            ELSE '—'
                        END AS "SentinelOne",
                        CASE
                            WHEN logmein_online THEN 'Online'
                            WHEN logmein_last_seen IS NOT NULL THEN 'Offline'
                            ELSE '—'
                        END AS "LogMeIn",
                        COALESCE(array_to_string(missing_required_platforms, ', '), '—') AS "Missing"
                    FROM ninja_agent_compliance.compliance_matrix_history
                    WHERE 1=1
                      [[AND client_name = {{customer}}]]
                      [[AND hostname = {{host}}]]
                    ORDER BY evaluated_at DESC
                    LIMIT 100
                """,
                0, 0, 24, 10,
                template_tags={
                    "customer": _DRILLDOWN_FILTER_TAGS["customer"],
                    "host": _DRILLDOWN_FILTER_TAGS["host"],
                },
                param_mappings={
                    PARAM_DD_CUSTOMER: _mapping("customer"),
                    PARAM_DD_HOST: _mapping("host"),
                },
            ),
            _card(
                "drilldown_findings",
                "Findings history",
                "table",
                """
                    SELECT
                        TO_CHAR(last_seen_at, 'YYYY-MM-DD HH24:MI') AS "Last seen",
                        TO_CHAR(first_seen_at, 'YYYY-MM-DD HH24:MI') AS "First seen",
                        finding_type AS "Type",
                        COALESCE(affected_platform, '—') AS "Platform",
                        severity AS "Severity",
                        status AS "Status",
                        summary AS "Summary"
                    FROM ninja_agent_compliance.compliance_findings
                    WHERE 1=1
                      [[AND client_name = {{customer}}]]
                      [[AND hostname = {{host}}]]
                    ORDER BY last_seen_at DESC
                    LIMIT 100
                """,
                10, 0, 24, 6,
                template_tags={
                    "customer": _DRILLDOWN_FILTER_TAGS["customer"],
                    "host": _DRILLDOWN_FILTER_TAGS["host"],
                },
                param_mappings={
                    PARAM_DD_CUSTOMER: _mapping("customer"),
                    PARAM_DD_HOST: _mapping("host"),
                },
            ),
            _card(
                "drilldown_alerts",
                "Alert deliveries",
                "table",
                """
                    SELECT
                        TO_CHAR(ae.attempted_at, 'YYYY-MM-DD HH24:MI') AS "When",
                        ae.event_type AS "Event",
                        COALESCE(nr.display_name, '—') AS "Route",
                        ae.status AS "Status",
                        COALESCE(ae.response_code::text, '—') AS "Code",
                        f.finding_type AS "Finding",
                        COALESCE(f.affected_platform, '—') AS "Platform"
                    FROM ninja_agent_compliance.alert_events ae
                    LEFT JOIN ninja_agent_compliance.notification_routes nr
                           ON nr.route_id = ae.route_id
                    JOIN ninja_agent_compliance.compliance_findings f
                           ON f.finding_id = ae.finding_id
                    WHERE 1=1
                      [[AND f.client_name = {{customer}}]]
                      [[AND f.hostname = {{host}}]]
                    ORDER BY ae.attempted_at DESC
                    LIMIT 50
                """,
                16, 0, 12, 6,
                template_tags={
                    "customer": _DRILLDOWN_FILTER_TAGS["customer"],
                    "host": _DRILLDOWN_FILTER_TAGS["host"],
                },
                param_mappings={
                    PARAM_DD_CUSTOMER: _mapping("customer"),
                    PARAM_DD_HOST: _mapping("host"),
                },
            ),
            _card(
                "drilldown_suppressions",
                "Ignore history",
                "table",
                """
                    SELECT
                        TO_CHAR(s.updated_at, 'YYYY-MM-DD HH24:MI') AS "Updated",
                        COALESCE(s.updated_by, '—') AS "By",
                        COALESCE(NULLIF(s.reason, ''), 'No reason') AS "Reason",
                        CASE WHEN s.enabled THEN 'Suppressed' ELSE 'Restored' END AS "State"
                    FROM ninja_agent_compliance.alert_suppressions s
                    JOIN ninja_agent_compliance.clients c
                           ON c.client_id = s.client_id
                    WHERE 1=1
                      [[AND c.client_name = {{customer}}]]
                      [[AND (s.display_name = {{host}} OR s.norm_name = lower({{host}}))]]
                    ORDER BY s.updated_at DESC
                    LIMIT 50
                """,
                16, 12, 12, 6,
                template_tags={
                    "customer": _DRILLDOWN_FILTER_TAGS["customer"],
                    "host": _DRILLDOWN_FILTER_TAGS["host"],
                },
                param_mappings={
                    PARAM_DD_CUSTOMER: _mapping("customer"),
                    PARAM_DD_HOST: _mapping("host"),
                },
            ),
        ],
    },
    {
        "name": DASH_ALERTS,
        "parameters_builder": _build_alerts_parameters,
        "section_headers": [
            {"row": 0, "text": "### Alert rules"},
            {"row": 8, "text": "### Customer alert setup"},
            {"row": 18, "text": "### First notifications ready"},
            {"row": 28, "text": "### Active findings"},
            {"row": 40, "text": "### Recent deliveries"},
        ],
        "cards": [
            _card(
                "alert_rules",
                "Alert rules",
                "table",
                """
                    SELECT
                        r.rule_key AS "Rule",
                        CASE
                            WHEN r.finding_type = 'missing_required_platform'
                                THEN COALESCE(r.affected_platform, 'Required platform') || ' missing'
                            WHEN r.finding_type = 'stale_required_platform'
                                THEN COALESCE(r.affected_platform, 'Required platform') || ' stale'
                            WHEN r.finding_type = 'source_failure'
                                THEN 'Collector failed'
                            WHEN r.finding_type = 'cross_client_conflict'
                                THEN 'Device appears under multiple customers'
                            ELSE r.finding_type
                        END AS "Alert",
                        COALESCE(c.client_name, 'All customers') AS "Customer",
                        COALESCE(r.device_scope, 'any device') AS "Applies to",
                        r.severity AS "Severity",
                        COALESCE(nr.display_name, 'No route') AS "Route",
                        CASE WHEN nr.enabled THEN 'On' WHEN nr.enabled IS FALSE THEN 'Off' ELSE 'No route' END AS "Route state",
                        CASE WHEN r.enabled THEN 'On' ELSE 'Off' END AS "Rule state",
                        CASE WHEN r.enabled THEN 'Turn off' ELSE '' END AS "Turn off",
                        CASE WHEN NOT r.enabled THEN 'Turn on' ELSE '' END AS "Turn on"
                    FROM ninja_agent_compliance.alert_rules r
                    LEFT JOIN ninja_agent_compliance.clients c
                           ON c.client_id = r.client_id
                    LEFT JOIN ninja_agent_compliance.notification_routes nr
                           ON nr.route_id = r.route_id
                    ORDER BY
                        CASE WHEN r.enabled THEN 0 ELSE 1 END,
                        CASE r.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                        "Alert",
                        "Customer"
                """,
                0, 0, 24, 8,
                column_click_behaviors={
                    "Turn off": {
                        "url_template": f"{ACTION_BASE_URL}/a/tr?rule={{{{Rule}}}}&state=off&confirm=1",
                    },
                    "Turn on": {
                        "url_template": f"{ACTION_BASE_URL}/a/tr?rule={{{{Rule}}}}&state=on&confirm=1",
                    },
                },
            ),
            _card(
                "customer_alert_rules",
                "Customer alert setup",
                "table",
                """
                    WITH alert_types(alert_key, finding_type, affected_platform, alert_name) AS (
                        VALUES
                            ('missing_ninja', 'missing_required_platform', 'Ninja', 'Ninja missing'),
                            ('missing_sentinelone', 'missing_required_platform', 'SentinelOne', 'SentinelOne missing'),
                            ('missing_logmein', 'missing_required_platform', 'LogMeIn', 'LogMeIn missing'),
                            ('missing_screenconnect', 'missing_required_platform', 'ScreenConnect', 'ScreenConnect missing'),
                            ('stale', 'stale_required_platform', NULL, 'Required platform stale')
                    )
                    SELECT
                        c.client_name AS "Customer",
                        a.alert_key AS "Alert key",
                        a.alert_name AS "Alert",
                        CASE WHEN cr.enabled THEN 'On' WHEN cr.rule_id IS NOT NULL THEN 'Off' ELSE 'Not set' END AS "Customer rule",
                        CASE WHEN gr.enabled THEN 'On' ELSE 'Off' END AS "Global rule",
                        CASE
                            WHEN cr.enabled THEN 'On for this customer'
                            WHEN gr.enabled THEN 'On from global rule'
                            ELSE 'Off'
                        END AS "Effective",
                        CASE WHEN cr.enabled IS NOT TRUE THEN 'Turn on' ELSE '' END AS "Turn on",
                        CASE WHEN cr.enabled THEN 'Turn off' ELSE '' END AS "Turn off"
                    FROM ninja_agent_compliance.clients c
                    CROSS JOIN alert_types a
                    LEFT JOIN ninja_agent_compliance.alert_rules cr
                           ON cr.client_id = c.client_id
                          AND cr.finding_type = a.finding_type
                          AND cr.affected_platform IS NOT DISTINCT FROM a.affected_platform
                    LEFT JOIN ninja_agent_compliance.alert_rules gr
                           ON gr.client_id IS NULL
                          AND gr.finding_type = a.finding_type
                          AND gr.affected_platform IS NOT DISTINCT FROM a.affected_platform
                    WHERE c.enabled
                      AND c.source NOT IN ('alignment', 'demoted')
                    ORDER BY c.client_name, a.alert_name
                    LIMIT 500
                """,
                8, 0, 24, 10,
                column_click_behaviors={
                    "Turn on": {
                        "url_template": f"{ACTION_BASE_URL}/a/sca?customer={{{{Customer}}}}&alert={{{{Alert key}}}}&state=on&confirm=1",
                    },
                    "Turn off": {
                        "url_template": f"{ACTION_BASE_URL}/a/sca?customer={{{{Customer}}}}&alert={{{{Alert key}}}}&state=off&confirm=1",
                    },
                },
            ),
            _card(
                "alerts_would_fire",
                "First notifications ready",
                "table",
                """
                    SELECT
                        severity AS "Severity",
                        client_name AS "Customer",
                        COALESCE(hostname, '-') AS "Device",
                        issue AS "Issue",
                        COALESCE(route_name, 'No route') AS "Route",
                        notification_status AS "Status",
                        summary AS "Summary"
                    FROM ninja_agent_compliance.v_notifications_ready
                    WHERE 1=1
                      [[AND client_name IN ({{customer}})]]
                      [[AND severity IN ({{severity}})]]
                      [[AND finding_type IN ({{finding_type}})]]
                    ORDER BY
                        CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                        client_name, hostname
                    LIMIT 200
                """,
                18, 0, 24, 10,
                template_tags={
                    "customer": _ALERTS_FILTER_TAGS["customer"],
                    "severity": _ALERTS_FILTER_TAGS["severity"],
                    "finding_type": _ALERTS_FILTER_TAGS["finding_type"],
                },
                param_mappings={
                    PARAM_AL_CUSTOMER: _mapping("customer"),
                    PARAM_AL_SEVERITY: _mapping("severity"),
                    PARAM_AL_TYPE: _mapping("finding_type"),
                },
            ),
            _card(
                "alerts_active_findings",
                "Active findings",
                "table",
                """
                    SELECT
                        f.severity AS "Severity",
                        f.client_name AS "Customer",
                        COALESCE(f.hostname, '-') AS "Device",
                        CASE
                            WHEN f.finding_type = 'missing_required_platform'
                                THEN COALESCE(f.affected_platform, 'Required platform') || ' missing'
                            WHEN f.finding_type = 'stale_required_platform'
                                THEN COALESCE(f.affected_platform, 'Required platform') || ' stale'
                            WHEN f.finding_type = 'source_failure'
                                THEN 'Collector failed'
                            WHEN f.finding_type = 'cross_client_conflict'
                                THEN 'Device appears under multiple customers'
                            ELSE f.finding_type
                        END AS "Issue",
                        TO_CHAR(f.first_seen_at, 'YYYY-MM-DD HH24:MI') AS "First seen",
                        TO_CHAR(f.last_seen_at, 'YYYY-MM-DD HH24:MI') AS "Last seen",
                        COALESCE(TO_CHAR(s.last_alerted_at, 'YYYY-MM-DD HH24:MI'), 'never') AS "Last notified",
                        CASE WHEN s.last_alerted_at IS NULL THEN 'No' ELSE 'Yes' END AS "Notified",
                        f.summary AS "Summary"
                    FROM ninja_agent_compliance.v_active_findings f
                    LEFT JOIN ninja_agent_compliance.alert_state s
                           ON s.finding_signature = f.finding_signature
                    WHERE 1=1
                      [[AND f.client_name IN ({{customer}})]]
                      [[AND f.severity IN ({{severity}})]]
                      [[AND f.finding_type IN ({{finding_type}})]]
                    ORDER BY
                        CASE f.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                        f.last_seen_at DESC
                    LIMIT 500
                """,
                28, 0, 24, 12,
                template_tags={
                    "customer": _ALERTS_FILTER_TAGS["customer"],
                    "severity": _ALERTS_FILTER_TAGS["severity"],
                    "finding_type": _ALERTS_FILTER_TAGS["finding_type"],
                },
                param_mappings={
                    PARAM_AL_CUSTOMER: _mapping("customer"),
                    PARAM_AL_SEVERITY: _mapping("severity"),
                    PARAM_AL_TYPE: _mapping("finding_type"),
                },
            ),
            _card(
                "alerts_recent_deliveries",
                "Recent deliveries",
                "table",
                """
                    SELECT
                        TO_CHAR(ae.attempted_at, 'YYYY-MM-DD HH24:MI') AS "When",
                        ae.event_type AS "Event",
                        ae.status AS "Status",
                        COALESCE(ae.response_code::text, '-') AS "Code",
                        COALESCE(nr.display_name, '-') AS "Route",
                        f.severity AS "Severity",
                        COALESCE(f.client_name, '-') AS "Customer",
                        COALESCE(f.hostname, '-') AS "Device",
                        CASE
                            WHEN f.finding_type = 'missing_required_platform'
                                THEN COALESCE(f.affected_platform, 'Required platform') || ' missing'
                            WHEN f.finding_type = 'stale_required_platform'
                                THEN COALESCE(f.affected_platform, 'Required platform') || ' stale'
                            WHEN f.finding_type = 'source_failure'
                                THEN 'Collector failed'
                            WHEN f.finding_type = 'cross_client_conflict'
                                THEN 'Device appears under multiple customers'
                            ELSE f.finding_type
                        END AS "Issue"
                    FROM ninja_agent_compliance.alert_events ae
                    LEFT JOIN ninja_agent_compliance.notification_routes nr
                           ON nr.route_id = ae.route_id
                    LEFT JOIN ninja_agent_compliance.compliance_findings f
                           ON f.finding_id = ae.finding_id
                    WHERE 1=1
                      [[AND f.client_name IN ({{customer}})]]
                      [[AND f.severity IN ({{severity}})]]
                      [[AND f.finding_type IN ({{finding_type}})]]
                    ORDER BY ae.attempted_at DESC
                    LIMIT 100
                """,
                40, 0, 24, 8,
                template_tags={
                    "customer": _ALERTS_FILTER_TAGS["customer"],
                    "severity": _ALERTS_FILTER_TAGS["severity"],
                    "finding_type": _ALERTS_FILTER_TAGS["finding_type"],
                },
                param_mappings={
                    PARAM_AL_CUSTOMER: _mapping("customer"),
                    PARAM_AL_SEVERITY: _mapping("severity"),
                    PARAM_AL_TYPE: _mapping("finding_type"),
                },
            ),
        ],
    },
    {
        "name": DASH_CUSTOMERS,
        "parameters_builder": _build_customers_parameters,
        "cards": [
            _card(
                "customer_directory",
                "Customers and platform names",
                "table",
                """
                    WITH names AS (
                        SELECT
                            c.client_id,
                            c.client_name,
                            STRING_AGG(DISTINCT a.alias_value, ', ' ORDER BY a.alias_value)
                                FILTER (WHERE a.enabled AND a.platform = 'Ninja') AS ninja_names,
                            STRING_AGG(DISTINCT a.alias_value, ', ' ORDER BY a.alias_value)
                                FILTER (WHERE a.enabled AND a.platform = 'SentinelOne') AS s1_names,
                            STRING_AGG(DISTINCT a.alias_value, ', ' ORDER BY a.alias_value)
                                FILTER (WHERE a.enabled AND a.platform = 'LogMeIn') AS lmi_names,
                            STRING_AGG(DISTINCT a.alias_value, ', ' ORDER BY a.alias_value)
                                FILTER (WHERE a.enabled AND a.platform = 'ScreenConnect') AS sc_names
                        FROM ninja_agent_compliance.clients c
                        LEFT JOIN ninja_agent_compliance.client_aliases a
                          ON a.client_id = c.client_id
                         AND a.source IN ('manual', 'seed', 'alignment')
                        WHERE c.enabled
                          AND c.source NOT IN ('alignment', 'demoted')
                          AND lower(trim(c.client_name)) NOT IN ('default site', 'unknown', 'various', '.default')
                        GROUP BY c.client_id, c.client_name
                    )
                    SELECT
                        n.client_name AS "Customer",
                        COALESCE(a.overall_status, 'Not seen') AS "Mapping",
                        COALESCE(NULLIF(n.ninja_names, ''), '-') AS "Ninja",
                        COALESCE(NULLIF(n.s1_names, ''), '-') AS "SentinelOne",
                        COALESCE(NULLIF(n.lmi_names, ''), '-') AS "LogMeIn",
                        COALESCE(NULLIF(n.sc_names, ''), '-') AS "ScreenConnect"
                    FROM names n
                    LEFT JOIN ninja_agent_compliance.v_org_alignment_current a
                      ON a.client_id = n.client_id
                    ORDER BY n.client_name
                    LIMIT 300
                """,
                0, 0, 24, 10,
            ),
            _card(
                "new_names",
                "Customer names to review",
                "table",
                """
                    WITH latest_runs AS (
                        SELECT DISTINCT ON (platform, source_id)
                            platform,
                            source_id,
                            source_run_id
                        FROM ninja_agent_compliance.platform_observations
                        ORDER BY platform, source_id, observed_at DESC
                    ),
                    latest_counts AS (
                        SELECT
                            po.platform,
                            lower(trim(po.platform_group_name)) AS norm_name,
                            COUNT(*) AS latest_devices
                        FROM ninja_agent_compliance.platform_observations po
                        JOIN latest_runs lr
                          ON lr.source_run_id = po.source_run_id
                        WHERE COALESCE(NULLIF(po.platform_group_name, ''), '') <> ''
                        GROUP BY po.platform, lower(trim(po.platform_group_name))
                    ),
                    suggestions AS (
                        SELECT DISTINCT ON (c.candidate_id)
                            c.candidate_id,
                            t.client_name AS suggested_customer
                        FROM ninja_agent_compliance.v_org_candidates_current c
                        JOIN ninja_agent_compliance.clients t
                          ON t.enabled
                         AND t.source NOT IN ('alignment', 'demoted')
                         AND lower(trim(t.client_name)) NOT IN ('default site', 'unknown', 'various', '.default')
                        WHERE lower(regexp_replace(c.candidate_name, '[[:space:]_.-]', '', 'g'))
                                  <> lower(regexp_replace(t.client_name, '[[:space:]_.-]', '', 'g'))
                          AND (
                              lower(regexp_replace(c.candidate_name, '[[:space:]_.-]', '', 'g'))
                                  LIKE lower(regexp_replace(t.client_name, '[[:space:]_.-]', '', 'g')) || '%'
                              OR lower(regexp_replace(t.client_name, '[[:space:]_.-]', '', 'g'))
                                  LIKE lower(regexp_replace(c.candidate_name, '[[:space:]_.-]', '', 'g')) || '%'
                          )
                        ORDER BY
                            c.candidate_id,
                            ABS(length(t.client_name) - length(c.candidate_name)),
                            t.client_name
                    )
                    SELECT
                        c.candidate_name AS "Customer name",
                        c.platform AS "Found in",
                        COALESCE(l.latest_devices, 0) AS "Current devices",
                        COALESCE(NULLIF(c.suggested_target, ''), s.suggested_customer, '') AS "Suggested customer",
                        COALESCE(TO_CHAR(c.last_seen_at, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "Last seen",
                        'This is a customer' AS "Approve",
                        CASE
                            WHEN COALESCE(NULLIF(c.suggested_target, ''), s.suggested_customer, '') <> ''
                                THEN 'Alias suggestion'
                            ELSE ''
                        END AS "Alias suggestion",
                        'Choose customer' AS "Manual alias",
                        'Ignore name' AS "Ignore"
                    FROM ninja_agent_compliance.v_org_candidates_current c
                    LEFT JOIN latest_counts l
                      ON l.platform = c.platform
                     AND l.norm_name = lower(trim(c.candidate_name))
                    LEFT JOIN suggestions s
                      ON s.candidate_id = c.candidate_id
                    WHERE 1=1
                      [[AND c.candidate_name ILIKE '%' || {{review_name}} || '%']]
                    ORDER BY c.last_seen_at DESC, c.candidate_name
                    LIMIT 200
                """,
                10, 0, 24, 8,
                column_click_behaviors={
                    "Approve": {
                        "url_template": _url_template(
                            "/a/ac",
                            [("name", "Customer name")],
                        ),
                    },
                    "Alias suggestion": {
                        "url_template": _url_template(
                            "/a/aa",
                            [
                                ("client_name", "Suggested customer"),
                                ("platform", "Found in"),
                                ("alias", "Customer name"),
                            ],
                        ),
                    },
                    "Manual alias": {
                        "url_template": _url_template(
                            "/a/ma",
                            [
                                ("platform", "Found in"),
                                ("alias", "Customer name"),
                            ],
                        ),
                    },
                    "Ignore": {
                        "url_template": _url_template(
                            "/a/eo",
                            [("pattern", "Customer name")],
                        ),
                    },
                },
                template_tags={
                    "review_name": _CUSTOMERS_FILTER_TAGS["review_name"],
                },
                param_mappings={
                    PARAM_CU_REVIEW_NAME: _mapping("review_name"),
                },
            ),
            _card(
                "customer_name_rules",
                "Customer names by platform",
                "table",
                """
                    SELECT
                        c.client_name AS "Customer",
                        a.platform AS "Platform",
                        a.alias_value AS "Name used there",
                        COALESCE(TO_CHAR(a.updated_at, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "Updated"
                    FROM ninja_agent_compliance.client_aliases a
                    JOIN ninja_agent_compliance.clients c
                      ON c.client_id = a.client_id
                    WHERE a.enabled
                      AND c.enabled
                      AND c.source NOT IN ('alignment', 'demoted')
                    ORDER BY c.client_name, a.platform, a.alias_value
                    LIMIT 500
                """,
                18, 0, 24, 8,
            ),
            _card(
                "customer_requirements",
                "Required coverage",
                "table",
                """
                    WITH customers AS (
                        SELECT client_id, client_name
                        FROM ninja_agent_compliance.clients
                        WHERE enabled
                          AND source NOT IN ('alignment', 'demoted')
                          AND lower(trim(client_name)) NOT IN ('default site', 'unknown', 'various', '.default')
                    ),
                    scopes(device_scope, label) AS (
                        VALUES
                            ('all', 'All devices'),
                            ('server', 'Servers'),
                            ('workstation', 'Workstations')
                    ),
                    effective AS (
                        SELECT
                            c.client_id,
                            c.client_name,
                            s.device_scope,
                            s.label,
                            req.required_platforms,
                            req.max_age_days,
                            req.source,
                            req.notes,
                            req.source_scope,
                            req.client_id AS source_client_id
                        FROM customers c
                        CROSS JOIN scopes s
                        JOIN LATERAL (
                            SELECT
                                pr.client_id,
                                pr.device_scope AS source_scope,
                                pr.required_platforms,
                                pr.max_age_days,
                                pr.source,
                                pr.notes
                            FROM ninja_agent_compliance.platform_requirements pr
                            WHERE pr.enabled
                              AND (
                                  (pr.client_id = c.client_id AND pr.device_scope = s.device_scope)
                                  OR (pr.client_id = c.client_id AND pr.device_scope = 'all')
                                  OR (pr.client_id IS NULL AND pr.device_scope = s.device_scope)
                                  OR (pr.client_id IS NULL AND pr.device_scope = 'all')
                              )
                            ORDER BY
                                CASE
                                    WHEN pr.client_id = c.client_id AND pr.device_scope = s.device_scope THEN 0
                                    WHEN pr.client_id = c.client_id AND pr.device_scope = 'all' THEN 1
                                    WHEN pr.client_id IS NULL AND pr.device_scope = s.device_scope THEN 2
                                    ELSE 3
                                END
                            LIMIT 1
                        ) req ON true
                    )
                    SELECT
                        client_name AS "Customer",
                        label AS "Applies to",
                        CASE WHEN 'Ninja' = ANY(required_platforms) THEN 'On' ELSE 'Off' END AS "Ninja",
                        CASE WHEN 'SentinelOne' = ANY(required_platforms) THEN 'On' ELSE 'Off' END AS "SentinelOne",
                        CASE WHEN 'LogMeIn' = ANY(required_platforms) THEN 'On' ELSE 'Off' END AS "LogMeIn",
                        CASE WHEN 'ScreenConnect' = ANY(required_platforms) THEN 'On' ELSE 'Off' END AS "ScreenConnect",
                        COALESCE(max_age_days, 30) AS "Max age",
                        CASE
                            WHEN source_client_id IS NULL THEN 'Default'
                            WHEN source_scope <> device_scope AND source = 'manual' THEN 'Reviewed, from all devices'
                            WHEN source_scope <> device_scope AND source = 'seed' THEN 'Built in, from all devices'
                            WHEN source = 'manual' THEN 'Reviewed'
                            WHEN source = 'seed' THEN 'Built in'
                            ELSE source
                        END AS "Source",
                        '7d' AS "Age 7d",
                        '30d' AS "Age 30d",
                        '90d' AS "Age 90d",
                        CASE
                            WHEN source_client_id IS NOT NULL AND source_scope = device_scope THEN 'Use default'
                            ELSE ''
                        END AS "Default"
                    FROM effective
                    ORDER BY client_name,
                        CASE device_scope WHEN 'all' THEN 0 WHEN 'server' THEN 1 ELSE 2 END
                    LIMIT 500
                """,
                36, 0, 24, 10,
                column_click_behaviors={
                    "Ninja": {
                        "url_template": f"{ACTION_BASE_URL}/a/tp?customer={{{{Customer}}}}&scope={{{{Applies to}}}}&platform=Ninja&confirm=1",
                    },
                    "SentinelOne": {
                        "url_template": f"{ACTION_BASE_URL}/a/tp?customer={{{{Customer}}}}&scope={{{{Applies to}}}}&platform=SentinelOne&confirm=1",
                    },
                    "LogMeIn": {
                        "url_template": f"{ACTION_BASE_URL}/a/tp?customer={{{{Customer}}}}&scope={{{{Applies to}}}}&platform=LogMeIn&confirm=1",
                    },
                    "ScreenConnect": {
                        "url_template": f"{ACTION_BASE_URL}/a/tp?customer={{{{Customer}}}}&scope={{{{Applies to}}}}&platform=ScreenConnect&confirm=1",
                    },
                    "Age 7d": {
                        "url_template": f"{ACTION_BASE_URL}/a/sd?customer={{{{Customer}}}}&scope={{{{Applies to}}}}&days=7&confirm=1",
                    },
                    "Age 30d": {
                        "url_template": f"{ACTION_BASE_URL}/a/sd?customer={{{{Customer}}}}&scope={{{{Applies to}}}}&days=30&confirm=1",
                    },
                    "Age 90d": {
                        "url_template": f"{ACTION_BASE_URL}/a/sd?customer={{{{Customer}}}}&scope={{{{Applies to}}}}&days=90&confirm=1",
                    },
                    "Default": {
                        "url_template": f"{ACTION_BASE_URL}/a/sr?customer={{{{Customer}}}}&scope={{{{Applies to}}}}&profile=default&confirm=1",
                    },
                },
            ),
            _card(
                "ignored_names",
                "Ignored customer names",
                "table",
                """
                    SELECT
                        pattern AS "Name",
                        source AS "Source",
                        COALESCE(NULLIF(notes, ''), 'No notes') AS "Notes",
                        COALESCE(TO_CHAR(updated_at, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "Updated",
                        CASE WHEN source = 'manual' THEN 'Restore' ELSE '' END AS "Action"
                    FROM ninja_agent_compliance.org_excludes
                    WHERE enabled
                    ORDER BY source, pattern
                    LIMIT 200
                """,
                48, 0, 24, 4,
                column_click_behaviors={
                    "Action": {
                        "url_template": _url_template(
                            "/a/ue",
                            [("pattern", "Name")],
                        ),
                    },
                },
            ),
        ],
    },
    {
        "name": DASH_HEALTH,
        "cards": [
            _card(
                "missing_by_platform",
                "Missing by platform",
                "bar",
                """
                    SELECT
                        platform AS "Platform",
                        COUNT(*) AS "Devices"
                    FROM ninja_agent_compliance.v_compliance_matrix_current m
                    CROSS JOIN LATERAL unnest(m.missing_required_platforms) AS platform
                    WHERE NOT (platform = 'SentinelOne' AND m.s1_exempt)
                      AND NOT EXISTS (
                          SELECT 1
                          FROM ninja_agent_compliance.alert_suppressions s
                          WHERE s.enabled
                            AND (s.client_id IS NULL OR s.client_id = m.client_id)
                            AND (s.norm_name IS NULL OR s.norm_name = m.norm_name)
                            AND (s.expires_at IS NULL OR s.expires_at > now())
                      )
                      AND NOT EXISTS (
                          SELECT 1
                          FROM ninja_agent_compliance.org_excludes e
                          WHERE e.enabled
                            AND e.pattern = lower(trim(m.client_name))
                      )
                    GROUP BY platform
                    ORDER BY "Devices" DESC
                """,
                0, 0, 12, 8,
            ),
            _card(
                "source_work",
                "Source work",
                "table",
                """
                    SELECT
                        work_type AS "Work",
                        platform AS "Platform",
                        source_name AS "Source",
                        COALESCE(NULLIF(client_name, ''), 'Shared') AS "Customer",
                        rows_observed AS "Rows",
                        COALESCE(NULLIF(issue, ''), 'OK') AS "Issue"
                    FROM ninja_agent_compliance.v_source_work_current
                    ORDER BY severity DESC, platform, source_name
                """,
                0, 12, 12, 8,
            ),
            _card(
                "source_health",
                "All sources",
                "table",
                """
                    SELECT
                        source_name AS "Source",
                        platform AS "Platform",
                        COALESCE(NULLIF(client_name, ''), 'Shared') AS "Customer",
                        status AS "State",
                        rows_observed AS "Rows",
                        COALESCE(TO_CHAR(finished_at, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "Finished"
                    FROM ninja_agent_compliance.v_source_health_current
                    ORDER BY platform, source_name
                """,
                8, 0, 24, 6,
            ),
        ],
    },
    {
        "name": DASH_DEBUG,
        "cards": [
            _card(
                "raw_observations",
                "Raw observations",
                "table",
                """
                    SELECT
                        observed_at AS "Seen",
                        platform AS "Platform",
                        source_name AS "Source",
                        COALESCE(NULLIF(resolved_client_name, ''), 'Unresolved') AS "Customer",
                        hostname AS "Device",
                        COALESCE(NULLIF(platform_group_name, ''), 'Unknown') AS "Group",
                        COALESCE(NULLIF(platform_group_id, ''), 'Unknown') AS "Group ID",
                        raw_data AS "Raw data"
                    FROM ninja_agent_compliance.platform_observations
                    ORDER BY observed_at DESC
                    LIMIT 200
                """,
                0, 0, 24, 10,
            ),
                _card(
                    "cross_customer_conflicts",
                    "Same name across customers",
                    "table",
                    """
                    WITH conflicts AS (
                        SELECT
                            norm_name,
                            string_agg(DISTINCT client_name, ', ' ORDER BY client_name) AS customers,
                            string_agg(DISTINCT hostname, ', ' ORDER BY hostname) AS devices,
                            string_agg(DISTINCT platform_name, ', ' ORDER BY platform_name) AS platforms_seen
                        FROM ninja_agent_compliance.v_cross_client_conflicts
                        CROSS JOIN LATERAL unnest(observed_platforms) AS p(platform_name)
                        GROUP BY norm_name
                    )
                    SELECT
                        norm_name AS "Match key",
                        customers AS "Customers",
                        devices AS "Device",
                        COALESCE(platforms_seen, '-') AS "Platforms seen"
                    FROM conflicts
                    ORDER BY norm_name
                    LIMIT 300
                """,
                10, 0, 24, 8,
                column_click_behaviors={
                    "Device": _dashboard_link(
                        DASH_DEVICE_DRILLDOWN,
                        params=[("host", "Device")],
                    ),
                },
            ),
        ],
    },
]


def _level1_dashboards() -> list[dict[str, Any]]:
    """Active Level 1 workflow dashboards.

    The earlier dashboard spec is intentionally superseded here so the
    operational UI is driven by the queue views added in migration 037.
    This keeps the bootstrap helpers stable while making the active
    surface human/workflow-first.
    """
    return [
        {
            "name": DASH_TODAY,
            "cards": [
                _card(
                    "today_total_devices",
                    "Total devices",
                    "scalar",
                    """
                        SELECT COUNT(*) AS "Total devices"
                        FROM ninja_agent_compliance.v_all_devices_human
                    """,
                    0, 0, 5, 4,
                    click_behavior=_dashboard_link(DASH_DEVICES),
                ),
                _card(
                    "today_compliant_percent",
                    "Compliant %",
                    "scalar",
                    """
                        SELECT ROUND(
                            COUNT(*) FILTER (WHERE is_compliant AND state <> 'Stale' AND NOT ignored) * 100.0
                                / NULLIF(COUNT(*) FILTER (WHERE state <> 'Stale' AND NOT ignored), 0),
                            1
                        ) AS "Compliant %"
                        FROM ninja_agent_compliance.v_all_devices_human
                    """,
                    0, 5, 5, 4,
                    click_behavior=_dashboard_link(DASH_DEVICES),
                ),
                _card(
                    "today_fix_now",
                    "Fix now",
                    "scalar",
                    """
                        SELECT COUNT(*) AS "Fix now"
                        FROM ninja_agent_compliance.v_device_work_queue
                        WHERE work_state = 'Fix now'
                    """,
                    0, 10, 5, 4,
                    click_behavior=_dashboard_link(DASH_DEVICES),
                ),
                _card(
                    "today_review",
                    "Review",
                    "scalar",
                    """
                        SELECT COUNT(*) AS "Review"
                        FROM ninja_agent_compliance.v_device_work_queue
                        WHERE work_state = 'Review'
                    """,
                    0, 15, 5, 4,
                    click_behavior=_dashboard_link(DASH_DEVICES),
                ),
                _card(
                    "today_stale",
                    "Stale",
                    "scalar",
                    """
                        SELECT COUNT(*) AS "Stale"
                        FROM ninja_agent_compliance.v_device_work_queue
                        WHERE work_state = 'Stale'
                    """,
                    0, 20, 4, 4,
                    click_behavior=_dashboard_link(DASH_DEVICES),
                ),
                _card(
                    "today_notifications_ready",
                    "Ready to notify",
                    "scalar",
                    """
                        SELECT COUNT(*) AS "Ready to notify"
                        FROM ninja_agent_compliance.v_notifications_ready
                    """,
                    4, 0, 8, 4,
                    click_behavior=_dashboard_link(DASH_ALERTS),
                ),
                _card(
                    "today_names_to_review",
                    "Names to review",
                    "scalar",
                    """
                        SELECT COUNT(*) AS "Names to review"
                        FROM ninja_agent_compliance.v_customer_name_queue
                    """,
                    4, 8, 8, 4,
                    click_behavior=_dashboard_link(DASH_CUSTOMERS),
                ),
                _card(
                    "today_collection_problems",
                    "Collection issues",
                    "scalar",
                    """
                        SELECT COUNT(*) AS "Collection issues"
                        FROM ninja_agent_compliance.v_system_health_queue
                    """,
                    4, 16, 8, 4,
                    click_behavior=_dashboard_link(DASH_HEALTH),
                ),
                _card(
                    "today_fix_now_by_customer",
                    "Fix now by customer",
                    "table",
                    """
                        SELECT
                            client_name AS "Customer",
                            COUNT(*) AS "Devices",
                            'Fix now' AS "State"
                        FROM ninja_agent_compliance.v_device_work_queue
                        WHERE work_state = 'Fix now'
                        GROUP BY client_name
                        ORDER BY COUNT(*) DESC, client_name
                    """,
                    8, 0, 12, 6,
                    click_behavior=_dashboard_link(
                        DASH_DEVICES,
                        params=[("customer", "Customer"), ("state", "State")],
                    ),
                    column_widths={
                        "Customer": 280,
                        "Devices": 100,
                        "State": 60,
                    },
                ),
                _card(
                    "today_fix_now_by_issue_type",
                    "Fix now by issue type",
                    "table",
                    """
                        WITH classified AS (
                            SELECT
                                CASE
                                    WHEN cardinality(cross_customer_actionable_platforms) > 0
                                        THEN 'Missing platform found elsewhere'
                                    WHEN 'Ninja' = ANY(missing_platforms) THEN 'Missing Ninja'
                                    WHEN 'SentinelOne' = ANY(missing_platforms) THEN 'Missing SentinelOne'
                                    WHEN 'ScreenConnect' = ANY(missing_platforms) THEN 'Missing ScreenConnect'
                                    WHEN 'LogMeIn' = ANY(missing_platforms) THEN 'Missing LogMeIn'
                                    WHEN is_degraded THEN 'Agent degraded'
                                    ELSE 'Other'
                                END AS issue_type
                            FROM ninja_agent_compliance.v_device_work_queue
                            WHERE work_state = 'Fix now'
                        )
                        SELECT
                            issue_type AS "Issue type",
                            COUNT(*) AS "Devices",
                            'Fix now' AS "State"
                        FROM classified
                        GROUP BY issue_type
                        ORDER BY COUNT(*) DESC, issue_type
                    """,
                    8, 12, 12, 6,
                    click_behavior=_dashboard_link(
                        DASH_DEVICES,
                        params=[("state", "State")],
                    ),
                    column_widths={
                        "Issue type": 280,
                        "Devices": 100,
                        "State": 60,
                    },
                ),
                _card(
                    "today_fix_now_by_os_family",
                    "Fix now by OS family",
                    "table",
                    """
                        SELECT
                            os_family AS "OS family",
                            COUNT(*) AS "Devices",
                            'Fix now' AS "State"
                        FROM ninja_agent_compliance.v_device_work_queue
                        WHERE work_state = 'Fix now'
                        GROUP BY os_family
                        ORDER BY COUNT(*) DESC, os_family
                    """,
                    14, 0, 12, 6,
                    click_behavior=_dashboard_link(
                        DASH_DEVICES,
                        params=[("os_family", "OS family"), ("state", "State")],
                    ),
                    column_widths={
                        "OS family": 280,
                        "Devices": 100,
                        "State": 60,
                    },
                ),
                _card(
                    "today_fix_now_by_device_type",
                    "Fix now by device type",
                    "table",
                    """
                        SELECT
                            INITCAP(device_type) AS "Device type",
                            COUNT(*) AS "Devices",
                            'Fix now' AS "State"
                        FROM ninja_agent_compliance.v_device_work_queue
                        WHERE work_state = 'Fix now'
                        GROUP BY device_type
                        ORDER BY COUNT(*) DESC, device_type
                    """,
                    14, 12, 12, 6,
                    click_behavior=_dashboard_link(
                        DASH_DEVICES,
                        params=[("device_type", "Device type"), ("state", "State")],
                    ),
                    column_widths={
                        "Device type": 280,
                        "Devices": 100,
                        "State": 60,
                    },
                ),
                _card(
                    "today_top_device_issues",
                    "Top device issues",
                    "table",
                    """
                        SELECT
                            client_name AS "Customer",
                            hostname AS "Device",
                            CASE
                                WHEN os_family LIKE 'Windows Server %' THEN REPLACE(os_family, 'Windows Server ', 'Srv ')
                                WHEN os_family = 'Windows Server (other)' THEN 'Srv ?'
                                WHEN os_family LIKE 'Windows %' THEN REPLACE(os_family, 'Windows ', 'Win ')
                                WHEN os_family = 'Windows (other)' THEN 'Win ?'
                                ELSE os_family
                            END || ' · ' || CASE WHEN device_type = 'server' THEN 'SRV' ELSE 'WS' END AS "OS / Type",
                            issue AS "Issue",
                            COALESCE(array_to_string(online_platforms, ', '), '-') AS "Online in",
                            COALESCE(TO_CHAR(last_seen_anywhere, 'YYYY-MM-DD HH24:MI'), 'Never') AS "Last seen",
                            work_state AS "State"
                        FROM ninja_agent_compliance.v_device_work_queue
                        WHERE work_state IN ('Fix now', 'Review')
                        ORDER BY
                            CASE work_state
                                WHEN 'Fix now' THEN 0
                                WHEN 'Review' THEN 1
                                WHEN 'Stale' THEN 2
                                ELSE 5
                            END,
                            client_name,
                            hostname
                        LIMIT 25
                    """,
                    20, 0, 24, 8,
                    column_click_behaviors={
                        "Device": _dashboard_link(
                            DASH_DEVICE_DRILLDOWN,
                            params=[("customer", "Customer"), ("host", "Device")],
                        ),
                    },
                ),
                _card(
                    "today_customer_names",
                    "Customer names needing review",
                    "table",
                    """
                        SELECT
                            candidate_name AS "Name found",
                            platform AS "Found in",
                            current_devices AS "Devices",
                            COALESCE(NULLIF(suggested_customer, ''), '-') AS "Suggested customer",
                            review_reason AS "Why review",
                            'Review' AS "Action"
                        FROM ninja_agent_compliance.v_customer_name_queue
                        ORDER BY current_devices DESC, candidate_name
                        LIMIT 15
                    """,
                    28, 0, 12, 6,
                    column_click_behaviors={
                        "Action": _dashboard_link(DASH_CUSTOMERS),
                    },
                ),
                _card(
                    "today_health_problems",
                    "Collection and delivery problems",
                    "table",
                    """
                        SELECT
                            work_type AS "Problem",
                            platform AS "Area",
                            source_name AS "Source",
                            customer_name AS "Customer",
                            issue AS "Issue"
                        FROM ninja_agent_compliance.v_system_health_queue
                        ORDER BY severity DESC, platform, source_name
                        LIMIT 15
                    """,
                    28, 12, 12, 6,
                    column_click_behaviors={
                        "Problem": _dashboard_link(DASH_HEALTH),
                    },
                ),
            ],
        },
        {
            "name": DASH_DEVICES,
            "parameters_builder": _build_devices_parameters,
            "section_headers": [
                {"row": 0, "text": "### Fix now"},
                {"row": 24, "text": "### Platform gaps"},
                {"row": 38, "text": "### Stale and ignored"},
                {"row": 50, "text": "### All devices"},
            ],
            "cards": [
                _card(
                    "devices_fix_now_by_customer",
                    "Fix now by customer",
                    "table",
                    """
                        SELECT
                            client_name AS "Customer",
                            COUNT(*) AS "Devices",
                            'Fix now' AS "State"
                        FROM ninja_agent_compliance.v_device_work_queue
                        WHERE work_state = 'Fix now'
                          [[AND client_name IN ({{customer}})]]
                        GROUP BY client_name
                        ORDER BY COUNT(*) DESC, client_name
                    """,
                    12, 0, 12, 6,
                    click_behavior=_dashboard_link(
                        DASH_DEVICES,
                        params=[("customer", "Customer"), ("state", "State")],
                    ),
                    column_widths={
                        "Customer": 280,
                        "Devices": 100,
                        "State": 60,
                    },
                    template_tags={"customer": _DEVICES_FILTER_TAGS["customer"]},
                    param_mappings={PARAM_CUSTOMER: _mapping("customer")},
                ),
                _card(
                    "devices_fix_now_by_issue_type",
                    "Fix now by issue type",
                    "table",
                    """
                        WITH classified AS (
                            SELECT
                                CASE
                                    WHEN cardinality(cross_customer_actionable_platforms) > 0
                                        THEN 'Missing platform found elsewhere'
                                    WHEN 'Ninja' = ANY(missing_platforms) THEN 'Missing Ninja'
                                    WHEN 'SentinelOne' = ANY(missing_platforms) THEN 'Missing SentinelOne'
                                    WHEN 'ScreenConnect' = ANY(missing_platforms) THEN 'Missing ScreenConnect'
                                    WHEN 'LogMeIn' = ANY(missing_platforms) THEN 'Missing LogMeIn'
                                    WHEN is_degraded THEN 'Agent degraded'
                                    ELSE 'Other'
                                END AS issue_type
                            FROM ninja_agent_compliance.v_device_work_queue
                            WHERE work_state = 'Fix now'
                              [[AND client_name IN ({{customer}})]]
                        )
                        SELECT
                            issue_type AS "Issue type",
                            COUNT(*) AS "Devices",
                            'Fix now' AS "State"
                        FROM classified
                        GROUP BY issue_type
                        ORDER BY COUNT(*) DESC, issue_type
                    """,
                    12, 12, 12, 6,
                    click_behavior=_dashboard_link(
                        DASH_DEVICES,
                        params=[("state", "State")],
                    ),
                    column_widths={
                        "Issue type": 280,
                        "Devices": 100,
                        "State": 60,
                    },
                    template_tags={"customer": _DEVICES_FILTER_TAGS["customer"]},
                    param_mappings={PARAM_CUSTOMER: _mapping("customer")},
                ),
                _card(
                    "devices_fix_now_by_os_family",
                    "Fix now by OS family",
                    "table",
                    """
                        SELECT
                            os_family AS "OS family",
                            COUNT(*) AS "Devices",
                            'Fix now' AS "State"
                        FROM ninja_agent_compliance.v_device_work_queue
                        WHERE work_state = 'Fix now'
                          [[AND client_name IN ({{customer}})]]
                        GROUP BY os_family
                        ORDER BY COUNT(*) DESC, os_family
                    """,
                    18, 0, 12, 6,
                    click_behavior=_dashboard_link(
                        DASH_DEVICES,
                        params=[("os_family", "OS family"), ("state", "State")],
                    ),
                    column_widths={
                        "OS family": 280,
                        "Devices": 100,
                        "State": 60,
                    },
                    template_tags={"customer": _DEVICES_FILTER_TAGS["customer"]},
                    param_mappings={PARAM_CUSTOMER: _mapping("customer")},
                ),
                _card(
                    "devices_fix_now_by_device_type",
                    "Fix now by device type",
                    "table",
                    """
                        SELECT
                            INITCAP(device_type) AS "Device type",
                            COUNT(*) AS "Devices",
                            'Fix now' AS "State"
                        FROM ninja_agent_compliance.v_device_work_queue
                        WHERE work_state = 'Fix now'
                          [[AND client_name IN ({{customer}})]]
                        GROUP BY device_type
                        ORDER BY COUNT(*) DESC, device_type
                    """,
                    18, 12, 12, 6,
                    click_behavior=_dashboard_link(
                        DASH_DEVICES,
                        params=[("device_type", "Device type"), ("state", "State")],
                    ),
                    column_widths={
                        "Device type": 280,
                        "Devices": 100,
                        "State": 60,
                    },
                    template_tags={"customer": _DEVICES_FILTER_TAGS["customer"]},
                    param_mappings={PARAM_CUSTOMER: _mapping("customer")},
                ),
                _card(
                    "devices_work_queue",
                    "Devices needing action",
                    "table",
                    """
                        SELECT
                            client_name AS "Customer",
                            hostname AS "Device",
                            CASE
                                WHEN os_family LIKE 'Windows Server %' THEN REPLACE(os_family, 'Windows Server ', 'Srv ')
                                WHEN os_family = 'Windows Server (other)' THEN 'Srv ?'
                                WHEN os_family LIKE 'Windows %' THEN REPLACE(os_family, 'Windows ', 'Win ')
                                WHEN os_family = 'Windows (other)' THEN 'Win ?'
                                ELSE os_family
                            END || ' · ' || CASE WHEN device_type = 'server' THEN 'SRV' ELSE 'WS' END AS "OS / Type",
                            issue AS "Issue",
                            COALESCE(array_to_string(online_platforms, ', '), '-') AS "Online in",
                            COALESCE(array_to_string(missing_platforms, ', '), '-') AS "Missing",
                            COALESCE(TO_CHAR(last_seen_anywhere, 'YYYY-MM-DD HH24:MI'), 'Never') AS "Last seen",
                            work_state AS "State",
                            'Ignore' AS "Action"
                        FROM ninja_agent_compliance.v_device_work_queue
                        WHERE 1=1
                          [[AND client_name IN ({{customer}})]]
                          [[AND EXISTS (
                              SELECT 1 FROM unnest(missing_platforms) AS p
                              WHERE p IN ({{missing}})
                          )]]
                          [[AND EXISTS (
                              SELECT 1 FROM unnest(online_platforms) AS p
                              WHERE p IN ({{online_in}})
                          )]]
                          [[AND work_state IN ({{state}})]]
                          [[AND (CASE WHEN s1_exempt THEN 'Yes' ELSE 'No' END) IN ({{av}})]]
                          [[AND os_family IN ({{os_family}})]]
                          [[AND INITCAP(device_type) IN ({{device_type}})]]
                        ORDER BY
                            CASE work_state
                                WHEN 'Fix now' THEN 0
                                WHEN 'Review' THEN 1
                                WHEN 'Stale' THEN 2
                                ELSE 5
                            END,
                            client_name,
                            hostname
                        LIMIT 500
                    """,
                    0, 0, 24, 12,
                    column_click_behaviors={
                        "Device": _dashboard_link(
                            DASH_DEVICE_DRILLDOWN,
                            params=[("customer", "Customer"), ("host", "Device")],
                        ),
                        "Action": {
                            "url_template": _url_template(
                                "/a/ig",
                                [("client", "Customer"), ("host", "Device")],
                                confirm=False,
                            ),
                        },
                    },
                    column_widths={
                        "Customer": 200,
                        "Device": 160,
                        "OS / Type": 130,
                        "Issue": 320,
                        "Online in": 150,
                        "Missing": 160,
                        "Last seen": 140,
                        "State": 90,
                        "Action": 80,
                    },
                    template_tags=_DEVICES_FILTER_TAGS,
                    param_mappings={
                        PARAM_CUSTOMER: _mapping("customer"),
                        PARAM_MISSING: _mapping("missing"),
                        PARAM_ONLINE_IN: _mapping("online_in"),
                        PARAM_STATE: _mapping("state"),
                        PARAM_AV_EXEMPT: _mapping("av"),
                        PARAM_OS_FAMILY: _mapping("os_family"),
                        PARAM_DEVICE_TYPE: _mapping("device_type"),
                    },
                ),
                _card(
                    "devices_gap_summary",
                    "Missing but online somewhere else",
                    "table",
                    """
                        SELECT
                            missing_platform AS "Missing",
                            online_platform AS "Online in",
                            devices AS "Devices"
                        FROM ninja_agent_compliance.v_device_gap_summary
                        WHERE 1=1
                          [[AND missing_platform IN ({{missing}})]]
                          [[AND online_platform IN ({{online_in}})]]
                        ORDER BY devices DESC, missing_platform, online_platform
                    """,
                    24, 0, 12, 6,
                    click_behavior=_dashboard_link(
                        DASH_DEVICES,
                        params=[("missing", "Missing"), ("online_in", "Online in")],
                    ),
                    template_tags={
                        "missing": _DEVICES_FILTER_TAGS["missing"],
                        "online_in": _DEVICES_FILTER_TAGS["online_in"],
                    },
                    param_mappings={
                        PARAM_MISSING: _mapping("missing"),
                        PARAM_ONLINE_IN: _mapping("online_in"),
                    },
                ),
                _card(
                    "devices_missing_by_platform",
                    "Devices by missing platform",
                    "bar",
                    """
                        SELECT
                            p AS "Missing",
                            COUNT(DISTINCT (client_id, norm_name)) AS "Devices"
                        FROM ninja_agent_compliance.v_device_work_queue q
                        CROSS JOIN LATERAL unnest(q.missing_platforms) AS p
                        WHERE 1=1
                          [[AND client_name IN ({{customer}})]]
                          [[AND p IN ({{missing}})]]
                        GROUP BY p
                        ORDER BY "Devices" DESC
                    """,
                    24, 12, 12, 6,
                    click_behavior=_dashboard_link(DASH_DEVICES, params=[("missing", "Missing")]),
                    template_tags={
                        "customer": _DEVICES_FILTER_TAGS["customer"],
                        "missing": _DEVICES_FILTER_TAGS["missing"],
                    },
                    param_mappings={
                        PARAM_CUSTOMER: _mapping("customer"),
                        PARAM_MISSING: _mapping("missing"),
                    },
                ),
                _card(
                    "devices_stale_by_customer",
                    "Stale devices by customer",
                    "table",
                    """
                        SELECT
                            client_name AS "Customer",
                            COUNT(*) AS "Stale devices",
                            COALESCE(TO_CHAR(MAX(last_seen_anywhere), 'YYYY-MM-DD HH24:MI'), 'Never') AS "Last seen",
                            'Ignore 30d' AS "Action"
                        FROM ninja_agent_compliance.v_device_work_queue
                        WHERE work_state = 'Stale'
                          [[AND client_name IN ({{customer}})]]
                        GROUP BY client_name
                        ORDER BY "Stale devices" DESC, client_name
                        LIMIT 100
                    """,
                    38, 0, 12, 6,
                    column_click_behaviors={
                        "Action": {
                            "url_template": _url_template(
                                "/a/bs",
                                [("client", "Customer")],
                            ),
                        },
                    },
                    template_tags={"customer": _DEVICES_FILTER_TAGS["customer"]},
                    param_mappings={PARAM_CUSTOMER: _mapping("customer")},
                ),
                _card(
                    "devices_ignored",
                    "Ignored devices",
                    "table",
                    """
                        SELECT
                            client_name AS "Customer",
                            COALESCE(NULLIF(display_name, ''), norm_name) AS "Device",
                            COALESCE(NULLIF(reason, ''), 'Ignored') AS "Reason",
                            expires AS "Expires",
                            COALESCE(TO_CHAR(updated_at, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "Updated",
                            'Restore' AS "Action"
                        FROM ninja_agent_compliance.v_device_ignores_current
                        WHERE 1=1
                          [[AND client_name IN ({{customer}})]]
                        ORDER BY updated_at DESC, client_name, display_name
                        LIMIT 200
                    """,
                    38, 12, 12, 6,
                    column_click_behaviors={
                        "Device": _dashboard_link(
                            DASH_DEVICE_DRILLDOWN,
                            params=[("customer", "Customer"), ("host", "Device")],
                        ),
                        "Action": {
                            "url_template": _url_template(
                                "/a/ui",
                                [("client", "Customer"), ("host", "Device")],
                            ),
                        },
                    },
                    template_tags={"customer": _DEVICES_FILTER_TAGS["customer"]},
                    param_mappings={PARAM_CUSTOMER: _mapping("customer")},
                ),
                _card(
                    "devices_all",
                    "All devices",
                    "table",
                    """
                        SELECT
                            client_name AS "Customer",
                            hostname AS "Device",
                            CASE
                                WHEN os_family LIKE 'Windows Server %' THEN REPLACE(os_family, 'Windows Server ', 'Srv ')
                                WHEN os_family = 'Windows Server (other)' THEN 'Srv ?'
                                WHEN os_family LIKE 'Windows %' THEN REPLACE(os_family, 'Windows ', 'Win ')
                                WHEN os_family = 'Windows (other)' THEN 'Win ?'
                                ELSE os_family
                            END || ' · ' || CASE WHEN device_type = 'server' THEN 'SRV' ELSE 'WS' END AS "OS / Type",
                            state AS "State",
                            issue AS "Issue",
                            COALESCE(array_to_string(found_platforms, ', '), '-') AS "Found in",
                            COALESCE(array_to_string(online_platforms, ', '), '-') AS "Online in",
                            COALESCE(array_to_string(missing_platforms, ', '), '-') AS "Missing",
                            CASE WHEN ignored THEN 'Yes' ELSE 'No' END AS "Ignored",
                            COALESCE(TO_CHAR(last_seen_anywhere, 'YYYY-MM-DD HH24:MI'), 'Never') AS "Last seen"
                        FROM ninja_agent_compliance.v_all_devices_human
                        WHERE 1=1
                          [[AND client_name IN ({{customer}})]]
                          [[AND EXISTS (
                              SELECT 1 FROM unnest(missing_platforms) AS p
                              WHERE p IN ({{missing}})
                          )]]
                          [[AND EXISTS (
                              SELECT 1 FROM unnest(online_platforms) AS p
                              WHERE p IN ({{online_in}})
                          )]]
                          [[AND state IN ({{state}})]]
                          [[AND (CASE WHEN s1_exempt THEN 'Yes' ELSE 'No' END) IN ({{av}})]]
                          [[AND os_family IN ({{os_family}})]]
                          [[AND INITCAP(device_type) IN ({{device_type}})]]
                        ORDER BY client_name, hostname
                        LIMIT 1000
                    """,
                    50, 0, 24, 8,
                    column_click_behaviors={
                        "Device": _dashboard_link(
                            DASH_DEVICE_DRILLDOWN,
                            params=[("customer", "Customer"), ("host", "Device")],
                        ),
                    },
                    template_tags=_DEVICES_FILTER_TAGS,
                    param_mappings={
                        PARAM_CUSTOMER: _mapping("customer"),
                        PARAM_MISSING: _mapping("missing"),
                        PARAM_ONLINE_IN: _mapping("online_in"),
                        PARAM_STATE: _mapping("state"),
                        PARAM_AV_EXEMPT: _mapping("av"),
                        PARAM_OS_FAMILY: _mapping("os_family"),
                        PARAM_DEVICE_TYPE: _mapping("device_type"),
                    },
                ),
            ],
        },
        {
            "name": DASH_DEVICE_DRILLDOWN,
            "parameters_builder": _build_drilldown_parameters,
            "section_headers": [
                {"row": 0, "text": "### Current device"},
                {"row": 8, "text": "### History"},
                {"row": 18, "text": "### Notifications and ignores"},
            ],
            "cards": [
                _card(
                    "drilldown_current",
                    "Current device state",
                    "table",
                    """
                        WITH anchor AS (
                            SELECT norm_name
                            FROM ninja_agent_compliance.v_all_devices_human
                            WHERE hostname = {{host}}
                              [[AND client_name = {{customer}}]]
                            ORDER BY
                                [[CASE WHEN client_name = {{customer}} THEN 0 ELSE 1 END,]]
                                evaluated_at DESC
                            LIMIT 1
                        )
                        SELECT
                            client_name AS "Customer",
                            hostname AS "Device",
                            state AS "State",
                            issue AS "Issue",
                            COALESCE(array_to_string(required_platforms, ', '), '-') AS "Required",
                            COALESCE(array_to_string(found_platforms, ', '), '-') AS "Found in",
                            COALESCE(array_to_string(online_platforms, ', '), '-') AS "Online in",
                            COALESCE(array_to_string(missing_platforms, ', '), '-') AS "Missing",
                            COALESCE(TO_CHAR(last_seen_anywhere, 'YYYY-MM-DD HH24:MI'), 'Never') AS "Last seen"
                        FROM ninja_agent_compliance.v_all_devices_human
                        WHERE norm_name = (SELECT norm_name FROM anchor)
                        ORDER BY client_name, hostname
                    """,
                    0, 0, 24, 6,
                    template_tags=_DRILLDOWN_FILTER_TAGS,
                    param_mappings={
                        PARAM_DD_CUSTOMER: _mapping("customer"),
                        PARAM_DD_HOST: _mapping("host"),
                    },
                ),
                _card(
                    "drilldown_history",
                    "Recent state history",
                    "table",
                    """
                        SELECT
                            TO_CHAR(evaluated_at, 'YYYY-MM-DD HH24:MI') AS "When",
                            CASE WHEN is_compliant THEN 'Good' ELSE 'Needs review' END AS "State",
                            COALESCE(array_to_string(missing_required_platforms, ', '), '-') AS "Missing",
                            COALESCE(array_to_string(observed_platforms, ', '), '-') AS "Found in",
                            COALESCE(array_to_string(source_failed_platforms, ', '), '-') AS "Source issue"
                        FROM ninja_agent_compliance.compliance_matrix_history
                        WHERE hostname = {{host}}
                          [[AND client_name = {{customer}}]]
                        ORDER BY evaluated_at DESC
                        LIMIT 50
                    """,
                    8, 0, 24, 8,
                    template_tags=_DRILLDOWN_FILTER_TAGS,
                    param_mappings={
                        PARAM_DD_CUSTOMER: _mapping("customer"),
                        PARAM_DD_HOST: _mapping("host"),
                    },
                ),
                _card(
                    "drilldown_findings",
                    "Open and recent issues",
                    "table",
                    """
                        SELECT
                            severity AS "Severity",
                            CASE
                                WHEN finding_type = 'missing_required_platform'
                                    THEN COALESCE(affected_platform, 'Required platform') || ' missing'
                                WHEN finding_type = 'stale_required_platform'
                                    THEN COALESCE(affected_platform, 'Required platform') || ' stale'
                                WHEN finding_type = 'source_failure'
                                    THEN 'Collector failed'
                                ELSE finding_type
                            END AS "Issue",
                            status AS "State",
                            TO_CHAR(first_seen_at, 'YYYY-MM-DD HH24:MI') AS "First seen",
                            TO_CHAR(last_seen_at, 'YYYY-MM-DD HH24:MI') AS "Last seen",
                            summary AS "Summary"
                        FROM ninja_agent_compliance.compliance_findings
                        WHERE hostname = {{host}}
                          [[AND client_name = {{customer}}]]
                        ORDER BY last_seen_at DESC
                        LIMIT 50
                    """,
                    18, 0, 12, 8,
                    template_tags=_DRILLDOWN_FILTER_TAGS,
                    param_mappings={
                        PARAM_DD_CUSTOMER: _mapping("customer"),
                        PARAM_DD_HOST: _mapping("host"),
                    },
                ),
                _card(
                    "drilldown_suppressions",
                    "Ignores for this device",
                    "table",
                    """
                        SELECT
                            client_name AS "Customer",
                            COALESCE(NULLIF(display_name, ''), norm_name) AS "Device",
                            COALESCE(NULLIF(reason, ''), 'Ignored') AS "Reason",
                            expires AS "Expires",
                            TO_CHAR(updated_at, 'YYYY-MM-DD HH24:MI') AS "Updated",
                            'Restore' AS "Action"
                        FROM ninja_agent_compliance.v_device_ignores_current
                        WHERE display_name = {{host}}
                          [[AND client_name = {{customer}}]]
                        ORDER BY updated_at DESC
                        LIMIT 20
                    """,
                    18, 12, 12, 8,
                    column_click_behaviors={
                        "Action": {
                            "url_template": _url_template(
                                "/a/ui",
                                [("client", "Customer"), ("host", "Device")],
                            ),
                        },
                    },
                    template_tags=_DRILLDOWN_FILTER_TAGS,
                    param_mappings={
                        PARAM_DD_CUSTOMER: _mapping("customer"),
                        PARAM_DD_HOST: _mapping("host"),
                    },
                ),
            ],
        },
        {
            "name": DASH_ALERTS,
            "parameters_builder": _build_alerts_parameters,
            "section_headers": [
                {"row": 0, "text": "### Ready to notify"},
                {"row": 12, "text": "### Not notifying"},
                {"row": 24, "text": "### Delivery history"},
                {"row": 34, "text": "### Open issues"},
            ],
            "cards": [
                _card(
                    "alerts_ready",
                    "First notifications ready to send",
                    "table",
                    """
                        SELECT
                            severity AS "Severity",
                            client_name AS "Customer",
                            COALESCE(hostname, '-') AS "Device",
                            issue AS "Issue",
                            COALESCE(route_name, 'No route') AS "Route",
                            notification_status AS "Why",
                            summary AS "Summary"
                        FROM ninja_agent_compliance.v_notifications_ready
                        WHERE 1=1
                          [[AND client_name IN ({{customer}})]]
                          [[AND severity IN ({{severity}})]]
                          [[AND finding_type IN ({{finding_type}})]]
                        ORDER BY
                            CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                            client_name,
                            hostname
                        LIMIT 300
                    """,
                    0, 0, 24, 10,
                    column_widths={
                        "Severity": 90,
                        "Customer": 220,
                        "Device": 180,
                        "Issue": 300,
                        "Route": 180,
                        "Why": 260,
                        "Summary": 420,
                    },
                    template_tags=_ALERTS_FILTER_TAGS,
                    param_mappings={
                        PARAM_AL_CUSTOMER: _mapping("customer"),
                        PARAM_AL_SEVERITY: _mapping("severity"),
                        PARAM_AL_TYPE: _mapping("finding_type"),
                    },
                ),
                _card(
                    "alerts_not_notifying",
                    "Open issues not sending a first notification",
                    "table",
                    """
                        SELECT
                            severity AS "Severity",
                            client_name AS "Customer",
                            COALESCE(hostname, '-') AS "Device",
                            issue AS "Issue",
                            notification_status AS "Why not notifying",
                            COALESCE(TO_CHAR(last_seen_at, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "Last seen"
                        FROM ninja_agent_compliance.v_notification_queue
                        WHERE NOT ready_to_notify
                          [[AND client_name IN ({{customer}})]]
                          [[AND severity IN ({{severity}})]]
                          [[AND finding_type IN ({{finding_type}})]]
                        ORDER BY
                            CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                            client_name,
                            hostname
                        LIMIT 300
                    """,
                    12, 0, 24, 10,
                    column_widths={
                        "Severity": 90,
                        "Customer": 220,
                        "Device": 180,
                        "Issue": 300,
                        "Why not notifying": 420,
                        "Last seen": 150,
                    },
                    template_tags=_ALERTS_FILTER_TAGS,
                    param_mappings={
                        PARAM_AL_CUSTOMER: _mapping("customer"),
                        PARAM_AL_SEVERITY: _mapping("severity"),
                        PARAM_AL_TYPE: _mapping("finding_type"),
                    },
                ),
                _card(
                    "alerts_recent_deliveries_l1",
                    "Recently notified",
                    "table",
                    """
                        SELECT
                            TO_CHAR(ae.attempted_at, 'YYYY-MM-DD HH24:MI') AS "When",
                            ae.event_type AS "Event",
                            ae.status AS "Result",
                            COALESCE(nr.display_name, '-') AS "Route",
                            COALESCE(f.client_name, '-') AS "Customer",
                            COALESCE(f.hostname, '-') AS "Device",
                            COALESCE(f.summary, ae.response_preview, '-') AS "Summary"
                        FROM ninja_agent_compliance.alert_events ae
                        LEFT JOIN ninja_agent_compliance.notification_routes nr ON nr.route_id = ae.route_id
                        LEFT JOIN ninja_agent_compliance.compliance_findings f ON f.finding_id = ae.finding_id
                        WHERE 1=1
                          [[AND f.client_name IN ({{customer}})]]
                          [[AND f.severity IN ({{severity}})]]
                          [[AND f.finding_type IN ({{finding_type}})]]
                        ORDER BY ae.attempted_at DESC
                        LIMIT 150
                    """,
                    24, 0, 24, 8,
                    template_tags=_ALERTS_FILTER_TAGS,
                    param_mappings={
                        PARAM_AL_CUSTOMER: _mapping("customer"),
                        PARAM_AL_SEVERITY: _mapping("severity"),
                        PARAM_AL_TYPE: _mapping("finding_type"),
                    },
                ),
                _card(
                    "alerts_open_issues",
                    "Open device issues",
                    "table",
                    """
                        SELECT
                            severity AS "Severity",
                            client_name AS "Customer",
                            COALESCE(hostname, '-') AS "Device",
                            issue AS "Issue",
                            summary AS "Summary",
                            notification_status AS "Notification status"
                        FROM ninja_agent_compliance.v_notification_queue
                        WHERE 1=1
                          [[AND client_name IN ({{customer}})]]
                          [[AND severity IN ({{severity}})]]
                          [[AND finding_type IN ({{finding_type}})]]
                        ORDER BY
                            CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                            last_seen_at DESC
                        LIMIT 500
                    """,
                    34, 0, 24, 10,
                    template_tags=_ALERTS_FILTER_TAGS,
                    param_mappings={
                        PARAM_AL_CUSTOMER: _mapping("customer"),
                        PARAM_AL_SEVERITY: _mapping("severity"),
                        PARAM_AL_TYPE: _mapping("finding_type"),
                    },
                ),
            ],
        },
        {
            "name": DASH_CUSTOMERS,
            "parameters_builder": _build_customers_parameters,
            "cards": [
                _card(
                    "customers_directory_l1",
                    "Customers and platform names",
                    "table",
                    """
                        WITH names AS (
                            SELECT
                                c.client_id,
                                c.client_name,
                                STRING_AGG(DISTINCT a.alias_value, ', ' ORDER BY a.alias_value)
                                    FILTER (WHERE a.enabled AND a.platform = 'Ninja') AS ninja_names,
                                STRING_AGG(DISTINCT a.alias_value, ', ' ORDER BY a.alias_value)
                                    FILTER (WHERE a.enabled AND a.platform = 'SentinelOne') AS s1_names,
                                STRING_AGG(DISTINCT a.alias_value, ', ' ORDER BY a.alias_value)
                                    FILTER (WHERE a.enabled AND a.platform = 'LogMeIn') AS lmi_names,
                                STRING_AGG(DISTINCT a.alias_value, ', ' ORDER BY a.alias_value)
                                    FILTER (WHERE a.enabled AND a.platform = 'ScreenConnect') AS sc_names
                            FROM ninja_agent_compliance.clients c
                            LEFT JOIN ninja_agent_compliance.client_aliases a ON a.client_id = c.client_id
                            WHERE c.enabled
                              AND c.source NOT IN ('alignment', 'demoted')
                              AND lower(trim(c.client_name)) NOT IN ('default site', 'unknown', 'various', '.default')
                            GROUP BY c.client_id, c.client_name
                        )
                        SELECT
                            client_name AS "Customer",
                            COALESCE(NULLIF(ninja_names, ''), '-') AS "Ninja",
                            COALESCE(NULLIF(s1_names, ''), '-') AS "SentinelOne",
                            COALESCE(NULLIF(lmi_names, ''), '-') AS "LogMeIn",
                            COALESCE(NULLIF(sc_names, ''), '-') AS "ScreenConnect"
                        FROM names
                        ORDER BY client_name
                        LIMIT 300
                    """,
                    0, 0, 24, 10,
                ),
                _card(
                    "customers_names_to_review_l1",
                    "Customer names to review",
                    "table",
                    """
                        SELECT
                            candidate_name AS "Name found",
                            platform AS "Found in",
                            current_devices AS "Devices",
                            COALESCE(NULLIF(suggested_customer, ''), '-') AS "Suggested customer",
                            review_reason AS "Why review",
                            'Add customer' AS "Add",
                            CASE WHEN suggested_customer <> '' THEN 'Alias suggestion' ELSE '' END AS "Alias suggestion",
                            'Choose customer' AS "Choose customer",
                            'Ignore name' AS "Ignore"
                        FROM ninja_agent_compliance.v_customer_name_queue
                        WHERE 1=1
                          [[AND candidate_name ILIKE '%' || {{review_name}} || '%']]
                        ORDER BY current_devices DESC, candidate_name
                        LIMIT 200
                    """,
                    10, 0, 24, 8,
                    column_click_behaviors={
                        "Add": {
                            "url_template": _url_template("/a/ac", [("name", "Name found")]),
                        },
                        "Alias suggestion": {
                            "url_template": _url_template(
                                "/a/aa",
                                [
                                    ("client_name", "Suggested customer"),
                                    ("platform", "Found in"),
                                    ("alias", "Name found"),
                                ],
                            ),
                        },
                        "Choose customer": {
                            "url_template": _url_template(
                                "/a/ma",
                                [("platform", "Found in"), ("alias", "Name found")],
                            ),
                        },
                        "Ignore": {
                            "url_template": _url_template("/a/eo", [("pattern", "Name found")]),
                        },
                    },
                    template_tags={"review_name": _CUSTOMERS_FILTER_TAGS["review_name"]},
                    param_mappings={PARAM_CU_REVIEW_NAME: _mapping("review_name")},
                ),
                _card(
                    "customers_platform_names_l1",
                    "Platform names by customer",
                    "table",
                    """
                        SELECT
                            c.client_name AS "Customer",
                            a.platform AS "Platform",
                            a.alias_value AS "Name used there",
                            COALESCE(TO_CHAR(a.updated_at, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "Updated"
                        FROM ninja_agent_compliance.client_aliases a
                        JOIN ninja_agent_compliance.clients c ON c.client_id = a.client_id
                        WHERE a.enabled
                          AND c.enabled
                          AND c.source NOT IN ('alignment', 'demoted')
                        ORDER BY c.client_name, a.platform, a.alias_value
                        LIMIT 500
                    """,
                    18, 0, 24, 8,
                ),
                _card(
                    "customers_ignored_names_l1",
                    "Ignored customer names",
                    "table",
                    """
                        SELECT
                            pattern AS "Name",
                            COALESCE(NULLIF(notes, ''), 'No notes') AS "Reason",
                            COALESCE(TO_CHAR(updated_at, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "Updated",
                            CASE WHEN source = 'manual' THEN 'Restore' ELSE '' END AS "Action"
                        FROM ninja_agent_compliance.org_excludes
                        WHERE enabled
                        ORDER BY source, pattern
                        LIMIT 200
                    """,
                    26, 0, 24, 5,
                    column_click_behaviors={
                        "Action": {
                            "url_template": _url_template("/a/ue", [("pattern", "Name")]),
                        },
                    },
                ),
            ],
        },
        {
            "name": DASH_SETUP,
            "section_headers": [
                {"row": 0, "text": "### Required platforms"},
                {"row": 12, "text": "### Alert setup"},
                {"row": 30, "text": "### Routes and sources"},
            ],
            "cards": [
                _card(
                    "setup_required_platforms",
                    "Required platforms",
                    "table",
                    """
                        SELECT
                            client_name AS "Customer",
                            label AS "Applies to",
                            ninja_required AS "Ninja",
                            sentinelone_required AS "SentinelOne",
                            logmein_required AS "LogMeIn",
                            screenconnect_required AS "ScreenConnect",
                            max_age_days AS "Max age",
                            setting_source AS "Setting",
                            '7d' AS "Age 7d",
                            '30d' AS "Age 30d",
                            '90d' AS "Age 90d",
                            CASE WHEN can_use_default THEN 'Use default' ELSE '' END AS "Default"
                        FROM ninja_agent_compliance.v_required_platforms_effective
                        ORDER BY client_name, CASE label WHEN 'All devices' THEN 0 WHEN 'Servers' THEN 1 ELSE 2 END
                        LIMIT 500
                    """,
                    0, 0, 24, 10,
                    column_click_behaviors={
                        "Ninja": {
                            "url_template": f"{ACTION_BASE_URL}/a/tp?customer={{{{Customer}}}}&scope={{{{Applies to}}}}&platform=Ninja&confirm=1",
                        },
                        "SentinelOne": {
                            "url_template": f"{ACTION_BASE_URL}/a/tp?customer={{{{Customer}}}}&scope={{{{Applies to}}}}&platform=SentinelOne&confirm=1",
                        },
                        "LogMeIn": {
                            "url_template": f"{ACTION_BASE_URL}/a/tp?customer={{{{Customer}}}}&scope={{{{Applies to}}}}&platform=LogMeIn&confirm=1",
                        },
                        "ScreenConnect": {
                            "url_template": f"{ACTION_BASE_URL}/a/tp?customer={{{{Customer}}}}&scope={{{{Applies to}}}}&platform=ScreenConnect&confirm=1",
                        },
                        "Age 7d": {
                            "url_template": f"{ACTION_BASE_URL}/a/sd?customer={{{{Customer}}}}&scope={{{{Applies to}}}}&days=7&confirm=1",
                        },
                        "Age 30d": {
                            "url_template": f"{ACTION_BASE_URL}/a/sd?customer={{{{Customer}}}}&scope={{{{Applies to}}}}&days=30&confirm=1",
                        },
                        "Age 90d": {
                            "url_template": f"{ACTION_BASE_URL}/a/sd?customer={{{{Customer}}}}&scope={{{{Applies to}}}}&days=90&confirm=1",
                        },
                        "Default": {
                            "url_template": f"{ACTION_BASE_URL}/a/sr?customer={{{{Customer}}}}&scope={{{{Applies to}}}}&profile=default&confirm=1",
                        },
                    },
                ),
                _card(
                    "setup_customer_alerts",
                    "Customer alert setup",
                    "table",
                    """
                        SELECT
                            client_name AS "Customer",
                            alert_key AS "Alert key",
                            alert_name AS "Alert",
                            customer_alert AS "State",
                            route_name AS "Route",
                            route_state AS "Route state",
                            CASE WHEN NOT enabled_for_customer THEN 'Turn on' ELSE '' END AS "Turn on",
                            CASE WHEN enabled_for_customer THEN 'Turn off' ELSE '' END AS "Turn off"
                        FROM ninja_agent_compliance.v_customer_alert_setup
                        ORDER BY client_name, alert_name
                        LIMIT 500
                    """,
                    12, 0, 24, 10,
                    column_click_behaviors={
                        "Turn on": {
                            "url_template": f"{ACTION_BASE_URL}/a/sca?customer={{{{Customer}}}}&alert={{{{Alert key}}}}&state=on&confirm=1",
                        },
                        "Turn off": {
                            "url_template": f"{ACTION_BASE_URL}/a/sca?customer={{{{Customer}}}}&alert={{{{Alert key}}}}&state=off&confirm=1",
                        },
                    },
                ),
                _card(
                    "setup_alert_rules",
                    "Alert rules",
                    "table",
                    """
                        SELECT
                            rule_key AS "Rule",
                            alert_name AS "Alert",
                            customer_name AS "Customer",
                            applies_to AS "Applies to",
                            severity AS "Severity",
                            route_name AS "Route",
                            route_state AS "Route state",
                            rule_state AS "State",
                            CASE WHEN enabled THEN 'Turn off' ELSE '' END AS "Turn off",
                            CASE WHEN NOT enabled THEN 'Turn on' ELSE '' END AS "Turn on"
                        FROM ninja_agent_compliance.v_alert_rules_human
                        ORDER BY
                            CASE WHEN rule_state = 'On' THEN 0 ELSE 1 END,
                            alert_name,
                            customer_name
                        LIMIT 300
                    """,
                    22, 0, 24, 8,
                    column_click_behaviors={
                        "Turn off": {
                            "url_template": f"{ACTION_BASE_URL}/a/tr?rule={{{{Rule}}}}&state=off&confirm=1",
                        },
                        "Turn on": {
                            "url_template": f"{ACTION_BASE_URL}/a/tr?rule={{{{Rule}}}}&state=on&confirm=1",
                        },
                    },
                ),
                _card(
                    "setup_routes",
                    "Notification routes",
                    "table",
                    """
                        SELECT
                            display_name AS "Route",
                            route_type AS "Type",
                            state AS "State",
                            setting AS "Configured from",
                            updated AS "Updated"
                        FROM ninja_agent_compliance.v_notification_routes_human
                        ORDER BY "Type", "Route"
                    """,
                    30, 0, 12, 6,
                ),
                _card(
                    "setup_sources",
                    "Sources",
                    "table",
                    """
                        SELECT
                            source_name AS "Source",
                            platform AS "Platform",
                            COALESCE(NULLIF(client_name, ''), 'Shared') AS "Customer",
                            CASE WHEN enabled THEN 'On' ELSE 'Off' END AS "State",
                            CASE
                                WHEN base_url IS NULL OR base_url = '' THEN 'No URL'
                                ELSE 'URL set'
                            END AS "Connection"
                        FROM ninja_agent_compliance.platform_sources ps
                        LEFT JOIN ninja_agent_compliance.clients c ON c.client_id = ps.client_id
                        ORDER BY platform, source_name
                    """,
                    30, 12, 12, 6,
                ),
            ],
        },
        {
            "name": DASH_HEALTH,
            "cards": [
                _card(
                    "health_problems",
                    "Collection and delivery problems",
                    "table",
                    """
                        SELECT
                            work_type AS "Problem",
                            platform AS "Area",
                            source_name AS "Source",
                            customer_name AS "Customer",
                            rows_observed AS "Rows",
                            issue AS "Issue"
                        FROM ninja_agent_compliance.v_system_health_queue
                        ORDER BY severity DESC, platform, source_name, customer_name
                        LIMIT 200
                    """,
                    0, 0, 24, 8,
                ),
                _card(
                    "health_sources",
                    "All sources",
                    "table",
                    """
                        SELECT
                            source_name AS "Source",
                            platform AS "Platform",
                            COALESCE(NULLIF(client_name, ''), 'Shared') AS "Customer",
                            status AS "State",
                            rows_observed AS "Rows",
                            COALESCE(TO_CHAR(finished_at, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "Finished",
                            COALESCE(NULLIF(error_text, ''), '-') AS "Issue"
                        FROM ninja_agent_compliance.v_source_health_current
                        ORDER BY platform, source_name
                    """,
                    8, 0, 24, 8,
                ),
                _card(
                    "health_missing_by_platform",
                    "Current device gaps",
                    "bar",
                    """
                        SELECT
                            p AS "Missing",
                            COUNT(DISTINCT (client_id, norm_name)) AS "Devices"
                        FROM ninja_agent_compliance.v_device_work_queue q
                        CROSS JOIN LATERAL unnest(q.missing_platforms) AS p
                        GROUP BY p
                        ORDER BY "Devices" DESC
                    """,
                    16, 0, 12, 6,
                ),
                _card(
                    "health_names_by_platform",
                    "Names needing review by platform",
                    "bar",
                    """
                        SELECT
                            platform AS "Platform",
                            COUNT(*) AS "Names"
                        FROM ninja_agent_compliance.v_customer_name_queue
                        GROUP BY platform
                        ORDER BY "Names" DESC
                    """,
                    16, 12, 12, 6,
                ),
            ],
        },
        {
            "name": DASH_DEBUG,
            "cards": [
                _card(
                    "debug_raw_observations",
                    "Raw observations",
                    "table",
                    """
                        SELECT
                            observed_at AS "Seen",
                            platform AS "Platform",
                            source_name AS "Source",
                            COALESCE(NULLIF(resolved_client_name, ''), 'Unresolved') AS "Customer",
                            hostname AS "Device",
                            COALESCE(NULLIF(platform_group_name, ''), 'Unknown') AS "Group",
                            COALESCE(NULLIF(platform_group_id, ''), 'Unknown') AS "Group ID",
                            raw_data AS "Raw data"
                        FROM ninja_agent_compliance.platform_observations
                        ORDER BY observed_at DESC
                        LIMIT 200
                    """,
                    0, 0, 24, 10,
                ),
                _card(
                    "debug_cross_customer_conflicts",
                    "Same name across customers",
                    "table",
                    """
                        WITH conflicts AS (
                            SELECT
                                norm_name,
                                string_agg(DISTINCT client_name, ', ' ORDER BY client_name) AS customers,
                                string_agg(DISTINCT hostname, ', ' ORDER BY hostname) AS devices,
                                string_agg(DISTINCT platform_name, ', ' ORDER BY platform_name) AS platforms_seen
                            FROM ninja_agent_compliance.v_cross_client_conflicts
                            CROSS JOIN LATERAL unnest(observed_platforms) AS p(platform_name)
                            GROUP BY norm_name
                        )
                        SELECT
                            norm_name AS "Match key",
                            customers AS "Customers",
                            devices AS "Device",
                            COALESCE(platforms_seen, '-') AS "Platforms seen"
                        FROM conflicts
                        ORDER BY norm_name
                        LIMIT 300
                    """,
                    10, 0, 24, 8,
                    column_click_behaviors={
                        "Device": _dashboard_link(
                            DASH_DEVICE_DRILLDOWN,
                            params=[("host", "Device")],
                        ),
                    },
                ),
                _card(
                    "debug_notification_queue",
                    "Notification decision details",
                    "table",
                    """
                        SELECT
                            finding_signature AS "Signature",
                            client_name AS "Customer",
                            COALESCE(hostname, '-') AS "Device",
                            finding_type AS "Finding type",
                            COALESCE(affected_platform, '-') AS "Platform",
                            ready_to_notify AS "Ready",
                            notification_status AS "Decision",
                            COALESCE(rule_key, '-') AS "Rule",
                            COALESCE(route_name, '-') AS "Route"
                        FROM ninja_agent_compliance.v_notification_queue
                        ORDER BY ready_to_notify DESC, client_name, hostname
                        LIMIT 300
                    """,
                    18, 0, 24, 8,
                ),
            ],
        },
    ]


DASHBOARDS = _level1_dashboards()


def run_bootstrap(url: str, user: str, password: str, db_name: str = "Ninja") -> list[str]:
    with httpx.Client(base_url=url, timeout=60) as client:
        _authenticate(client, user, password)
        db_id = _find_database(client, db_name)
        collection_id = _upsert_collection(client, COLLECTION_NAME)
        existing_cards = _list_cards(client, collection_id)

        all_cards = [card for dash in DASHBOARDS for card in dash["cards"]]
        card_ids = {
            card["key"]: _upsert_card(client, card, db_id, collection_id, existing_cards)
            for card in all_cards
        }

        # Build dashboard-level parameter widgets up front. Customer lists
        # come from Postgres so they can't be baked into the module-level
        # DASHBOARDS constant.
        dashboard_params: dict[str, list[dict[str, Any]]] = {}
        for dash_spec in DASHBOARDS:
            builder: Callable[[], list[dict[str, Any]]] | None = dash_spec.get("parameters_builder")
            if builder is None:
                continue
            try:
                dashboard_params[dash_spec["name"]] = builder()
            except Exception:
                log.exception(
                    "Parameter builder failed for dashboard %r; falling back to no filters",
                    dash_spec["name"],
                )
                dashboard_params[dash_spec["name"]] = []

        dash_id_by_name: dict[str, int] = {}
        dash_obj_by_name: dict[str, dict[str, Any]] = {}
        urls: list[str] = []

        for dash_spec in DASHBOARDS:
            dashboard = _upsert_dashboard(
                client,
                dash_spec["name"],
                collection_id,
                parameters=dashboard_params.get(dash_spec["name"]),
            )
            dash_id_by_name[dash_spec["name"]] = int(dashboard["id"])
            dash_obj_by_name[dash_spec["name"]] = dashboard
            urls.append(f"dashboard/{dashboard['id']}  ({dash_spec['name']})")

        for dash_spec in DASHBOARDS:
            nav_md = _build_nav_markdown(dash_spec["name"], dash_id_by_name)
            _set_layout(
                client,
                dash_obj_by_name[dash_spec["name"]],
                dash_spec["cards"],
                card_ids,
                nav_markdown=nav_md,
                dash_id_by_name=dash_id_by_name,
                section_headers=dash_spec.get("section_headers"),
            )

        card_ids_by_dash = {
            dash_spec["name"]: {card["key"]: card_ids[card["key"]] for card in dash_spec["cards"]}
            for dash_spec in DASHBOARDS
        }
        _apply_click_behaviors(client, DASHBOARDS, card_ids_by_dash, dash_id_by_name)

        _set_custom_homepage(client, dash_id_by_name.get(DASH_TODAY))
        return urls


def _authenticate(client: httpx.Client, user: str, password: str) -> None:
    resp = client.post("/api/session", json={"username": user, "password": password})
    resp.raise_for_status()
    client.headers["X-Metabase-Session"] = resp.json()["id"]


def _find_database(client: httpx.Client, name: str) -> int:
    resp = client.get("/api/database")
    resp.raise_for_status()
    for db in resp.json().get("data", []):
        if db.get("name") == name:
            return int(db["id"])
    raise RuntimeError(f"Metabase database not found: {name}")


def _upsert_collection(client: httpx.Client, name: str) -> int:
    resp = client.get("/api/collection")
    resp.raise_for_status()
    for collection in resp.json():
        if collection.get("name") == name and not collection.get("archived", False):
            return int(collection["id"])
    resp = client.post("/api/collection", json={"name": name, "color": "#546E7A"})
    resp.raise_for_status()
    return int(resp.json()["id"])


def _list_cards(client: httpx.Client, collection_id: int) -> list[dict[str, Any]]:
    resp = client.get(f"/api/collection/{collection_id}/items", params={"models": "card"})
    resp.raise_for_status()
    payload = resp.json()
    items = payload["data"] if isinstance(payload, dict) and "data" in payload else payload
    return [item for item in items if item.get("model") == "card"]


def _uid(key: str) -> str:
    return f"agent-compliance:{key}"


def _upsert_card(
    client: httpx.Client,
    spec: dict[str, Any],
    db_id: int,
    collection_id: int,
    existing_cards: list[dict[str, Any]],
) -> int:
    native: dict[str, Any] = {"query": spec["query"].strip()}
    if "template_tags" in spec:
        native["template-tags"] = spec["template_tags"]
    body = {
        "name": spec["name"],
        "description": _uid(spec["key"]),
        "display": spec["display"],
        "visualization_settings": {},
        "collection_id": collection_id,
        "dataset_query": {
            "type": "native",
            "database": db_id,
            "native": native,
        },
    }
    existing = next((card for card in existing_cards if card.get("description") == _uid(spec["key"])), None)
    if existing:
        card_id = int(existing["id"])
        resp = client.put(f"/api/card/{card_id}", json=body)
        resp.raise_for_status()
        return card_id
    resp = client.post("/api/card", json=body)
    resp.raise_for_status()
    return int(resp.json()["id"])


def _upsert_dashboard(
    client: httpx.Client,
    name: str,
    collection_id: int,
    parameters: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resp = client.get("/api/dashboard")
    resp.raise_for_status()
    dashboard = None
    for d in resp.json():
        if d.get("name") == name and d.get("collection_id") == collection_id:
            detail = client.get(f"/api/dashboard/{d['id']}")
            detail.raise_for_status()
            dashboard = detail.json()
            break
    if dashboard is None:
        resp = client.post("/api/dashboard", json={"name": name, "collection_id": collection_id})
        resp.raise_for_status()
        dashboard = resp.json()
    if parameters is not None:
        resp = client.put(
            f"/api/dashboard/{dashboard['id']}",
            json={"parameters": parameters},
        )
        resp.raise_for_status()
        dashboard = resp.json()
    return dashboard


def _build_nav_markdown(current_dash_name: str, dash_id_by_name: dict[str, int]) -> str:
    parts: list[str] = []
    for name in NAV_ORDER:
        label = NAV_LABELS.get(name, name)
        if name == current_dash_name:
            parts.append(f"**{label}**")
            continue
        dash_id = dash_id_by_name.get(name)
        if dash_id is None:
            continue
        parts.append(f"[{label}](/dashboard/{dash_id})")
    return " | ".join(parts)


def _nav_dashcard(text: str) -> dict[str, Any]:
    return {
        "id": -1,
        "card_id": None,
        "row": 0,
        "col": 0,
        "size_x": 24,
        "size_y": NAV_HEIGHT,
        "parameter_mappings": [],
        "visualization_settings": {
            "virtual_card": {
                "display": "text",
                "name": None,
                "archived": False,
                "dataset_query": {},
            },
            "text": text,
        },
    }


def _section_header_dashcard(text: str, row: int, idx: int) -> dict[str, Any]:
    """Markdown divider between groups of cards. `text` is rendered
    verbatim — use `### Section name` or similar for emphasis."""
    return {
        "id": -(1000 + idx),
        "card_id": None,
        "row": row,
        "col": 0,
        "size_x": 24,
        "size_y": SECTION_HEADER_HEIGHT,
        "parameter_mappings": [],
        "visualization_settings": {
            "virtual_card": {
                "display": "text",
                "name": None,
                "archived": False,
                "dataset_query": {},
            },
            "text": text,
        },
    }


def _set_layout(
    client: httpx.Client,
    dashboard: dict[str, Any],
    specs: list[dict[str, Any]],
    card_ids: dict[str, int],
    nav_markdown: str | None = None,
    dash_id_by_name: dict[str, int] | None = None,
    section_headers: list[dict[str, Any]] | None = None,
) -> None:
    """Section headers are markdown dividers between groups of cards.
    Pass `[{"row": <natural_row>, "text": "### Triage"}, ...]`. Each
    header inserted at a natural row pushes every card at or below
    that row down by SECTION_HEADER_HEIGHT, so card spec rows stay at
    their natural positions and don't need to bake in header offsets."""
    dashcards = []
    row_offset = NAV_HEIGHT if nav_markdown is not None else 0
    if nav_markdown is not None:
        dashcards.append(_nav_dashcard(nav_markdown))

    headers = sorted(section_headers or [], key=lambda h: h["row"])

    def shift(orig_row: int) -> int:
        return orig_row + sum(
            SECTION_HEADER_HEIGHT for h in headers if h["row"] <= orig_row
        )

    for i, h in enumerate(headers):
        prior = sum(1 for hh in headers if hh["row"] < h["row"])
        header_row = h["row"] + prior * SECTION_HEADER_HEIGHT
        dashcards.append(
            _section_header_dashcard(h["text"], header_row + row_offset, i)
        )

    for i, spec in enumerate(specs):
        card_id = card_ids[spec["key"]]
        param_mappings = [
            {"parameter_id": pid, "card_id": card_id, "target": target}
            for pid, target in (spec.get("param_mappings") or {}).items()
        ]
        dashcard_viz: dict[str, Any] = {}
        column_settings = _build_column_settings(spec, dash_id_by_name)
        if column_settings:
            dashcard_viz["column_settings"] = column_settings
        dashcards.append({
            "id": -(i + 2),
            "card_id": card_id,
            "row": shift(spec["row"]) + row_offset,
            "col": spec["col"],
            "size_x": spec["size_x"],
            "size_y": spec["size_y"],
            "parameter_mappings": param_mappings,
            "visualization_settings": dashcard_viz,
        })
    resp = client.put(f"/api/dashboard/{dashboard['id']}", json={"dashcards": dashcards})
    resp.raise_for_status()


def _apply_click_behaviors(
    client: httpx.Client,
    dashboards: list[dict[str, Any]],
    card_ids_by_dash: dict[str, dict[str, int]],
    dash_id_by_name: dict[str, int],
) -> None:
    for dash_spec in dashboards:
        current_dash_name = dash_spec["name"]
        for card_spec in dash_spec["cards"]:
            click_spec = card_spec.get("click_behavior")
            column_specs = card_spec.get("column_click_behaviors") or {}
            if not click_spec and not column_specs:
                continue
            card_id = card_ids_by_dash[current_dash_name][card_spec["key"]]
            r = client.get(f"/api/card/{card_id}")
            r.raise_for_status()
            current = r.json().get("visualization_settings") or {}
            if click_spec:
                cb = _build_click_behavior_json(click_spec, dash_id_by_name)
                if cb:
                    current["click_behavior"] = cb
            if column_specs:
                column_settings: dict[str, dict[str, Any]] = dict(current.get("column_settings") or {})
                for col, col_spec in column_specs.items():
                    cb = _build_click_behavior_json(col_spec, dash_id_by_name)
                    if cb:
                        column_settings[f'["name","{col}"]'] = {"click_behavior": cb}
                if column_settings:
                    current["column_settings"] = column_settings
            r = client.put(
                f"/api/card/{card_id}",
                json={"visualization_settings": current},
            )
            r.raise_for_status()


def _build_column_settings(
    spec: dict[str, Any],
    dash_id_by_name: dict[str, int] | None = None,
) -> dict[str, dict[str, Any]]:
    column_settings: dict[str, dict[str, Any]] = {}
    for col, width in (spec.get("column_widths") or {}).items():
        column_settings[f'["name","{col}"]'] = {"column_width": int(width)}
    for col, col_spec in (spec.get("column_click_behaviors") or {}).items():
        cb = _build_click_behavior_json(col_spec, dash_id_by_name or {})
        if cb:
            column_settings.setdefault(f'["name","{col}"]', {})["click_behavior"] = cb
    return column_settings


def _set_custom_homepage(client: httpx.Client, dashboard_id: int | None) -> None:
    if dashboard_id is None:
        log.warning("Custom homepage: dashboard id unknown, skipping")
        return
    for endpoint, payload in (
        ("/api/setting/custom-homepage", {"value": True}),
        ("/api/setting/custom-homepage-dashboard", {"value": dashboard_id}),
    ):
        try:
            resp = client.put(endpoint, json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            log.warning("Custom homepage setting failed for %s: %s", endpoint, exc)
            return
    log.info("Set custom homepage to Agent Compliance today id=%d", dashboard_id)
