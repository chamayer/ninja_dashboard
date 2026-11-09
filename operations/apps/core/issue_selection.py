"""The one Issues selection contract (PLAN-003 R3).

Every Issues count, group header, page, export and the home mapping link reads
the same normalized item relation: findings of both namespaces plus pending
identity candidates, keyed by ``(kind, id)``. Candidates keep their own records
and actions; no Finding row is fabricated for them.

Counting rules (current design, "Resolved decision: client mapping counts"):

* A count is of independent corrective actions. Records that settle with one
  action share an ``action_key`` (today: the entity ``unmatched_source_group``
  and the admin ``client_unattached_group`` finding for the same source group).
  One record represents the action; the others stay reachable as related
  evidence of that row.
* A finding covered by another open finding is not independent work. It stays
  evaluated and reachable through the parent's Related issues scope.
* Open and Paused are disjoint: Paused is unresolved work with a current pause.
  Readiness (needs action / blocked / pending) is not a status, filter or count.

Filters never widen: a malformed or inapplicable value selects nothing rather
than everything. OS and Computer type apply to Computer subjects only, so other
item kinds drop out while they are set (the page says so).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlencode

from django.db import connection
from django.urls import reverse

from . import finding_registry

TENANT_ID = 1
SEVERITIES = ("critical", "high", "medium", "low", "info")
SEVERITY_LABELS = {
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "info": "Info",
}
STATUSES = ("open", "paused", "resolved")
STATUS_LABELS = {"open": "Open", "paused": "Paused", "resolved": "Resolved"}
VIEWS = ("severity", "type", "flat")
VIEW_LABELS = {
    "severity": "Category → Type → Severity",
    "type": "Category → Type",
    "flat": "Flat",
}
SORTS = ("severity", "detected", "issue", "subject", "client")
PAGE_SIZE = 50
CLIENT_UNASSIGNED = "unassigned"
COMPUTER_TYPES = ("server", "workstation", "unknown")
# Home "Critical mapping issues" counts this registry group.
MAPPING_GROUP = "client_mapping"
# Software approval rows keep affected-Computer ordering.
APPROVAL_TYPES = frozenset({"rare_recent", "whitelist_suggestion"})

_ACTIVE = ("open", "acknowledged", "investigating")
_CLOSED = ("resolved", "suppressed", "wontfix")
_DETAIL_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SEVERITY_RANK_SQL = (
    "CASE i.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 "
    "WHEN 'low' THEN 3 ELSE 4 END"
)


@dataclass(frozen=True)
class Scope:
    """A normalized selection. ``types`` None means every registered type."""

    status: str = "open"
    types: tuple[str, ...] | None = None
    severity: str = ""
    client: str = ""
    q: str = ""
    os: str = ""
    computer_type: str = ""
    platform: str = ""
    subject_id: str = ""
    device_id: str = ""
    detail_key: str = ""
    detail_value: str = ""
    related_to: str = ""
    invalid: bool = False

    def narrowed(self, **changes: Any) -> Scope:
        return replace(self, **changes)


def _uuid_or_none(value: str) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError):
        return None


def _client_id(slug: str) -> str | None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id::text FROM operations.clients"
            " WHERE tenant_id = %s AND slug = %s AND deleted_at IS NULL",
            [TENANT_ID, slug],
        )
        row = cursor.fetchone()
    return row[0] if row else None


def _items_sql(
    scope: Scope, *, covered_only: bool = False, home_compact: bool = False
) -> tuple[str, dict[str, Any]]:
    """The filtered item relation, before ranking. Columns are documented in ``_ITEM_COLUMNS``."""
    params: dict[str, Any] = {"tenant": TENANT_ID}
    finding_where = [
        "f.status = ANY(%(closed)s)" if scope.status == "resolved" else "f.status = ANY(%(active)s)"
    ]
    params["closed"] = list(_CLOSED)
    params["active"] = list(_ACTIVE)
    if scope.status == "open":
        finding_where.append("(f.snoozed_until IS NULL OR f.snoozed_until <= now())")
    elif scope.status == "paused":
        finding_where.append("f.snoozed_until > now()")
    if scope.types is not None:
        finding_where.append("t.name = ANY(%(types)s)")
        params["types"] = list(scope.types)
    # Candidates are never paused or resolved items of this queue.
    include_candidates = scope.status in {"open", "open_paused"} and (
        scope.types is None or "identity_resolution_pending" in scope.types
    )
    # Aggregate consumers need only whether a representative is covered, not
    # the rest of its state. Filtering here uses the existing attention index
    # and avoids hashing all state rows against wide finding JSON values.
    state_filter = " AND s.attention = 'covered'" if covered_only else ""
    label_column = "" if home_compact else ", t.display_name::text AS issue_label"
    detail_columns = (
        "" if home_compact else
        ", COALESCE(f.last_detected_at, f.last_seen_at) AS detected_at,"
        " COALESCE(NULLIF(f.finding_details->>'platform', ''),"
        " NULLIF(f.subject_ref->'legacy_ref'->>'platform', '')) AS platform,"
        " f.finding_details AS details, f.subject_ref"
    )
    candidate_label_column = "" if home_compact else ", ct.display_name::text"
    candidate_details = (
        "" if home_compact else ", c.last_observed_at, NULL,"
        " jsonb_build_object('external_id', c.external_id,"
        " 'record_type', c.external_namespace), '{}'::jsonb"
    )
    # Home reports the recorded association on selected actions. Other Issues
    # readers retain their current ownership checks for filtering and access.
    client_expression = (
        "f.client_id" if home_compact else
        "CASE WHEN f.subject_type = 'device' AND NOT EXISTS ("
        "SELECT 1 FROM operations.computer_client_ownership owner "
        "WHERE owner.tenant_id = f.tenant_id AND owner.device_id = f.subject_id "
        "AND owner.effective_client_id = f.client_id "
        "AND owner.state IN ('resolved', 'decision_protected')) THEN NULL "
        "WHEN f.subject_type = 'source_record' THEN "
        "(SELECT operations.computer_client_independent_evidence("
        "subject.tenant_id, subject.observation_id) "
        "FROM operations.source_record_subjects subject "
        "WHERE subject.tenant_id = f.tenant_id AND subject.id = f.subject_id) "
        "ELSE f.client_id END"
    )
    sql = f"""
        SELECT 'finding'::text AS kind, f.id, f.condition_namespace::text AS namespace,
               t.name::text AS type_name, t.issue_category::text AS issue_category
               {label_column},
               f.severity::text AS severity,
               CASE WHEN f.status = ANY(%(closed)s) THEN 'resolved'
                    WHEN f.snoozed_until > now() THEN 'paused' ELSE 'open' END AS status,
               COALESCE(f.status = ANY(%(active)s) AND s.attention = 'covered', false) AS covered,
               COALESCE(s.covered_by, '{{}}'::uuid[]) AS covered_by,
               {client_expression} AS client_id,
               f.subject_type::text AS subject_type, f.subject_id,
               CASE t.name
                   WHEN 'unmatched_source_group' THEN 'source_group:'
                        || COALESCE(f.finding_details->>'source_id', '') || ':'
                        || COALESCE(f.finding_details->>'external_id', '')
                   WHEN 'client_unattached_group' THEN 'source_group:'
                        || COALESCE(si.source_id::text, f.subject_ref->>'source_id', '') || ':'
                        || COALESCE(f.subject_ref->>'external_id', '')
                   ELSE 'finding:' || f.id::text
               END AS action_key
               {detail_columns}
          FROM operations.findings f
          JOIN operations.finding_types t ON t.id = f.finding_type_id
          LEFT JOIN operations.finding_state s ON s.finding_id = f.id{state_filter}
          LEFT JOIN operations.source_bindings b
            ON t.name = 'client_unattached_group' AND b.tenant_id = f.tenant_id
           AND b.id::text = f.subject_ref->>'source_binding_id'
          LEFT JOIN operations.source_instances si ON si.id = b.source_instance_id
         WHERE f.tenant_id = %(tenant)s AND {" AND ".join(finding_where)}
    """
    if include_candidates:
        sql += f"""
        UNION ALL
        SELECT 'candidate', c.id, 'candidate', ct.name::text, ct.issue_category::text
               {candidate_label_column},
               ct.default_severity::text, 'open', false, '{{}}'::uuid[],
               c.client_id, 'entity_candidate', NULL::uuid, 'candidate:' || c.id::text
               {candidate_details}
          FROM operations.entity_candidates c
          JOIN operations.finding_types ct ON ct.name = 'identity_resolution_pending'
         WHERE c.tenant_id = %(tenant)s AND c.status = 'pending'
        """
    return sql, params


_SUBJECT_LABEL_SQL = """
    COALESCE(
        d.canonical_hostname,
        NULLIF(i.details->>'canonical_name', ''),
        NULLIF(i.details->>'hostname', ''),
        NULLIF(i.details->>'external_name', ''),
        NULLIF(i.details->>'observed_name', ''),
        NULLIF(i.subject_ref->'legacy_ref'->>'external_name', ''),
        NULLIF(i.details->>'name', ''),
        NULLIF(i.details->>'external_id', ''),
        ''
    )
