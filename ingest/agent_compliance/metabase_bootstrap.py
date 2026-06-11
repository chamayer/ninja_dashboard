"""Provision the Agent Compliance Metabase collection and dashboards.

This module builds the dashboard surface from scratch around a simple
human workflow:

* Today: what needs attention right now.
* Devices: device-level fixes and ignore/restore.
* Customers: customer names across platforms and customer-name review.
* Health: source health and system-level collection work.
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
DASH_CUSTOMERS = "Agent Compliance - Customers"
DASH_HEALTH = "Agent Compliance - Health"
DASH_DEBUG = "Agent Compliance - Debug"

# ── Devices dashboard parameter slugs + IDs ─────────────────────────
# These slugs also act as URL query keys for cross-card drill-through.
PARAM_CUSTOMER = "p_dev_customer"
PARAM_MISSING = "p_dev_missing"
PARAM_ONLINE_IN = "p_dev_online_in"
PARAM_STATE = "p_dev_state"
PARAM_AV_EXEMPT = "p_dev_av"

PLATFORM_VALUES = ["Ninja", "ScreenConnect", "SentinelOne", "LogMeIn"]
STATE_VALUES = ["Stale", "Degraded", "Review"]
AV_EXEMPT_VALUES = ["Yes", "No"]

NAV_ORDER = [DASH_TODAY, DASH_DEVICES, DASH_CUSTOMERS, DASH_HEALTH, DASH_DEBUG]
NAV_LABELS = {
    DASH_TODAY: "Today",
    DASH_DEVICES: "Devices",
    DASH_CUSTOMERS: "Customers",
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


def _url_template(path: str, params: list[tuple[str, str]]) -> str:
    query = "&".join(f"{key}={{{{{field}}}}}" for key, field in params)
    suffix = f"?{query}&confirm=1" if query else "?confirm=1"
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


def _build_devices_parameters() -> list[dict[str, Any]]:
    customer_values = _fetch_customer_values()
    return [
        _param_multiselect(PARAM_CUSTOMER, "Customer", "customer", customer_values),
        _param_multiselect(PARAM_MISSING, "Missing platform", "missing", PLATFORM_VALUES),
        _param_multiselect(PARAM_ONLINE_IN, "Online in", "online_in", PLATFORM_VALUES),
        _param_multiselect(PARAM_STATE, "State", "state", STATE_VALUES),
        _param_multiselect(PARAM_AV_EXEMPT, "NO AV", "av", AV_EXEMPT_VALUES),
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
}


DASHBOARDS = [
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
                0, 0, 5, 4,
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
                0, 5, 5, 4,
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
                0, 10, 5, 4,
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
                0, 15, 5, 4,
                click_behavior=_dashboard_link(DASH_CUSTOMERS),
            ),
            _card(
                "ignored_devices_count",
                "Ignored devices",
                "scalar",
                """
                    SELECT COUNT(*) AS "Ignored devices"
                    FROM ninja_agent_compliance.v_device_ignores_current
                """,
                0, 20, 4, 4,
                click_behavior=_dashboard_link(DASH_DEVICES),
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
        ],
        "cards": [
            _card(
                "device_queue",
                "Need action",
                "table",
                """
                    SELECT
                        m.client_name AS "Customer",
                        m.hostname AS "Device",
                        m.device_type AS "Type",
                        COALESCE(array_to_string(m.missing_required_platforms, ', '), 'None') AS "Need",
                        CASE
                            WHEN m.is_degraded THEN 'Degraded'
                            WHEN m.is_stale THEN 'Stale'
                            ELSE 'Review'
                        END AS "State",
                        CASE WHEN m.s1_exempt THEN 'Yes' ELSE 'No' END AS "NO AV",
                        'Ignore' AS "Action"
                    FROM ninja_agent_compliance.compliance_matrix_current m
                    WHERE NOT m.is_unknown
                      -- Include both noncompliant and degraded-but-compliant rows.
                      -- Degraded = compliant overall but at least one required
                      -- platform is offline; PowerShell parity surfaces these in
                      -- the operator queue, not only the strict noncompliant set.
                      AND (NOT m.is_compliant OR m.is_degraded)
                      AND NOT EXISTS (
                          SELECT 1
                          FROM ninja_agent_compliance.alert_suppressions s
                          WHERE s.enabled
                            AND (s.client_id IS NULL OR s.client_id = m.client_id)
                            AND (s.norm_name IS NULL OR s.norm_name = m.norm_name)
                            AND (s.expires_at IS NULL OR s.expires_at > now())
                      )
                      [[AND m.client_name IN ({{customer}})]]
                      [[AND (
                          CASE
                              WHEN m.is_degraded THEN 'Degraded'
                              WHEN m.is_stale THEN 'Stale'
                              ELSE 'Review'
                          END
                      ) IN ({{state}})]]
                      [[AND (CASE WHEN m.s1_exempt THEN 'Yes' ELSE 'No' END) IN ({{av}})]]
                    ORDER BY m.client_name, m.hostname
                    LIMIT 500
                """,
                0, 0, 24, 10,
                column_click_behaviors={
                    "Action": {
                        "url_template": _url_template(
                            "/a/ig",
                            [("client", "Customer"), ("host", "Device")],
                        ),
                    },
                },
                template_tags={
                    "customer": _DEVICES_FILTER_TAGS["customer"],
                    "state": _DEVICES_FILTER_TAGS["state"],
                    "av": _DEVICES_FILTER_TAGS["av"],
                },
                param_mappings={
                    PARAM_CUSTOMER: _mapping("customer"),
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
                        COALESCE(TO_CHAR(last_seen_at, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "Seen there",
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
        "name": DASH_CUSTOMERS,
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
                    )
                    SELECT
                        c.candidate_name AS "Customer name",
                        c.platform AS "Found in",
                        COALESCE(l.latest_devices, 0) AS "Current devices",
                        COALESCE(NULLIF(c.source_name, ''), 'Unknown') AS "Source",
                        COALESCE(TO_CHAR(c.last_seen_at, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "Last seen",
                        'This is a customer' AS "Approve",
                        'Ignore name' AS "Ignore"
                    FROM ninja_agent_compliance.v_org_candidates_current c
                    LEFT JOIN latest_counts l
                      ON l.platform = c.platform
                     AND l.norm_name = lower(trim(c.candidate_name))
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
                    "Ignore": {
                        "url_template": _url_template(
                            "/a/eo",
                            [("pattern", "Customer name")],
                        ),
                    },
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
                        CASE
                            WHEN a.source = 'manual' THEN 'Reviewed'
                            WHEN a.source = 'seed' THEN 'Built in'
                            WHEN a.source = 'alignment' THEN 'Auto matched'
                            ELSE a.source
                        END AS "Source",
                        COALESCE(NULLIF(a.notes, ''), '') AS "Notes",
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
                22, 0, 24, 8,
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
                        array_to_string(required_platforms, ', ') AS "Required",
                        COALESCE(max_age_days, 30) AS "Max age",
                        CASE
                            WHEN source_client_id IS NULL THEN 'Default'
                            WHEN source_scope <> device_scope AND source = 'manual' THEN 'Reviewed, from all devices'
                            WHEN source_scope <> device_scope AND source = 'seed' THEN 'Built in, from all devices'
                            WHEN source = 'manual' THEN 'Reviewed'
                            WHEN source = 'seed' THEN 'Built in'
                            ELSE source
                        END AS "Source",
                        'Set' AS "Ninja + S1",
                        'Set' AS "Ninja + LMI",
                        'Set' AS "Ninja + S1 + LMI",
                        'Set' AS "Ninja + S1 + SC",
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
                30, 0, 24, 10,
                column_click_behaviors={
                    "Ninja + S1": {
                        "url_template": f"{ACTION_BASE_URL}/a/sr?customer={{{{Customer}}}}&scope={{{{Applies to}}}}&profile=ninja_s1&confirm=1",
                    },
                    "Ninja + LMI": {
                        "url_template": f"{ACTION_BASE_URL}/a/sr?customer={{{{Customer}}}}&scope={{{{Applies to}}}}&profile=ninja_lmi&confirm=1",
                    },
                    "Ninja + S1 + LMI": {
                        "url_template": f"{ACTION_BASE_URL}/a/sr?customer={{{{Customer}}}}&scope={{{{Applies to}}}}&profile=ninja_s1_lmi&confirm=1",
                    },
                    "Ninja + S1 + SC": {
                        "url_template": f"{ACTION_BASE_URL}/a/sr?customer={{{{Customer}}}}&scope={{{{Applies to}}}}&profile=ninja_s1_sc&confirm=1",
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
                "cross_customer_conflicts",
                "Same device under multiple customers",
                "table",
                """
                    SELECT
                        norm_name AS "Match key",
                        client_name AS "Customer",
                        hostname AS "Device",
                        COALESCE(NULLIF(os_name, ''), '') AS "OS",
                        COALESCE(array_to_string(observed_platforms, ', '), '') AS "Found in",
                        COALESCE(array_to_string(missing_required_platforms, ', '), '') AS "Missing"
                    FROM ninja_agent_compliance.v_cross_client_conflicts
                    ORDER BY norm_name, client_name, hostname
                    LIMIT 300
                """,
                40, 0, 24, 8,
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
        ],
    },
]


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
    for col, col_spec in (spec.get("column_click_behaviors") or {}).items():
        cb = _build_click_behavior_json(col_spec, dash_id_by_name or {})
        if cb:
            column_settings[f'["name","{col}"]'] = {"click_behavior": cb}
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