"""


def _filtered_sql(
    scope: Scope, *, labels: bool = False, summary: bool = False, home_compact: bool = False
) -> tuple[str, dict[str, Any]]:
    """Items after every scope filter, ranked into corrective actions.

    Subject and client labels (two joins per item) are built only when a search
    or a label sort needs them; counts do not.
    """
    labels = labels or bool(scope.q)
    # Related scopes inspect covered_by even on a non-covered state row;
    # preserve the full state join for those scopes and for row consumers.
    items, params = _items_sql(
        scope,
        covered_only=summary and not scope.related_to,
        home_compact=home_compact,
    )
    where = ["true"]
    if scope.invalid:
        where.append("false")
    if scope.severity:
        if scope.severity in SEVERITIES:
            where.append("i.severity = %(severity)s")
            params["severity"] = scope.severity
        else:
            where.append("false")
    if scope.client == CLIENT_UNASSIGNED:
        # Work that belongs to a client but has none yet. Fleet-wide software
        # and platform work is not "unassigned".
        where.append(
            "((i.client_id IS NULL AND (i.subject_type IN"
            " ('device', 'source_group', 'source_group_set', 'entity_candidate',"
            " 'source_record', 'source_record_case')"
            " OR i.type_name = 'unmatched_source_group')) OR (i.subject_type = 'device'"
            " AND NOT EXISTS (SELECT 1 FROM operations.computer_client_ownership owner"
            " WHERE owner.tenant_id = %(tenant)s AND owner.device_id = i.subject_id"
            " AND owner.effective_client_id = i.client_id"
            " AND owner.state IN ('resolved', 'decision_protected'))))"
        )
    elif scope.client:
        client_id = _client_id(scope.client)
        if client_id is None:
            where.append("false")
        else:
            params["client_id"] = client_id
            # A software approval case affects a client through its uncovered
            # installations; its decision scope does not change.
            where.append(
                "((i.client_id = %(client_id)s::uuid AND (i.subject_type IS DISTINCT FROM 'device'"
                " OR EXISTS (SELECT 1 FROM operations.computer_client_ownership owner"
                " WHERE owner.tenant_id = %(tenant)s AND owner.device_id = i.subject_id"
                " AND owner.effective_client_id = %(client_id)s::uuid"
                " AND owner.state IN ('resolved', 'decision_protected')))) OR (i.subject_type IN"
                " ('software_product', 'software_version') AND EXISTS ("
                " SELECT 1 FROM operations.v_device_software_exposure e"
                " JOIN operations.computer_client_ownership owner"
                " ON owner.tenant_id = e.tenant_id AND owner.device_id = e.device_id"
                " AND owner.effective_client_id = e.client_id"
                " AND owner.state IN ('resolved', 'decision_protected')"
                " WHERE e.tenant_id = %(tenant)s AND e.finding_id = i.id"
                " AND e.client_id = %(client_id)s::uuid)))"
            )
    if scope.os or scope.computer_type:
        device_where = [
            "dv.tenant_id = %(tenant)s",
            "dv.deleted_at IS NULL",
            "dv.id = i.subject_id",
        ]
        if scope.os:
            device_where.append("dv.os_name = %(os)s")
            params["os"] = scope.os
        if scope.computer_type:
            if scope.computer_type in COMPUTER_TYPES:
                device_where.append("dv.device_role = %(computer_type)s")
                params["computer_type"] = scope.computer_type
            else:
                device_where.append("false")
        where.append(
            "i.subject_type = 'device' AND EXISTS (SELECT 1 FROM operations.devices dv WHERE "
            + " AND ".join(device_where)
            + ")"
        )
    if scope.platform:
        where.append("i.platform = %(platform)s")
        params["platform"] = scope.platform
    if scope.subject_id:
        subject_id = _uuid_or_none(scope.subject_id)
        if subject_id is None:
            where.append("false")
        else:
            where.append("i.subject_id = %(subject_id)s::uuid")
            params["subject_id"] = subject_id
    if scope.device_id:
        device_id = _uuid_or_none(scope.device_id)
        if device_id is None:
            where.append("false")
        else:
            # The Computer's own issues and the software issues it inherits
            # through current installations (the Computer page's scope).
            where.append(
                "((i.subject_type = 'device' AND i.subject_id = %(device_id)s::uuid)"
                " OR EXISTS (SELECT 1 FROM operations.v_device_software_exposure e"
                " WHERE e.tenant_id = %(tenant)s AND e.finding_id = i.id"
                " AND e.device_id = %(device_id)s::uuid))"
            )
            params["device_id"] = device_id
    if scope.detail_key or scope.detail_value:
        if _DETAIL_KEY_RE.fullmatch(scope.detail_key or "") and scope.detail_value:
            where.append("lower(i.details->>%(detail_key)s) = lower(%(detail_value)s)")
            params["detail_key"] = scope.detail_key
            params["detail_value"] = scope.detail_value
        else:
            where.append("false")
    if scope.q:
        where.append(
            f"(({_SUBJECT_LABEL_SQL}) ILIKE %(q)s OR COALESCE(c.display_name, '') ILIKE %(q)s"
            " OR i.issue_label ILIKE %(q)s)"
        )
        params["q"] = f"%{scope.q}%"
    related = ""
    if scope.related_to:
        related_id = _uuid_or_none(scope.related_to)
        if related_id is None:
            where.append("false")
        else:
            params["related_to"] = related_id
            related = related_id
    label_columns = label_joins = ""
    if labels:
        label_columns = (
            f", ({_SUBJECT_LABEL_SQL}) AS subject_label,"
            " COALESCE(c.display_name, '') AS client_label"
        )
        label_joins = (
            " LEFT JOIN operations.devices d ON i.subject_type = 'device'"
            " AND d.id = i.subject_id AND d.tenant_id = %(tenant)s"
            " LEFT JOIN operations.clients c ON c.id = i.client_id"
            " AND (i.subject_type IS DISTINCT FROM 'device' OR EXISTS ("
            " SELECT 1 FROM operations.computer_client_ownership owner"
            " WHERE owner.tenant_id = %(tenant)s AND owner.device_id = i.subject_id"
            " AND owner.effective_client_id = i.client_id"
            " AND owner.state IN ('resolved', 'decision_protected')))"
        )
    filtered_cte = "filtered AS MATERIALIZED" if home_compact else "filtered AS"
    sql = f"""
        WITH items AS ({items}),
        {filtered_cte} (
            SELECT i.*, {_SEVERITY_RANK_SQL} AS severity_rank{label_columns}
              FROM items i{label_joins}
             WHERE {" AND ".join(where)}
        )
    """
    if home_compact:
        params["shared_action_types"] = [
            "unmatched_source_group",
            "client_unattached_group",
        ]
        return sql + """
        , shared_actions AS (
            SELECT DISTINCT ON (action_key, status) *
              FROM filtered
             WHERE type_name = ANY(%(shared_action_types)s)
             ORDER BY action_key, status,
                      (namespace = 'admin') DESC, severity_rank, id
        ),
        selected AS (
            SELECT * FROM filtered
             WHERE type_name <> ALL(%(shared_action_types)s) AND NOT covered
            UNION ALL
            SELECT * FROM shared_actions WHERE NOT covered
        )
        """, params

    sql += f"""
        , ranked AS (
            SELECT filtered.*,
                   row_number() OVER (
                       PARTITION BY action_key, status
                       ORDER BY (namespace = 'admin') DESC, severity_rank, id
                   ) AS action_rank
                   {", count(*) OVER (PARTITION BY action_key, status) AS action_records" if not summary else ""}
              FROM filtered
        )
    """
    if related:
        # The parent's covered children and the other records of its action.
        independent = (
            "(%(related_to)s::uuid = ANY(covered_by) OR (id <> %(related_to)s::uuid"
            " AND action_key = (SELECT action_key FROM ranked WHERE id = %(related_to)s::uuid"
            " LIMIT 1)))"
        )
    else:
        independent = "action_rank = 1 AND NOT covered"
    return sql + f", selected AS (SELECT * FROM ranked WHERE {independent})", params


def counts(scope: Scope) -> dict[tuple[str, str, str], int]:
    """Independent items by (type name, severity, status) for open and paused.

    ``scope.status`` is ignored unless it is Resolved; Open and Paused are
    always both counted so headers can show ``Open (n) · Paused (n)``.
    """
    results: dict[tuple[str, str, str], int] = {}
    statuses = ("resolved",) if scope.status == "resolved" else ("open", "paused")
    for status in statuses:
        sql, params = _filtered_sql(scope.narrowed(status=status), summary=True)
        with connection.cursor() as cursor:
            cursor.execute(
                sql + " SELECT type_name, severity, count(*) FROM selected GROUP BY 1, 2",
                params,
            )
            for type_name, severity, count in cursor.fetchall():
                results[(type_name, severity, status)] = count
    return results


def count(scope: Scope) -> int:
    sql, params = _filtered_sql(scope, summary=True)
    with connection.cursor() as cursor:
        cursor.execute(sql + " SELECT count(*) FROM selected", params)
        return cursor.fetchone()[0]


def client_count(scope: Scope) -> int:
    """Distinct known clients among a scope's independent items."""
    sql, params = _filtered_sql(scope, summary=True)
    with connection.cursor() as cursor:
        cursor.execute(
            sql + " SELECT count(DISTINCT client_id) FROM selected WHERE client_id IS NOT NULL",
            params,
        )
        return cursor.fetchone()[0]


def count_and_client_count(scope: Scope) -> tuple[int, int]:
    """Count independent items and their distinct known clients in one selection."""
    sql, params = _filtered_sql(scope, summary=True)
    with connection.cursor() as cursor:
        cursor.execute(
            sql + " SELECT count(*), count(DISTINCT client_id) FROM selected", params
        )
        return cursor.fetchone()


def _order_sql(scope: Scope, sort: str, direction: str) -> str:
    descending = direction == "desc"
    tie = "detected_at DESC NULLS LAST, id"
    if sort == "detected":
        return f"detected_at {'DESC' if descending else 'ASC'} NULLS LAST, severity_rank, id"
    if sort == "issue":
        return f"issue_label {'DESC' if descending else 'ASC'}, severity_rank, {tie}"
    if sort == "subject":
        return f"lower(subject_label) {'DESC' if descending else 'ASC'}, severity_rank, {tie}"
    if sort == "client":
        return f"lower(client_label) {'DESC' if descending else 'ASC'} NULLS LAST, severity_rank, {tie}"
    if scope.types is not None and set(scope.types) <= APPROVAL_TYPES:
        # Software approval: the most widespread title first.
        return (
            "severity_rank, COALESCE(NULLIF(details->>'uncovered_device_count', '')::int,"
            " NULLIF(details->>'fleet_device_count', '')::int) DESC NULLS LAST, " + tie
        )
    return f"severity_rank {'DESC' if descending else 'ASC'}, {tie}"


def _select(
    scope: Scope, *, sort: str, direction: str, limit: int, offset: int = 0
) -> list[dict[str, Any]]:
    sql, params = _filtered_sql(scope, labels=sort in ("subject", "client"))
    with connection.cursor() as cursor:
        cursor.execute(
            sql + " SELECT kind, id, namespace, type_name, severity, status, action_key,"
            " action_records, detected_at FROM selected"
            f" ORDER BY {_order_sql(scope, sort, direction)} LIMIT %(limit)s OFFSET %(offset)s",
            {**params, "limit": limit, "offset": offset},
        )
        columns = [column.name for column in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def page(
    scope: Scope, *, sort: str = "severity", direction: str = "asc", number: int = 1
) -> tuple[list[dict[str, Any]], int]:
    """One page of independent items in display order, and the total."""
    total = count(scope)
    pages = max(1, -(-total // PAGE_SIZE))
    number = min(max(1, number), pages)
    rows = _select(
        scope, sort=sort, direction=direction, limit=PAGE_SIZE, offset=(number - 1) * PAGE_SIZE
    )
    return rows, total


def items(
    scope: Scope, *, sort: str = "severity", direction: str = "asc", limit: int = 100000
) -> list[dict[str, Any]]:
    """Every independent item of a scope in display order (export and 'select all')."""
    return _select(scope, sort=sort, direction=direction, limit=limit)


def related_counts(ids: list[str]) -> dict[str, dict[str, Any]]:
    """For visible findings: covered children (both namespaces) by parent."""
    if not ids:
        return {}
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT p.parent::text, count(*),
                   count(*) FILTER (WHERE f.severity IN ('critical', 'high')),
                   (array_agg(f.severity ORDER BY CASE f.severity WHEN 'critical' THEN 4
                        WHEN 'high' THEN 3 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END
                        DESC))[1]
              FROM operations.finding_state s
              JOIN operations.findings f ON f.id = s.finding_id AND f.status = ANY(%s)
             CROSS JOIN LATERAL unnest(s.covered_by) p(parent)
             WHERE s.tenant_id = %s AND s.attention = 'covered'
               AND s.covered_by && %s::uuid[] AND p.parent = ANY(%s::uuid[])
             GROUP BY p.parent
            """,
            [list(_ACTIVE), TENANT_ID, ids, ids],
        )
        return {
            parent: {"n": n, "high": high, "top": top} for parent, n, high, top in cursor.fetchall()
        }


def mapping_types() -> tuple[str, ...]:
    _categories, groups = finding_registry.build_taxonomy()
    group = groups.get(MAPPING_GROUP)
    return tuple(sorted(group["types"])) if group else ()


def mapping_scope() -> Scope:
    """Home "Critical mapping issues": open, unpaused, Critical, client mapping."""
    return Scope(status="open", types=mapping_types(), severity="critical")


def mapping_query() -> dict[str, str]:
    """The Issues URL parameters that open exactly the ``mapping_scope`` selection."""
    _categories, groups = finding_registry.build_taxonomy()
    group = groups.get(MAPPING_GROUP) or {}
    return {
        "category": group.get("category", ""),
        "type": MAPPING_GROUP,
        "severity": "critical",
        "status": "open",
    }


def home_data(*, attention_limit: int = 6) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build Home action totals and attention from one governed Issues selection."""
    sql, params = _filtered_sql(
        Scope(status="open_paused"), summary=True, home_compact=True
    )
    params["mapping_types"] = list(mapping_types())
    # A type-filtered Issues link ranks only that type. Shared actions need a
    # separate type-level representative for attention; global totals retain
    # the single representative across both source-group finding types.
    # Critical and mapping scopes also filter before choosing a representative.
    with connection.cursor() as cursor:
        cursor.execute(
            sql
            + """
            , shared_issue_actions AS (
                SELECT DISTINCT ON (action_key, status, type_name) *
                  FROM filtered
                 WHERE type_name = ANY(%(shared_action_types)s) AND status = 'open'
                 ORDER BY action_key, status, type_name,
                          (namespace = 'admin') DESC, severity_rank, id
            ), critical_shared AS (
                SELECT DISTINCT ON (action_key, status) *
                  FROM filtered
                 WHERE type_name = ANY(%(shared_action_types)s)
                   AND status = 'open' AND severity = 'critical'
                 ORDER BY action_key, status,
                          (namespace = 'admin') DESC, severity_rank, id
            ), critical_actions AS (
                SELECT * FROM filtered
                 WHERE type_name <> ALL(%(shared_action_types)s)
                   AND status = 'open' AND severity = 'critical' AND NOT covered
                UNION ALL
                SELECT * FROM critical_shared WHERE NOT covered
            ), mapping_shared AS (
                SELECT DISTINCT ON (action_key, status) *
                  FROM filtered
                 WHERE type_name = ANY(%(shared_action_types)s)
                   AND type_name = ANY(%(mapping_types)s)
                   AND status = 'open' AND severity = 'critical'
                 ORDER BY action_key, status,
                          (namespace = 'admin') DESC, severity_rank, id
            ), critical_mapping_actions AS (
                SELECT * FROM filtered
                 WHERE type_name <> ALL(%(shared_action_types)s)
                   AND type_name = ANY(%(mapping_types)s)
                   AND status = 'open' AND severity = 'critical' AND NOT covered
                UNION ALL
                SELECT * FROM mapping_shared WHERE NOT covered
            )
            SELECT type_name, issue_category, severity, status,
                   count(*)::int AS action_count,
                   count(DISTINCT client_id)::int AS client_count,
                   (count(DISTINCT (subject_type, subject_id))
                      FILTER (WHERE subject_id IS NOT NULL)
                    + count(*) FILTER (WHERE kind = 'candidate'))::int AS subject_count,
                   MAX(CASE severity WHEN 'critical' THEN 5 WHEN 'high' THEN 4
                       WHEN 'medium' THEN 3 WHEN 'low' THEN 2 ELSE 1 END)::int
                       AS severity_level,
                   GROUPING(severity)::int AS attention_row,
                   GROUPING(type_name)::int AS total_row,
                   count(*) FILTER (WHERE status = 'open')::int AS total_open_actions,
                   count(*) FILTER (WHERE status = 'paused')::int AS total_paused_actions,
                   (SELECT count(*)::int FROM critical_actions) AS total_critical_actions,
                   (SELECT count(*)::int FROM critical_mapping_actions) AS mapping_actions,
                   (SELECT count(DISTINCT client_id)::int FROM critical_mapping_actions)
                       AS mapping_clients
              FROM selected
             GROUP BY GROUPING SETS (
                 (type_name, issue_category, severity, status),
                 (type_name, issue_category, status),
                 ()
             )
            HAVING GROUPING(type_name) = 1 OR GROUPING(severity) = 0
                OR type_name <> ALL(%(shared_action_types)s)
            UNION ALL
            SELECT type_name, issue_category, NULL::text AS severity, status,
                   count(*)::int, count(DISTINCT client_id)::int,
                   count(DISTINCT (subject_type, subject_id))
                       FILTER (WHERE subject_id IS NOT NULL)::int,
                   MAX(CASE severity WHEN 'critical' THEN 5 WHEN 'high' THEN 4
                       WHEN 'medium' THEN 3 WHEN 'low' THEN 2 ELSE 1 END)::int,
                   1, 0, 0, 0, 0, 0, 0
              FROM shared_issue_actions
             WHERE NOT covered
             GROUP BY type_name, issue_category, status
            UNION ALL
            SELECT type_name, issue_category, NULL::text, 'open'::text,
                   count(*)::int, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0
              FROM critical_actions
             GROUP BY type_name, issue_category
            """,
            params,
        )
        rows = cursor.fetchall()

    categories, groups = finding_registry.build_taxonomy()
    type_categories = {
        type_name: category["label"]
        for category in categories
        for type_name in category["types"]
    }
    category_counts = {
        category["label"]: {
            "open_actions": 0,
            "paused_actions": 0,
            "critical_actions": 0,
        }
        for category in categories
    }
    group_by_type = {
        type_name: group_key
        for group_key, group in groups.items()
        for type_name in group["types"]
    }
    severity_names = {5: "critical", 4: "high", 3: "medium", 2: "low", 1: "info"}
    summary = {
        "open_actions": 0,
        "paused_actions": 0,
        "critical_actions": 0,
        "mapping_actions": 0,
        "mapping_clients": 0,
        "categories": category_counts,
    }
    attention = []
    critical_category_row = 2
    for (
        type_name,
        category,
        _severity,
        status,
        count,
        clients,
        subjects,
        severity_level,
        attention_row,
        total_row,
        total_open,
        total_paused,
        total_critical,
        mapping_actions,
        mapping_clients,
    ) in rows:
        if total_row:
            summary.update(
                open_actions=total_open,
                paused_actions=total_paused,
                critical_actions=total_critical,
                mapping_actions=mapping_actions,
                mapping_clients=mapping_clients,
            )
        elif attention_row == critical_category_row:
            category_name = type_categories.get(type_name)
            if category_name:
                category_counts[category_name]["critical_actions"] += count
        elif attention_row:
            if status != "open":
                continue
            label = finding_registry.finding_type_name(type_name)
            issue_group = group_by_type.get(type_name, type_name)
            item = {
                "type_name": type_name,
                "category": category or "",
                "label": label,
                "severity": severity_names.get(severity_level, "info"),
                "count": count,
                "clients": clients,
                "subjects": subjects,
                "href": f"{reverse('findings_queue')}?"
                + urlencode({"type": issue_group, "issue": type_name}),
            }
            item["affected"] = (
                f"{subjects:,} affected · {clients:,} recorded client{'s' if clients != 1 else ''}"
                if clients
                else f"{subjects:,} affected"
            )
            attention.append(item)
        elif type_name:
            category_name = type_categories.get(type_name)
            if category_name:
                category_totals = category_counts[category_name]
                if status == "open":
                    category_totals["open_actions"] += count
                elif status == "paused":
                    category_totals["paused_actions"] += count

    severity_rank = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}
    attention.sort(
        key=lambda item: (
            -severity_rank[item["severity"]],
            -item["clients"],
            -item["count"],
            item["type_name"],
        )
    )
    return summary, attention[:attention_limit]
