from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import uuid
from collections import Counter
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from urllib import request as _urllib_request
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.models import (
    Case,
    CharField,
    Count,
    F,
    Func,
    IntegerField,
    Max,
    OuterRef,
    Q,
    Subquery,
    Value,
    When,
)
from django.db.models.expressions import RawSQL
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Coalesce, Concat
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_POST
from shared import software_coverage, software_settings
from shared.jobs_registry import (
    EXECUTION_POOL_POLICIES,
    capability_state,
    definition,
    definition_keys,
    definitions,
    legacy_job_definition_keys,
    operator_job_definition,
    operator_job_definitions,
    operator_job_group_definitions,
    operator_job_key_for_execution,
    registry_digest,
    schedule_definitions,
    system_service_definition_keys,
    validate_registry,
    workflow_edges,
)
from shared.patch_compliance import COMPLIANCE_MISSING_STATUSES, excluded_patch_categories

from . import capability as capability_evidence
from . import category as category_evidence
from . import (
    computer_naming,
    finding_registry,
    requirement_baselines,
    software_decision_rules,
    software_review,
)
from .capability_review_actions import decide_capability
from .client_workspace import (
    build_client_directory,
    build_client_workspace,
    client_source_references,
)
from .computer_reads import current_computer_sql, current_computers
from .conditions.live import load_active_profile
from .conditions.operator import (
    ATTENTION_BLOCKED,
    ATTENTION_COVERED,
    ATTENTION_NEEDS_ACTION,
    ATTENTION_PAUSED,
    ATTENTION_PENDING,
    OPERATOR_ATTENTION_CHOICES,
    OPERATOR_ATTENTION_LABELS,
    OPERATOR_STATUS_CHOICES,
    OPERATOR_STATUS_LABELS,
    operator_state,
    operator_status,
)
from .conditions.review import record_identity_reviewed_distinct
from .csv_export import csv_response, wants_csv
from .decorators import require_admin
from .device_status import DEFAULTS as DEVICE_STATUS_DEFAULTS
from .device_status import POLICY_NAME as DEVICE_STATUS_POLICY_NAME
from .device_status import get_device_status_policy
from .finding_actions import (
    APPROVE_REMOTE_ACCESS_ALL,
    APPROVE_REMOTE_ACCESS_CLIENT,
    ARCHIVE_HUDU_ASSETS,
    BULK_RETIRE_COMPUTERS,
    CAPABILITY_CONFIRM,
    CAPABILITY_REJECT,
    FINDING_ACTIONS,
    IDENTITY_ACTIONS,
    available_finding_actions,
    can_manage_lifecycle,
    can_run_action,
)
from .forms import ClientPolicyForm
from .identity_actions import run_identity_action
from .models import (
    AdminFinding,
    Agent,
    AttributeDefinition,
    AuditLog,
    Client,
    ClientCandidate,
    ClientNameAlias,
    ClientOrgExclude,
    ClientPolicy,
    CoverageRequirement,
    Device,
    DeviceOperatorDecision,
    DevicePatchingOverride,
    DeviceSourceLink,
    Entity,
    EntityCandidate,
    EntityType,
    EvaluatorConfig,
    Finding,
    FindingType,
    MergeCandidate,
    NotificationEvent,
    NotificationRoute,
    NotificationRule,
    ProductAuthorization,
    RequirementProfile,
    RequirementProfileItem,
    SoftwareCatalog,
    SoftwareDecision,
    SoftwareSuggestionRule,
    Source,
    StoredFindingState,
    SuppressionRule,
)
from .remote_access_approval import approve_remote_access
from .software_decision_actions import decide_software, decision_for
from .templatetags.human_labels import humanize_label


def _source_record_type_label(entity_type: str) -> str:
    """Return a readable source-record type without requiring a UI release.

    Registered types retain their curated operator wording. A newly observed
    type still appears immediately, with its dotted identifier converted to a
    readable fallback (for example, ``monitor.process`` becomes
    ``Monitor process``).
    """
    label = humanize_label(entity_type)
    if label != entity_type:
        return label
    return re.sub(r"[._-]+", " ", entity_type).strip().capitalize()


DEVICE_PAGE_SIZE = 100

_FINDING_ACTIVE_STATUSES = (
    Finding.Status.OPEN,
    Finding.Status.ACKNOWLEDGED,
    Finding.Status.INVESTIGATING,
)

# These are title-level policy recommendations, not incidents. Their
# authoritative state changes live in SoftwareDecision, whose scope resolves
# device before client before global.
# Undecided software appears in the Issues queue, but a decision (approve,
# reject, investigate) is its action; pausing or excluding it is blocked.
_SOFTWARE_POLICY_CANDIDATE_TYPES = ("whitelist_suggestion",)
# The one definition of "software needs a decision": an open prompt finding,
# one per undecided title. The Issues tile and the Software page both count it.
_SOFTWARE_DECISION_PROMPT_TYPES = ("whitelist_suggestion", "rare_recent")

log = logging.getLogger(__name__)

_NINJA_PATCH_DEVICE_ID_MAX = 2_147_483_647
_LIFECYCLE_REASON_MAX_LENGTH = 120
_FINDING_DETAIL_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _safe_ninja_external_id_integer_sql(alias: str) -> str:
    """Return a total SQL cast for a Ninja-owned numeric external ID.

    A regex predicate on its own is not safe: PostgreSQL may evaluate a
    projected cast before applying the predicate.  The range check also keeps
    a numeric but oversized foreign ID out of Ninja's integer-keyed tables.
    ``alias`` is internal, fixed SQL supplied by the caller.
    """
    return f"""CASE
        WHEN {alias}.external_id ~ '^\\d+$'
         AND (
             length({alias}.external_id) < 10
             OR (
                 length({alias}.external_id) = 10
                 AND {alias}.external_id <= '2147483647'
             )
         )
        THEN {alias}.external_id::integer
        ELSE NULL::integer
    END"""


def _ninja_patch_device_ids(links) -> list[int]:
    """Return patch-table-compatible IDs from this device's Ninja links.

    Source-link IDs are text because their source owns their shape.  Ninja
    patch facts use PostgreSQL ``integer`` IDs, so an unrelated source's large
    numeric ID must never be cast by the device-detail patch lookup.
    """
    result: list[int] = []
    seen: set[int] = set()
    for link in links:
        if link.source.name != "Ninja":
            continue
        external_id = (link.external_id or "").strip()
        if not external_id.isascii() or not external_id.isdecimal():
            continue
        ninja_id = int(external_id)
        if ninja_id > _NINJA_PATCH_DEVICE_ID_MAX or ninja_id in seen:
            continue
        seen.add(ninja_id)
        result.append(ninja_id)
    return result


def _finding_group_lookup(
    *,
    finding_type_name: str,
    configured_key: str,
    requested_key: str,
    requested_value: str,
) -> dict[str, str] | None:
    """Return the registered evidence-group filter, or reject the request.

    The URL carries a value, but it does not choose which JSON evidence field
    can be queried. Only a FindingType's registry field may do that.
    """
    if not (
        finding_type_name
        and requested_key
        and requested_value
        and configured_key == requested_key
        and _FINDING_DETAIL_KEY_RE.fullmatch(configured_key)
    ):
        return None
    return {f"finding_details__{configured_key}__iexact": requested_value}


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


def _issue_taxonomy() -> tuple[list[dict], dict[str, dict]]:
    """Categories and groups for the Issues page, from the finding types registry."""
    categories, type_groups = finding_registry.build_taxonomy()
    if not categories:
        raise RuntimeError("The finding types registry has no categories")
    return categories, type_groups


def _operator_issue_taxonomy() -> tuple[list[dict], dict[str, dict]]:
    """Return every policy type for the unified Issues navigation."""
    categories, groups = _issue_taxonomy()
    visible_types = set().union(*(group["types"] for group in groups.values()))
    operator_groups = {}
    for key, group in groups.items():
        types = group["types"] & visible_types
        if not types:
            continue
        operator_groups[key] = {
            **group,
            "types": types,
            "issues": tuple(issue for issue in group["issues"] if issue["value"] in types),
            "legacy_types": group["legacy_types"],
        }
    operator_categories = []
    for category in categories:
        category_types = (
            set().union(
                *(
                    group["types"]
                    for group in operator_groups.values()
                    if group["category"] == category["key"]
                ),
            )
            if any(group["category"] == category["key"] for group in operator_groups.values())
            else set()
        )
        if category_types:
            operator_categories.append({**category, "types": category_types})
    return operator_categories, operator_groups


def _condition_assessment_display(row_kind: str, finding_ids) -> dict[str, dict]:
    """Load persisted dependency responses for visible findings."""
    ids = [str(value) for value in finding_ids if value]
    if not ids:
        return {}
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('operations.condition_assessments')")
        if cursor.fetchone()[0] is None:
            return {}
        cursor.execute(
            """
            SELECT a.finding_id, a.policy_version, a.policy_digest, a.assessed_at, a.response,
                   a.participant_kind, a.participant_id, a.participant_role
              FROM operations.condition_assessments a
             WHERE a.tenant_id = 1 AND a.row_kind = %s
               AND a.finding_id = ANY(%s::uuid[])
               AND a.participant_role <> 'context'
               AND a.policy_version = (
                   SELECT version FROM operations.condition_policy_versions
                    WHERE active ORDER BY version DESC LIMIT 1
               )
               AND a.assessed_at >= now() - (
                   SELECT (policy->>'freshness_hours')::integer * interval '1 hour'
                     FROM operations.condition_policy_versions
                    WHERE active ORDER BY version DESC LIMIT 1
               )
             ORDER BY assessed_at DESC
            """,
            [row_kind, ids],
        )
        rows = cursor.fetchall()

    result: dict[str, dict] = {}
    for (
        finding_id,
        policy_version,
        policy_digest,
        assessed_at,
        response,
        participant_kind,
        participant_id,
        participant_role,
    ) in rows:
        key = str(finding_id)
        assessment_response = json.loads(response) if isinstance(response, str) else response
        assessment_response = assessment_response or {}
        item = result.setdefault(
            key,
            {
                "available": True,
                "policy_version": policy_version,
                "policy_digest": policy_digest,
                "assessed_at": assessed_at,
                "dispositions": set(),
                "reasons": set(),
                "blockers": set(),
                "scopes": set(),
                "may_execute": True,
            },
        )
        item["dispositions"].add(assessment_response.get("disposition", "unknown"))
        item["reasons"].update(assessment_response.get("reasons") or [])
        item["blockers"].update(assessment_response.get("blockers") or [])
        item["scopes"].add(f"{participant_kind}:{participant_id}:{participant_role}")
        item["may_execute"] = item["may_execute"] and bool(assessment_response.get("may_execute"))
    for item in result.values():
        for field in ("reasons", "blockers"):
            item[field] = sorted(item[field])
        item["scopes"] = sorted(item["scopes"])
        item["disposition"] = (
            next(iter(item["dispositions"])) if len(item["dispositions"]) == 1 else "mixed"
        )
        del item["dispositions"]
    return result


def _condition_response_ids(finding_ids) -> dict[str, set[str]]:
    """Classify entity findings using current assessments and required scopes."""
    ids = [str(value) for value in finding_ids if value]
    result = {key: set() for key in ("actionable", "blocked", "pending", "covered")}
    if not ids:
        return result
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('operations.condition_assessments')")
        if cursor.fetchone()[0] is None:
            result["pending"].update(ids)
            return result
        # A finding without a current, non-context assessment cannot be Ready
        # or Blocked: it is necessarily Pending. Avoid joining participants
        # for that large population before the default Issues page has even
        # opened a Type.
        cursor.execute(
            """
            SELECT DISTINCT a.finding_id::text
              FROM operations.condition_assessments a
             WHERE a.tenant_id = 1 AND a.row_kind = 'entity'
               AND a.finding_id = ANY(%s::uuid[])
               AND a.participant_role <> 'context'
               AND a.policy_version = (
                   SELECT version FROM operations.condition_policy_versions
                    WHERE active ORDER BY version DESC LIMIT 1
               )
               AND a.assessed_at >= now() - (
                   SELECT (policy->>'freshness_hours')::integer * interval '1 hour'
                     FROM operations.condition_policy_versions
                    WHERE active ORDER BY version DESC LIMIT 1
               )
            """,
            [ids],
        )
        assessed_ids = {row[0] for row in cursor.fetchall()}
        candidate_ids = [finding_id for finding_id in ids if finding_id in assessed_ids]
        result["pending"].update(finding_id for finding_id in ids if finding_id not in assessed_ids)
        for offset in range(0, len(candidate_ids), 1000):
            batch = candidate_ids[offset : offset + 1000]
            cursor.execute(
                """
            WITH expected AS (
                SELECT f.id,
                       COALESCE(
                           array_agg(DISTINCT
                               cp.participant_kind || ':' || cp.participant_id::text || ':' || cp.participant_role
                               ORDER BY cp.participant_kind || ':' || cp.participant_id::text || ':' || cp.participant_role
                           ) FILTER (WHERE cp.participant_role <> 'context'),
                           ARRAY[]::text[]
                       ) AS expected_participants
                  FROM operations.findings f
                 LEFT JOIN operations.condition_participants cp
                    ON cp.tenant_id = f.tenant_id AND cp.row_kind = 'entity'
                   AND cp.finding_id = f.id
                 WHERE f.tenant_id = 1 AND f.id = ANY(%s::uuid[])
                   AND f.status IN ('open', 'acknowledged', 'investigating')
                   AND (f.snoozed_until IS NULL OR f.snoozed_until <= now())
                 GROUP BY f.id
            ), assessed AS (
                SELECT a.finding_id,
                       bool_or(a.participant_kind = 'condition'
                               AND (a.response->>'may_execute')::boolean IS TRUE) AS condition_execute,
                       COALESCE(
                           array_agg(DISTINCT
                               a.participant_kind || ':' || a.participant_id::text || ':' || a.participant_role
                               ORDER BY a.participant_kind || ':' || a.participant_id::text || ':' || a.participant_role
                           ) FILTER (WHERE a.participant_kind <> 'condition'),
                           ARRAY[]::text[]
                       ) AS assessed_participants,
                       COALESCE(
                           array_agg(DISTINCT
                               a.participant_kind || ':' || a.participant_id::text || ':' || a.participant_role
                               ORDER BY a.participant_kind || ':' || a.participant_id::text || ':' || a.participant_role
                           ) FILTER (WHERE a.participant_kind <> 'condition'
                                   AND (a.response->>'may_execute')::boolean IS TRUE),
                           ARRAY[]::text[]
                       ) AS executable_participants,
                       bool_or(a.response->>'disposition' = 'blocked') AS blocked,
                       bool_or(a.response->>'disposition' = 'unknown') AS unknown,
                       bool_or(EXISTS (
                           SELECT 1 FROM jsonb_array_elements_text(a.response->'reasons') r
                            WHERE r LIKE 'covered_by:%%'
                       )) AS covered
                  FROM operations.condition_assessments a
                 WHERE a.tenant_id = 1 AND a.row_kind = 'entity'
                   AND a.finding_id = ANY(%s::uuid[])
                   AND a.participant_role <> 'context'
                   AND a.policy_version = (SELECT version FROM operations.condition_policy_versions WHERE active ORDER BY version DESC LIMIT 1)
                   AND a.assessed_at >= now() - (SELECT (policy->>'freshness_hours')::integer * interval '1 hour' FROM operations.condition_policy_versions WHERE active ORDER BY version DESC LIMIT 1)
                 GROUP BY a.finding_id
            )
            SELECT e.id, e.expected_participants, a.condition_execute,
                   a.assessed_participants, a.executable_participants,
                   a.blocked, a.unknown, a.covered
              FROM expected e LEFT JOIN assessed a ON a.finding_id = e.id
                """,
                [batch, batch],
            )
            rows = cursor.fetchall()
            for (
                finding_id,
                expected,
                condition_execute,
                assessed,
                participant_execute,
                blocked,
                _unknown,
                covered,
            ) in rows:
                key = str(finding_id)
                complete = (
                    bool(condition_execute)
                    if not expected
                    else assessed == expected and participant_execute == expected
                )
                if covered:
                    result["covered"].add(key)
                elif complete:
                    result["actionable"].add(key)
                elif blocked:
                    result["blocked"].add(key)
                else:
                    result["pending"].add(key)
    for key in ids:
        if not any(key in values for values in result.values()):
            result["pending"].add(key)
    return result


_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}


def _covered_counts_by_parent(parent_ids) -> dict[str, dict]:
    """For each visible finding: how many findings it covers, how many are high or critical,
    and the highest severity among them. Read from the stored ``covered_by`` of each state."""
    ids = [str(value) for value in parent_ids if value]
    if not ids:
        return {}
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT p.parent::text, count(*),
                   count(*) FILTER (WHERE f.severity IN ('critical', 'high')),
                   (array_agg(f.severity ORDER BY CASE f.severity WHEN 'critical' THEN 4
                        WHEN 'high' THEN 3 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END DESC))[1]
              FROM operations.finding_state s
              JOIN operations.findings f ON f.id = s.finding_id AND f.status = ANY(%s)
             CROSS JOIN LATERAL unnest(s.covered_by) p(parent)
             WHERE s.attention = 'covered' AND s.covered_by && %s::uuid[] AND p.parent = ANY(%s::uuid[])
             GROUP BY p.parent
            """,
            [list(_FINDING_ACTIVE_STATUSES), ids, ids],
        )
        return {
            parent: {"n": n, "high": high, "top": top}
            for parent, n, high, top in cursor.fetchall()
        }


_STATE_LABELS = {
    ATTENTION_NEEDS_ACTION: "Needs action",
    ATTENTION_BLOCKED: "Blocked",
    ATTENTION_PENDING: "Pending",
    ATTENTION_COVERED: "Covered",
    ATTENTION_PAUSED: "Paused",
}

_STATE_REASONS = {
    ATTENTION_NEEDS_ACTION: "Ready for action",
    ATTENTION_BLOCKED: "Blocked by current evidence",
    ATTENTION_PENDING: "Pending current assessment",
    ATTENTION_PAUSED: "Paused by operator",
    ATTENTION_COVERED: "Covered by another finding",
}


def _active_policy_window():
    """(version, oldest acceptable compute time) of the active condition policy."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT version, (policy->>'freshness_hours')::integer "
            "FROM operations.condition_policy_versions WHERE active ORDER BY version DESC LIMIT 1"
        )
        row = cursor.fetchone()
    if row is None:
        return None, timezone.now()
    return row[0], timezone.now() - timedelta(hours=row[1])


def _state_rows():
    """Active findings' state from ``finding_state``, as the operator sees it.

    ``shown`` is the stored attention, except that a pause shows as paused and a state
    computed under an older policy, or older than the policy's freshness window, shows as
    pending. Those are comparisons of columns, not computations, and the stored value is
    written in the same transaction as every change that affects it (migration 0301).
    """
    version, oldest = _active_policy_window()
    return StoredFindingState.objects.filter(
        tenant_id=1, finding__status__in=_FINDING_ACTIVE_STATUSES
    ).annotate(
        shown=Case(
            When(finding__snoozed_until__gt=timezone.now(), then=Value(ATTENTION_PAUSED)),
            When(
                Q(computed_at__gte=oldest, policy_version=version, attention__isnull=False),
                then=F("attention"),
            ),
            default=Value(ATTENTION_PENDING),
            output_field=CharField(),
        )
    )


def _state_ids(attention: str):
    """Subquery of finding ids whose state is ``attention``."""
    return _state_rows().filter(shown=attention).values("finding_id")


def _fleet_state_counts() -> dict[str, dict[str, int]]:
    """Active findings by Type and operator attention."""
    counts: dict[str, dict[str, int]] = {}
    rows = (
        _state_rows()
        .values("finding__finding_type__name", "shown")
        .annotate(n=Count("pk"))
    )
    for row in rows:
        counts.setdefault(row["finding__finding_type__name"], {})[row["shown"]] = row["n"]
    return counts


def _state_counts_for(findings) -> dict[str, dict[str, int]]:
    """Needs action / blocked / pending counts by Type for a filtered set of findings."""
    counts: dict[str, dict[str, int]] = {}
    rows = (
        _state_rows()
        .filter(finding_id__in=findings.order_by().values("id"))
        .values("finding__finding_type__name", "shown")
        .annotate(n=Count("pk"))
    )
    for row in rows:
        entry = counts.setdefault(
            row["finding__finding_type__name"], {"needs_action": 0, "blocked": 0, "pending": 0}
        )
        if row["shown"] in entry:
            entry[row["shown"]] = row["n"]
    return counts


def _critical_issue_badges(ids: list[str]) -> dict[str, dict[str, str]]:
    """For the findings on screen: a critical needs-action finding on the same subject.

    Shown as a badge. It is not part of any state or count.
    """
    if not ids:
        return {}
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT ON (f.id) f.id::text, c.id::text, ct.name, c.subject_id::text
              FROM operations.findings f
              JOIN operations.findings c
                ON c.tenant_id = f.tenant_id AND c.subject_type = f.subject_type
               AND c.subject_id = f.subject_id AND c.id <> f.id
               AND c.severity = 'critical' AND c.status = ANY(%s)
              JOIN operations.finding_state cs
                ON cs.finding_id = c.id AND cs.attention = 'needs_action'
              JOIN operations.finding_types ct ON ct.id = c.finding_type_id
             WHERE f.id = ANY(%s::uuid[]) AND f.severity <> 'critical'
             ORDER BY f.id, c.id
            """,
            [list(_FINDING_ACTIVE_STATUSES), ids],
        )
        return {
            finding: {
                "critical_finding_id": critical,
                "critical_type": critical_type,
                "critical_subject_id": subject,
            }
            for finding, critical, critical_type, subject in cursor.fetchall()
        }


def _condition_operator_states(finding_ids, *, now=None) -> dict[str, dict[str, str]]:
    """Operator state (status, attention, reason) for the findings shown on a page."""
    ids = [str(value) for value in finding_ids if value]
    if not ids:
        return {}
    now = now or timezone.now()
    states: dict[str, dict[str, str]] = {}
    shown = {
        str(row["finding_id"]): row["shown"]
        for row in _state_rows().filter(finding_id__in=ids).values("finding_id", "shown")
    }
    for row in Finding.objects.filter(tenant_id=1, id__in=ids).values(
        "id", "status", "snoozed_until", "subject_type", "subject_id"
    ):
        key = str(row["id"])
        attention = shown.get(key, "")
        states[key] = {
            "status": operator_status(row["status"], row["snoozed_until"], now),
            "attention": attention,
            "reason": _STATE_REASONS.get(attention, ""),
            "subject_type": row["subject_type"],
            "subject_id": str(row["subject_id"]),
        }
    for key, badge in _critical_issue_badges(ids).items():
        if key in states:
            states[key].update(badge)
    return {key: states[key] for key in ids if key in states}


def _operator_issue_type_groups(
    finding_types: list[FindingType],
    category_key: str,
    categories: list[dict],
    type_groups: dict[str, dict],
) -> list[dict]:
    allowed = next((item["types"] for item in categories if item["key"] == category_key), None)
    available = {ft.name for ft in finding_types}
    result = []
    for group in type_groups.values():
        if allowed is not None and not group["types"].intersection(allowed):
            continue
        if group["types"].intersection(available):
            result.append({**group, "types": sorted(group["types"].intersection(available))})
    return sorted(result, key=lambda group: group["label"].casefold())


def _affected_device_rows(findings) -> list[dict]:
    """Return each device exposed to the filtered finding queryset once.

    A finding can be directly about a device or about a software release. The
    latter reaches devices through the established exposure view, so this CTE
    consumes the caller's already-filtered queryset rather than recreating its
    predicates. It remains tenant-scoped at every relationship boundary.
    """
    matching = findings.order_by().values("id")
    matching_sql, matching_params = matching.query.get_compiler(connection=connection).as_sql()
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
    finding_registry.PATCHING: "patching",
    finding_registry.AGENTS: "compliance",
    finding_registry.SOFTWARE: "software",
    finding_registry.INVENTORY: "inventory",
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
    review_devices = 0
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
        if row["lifecycle_status"] == Device.LifecycleStatus.PENDING_CLEANUP:
            review_devices += count
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
            SELECT COUNT(*)::int,
                   COUNT(*) FILTER (
                       WHERE last_contact_at >= NOW() - INTERVAL '{active_device_days} days'
                   )::int
            FROM operations.v_device
            WHERE tenant_id = 1
              AND lifecycle_status <> 'retired'
            """
        )
        total_devices, active_devices = cur.fetchone()

    # One grouping-set scan supplies both the per-client/domain rollup and
    # the fleet-wide attention list. Keeping the two aggregate levels in one
    # current-read query avoids scanning active findings twice while retaining
    # exact distinct-subject/client counts at each level.
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """
            WITH active AS MATERIALIZED (
                SELECT finding.client_id, finding_type.issue_category,
                       finding_type.name AS type_name, finding.severity,
                       finding.subject_id, finding.first_seen_at,
                       COALESCE(finding.last_detected_at, finding.last_seen_at) AS updated_at
                FROM operations.findings finding
                JOIN operations.finding_types finding_type
                  ON finding_type.id = finding.finding_type_id
                WHERE finding.tenant_id = 1
                  AND finding.status IN ('open', 'acknowledged', 'investigating')
                  AND (finding.snoozed_until IS NULL OR finding.snoozed_until < %s)
            )
            SELECT client_id, issue_category, type_name, severity,
                   COUNT(*)::int AS finding_count,
                   COUNT(DISTINCT subject_id)::int AS subject_count,
                   COUNT(*) FILTER (WHERE first_seen_at >= %s)::int AS new_count,
                   GROUPING(client_id) AS is_fleet_rollup,
                   COUNT(DISTINCT client_id)::int AS client_count,
                   MAX(updated_at) AS updated_at,
                   MAX(CASE severity
                       WHEN 'critical' THEN 5 WHEN 'high' THEN 4
                       WHEN 'medium' THEN 3 WHEN 'low' THEN 2 ELSE 1 END)::int
                       AS severity_level
            FROM active
            GROUP BY GROUPING SETS (
                (client_id, issue_category, type_name, severity),
                (issue_category, type_name)
            )
            """,
            [now, yesterday],
        )
        grouped_issue_rows = cur.fetchall()

    issue_rows = []
    attention_group_rows = []
    for row in grouped_issue_rows:
        (
            client_id,
            issue_category,
            type_name,
            severity,
            finding_count,
            subject_count,
            new_count,
            is_fleet_rollup,
            client_count,
            updated_at,
            severity_level,
        ) = row
        if is_fleet_rollup:
            attention_group_rows.append(
                {
                    "finding_type__name": type_name,
                    "finding_type__issue_category": issue_category or "",
                    "count": finding_count,
                    "clients": client_count,
                    "subjects": subject_count,
                    "new": new_count,
                    "updated_at": updated_at,
                    "severity_level": severity_level,
                }
            )
        elif issue_category in _DASHBOARD_DOMAIN_CATEGORIES:
            issue_rows.append(
                {
                    "client_id": client_id,
                    "finding_type__issue_category": issue_category,
                    "finding_type__name": type_name,
                    "severity": severity,
                    "n": finding_count,
                    "subjects": subject_count,
                    "new": new_count,
                }
            )
    client_domain_stats: dict = {}
    global_domain_stats = {
        name: {"severities": {}, "types": {}, "subjects": {}, "total": 0, "new_total": 0}
        for name in ("patching", "compliance", "software", "inventory")
    }
    global_category_counts: dict[str, int] = {}
    for row in issue_rows:
        category_name = row["finding_type__issue_category"]
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
    for reference in client_source_references():
        client_sources.setdefault(reference["client_id"], set()).add(reference["source_name"])

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
                    "label": f"{_count(global_domain_stats['patching'], 'patching_stalled')} no recent patch activity",
                    "href": f"{reverse('patching_queue')}?type=patching_stalled",
                },
                {
                    "label": f"{_count(global_domain_stats['patching'], 'device_never_patched')} no patch installed yet",
                    "href": f"{reverse('patching_queue')}?type=device_never_patched",
                },
                {
                    "label": f"{_count(global_domain_stats['patching'], 'reboot_pending')} restart required",
                    "href": f"{reverse('patching_queue')}?type=reboot_pending",
                },
            ],
        },
        {
            "key": "compliance",
            "name": "Security & coverage",
            "description": "Required security tools and reporting",
            "value": f"{_percent(compliance_covered, total_devices)}%",
            "value_label": "devices covered",
            "has_data": total_devices > 0,
            "delayed": any_source_delayed,
            "updated_at": min(observed_updates, default=None),
            "href": f"{reverse('findings_queue')}?category=agents_reporting",
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
                    "href": f"{reverse('findings_queue')}?category=agents_reporting",
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
                    "href": f"{reverse('findings_queue')}?category=software_security",
                },
                {
                    "label": f"{global_domain_stats['software']['total']} need review",
                    "href": f"{reverse('findings_queue')}?category=software_security",
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
                    "href": f"{reverse('findings_queue')}?category=inventory",
                },
                {
                    "label": f"{global_category_counts.get('lifecycle', 0)} lifecycle reviews",
                    "href": f"{reverse('findings_queue')}?category=inventory",
                },
                {
                    "label": f"{global_category_counts.get('data_quality', 0)} data-quality reviews",
                    "href": f"{reverse('findings_queue')}?category=inventory",
                },
                {
                    "label": f"{pending_merges} possible duplicates",
                    "href": f"{reverse('findings_queue')}?type=duplicate_computers",
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
                    f" · {_count(patch_stats, 'patching_stalled')} no recent patch activity"
                ),
                "href": f"{reverse('patching_queue')}?client={client.slug}",
            },
            {
                "key": "compliance",
                "name": "Security & coverage",
                "stats": compliance,
                "has_data": devices > 0 and bool(linked_health),
                "delayed": bool(delayed_links),
                "detail": (
                    f"{_percent(compliance_covered_client, devices)}% covered"
                    f" · {missing} missing"
                ),
                "href": f"{reverse('findings_queue')}?client={client.slug}&category=agents_reporting",
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
    total_clients = len(clients)
    clients_connected = sum(1 for client in clients if client_sources.get(client.id))
    attention_count = priority_counts["immediate"] + priority_counts["soon"]

    # Data status is an operator summary, not a second work queue.  Every
    # card deliberately opens the governed Issues inbox; Sources and
    # Computers remain evidence/control surfaces.
    active_issue_filter = Q(status__in=_FINDING_ACTIVE_STATUSES) & (
        Q(snoozed_until__isnull=True) | Q(snoozed_until__lt=now)
    )
    source_problem_count = AdminFinding.objects.filter(
        tenant_id=1,
        status__in=_FINDING_ACTIVE_STATUSES,
        finding_type__name="source_failure",
    ).count()
    open_issue_count = (
        Finding.objects.filter(active_issue_filter).count()
        + AdminFinding.objects.filter(
            tenant_id=1, status__in=_FINDING_ACTIVE_STATUSES
        ).count()
        + EntityCandidate.objects.filter(
            tenant_id=1, status=EntityCandidate.Status.PENDING
        ).count()
    )
    critical_issue_count = Finding.objects.filter(
        active_issue_filter, severity="critical"
    ).count() + AdminFinding.objects.filter(
        tenant_id=1,
        status__in=_FINDING_ACTIVE_STATUSES,
        severity="critical",
    ).count()
    patch_subject_count = Finding.objects.filter(
        active_issue_filter,
        tenant_id=1,
        finding_type__issue_category=finding_registry.PATCHING,
    ).values("subject_id").distinct().count()
    patch_clear_count = max(total_devices - patch_subject_count, 0)
    kpis = [
        {
            "name": "Clients",
            "value": f"{total_clients}",
            "detail": f"{attention_count} need attention",
            "href": reverse("org_index", kwargs={"org_slug": "all"}),
        },
        {
            "name": "Computers",
            "value": f"{total_devices:,}",
            "detail": f"{active_devices:,} active · {retired_devices:,} retired",
            "href": reverse("devices_page"),
            # ADR-0032: each count opens the matching list.
            "links": [
                (f"{active_devices:,} active", reverse("devices_page") + "?state=active"),
                (
                    f"{review_devices:,} need review",
                    reverse("devices_page") + "?lifecycle=pending_cleanup",
                ),
                (f"{retired_devices:,} retired", reverse("devices_page") + "?lifecycle=retired"),
            ],
        },
        {
            "name": "Issues",
            "value": f"{open_issue_count:,}",
            "detail": f"{critical_issue_count} critical · current action queue",
            "href": reverse("findings_queue"),
        },
        {
            "name": "Patching",
            "value": f"{_percent(patch_clear_count, total_devices)}%",
            "detail": f"{patch_subject_count:,} computers need patching attention",
            "href": reverse("patching_queue"),
        },
        {
            "name": "Software",
            "value": f"{software_catalog_titles:,}",
            "detail": f"{global_domain_stats['software']['total']:,} Issues need review",
            "href": reverse("software_page"),
        },
    ]
    _issue_categories, issue_type_groups = _operator_issue_taxonomy()
    issue_group_by_name = {
        issue_name: group_key
        for group_key, group in issue_type_groups.items()
        for issue_name in group["types"]
    }
    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    severity_from_level = {5: "critical", 4: "high", 3: "medium", 2: "low", 1: "info"}
    attention_by_type: dict[str, dict] = {}
    for row in attention_group_rows:
        type_name = row["finding_type__name"]
        row_severity = severity_from_level.get(row["severity_level"], "info")
        item = attention_by_type.setdefault(
            type_name,
            {
                "type_name": type_name,
                "category": row["finding_type__issue_category"] or "",
                "count": 0,
                "clients": 0,
                "subjects": 0,
                "new": 0,
                "severity": row_severity,
                "updated_at": row["updated_at"],
            },
        )
        item["count"] += row["count"]
        item["clients"] += row["clients"]
        item["subjects"] += row["subjects"]
        item["new"] += row["new"]
        if severity_rank.get(row_severity, 9) < severity_rank.get(item["severity"], 9):
            item["severity"] = row_severity
        if row["updated_at"] and (
            not item["updated_at"] or row["updated_at"] > item["updated_at"]
        ):
            item["updated_at"] = row["updated_at"]

    for row in (
        AdminFinding.objects.filter(tenant_id=1, status__in=_FINDING_ACTIVE_STATUSES)
        .values("finding_type__name", "finding_type__issue_category")
        .annotate(
            count=Count("id"),
            new=Count("id", filter=Q(first_detected_at__gte=yesterday)),
            updated_at=Max("last_detected_at"),
            severity_level=Max(
                Case(
                    When(severity="critical", then=Value(5)),
                    When(severity="high", then=Value(4)),
                    When(severity="medium", then=Value(3)),
                    When(severity="low", then=Value(2)),
                    default=Value(1),
                )
            ),
        )
    ):
        type_name = row["finding_type__name"]
        row_severity = severity_from_level.get(row["severity_level"], "info")
        item = attention_by_type.setdefault(
            type_name,
            {
                "type_name": type_name,
                "category": row["finding_type__issue_category"] or "",
                "count": 0,
                "clients": 0,
                "subjects": 0,
                "new": 0,
                "severity": row_severity,
                "updated_at": row["updated_at"],
            },
        )
        item["count"] += row["count"]
        item["subjects"] += row["count"]
        item["new"] += row["new"]
        if severity_rank.get(row_severity, 9) < severity_rank.get(item["severity"], 9):
            item["severity"] = row_severity
        if row["updated_at"] and (
            not item["updated_at"] or row["updated_at"] > item["updated_at"]
        ):
            item["updated_at"] = row["updated_at"]

    pending_candidates = EntityCandidate.objects.filter(
        tenant_id=1, status=EntityCandidate.Status.PENDING
    )
    candidate_count = pending_candidates.count()
    if candidate_count:
        candidate_clients = pending_candidates.exclude(client_id__isnull=True).values(
            "client_id"
        ).distinct().count()
        candidate_new = pending_candidates.filter(first_observed_at__gte=yesterday).count()
        item = attention_by_type.setdefault(
            "identity_resolution_pending",
            {
                "type_name": "identity_resolution_pending",
                "category": "identity",
                "count": 0,
                "clients": 0,
                "subjects": 0,
                "new": 0,
                "severity": "medium",
                "updated_at": None,
            },
        )
        item["count"] += candidate_count
        item["clients"] += candidate_clients
        item["subjects"] += candidate_count
        item["new"] += candidate_new

    attention_items = []
    for item in attention_by_type.values():
        item["label"] = finding_registry.finding_type_name(item["type_name"])
        issue_group = issue_group_by_name.get(item["type_name"], item["type_name"])
        item["href"] = (
            f"{reverse('findings_queue')}?type={issue_group}&issue={item['type_name']}"
        )
        if item["clients"]:
            item["affected"] = (
                f"{item['subjects']:,} affected · {item['clients']:,} "
                f"client{'s' if item['clients'] != 1 else ''}"
            )
        else:
            item["affected"] = f"{item['subjects']:,} affected"
        item["change"] = f"{item['new']:,} new today" if item["new"] else "Ongoing"
        attention_items.append(item)
    attention_items.sort(
        key=lambda item: (
            severity_rank.get(item["severity"], 9),
            -item["clients"],
            -item["count"],
            item["label"],
        )
    )

    affected_clients_by_domain = {
        key: sum(
            1
            for client_stats in client_domain_stats.values()
            if client_stats.get(key, {}).get("total", 0)
        )
        for key in ("patching", "compliance", "software", "inventory")
    }
    for summary in domain_summaries:
        summary["issue_count"] = global_domain_stats[summary["key"]]["total"]
        summary["affected_clients"] = affected_clients_by_domain[summary["key"]]
        if summary["key"] == "patching":
            summary["value"] = f"{_percent(patch_clear_count, total_devices)}%"
            summary["value_label"] = "computers without patch Issues"

    configured_sources, configured_sources_available = _configured_source_data_status(now)
    configured_sources_current = sum(
        not source["needs_attention"] for source in configured_sources
    )
    configured_updates = [
        source["observed_at"] for source in configured_sources if source["observed_at"]
    ]
    jobs_health = _jobs_control_health()
    jobs_summary = jobs_health.get("summary", {})
    current_runtime_kinds = {
        str(runtime.get("runtime_kind"))
        for runtime in jobs_health["runtimes"]
        if not runtime.get("stopped_at")
        and (heartbeat := parse_datetime(str(runtime.get("heartbeat_at") or "")))
        and now - heartbeat <= timedelta(minutes=3)
    }
    if not jobs_health["available"]:
        jobs_label = "Job status unavailable"
    elif not {"scheduler", "worker"}.issubset(current_runtime_kinds):
        jobs_label = "Job processing needs attention"
    elif int(jobs_summary.get("contained_claims") or 0):
        jobs_label = "Job processing needs recovery"
    else:
        jobs_label = "Jobs processing normally"
    system_status = {
        "sources_available": configured_sources_available,
        "sources_current": configured_sources_current,
        "sources_total": len(configured_sources),
        "source_problems": source_problem_count,
        "jobs_label": jobs_label,
        "jobs_running": int(jobs_summary.get("running_runs") or 0),
        "jobs_waiting": int(jobs_summary.get("waiting_runs") or 0),
        "processed_at": max(configured_updates, default=dashboard_updated_at),
    }

    issues_opened_24h = Finding.objects.filter(
        tenant_id=1, first_seen_at__gte=yesterday
    ).count() + AdminFinding.objects.filter(
        tenant_id=1, first_detected_at__gte=yesterday
    ).count() + EntityCandidate.objects.filter(
        tenant_id=1,
        status=EntityCandidate.Status.PENDING,
        first_observed_at__gte=yesterday,
    ).count()
    issues_closed_24h = Finding.objects.filter(
        tenant_id=1, closed_at__gte=yesterday
    ).count() + AdminFinding.objects.filter(
        tenant_id=1, resolved_at__gte=yesterday
    ).count()
    movement = [
        {
            "label": "Issues opened",
            "value": issues_opened_24h,
            "href": reverse("findings_queue"),
        },
        {
            "label": "Issues closed",
            "value": issues_closed_24h,
            "href": f"{reverse('findings_queue')}?status=resolved",
        },
        {
            "label": "Patches installed",
            "value": recent_patch_activity["installed"],
            "href": f"{reverse('patch_activity_search_page')}?days=1&status=Installed",
        },
        {
            "label": "Patch failures",
            "value": recent_patch_activity["failed"],
            "href": f"{reverse('patch_activity_search_page')}?days=1&status=Failed",
        },
        {
            "label": "New software Issues",
            "value": global_domain_stats["software"]["new_total"],
            "href": f"{reverse('findings_queue')}?category=software_security",
        },
    ]

    return render(
        request,
        "home.html",
        {
            "total_devices": total_devices,
            "active_devices": active_devices,
            "active_device_days": active_device_days,
            "retired_devices": retired_devices,
            "device_mix": device_mix,
            "total_clients": total_clients,
            "open_client_candidates": ClientCandidate.objects.filter(
                tenant_id=1, status=ClientCandidate.Status.OPEN
            ).count(),
            "clients_connected": clients_connected,
            "kpis": kpis,
            "attention_items": attention_items[:6],
            "attention_group_count": len(attention_items),
            "domain_summaries": domain_summaries,
            "movement": movement,
            "system_status": system_status,
            "client_rows": client_rows,
            "priority_counts": priority_counts,
            "attention_count": attention_count,
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
            current_computers(
                Device.objects.filter(tenant_id=1, client=client, deleted_at__isnull=True)
            ).only("device_type")
        )
        ctx["device_count"] = len(devices)
        ctx["type_summary"] = _type_summary(devices)
        ctx["client_links"] = client_source_references(client_id=client.id)
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
                    f"""
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
                  AND {current_computer_sql()}
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
            # Build each severity rollup once for this client's offline
            # population. The prior form ran the software-exposure view as a
            # correlated subquery for every candidate device before sorting;
            # that made an otherwise ten-row panel proportional to the whole
            # client's inventory many times over.
            cur.execute(
                """
                WITH offline_devices AS MATERIALIZED (
                    SELECT v.device_id, v.canonical_hostname, v.device_role,
                           v.os_group, v.last_contact_at
                      FROM operations.v_device v
                     WHERE v.tenant_id = 1 AND v.client_id = %s
                       AND {current_computer_sql("v")}
                       AND NOT v.is_online_any
                ), direct_severe AS (
                    SELECT f.subject_id AS device_id, COUNT(*)::int AS severe
                      FROM operations.findings f
                      JOIN offline_devices d ON d.device_id = f.subject_id
                     WHERE f.tenant_id = 1
                       AND f.subject_type = 'device'
                       AND f.status IN ('open', 'acknowledged', 'investigating')
                       AND f.severity IN ('critical', 'high')
                     GROUP BY f.subject_id
                ), software_severe AS (
                    SELECT e.device_id, COUNT(DISTINCT e.finding_id)::int AS severe
                      FROM operations.v_device_software_exposure e
                      JOIN offline_devices d ON d.device_id = e.device_id
                     WHERE e.tenant_id = 1
                       AND e.status IN ('open', 'acknowledged', 'investigating')
                       AND e.severity IN ('critical', 'high')
                     GROUP BY e.device_id
                )
                SELECT d.device_id, d.canonical_hostname, d.device_role, d.os_group,
                       d.last_contact_at,
                       COALESCE(direct_severe.severe, 0)
                       + COALESCE(software_severe.severe, 0) AS severe
                  FROM offline_devices d
             LEFT JOIN direct_severe ON direct_severe.device_id = d.device_id
             LEFT JOIN software_severe ON software_severe.device_id = d.device_id
                 ORDER BY severe DESC, d.last_contact_at ASC NULLS FIRST
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
            .annotate(
                device_count=Count(
                    "devices",
                    filter=(
                        Q(devices__deleted_at__isnull=True)
                        & ~Q(devices__lifecycle_status=Device.LifecycleStatus.RETIRED)
                    ),
                )
            )
            .order_by("-device_count", "display_name")
        )
        source_names_by_client: dict = {}
        for reference in client_source_references():
            source_names_by_client.setdefault(reference["client_id"], set()).add(
                reference["source_name"]
            )
        for c in clients_with_counts:
            c.source_names = sorted(source_names_by_client.get(c.id, set()))
        fleet_type_counts = {
            row["device_type"]: row["count"]
            for row in current_computers(
                Device.objects.filter(tenant_id=1, deleted_at__isnull=True)
            )
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
    base_qs = current_computers(
        Device.objects.filter(tenant_id=1, client=client, deleted_at__isnull=True)
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


def _coverage_policy_rows(device: Device, exemptions: dict) -> list[dict]:
    """Return the effective required platform rows for one Computer.

    This intentionally follows the same profile/global/client precedence as
    the Computers inventory reader.  Exemptions stay policy decisions; they
    do not remove the requirement from this display.
    """
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """
            WITH device AS (
                SELECT d.id, d.tenant_id, d.client_id, d.device_role, d.os_group,
                       c.requirement_profile_id
                  FROM operations.devices d
                  JOIN operations.clients c ON c.id = d.client_id
                 WHERE d.tenant_id = 1 AND d.id = %s
            ), baseline AS (
                SELECT item.entity_type, item.platform, item.applicable_os_groups
                  FROM device d
                  JOIN operations.requirement_profile_items item
                    ON item.tenant_id = d.tenant_id
                   AND item.profile_id = d.requirement_profile_id
                   AND d.requirement_profile_id IS NOT NULL
                   AND (item.device_scope = d.device_role OR (
                        item.device_scope = 'all' AND NOT EXISTS (
                            SELECT 1 FROM operations.requirement_profile_items role_item
                             WHERE role_item.tenant_id = d.tenant_id
                               AND role_item.profile_id = d.requirement_profile_id
                               AND role_item.device_scope = d.device_role)))
                UNION ALL
                SELECT requirement.entity_type, requirement.platform,
                       requirement.applicable_os_groups
                  FROM device d
                  JOIN operations.coverage_requirements requirement
                    ON requirement.tenant_id = d.tenant_id
                   AND requirement.client_id IS NULL AND requirement.enabled
                   AND d.requirement_profile_id IS NULL
                   AND (requirement.device_scope = d.device_role OR (
                        requirement.device_scope = 'all' AND NOT EXISTS (
                            SELECT 1 FROM operations.coverage_requirements role_requirement
                             WHERE role_requirement.tenant_id = d.tenant_id
                               AND role_requirement.client_id IS NULL
                               AND role_requirement.enabled
                               AND role_requirement.device_scope = d.device_role)))
            ), client_override AS (
                SELECT DISTINCT ON (requirement.entity_type, requirement.platform)
                       requirement.entity_type, requirement.platform,
                       requirement.applicable_os_groups, requirement.enabled
                  FROM device d
                  JOIN operations.coverage_requirements requirement
                    ON requirement.tenant_id = d.tenant_id
                   AND requirement.client_id = d.client_id
                   AND requirement.device_scope IN ('all', d.device_role)
                 ORDER BY requirement.entity_type, requirement.platform,
                          CASE WHEN requirement.device_scope = d.device_role THEN 0 ELSE 1 END
            ), effective AS (
                SELECT * FROM baseline
                 WHERE NOT EXISTS (
                     SELECT 1 FROM client_override override
                      WHERE override.entity_type = baseline.entity_type
                        AND override.platform = baseline.platform)
                UNION ALL
                SELECT entity_type, platform, applicable_os_groups
                  FROM client_override WHERE enabled
            )
            SELECT DISTINCT ON (effective.platform, effective.entity_type)
                   effective.platform, effective.entity_type
              FROM effective CROSS JOIN device d
             WHERE effective.applicable_os_groups IS NULL
                OR effective.applicable_os_groups ? d.os_group
             ORDER BY effective.platform, effective.entity_type
            """,
            [str(device.id)],
        )
        rows = cur.fetchall()
    policy_rows = [
        {
            "platform": platform or "Any platform",
            "entity_type": entity_type,
            "exempt": entity_type in exemptions,
            "reason": exemptions.get(entity_type, ""),
        }
        for platform, entity_type in rows
    ]
    effective_types = {row["entity_type"] for row in policy_rows}
    for entity_type, reason in exemptions.items():
        if entity_type not in effective_types:
            policy_rows.append(
                {
                    "platform": "—",
                    "entity_type": entity_type,
                    "exempt": True,
                    "reason": reason,
                }
            )
    return policy_rows


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
    ninja_patch_device_ids = _ninja_patch_device_ids(links)
    requested_tab = request.GET.get("tab") or "overview"
    # The former Observations tab is now the Source records section of Details.
    # Keep old bookmarks useful by taking an operator directly to that section.
    if requested_tab == "observations":
        return redirect(
            f"{reverse('device_detail', kwargs={'org_slug': org_slug, 'device_id': device.id})}"
            "?tab=details#source-records"
        )
    # Preserve existing Identity bookmarks while giving the tab a name that
    # describes what operators find there.
    active_tab = "details" if requested_tab == "identity" else requested_tab
    # The Activity tab is now History (ADR-0033); old links keep working.
    if active_tab == "activity":
        active_tab = "history"
    if active_tab not in ("overview", "history", "software", "details", "patching"):
        active_tab = "overview"
    same_name_devices = []
    same_name_device_count = 0
    merge_candidate = None
    for candidate in MergeCandidate.objects.filter(
        tenant_id=1, client_id=device.client_id, status=MergeCandidate.Status.OPEN
    ).only("id", "member_snapshots"):
        if any(
            str(device.id) == str(member.get("device_id"))
            for member in (candidate.member_snapshots or [])
        ):
            merge_candidate = candidate
            break
    if active_tab == "overview":
        same_name_devices_qs = (
            Device.objects.filter(
                tenant_id=1,
                client_id=device.client_id,
                canonical_hostname__iexact=device.canonical_hostname,
                deleted_at__isnull=True,
            )
            .exclude(id=device.id)
            .order_by("-updated_at", "-created_at")
        )
        same_name_device_count = same_name_devices_qs.count()
        same_name_devices = list(same_name_devices_qs[:20])

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
    response_ids = _condition_response_ids(finding.id for finding in active_findings)
    for finding in active_findings:
        finding.condition_response = next(
            (state for state, ids in response_ids.items() if str(finding.id) in ids),
            "pending",
        )
        if finding.snoozed_until and finding.snoozed_until > timezone.now():
            finding.condition_response = "paused"
        finding.condition_assessment = None
    assessments = _condition_assessment_display(
        "entity", (finding.id for finding in active_findings)
    )
    for finding in active_findings:
        finding.condition_assessment = assessments.get(str(finding.id))

    observations = []
    software_rows = []
    removed_software: list[dict] = []
    software_inventory: dict | None = None
    patch_rows = []
    patching = None
    windows_servicing = None
    operating_system_installation = None
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            observations = _device_source_records(cur, [device.id]).get(str(device.id), [])
            monitors = _device_process_monitors(cur, device.id)
            observations = [(*row, monitors.get(str(row[0]), [])) for row in observations]

            cur.execute(
                """
                SELECT installation_id, first_observed_at, last_observed_at, projected_at
                  FROM operations.v_computer_os_installation_current
                 WHERE tenant_id = %s AND device_id = %s
                 ORDER BY last_observed_at DESC
                 LIMIT 1
                """,
                [1, str(device.id)],
            )
            os_installation_row = cur.fetchone()
            if os_installation_row:
                operating_system_installation = {
                    "id": os_installation_row[0],
                    "first_observed_at": os_installation_row[1],
                    "last_observed_at": os_installation_row[2],
                    "projected_at": os_installation_row[3],
                }

            cur.execute(
                """
                SELECT installation.canonical_name, installation.publisher,
                       installation.version, installation.install_date,
                       installation.last_observed_at, installation.install_location,
                       COALESCE(evidence.evidence_state, 'withdrawn')
                  FROM operations.software_installations_current installation
                  LEFT JOIN LATERAL (
                      SELECT source_evidence.evidence_state
                        FROM operations.v_software_installation_evidence_current source_evidence
                       WHERE source_evidence.tenant_id = installation.tenant_id
                         AND source_evidence.device_id = installation.device_id
                         AND source_evidence.canonical_name = installation.canonical_name
                       ORDER BY CASE source_evidence.evidence_state
                                    WHEN 'current' THEN 0
                                    WHEN 'offline' THEN 1
                                    WHEN 'stale' THEN 2
                                    ELSE 3
                                END,
                                source_evidence.last_seen_at DESC
                       LIMIT 1
                  ) evidence ON TRUE
                 WHERE installation.tenant_id = %s
                   AND installation.device_id = %s
                   AND installation.deleted_at IS NULL
                   AND installation.stale_since IS NULL
                 ORDER BY installation.canonical_name
                LIMIT 300
                """,
                [1, str(device.id)],
            )
            software_rows = cur.fetchall()

            # Programs Ninja no longer lists for this computer, newest first.
            cur.execute(
                """
                SELECT canonical_name, publisher, version, stale_since, stale_reason
                  FROM operations.software_installations_current
                 WHERE tenant_id = %s AND device_id = %s
                   AND deleted_at IS NULL AND stale_since IS NOT NULL
                 ORDER BY stale_since DESC, canonical_name
                 LIMIT 200
                """,
                [1, str(device.id)],
            )
            removed_software = [
                {"name": r[0], "publisher": r[1], "version": r[2], "removed_at": r[3],
                 "reason": _software_removal_reason(r[4])}
                for r in cur.fetchall()
            ]

            # When Ninja last collected this computer's software list.
            cur.execute(
                """
                SELECT collected_at, listed_at, listed_count, listed_by, held_at, held_reason
                  FROM operations.software_inventory_devices
                 WHERE tenant_id = %s AND device_id = %s
                """,
                [1, str(device.id)],
            )
            inventory_row = cur.fetchone()
            if inventory_row:
                software_inventory = {
                    "collected_at": inventory_row[0], "listed_at": inventory_row[1],
                    "listed_count": inventory_row[2],
                    "listed_by": "full check" if inventory_row[3] == "fleet"
                    else "software change",
                    "held_at": inventory_row[4], "held_reason": inventory_row[5],
                }

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

                # Patch signal has one row per Ninja device ID.  Resolve
                # compatible Ninja IDs above from the already-loaded links:
                # casting arbitrary source IDs here can crash this page before
                # the source-name filter is applied.
                sig = None
                if ninja_patch_device_ids:
                    cur.execute(
                        """
                        SELECT dps.ever_installed,
                               dps.last_seen_at,
                               dps.install_attempts
                        FROM ninja_patches.device_patch_signal dps
                        WHERE dps.device_id = ANY(%s::integer[])
                        ORDER BY dps.last_seen_at DESC NULLS LAST
                        LIMIT 1
                        """,
                        [ninja_patch_device_ids],
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

                if active_tab == "patching" and ninja_patch_device_ids:
                    cur.execute(
                        """
                        SELECT patch_name, kb_number, status, severity,
                               patch_category, installed_at, last_observed_at
                        FROM ninja_patches.current_patch_state
                        WHERE device_id = ANY(%s::integer[])
                        ORDER BY last_observed_at DESC NULLS LAST, patch_name
                        LIMIT 300
                        """,
                        [ninja_patch_device_ids],
                    )
                    patch_rows = cur.fetchall()

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

    # Show each Hudu record that is either linked to this device or is an
    # unlinked name match. The latter remains distinct from a source identity:
    # it is useful context, but never attaches a record or changes coverage.
    hudu_records = []
    if active_tab == "details" and device.canonical_hostname:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                """
                SELECT hudu.observation_id,
                       hudu.source_layout,
                       hudu.source_url,
                       hudu.is_archived,
                       CASE
                           WHEN hudu.device_id = %s::uuid THEN 0
                           WHEN hudu.client_id = %s::uuid THEN 1
                           ELSE 2
                       END AS relationship_rank,
                       COUNT(DISTINCT hudu.card_source || ':' || hudu.card_id)
                           FILTER (WHERE hudu.card_id IS NOT NULL) AS card_count
                  FROM operations.v_cmdb_inventory_evidence_current hudu
                 WHERE hudu.tenant_id = 1
                   AND hudu.source_name = 'Hudu'
                   AND (
                        hudu.device_id = %s::uuid
                        OR (
                            hudu.device_id IS NULL
                            AND LOWER(hudu.hostname) = LOWER(%s)
                        )
                   )
                 GROUP BY hudu.observation_id,
                          hudu.source_layout,
                          hudu.source_url,
                          hudu.is_archived,
                          hudu.client_id,
                          hudu.device_id
                 ORDER BY relationship_rank,
                          hudu.is_archived ASC,
                          hudu.source_layout,
                          hudu.observation_id
                """,
                [
                    str(device.id),
                    str(device.client_id),
                    str(device.id),
                    device.canonical_hostname,
                ],
            )
            relationship_labels = {
                0: "Linked to this device",
                1: "Same client and name",
                2: "Name only",
            }
            hudu_records = [
                {
                    "layout": row[1] or "Asset",
                    "url": _safe_external_http_url(row[2]),
                    "is_archived": row[3],
                    "relationship": relationship_labels[row[4]],
                    "is_linked": row[4] == 0,
                    "card_count": row[5],
                }
                for row in cur.fetchall()
            ]

    attribute_fields = []
    if active_tab == "details":
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                """
                SELECT claim.attribute_key, claim.attribute_display_name,
                       claim.sensitivity, claim.value_display, source.name,
                       evidence.entity_type, evidence.external_id,
                       claim.last_observed_at
                  FROM operations.v_entity_attribute_claim_current claim
                  LEFT JOIN operations.v_device_observation_current evidence
                    ON evidence.tenant_id = claim.tenant_id
                   AND evidence.observation_id = claim.observation_id
                  JOIN operations.source_instances source_instance
                    ON source_instance.tenant_id = claim.tenant_id
                   AND source_instance.id = claim.source_instance_id
                  JOIN operations.sources source ON source.id = source_instance.source_id
                 WHERE claim.tenant_id = 1
                   AND claim.entity_id = %s
                 ORDER BY claim.attribute_display_name, claim.value_display,
                          source.name
                """,
                [str(device.entity_id)],
            )
            claim_rows = cur.fetchall()

        fields_by_key: dict[str, dict] = {}
        section_labels = {
            "identity": "Identity and inventory",
            "operating_system": "Operating system",
            "hardware": "Hardware and virtualization",
            "network": "Network",
            "management": "Security and management",
            "other": "Other reported information",
        }

        def _attribute_section(key: str, display_name: str) -> str:
            """Place every normalized claim in an operator-readable section."""
            text = f"{key} {display_name}".lower()
            if any(
                term in text
                for term in ("ip", "mac", "network", "gateway", "dns", "adapter", "subnet")
            ):
                return "network"
            if any(
                term in text
                for term in (
                    "serial",
                    "manufacturer",
                    "model",
                    "cpu",
                    "processor",
                    "memory",
                    "ram",
                    "disk",
                    "storage",
                    "bios",
                    "chassis",
                    "virtual",
                    "vm ",
                    "vm_",
                    "hypervisor",
                )
            ):
                return "hardware"
            if any(
                term in text
                for term in (
                    "operating system",
                    "os_",
                    "windows",
                    "kernel",
                    "boot",
                    "uptime",
                    "architecture",
                    "release",
                    "build",
                )
            ):
                return "operating_system"
            if any(
                term in text
                for term in (
                    "name",
                    "hostname",
                    "domain",
                    "fqdn",
                    "asset tag",
                    "role",
                    "device type",
                    "client",
                )
            ):
                return "identity"
            if any(
                term in text
                for term in (
                    "patch",
                    "reboot",
                    "threat",
                    "security",
                    "antivirus",
                    "agent",
                    "maintenance",
                    "health",
                    "user",
                    "power",
                )
            ):
                return "management"
            return "other"

        fields_by_key: dict[str, dict] = {}
        for (
            key,
            display_name,
            sensitivity,
            value,
            source_name,
            entity_type,
            external_id,
            _observed_at,
        ) in claim_rows:
            source_record_key = (source_name, entity_type, external_id)
            source_record = {
                "name": source_name,
                "entity_type": entity_type,
                "external_id": external_id,
            }
            field = fields_by_key.setdefault(
                key,
                {
                    "name": display_name,
                    "sensitivity": sensitivity,
                    "section": _attribute_section(key, display_name),
                    "values": {},
                },
            )
            field["values"].setdefault(value, {})[source_record_key] = source_record
        for field in fields_by_key.values():
            value_groups = [
                {
                    "value": value,
                    "sources": [sources[source_key] for source_key in sorted(sources)],
                }
                for value, sources in field["values"].items()
            ]
            value_groups.sort(key=lambda group: (group["value"] or "").lower())
            attribute_fields.append(
                {
                    "name": field["name"],
                    "sensitivity": field["sensitivity"],
                    "section": field["section"],
                    "value_groups": value_groups,
                    "differs": len(value_groups) > 1,
                }
            )
        attribute_fields.sort(key=lambda field: field["name"].lower())
        attribute_sections = [
            {
                "name": section_labels[section],
                "fields": [field for field in attribute_fields if field["section"] == section],
            }
            for section in section_labels
        ]
    else:
        attribute_sections = []

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
                name not in decisions_map or pub_entry["tier"] > decisions_map[name]["tier"]
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
            "evidence_state": r[6],
            "decision": (decisions_map.get(r[0]) or {}).get("decision"),
            "decision_scope": (
                None
                if r[0] not in decisions_map
                else (
                    "device"
                    if decisions_map[r[0]]["device_id"] is not None
                    else ("client" if decisions_map[r[0]]["client_id"] is not None else "global")
                )
            ),
        }
        for r in software_rows
    ]

    # Aggregate open-issue counts (for header + Overview snapshot).
    coverage_policy_rows = (
        _coverage_policy_rows(device, exemptions) if active_tab == "overview" else []
    )
    required_agent_rows = [
        row for row in coverage_policy_rows if row["platform"] != "—" and not row["exempt"]
    ]
    current_agent_records = {
        (source, entity_type)
        for _observation_id, source, entity_type, _external_id, _source_url, active, _last_seen, _reported_online, _last_contact, record_lifecycle, _process_monitors in observations
        if active and record_lifecycle not in {"archived", "retired", "decommissioned"}
    }
    agent_summary = {
        "required": len(required_agent_rows),
        "present": sum(
            (row["platform"], row["entity_type"]) in current_agent_records
            for row in required_agent_rows
        ),
    }
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
    # History (ADR-0033): only when the tab is open, to keep the hot path
    # lean. Ninja activity and patch evidence are read for every Ninja
    # record the Computer (or a Computer merged into it) has had.
    history_before = _parse_history_before(request.GET.get("before"))
    history_origin = request.GET.get("origin") or ""
    if history_origin not in HISTORY_ORIGINS:
        history_origin = ""
    history_next_before = None
    if active_tab == "history":
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            history_ids = _history_computer_ids(cur, device.id)
            users = dict(get_user_model().objects.filter(tenant_id=1).values_list("id", "username"))
            activity.extend(_change_history_events(cur, history_ids, history_before, users))
            activity.extend(_record_history_events(cur, history_ids, history_before))
            activity.extend(_audit_history_events(cur, history_ids, history_before, users))
            cur.execute(
                """SELECT DISTINCT eo.external_id FROM operations.v_entity_observation_admin_metadata eo
                    WHERE eo.tenant_id = 1 AND eo.device_id = ANY(%s::uuid[])
                      AND eo.platform = 'Ninja' AND eo.external_id ~ '^[0-9]+$'""",
                (history_ids,),
            )
            ninja_ids = [int(row[0]) for row in cur.fetchall()]
        if ninja_ids:
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute("SET LOCAL operations.tenant_id = 1")
                cur.execute(
                    """
                    SELECT activity_time, activity_type, source_name,
                           severity, subject, message, data, ingested_at
                    FROM ninja_activities.activities
                    WHERE device_id = ANY(%s)
                      AND (%s::timestamptz IS NULL OR activity_time < %s::timestamptz)
                    ORDER BY activity_time DESC
                    LIMIT 100
                    """,
                    [ninja_ids, history_before, history_before],
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
                    WHERE pf.device_id = ANY(%s)
                      AND (%s::timestamptz IS NULL
                           OR COALESCE(pf.installed_at, pf.ninja_observed_at,
                                       pf.last_observed_at) < %s::timestamptz)
                    ORDER BY COALESCE(pf.installed_at, pf.ninja_observed_at,
                                      pf.last_observed_at) DESC NULLS LAST
                    LIMIT 100
                    """,
                    [ninja_ids, history_before, history_before],
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

    for event in activity:
        event.setdefault(
            "origin", "source" if event["kind"] in ("ninja_event", "patch", "reboot") else "process"
        )
    if history_before is not None:
        activity = [e for e in activity if e["at"] and e["at"] < history_before]
    if history_origin:
        activity = [e for e in activity if e["origin"] == history_origin]
    activity.sort(key=lambda e: (e["at"] or timezone.now()), reverse=True)
    if len(activity) > HISTORY_PAGE_SIZE:
        activity = activity[:HISTORY_PAGE_SIZE]
        history_next_before = activity[-1]["at"]

    try:
        load_active_profile()
        condition_policy_available = True
    except (RuntimeError, ValueError):
        condition_policy_available = False

    return render(
        request,
        "device_detail.html",
        {
            "device": device,
            "name_provenance": computer_naming.name_provenance(device.id),
            "condition_policy_available": condition_policy_available,
            "same_name_devices": same_name_devices,
            "same_name_device_count": same_name_device_count,
            "merge_candidate": merge_candidate,
            "links": links,
            "hudu_records": hudu_records,
            "active_findings": active_findings,
            "observations": observations,
            "software_rows": software_view,
            "removed_software": removed_software,
            "software_inventory": software_inventory,
            "patch_rows": patch_rows,
            "patching": patching,
            "windows_servicing": windows_servicing,
            "operating_system_installation": operating_system_installation,
            "active_tab": active_tab,
            "sev_counts": sev_counts,
            "severe_open": severe_open,
            "device_health": device_health,
            "activity": activity,
            "history_origins": HISTORY_ORIGINS,
            "history_origin": history_origin,
            "history_before": history_before,
            "history_next_before": history_next_before,
            "exemptions": exemptions,
            "entity_type_choices": entity_type_choices,
            "coverage_policy_rows": coverage_policy_rows,
            "agent_summary": agent_summary,
            "attribute_fields": attribute_fields,
            "attribute_sections": attribute_sections,
            "can_view_entity_evidence": bool(
                device.entity_id
                and (
                    request.user.is_superuser or request.user.has_perm("operations.manage_catalog")
                )
            ),
            "can_manage_lifecycle": can_manage_lifecycle(request.user),
        },
    )


@login_required
@require_POST
@transaction.atomic
def device_lifecycle_set(
    request: HttpRequest, org_slug: str, device_id: str, target: str
) -> HttpResponse:
    """Retire or restore a Computer without deleting its evidence."""
    if not can_manage_lifecycle(request.user):
        raise PermissionDenied
    if target not in ("retired", "active"):
        messages.error(request, "That lifecycle action is not available.")
        return redirect("device_detail", org_slug=org_slug, device_id=device_id)

    reason = (request.POST.get("reason") or "").strip()
    if not reason:
        messages.warning(request, "A reason is required.")
        return redirect("device_detail", org_slug=org_slug, device_id=device_id)
    if len(reason) > _LIFECYCLE_REASON_MAX_LENGTH:
        messages.warning(
            request,
            f"Keep the reason to {_LIFECYCLE_REASON_MAX_LENGTH} characters or fewer.",
        )
        return redirect("device_detail", org_slug=org_slug, device_id=device_id)

    device = get_object_or_404(
        Device.objects.select_for_update(),
        tenant_id=1,
        id=device_id,
        client__slug=org_slug,
        deleted_at__isnull=True,
    )
    entity = get_object_or_404(
        Entity.objects.select_for_update(),
        tenant_id=1,
        id=device.entity_id,
        deleted_at__isnull=True,
    )
    desired_status = (
        Device.LifecycleStatus.RETIRED if target == "retired" else Device.LifecycleStatus.ACTIVE
    )
    if device.lifecycle_status == desired_status:
        messages.info(
            request,
            f"This Computer is already {device.get_lifecycle_status_display().lower()}.",
        )
        return redirect("device_detail", org_slug=org_slug, device_id=device_id)

    before = {
        "lifecycle_status": device.lifecycle_status,
        "entity_retired_at": entity.retired_at.isoformat() if entity.retired_at else None,
        "entity_retired_reason": entity.retired_reason,
    }
    now = timezone.now()
    device.lifecycle_status = desired_status
    device.updated_at = now
    device.updated_reason = f"operator.lifecycle_{target}"
    device.save(update_fields=["lifecycle_status", "updated_at", "updated_reason"])

    entity.retired_at = now if target == "retired" else None
    entity.retired_reason = reason if target == "retired" else ""
    entity.updated_at = now
    entity.updated_reason = f"operator.lifecycle_{target}"
    entity.save(update_fields=["retired_at", "retired_reason", "updated_at", "updated_reason"])
    _audit(
        request,
        f"device.lifecycle.{target}",
        device.id,
        before,
        {
            "lifecycle_status": device.lifecycle_status,
            "reason": reason,
            "entity_retired_at": entity.retired_at.isoformat() if entity.retired_at else None,
        },
        entity_type="device",
    )
    if target == "retired":
        messages.success(
            request,
            "Computer retired. Its source records and history were kept.",
        )
    else:
        messages.success(
            request,
            "Computer restored to the active inventory. Its current source status will refresh normally.",
        )
    return redirect("device_detail", org_slug=org_slug, device_id=device_id)


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
    """Fleet-wide search — Computer identity data, client name / slug.

    A Computer matches on its name or serial, or on the name, serial or VM
    UUID any of its records reports now or reported before (a withdrawn or
    merged-in record still finds the Computer it belonged to). Each Computer
    is listed once with what matched; retired Computers are included, labeled,
    after the others (ADR-0032).

    - Unique device match → redirect straight to device_detail.
    - Unique client match → redirect to client's org_index page.
    - Ambiguous or empty → render a results page.
    """
    q = (request.GET.get("q") or "").strip()
    if not q:
        return render(request, "search_results.html", {"q": "", "devices": [], "clients": []})

    matched = _search_computer_identity(q)
    devices = list(
        Device.objects.filter(tenant_id=1, deleted_at__isnull=True, id__in=matched)
        .select_related("client")
    )
    for device in devices:
        device.search_matched = matched[device.id]
    devices.sort(
        key=lambda d: (
            d.lifecycle_status == Device.LifecycleStatus.RETIRED,
            d.canonical_hostname.lower(),
        )
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
        {"q": q, "devices": devices, "clients": clients},
    )


_SEARCH_LIMIT = 100

# Computers by name, serial or VM UUID, from the Computer and from every record
# it has had (withdrawn and merged-in records included).
SEARCH_IDENTITY_SQL = """
            SELECT DISTINCT ON (device_id) device_id, matched
              FROM (
                  SELECT d.id AS device_id, 1 AS rank, 'name' AS matched
                    FROM operations.devices d
                   WHERE d.tenant_id = 1 AND d.deleted_at IS NULL
                     AND d.canonical_hostname ILIKE %(p)s
                  UNION ALL
                  SELECT d.id, 2, 'serial number'
                    FROM operations.devices d
                   WHERE d.tenant_id = 1 AND d.deleted_at IS NULL
                     AND d.canonical_serial ILIKE %(p)s
                  UNION ALL
                  -- A name the Computer had before a rename (ADR-0034).
                  SELECT d.id, 2, 'former name'
                    FROM operations.change_actions ca
                    JOIN operations.devices d
                      ON d.tenant_id = 1 AND d.deleted_at IS NULL
                     AND d.id::text = ca.evidence ->> 'device_id'
                   WHERE ca.tenant_id = 1 AND ca.action = 'computer.rename'
                     AND ca.evidence ->> 'from' ILIKE %(p)s
                  UNION ALL
                  -- The name of a Computer merged into this one.
                  SELECT m.survivor_id, 2, 'name of a merged Computer'
                    FROM operations.computer_merges m
                    JOIN operations.devices absorbed ON absorbed.id = m.absorbed_id
                    JOIN operations.devices d
                      ON d.id = m.survivor_id AND d.deleted_at IS NULL
                   WHERE m.tenant_id = 1 AND absorbed.canonical_hostname ILIKE %(p)s
                  UNION ALL
                  SELECT eo.device_id, 3,
                         CASE WHEN eo.reported_name ILIKE %(p)s
                                   THEN 'name in ' || eo.platform
                              WHEN eo.canonical_serial ILIKE %(p)s
                                   THEN 'serial number in ' || eo.platform
                              ELSE 'VM UUID in ' || eo.platform END
                         || CASE WHEN eo.active THEN '' ELSE ' (earlier record)' END
                    FROM operations.v_entity_observation_admin_metadata eo
                    JOIN operations.devices d
                      ON d.tenant_id = eo.tenant_id AND d.id = eo.device_id
                     AND d.deleted_at IS NULL
                   WHERE eo.tenant_id = 1 AND eo.entity_key NOT LIKE 'device-health:%%'
                     AND (eo.reported_name ILIKE %(p)s
                          OR eo.canonical_serial ILIKE %(p)s
                          OR eo.vm_uuid ILIKE %(p)s)
              ) hits
             ORDER BY device_id, rank
             LIMIT %(limit)s
            """


def _search_computer_identity(q: str) -> dict[uuid.UUID, str]:
    """Current Computers matching ``q``, each with what matched (first match wins)."""
    pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    with connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            SEARCH_IDENTITY_SQL,
            {"p": pattern, "limit": _SEARCH_LIMIT * 3},
        )
        return dict(cur.fetchall())


@login_required
@transaction.atomic
def findings_queue(request: HttpRequest) -> HttpResponse:
    """Entity findings review page."""
    with connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")

    status_filter = request.GET.get("status", "")
    if status_filter == "all":
        status_filter = ""
    severity_filter = request.GET.get("severity", "")
    type_filter = request.GET.get("type", "")
    issue_filter = request.GET.get("issue", "")
    category_filter = request.GET.get("category", "")
    confidence_filter = request.GET.get("confidence", "")
    client_filter = request.GET.get("client", "")
    platform_filter = request.GET.get("platform", "")
    os_filter = request.GET.get("os", "")
    computer_type_filter = request.GET.get("computer_type", "")
    online_filter = request.GET.get("online", "")
    attention_filter = request.GET.get("attention", "")
    legacy_response_filter = request.GET.get("response", "")
    if not attention_filter and legacy_response_filter:
        attention_filter = {
            "actionable": "needs_action",
            "blocked": "blocked",
            "pending": "pending",
            "paused": "paused",
            "all": "",
        }.get(legacy_response_filter, "")
    if attention_filter not in {"", "needs_action", "blocked", "pending", "covered"}:
        attention_filter = ""
    subject_id_filter = (request.GET.get("subject_id") or "").strip()
    requested_device_id_filter = (request.GET.get("device_id") or "").strip()
    device_id_filter = ""
    group_key_filter = (request.GET.get("group_key") or "").strip()
    group_value_filter = (request.GET.get("group_value") or "").strip()
    q_filter = (request.GET.get("q") or "").strip()
    try:
        issue_categories, issue_type_groups = _operator_issue_taxonomy()
        load_active_profile()  # the response states below need an active policy
        condition_policy_available = True
    except RuntimeError:
        # Evidence and retained findings remain reviewable when policy
        # authority is unavailable; governed response filters fail closed.
        issue_categories, issue_type_groups = [], {}
        condition_policy_available = False

    # A category may be given by its key or its label.
    category_filter = next(
        (item["key"] for item in issue_categories if category_filter in item["categories"]),
        category_filter,
    )
    for group_key, group in issue_type_groups.items():
        if type_filter in group["types"]:
            type_filter = group_key
            break

    selected_type = issue_type_groups.get(type_filter)
    valid_issue_names = (
        {issue["value"] for issue in selected_type["issues"]} if selected_type else set()
    )
    if issue_filter and issue_filter not in valid_issue_names:
        issue_filter = ""

    # Source names come from operations.sources (admin-editable
    # reference data) — never hardcoded in code.
    source_names = list(Source.objects.order_by("name").values_list("name", flat=True))
    source_names_set = set(source_names)

    qs = Finding.objects.filter(tenant_id=1).select_related(
        "finding_type",
        "client",
        "owner",
    )

    show_snoozed = request.GET.get("snoozed") != "0"
    if status_filter in ("", "active"):
        qs = qs.filter(status__in=_FINDING_ACTIVE_STATUSES)
    elif status_filter == "open":
        qs = qs.filter(status=Finding.Status.OPEN)
    elif status_filter == "acknowledged":
        qs = qs.filter(status__in=(Finding.Status.ACKNOWLEDGED, Finding.Status.INVESTIGATING))
    elif status_filter == "paused":
        qs = qs.filter(
            status__in=_FINDING_ACTIVE_STATUSES,
            snoozed_until__gt=timezone.now(),
        )
    elif status_filter == "resolved":
        qs = qs.filter(
            status__in=(Finding.Status.RESOLVED, Finding.Status.SUPPRESSED, Finding.Status.WONTFIX)
        )
    if not show_snoozed:
        qs = qs.filter(Q(snoozed_until__isnull=True) | Q(snoozed_until__lt=timezone.now()))
    # A finding another open finding on the same computer already explains is
    # covered: still evaluated and counted on its own tile, but not separate
    # work, so the queue leaves it out unless it is asked for.
    show_covered = attention_filter == ATTENTION_COVERED or request.GET.get("covered") == "1"
    if not show_covered:
        qs = qs.exclude(
            id__in=_state_ids(ATTENTION_COVERED)
        )

    if category_filter:
        category_types = next(
            (
                item.get("types", set())
                for item in issue_categories
                if item["key"] == category_filter
            ),
            set(),
        )
        qs = qs.filter(finding_type__name__in=category_types)
    if type_filter:
        type_names = issue_type_groups.get(type_filter, {}).get("types", {type_filter})
        qs = qs.filter(finding_type__name__in=type_names)
    if issue_filter:
        qs = qs.filter(finding_type__name=issue_filter)
    if confidence_filter:
        qs = qs.filter(confidence=confidence_filter)
    if client_filter:
        qs = qs.filter(client__slug=client_filter)
    if platform_filter:
        qs = qs.filter(finding_details__platform=platform_filter)
    if os_filter or computer_type_filter:
        scoped_devices = Device.objects.filter(tenant_id=1, deleted_at__isnull=True)
        if os_filter:
            scoped_devices = scoped_devices.filter(os_name=os_filter)
        if computer_type_filter in {"server", "workstation", "unknown"}:
            scoped_devices = scoped_devices.filter(device_role=computer_type_filter)
        qs = qs.filter(subject_type="device", subject_id__in=scoped_devices.values("id"))
    if subject_id_filter:
        # Filter to findings targeting a specific subject (device / client
        # / etc.). Used by Device Detail's "Issue → Issues page" clickthru.
        try:
            uuid.UUID(subject_id_filter)
        except (ValueError, TypeError):
            subject_id_filter = ""
        else:
            qs = qs.filter(subject_id=subject_id_filter)
    if requested_device_id_filter:
        # Device Detail counts both a device's direct findings and the
        # software findings it inherits through current installations. This
        # filter gives the Issues queue that same scope. A malformed value
        # fails closed rather than widening an operator's result set.
        try:
            uuid.UUID(requested_device_id_filter)
        except (ValueError, TypeError):
            qs = qs.none()
        else:
            device_id_filter = requested_device_id_filter
            with connection.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT finding_id
                      FROM operations.v_device_software_exposure
                     WHERE tenant_id = 1 AND device_id = %s::uuid
                    """,
                    [device_id_filter],
                )
                exposed_finding_ids = [row[0] for row in cur.fetchall()]
            qs = qs.filter(
                Q(subject_type=Finding.SubjectType.DEVICE, subject_id=device_id_filter)
                | Q(id__in=exposed_finding_ids)
            )
    active_group_key = ""
    if group_key_filter or group_value_filter:
        configured_key = (
            FindingType.objects.filter(name=type_filter)
            .values_list("drilldown_evidence_key", flat=True)
            .first()
            or ""
        )
        group_lookup = _finding_group_lookup(
            finding_type_name=type_filter,
            configured_key=configured_key,
            requested_key=group_key_filter,
            requested_value=group_value_filter,
        )
        if group_lookup is None:
            # A malformed URL must never become a broader Issues query.
            qs = qs.none()
        else:
            qs = qs.filter(**group_lookup)
            active_group_key = configured_key
    if q_filter:
        # Free-text match against canonical_name OR hostname in details
        qs = qs.filter(
            Q(finding_details__canonical_name__icontains=q_filter)
            | Q(finding_details__hostname__icontains=q_filter)
        )

    # Retained findings stay discoverable even when their device is offline.
    # The governed response filter controls whether an offline finding is
    # actionable, while status/response=all exposes the retained evidence.
    device_subject = Q(subject_type=Finding.SubjectType.DEVICE)

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

    # A collapsed queue is navigation, not a review scope.  Its fleet counters
    # must not first materialize every finding and participant assessment.
    show_finding_rows = bool(
        category_filter
        or type_filter
        or issue_filter
        or active_group_key
        or device_id_filter
        or subject_id_filter
        or wants_csv(request)
    )
    # Filters outside the navigation taxonomy still need exact, filtered
    # state counts. The fast set-based summary is only for the unfiltered
    # collapsed landing page.
    has_non_navigation_filter = any(
        (
            status_filter,
            severity_filter,
            confidence_filter,
            client_filter,
            platform_filter,
            os_filter,
            computer_type_filter,
            online_filter,
            q_filter,
            request.GET.get("snoozed") == "0",
        )
    )
    needs_per_finding_states = (
        show_finding_rows or bool(attention_filter) or has_non_navigation_filter
    )

    # Top cards are fleet-wide operator populations; they do not inherit selected filters.
    # State comes from ``finding_state`` (written in the same transaction as every change that
    # affects it) with pause and freshness read live, so nothing here builds a state per
    # finding.
    fleet_state_counts_by_type = _fleet_state_counts()
    fleet_total = sum(sum(counts.values()) for counts in fleet_state_counts_by_type.values())

    # Attention is separate from operator Status. It filters only after all subject and
    # evidence filters have been applied.
    if attention_filter:
        qs = qs.filter(id__in=_state_ids(attention_filter))

    if severity_filter:
        qs = qs.filter(severity=severity_filter)

    actionable_qs = qs
    fleet_counts = {
        attention: sum(counts.get(attention, 0) for counts in fleet_state_counts_by_type.values())
        for attention in (
            ATTENTION_NEEDS_ACTION,
            ATTENTION_BLOCKED,
            ATTENTION_PENDING,
            ATTENTION_PAUSED,
            ATTENTION_COVERED,
        )
    }
    fleet_policy_qs = Finding.objects.filter(
        tenant_id=1,
        status__in=_FINDING_ACTIVE_STATUSES,
        snoozed_until__isnull=True,
        finding_type__name__in=_SOFTWARE_DECISION_PROMPT_TYPES,
    )
    fleet_policy_count = fleet_policy_qs.count()
    fleet_summary_cards = [
        {
            "label": "Unresolved",
            "value": fleet_total,
            "note": "open, acknowledged, or paused Issues",
            "href": "?status=active",
            "tile_class": "tile-accent",
        },
        {
            "label": "Needs action",
            "value": fleet_counts[ATTENTION_NEEDS_ACTION],
            "note": "current evidence permits action",
            "href": "?status=active&attention=needs_action",
            "tile_class": "tile-alert",
        },
        {
            "label": "Blocked",
            "value": fleet_counts[ATTENTION_BLOCKED],
            "note": "a prerequisite prevents action",
            "href": "?status=active&attention=blocked",
            "tile_class": "tile-warn",
        },
        {
            "label": "Pending",
            "value": fleet_counts[ATTENTION_PENDING],
            "note": "assessment or source data is missing",
            "href": "?status=active&attention=pending",
            "tile_class": "tile-medium",
        },
        {
            "label": "Covered",
            "value": fleet_counts[ATTENTION_COVERED],
            "note": "already explained by another open Issue",
            "href": "?status=active&attention=covered",
            "tile_class": "tile-low",
        },
        {
            "label": "Paused",
            "value": fleet_counts[ATTENTION_PAUSED],
            "note": "paused by an operator",
            "href": "?status=paused",
            "tile_class": "tile-low",
        },
        {
            "label": "Software decisions",
            "value": fleet_policy_count,
            "note": "titles waiting for an approve or reject decision",
            "href": reverse("software_decisions_queue"),
            "tile_class": "tile-accent",
        },
    ]

    _SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    # Do not materialize the fleet queue merely to render collapsed group
    # headers. A Type/evidence selection opens rows; the unselected queue uses
    # database counts below and keeps the potentially very large finding set
    # out of Python memory.
    table_filter_keys = ("severity", "finding", "subject", "context", "status")
    table_filters = {
        key: (request.GET.get(f"table_{key}") or "").strip() for key in table_filter_keys
    }
    sort_key = request.GET.get("sort", "group")
    if sort_key not in {"group", "severity", "finding", "subject", "context", "status"}:
        sort_key = "group"
    sort_dir = request.GET.get("dir", "asc")
    if sort_dir not in {"asc", "desc"}:
        sort_dir = "asc"
    # Rendered labels are authoritative for operator sorting. Build database
    # expressions from those labels rather than ordering by condition keys,
    # UUIDs, or stored engine statuses.
    type_labels = {
        type_name: group["label"]
        for group in issue_type_groups.values()
        for type_name in group["types"]
    }
    issue_labels = {
        type_name: finding_registry.finding_type_name(type_name)
        for type_name in type_labels
    }

    def _label_case(labels: dict[str, str]):
        return Case(
            *[When(finding_type__name=key, then=Value(value)) for key, value in labels.items()],
            default=Value(""),
            output_field=CharField(),
        )

    type_label_expression = _label_case(type_labels)
    issue_label_expression = _label_case(issue_labels)
    severity_label_expression = Case(
        *[When(severity=value, then=Value(label)) for value, label in Finding.Severity.choices],
        default=Value(""),
        output_field=CharField(),
    )
    status_label_expression = Case(
        When(
            status__in=(Finding.Status.RESOLVED, Finding.Status.SUPPRESSED, Finding.Status.WONTFIX),
            then=Value("Resolved"),
        ),
        *[
            When(id__in=_state_ids(key), then=Value(label))
            for key, label in _STATE_LABELS.items()
        ],
        default=Value(""),
        output_field=CharField(),
    )
    device_name_expression = Coalesce(
        Subquery(
            Device.objects.filter(
                tenant_id=1,
                id=OuterRef("subject_id"),
                deleted_at__isnull=True,
            ).values("canonical_hostname")[:1],
            output_field=CharField(),
        ),
        Value("(unnamed device)"),
        output_field=CharField(),
    )
    subject_label_expression = Case(
        When(subject_type=Finding.SubjectType.DEVICE, then=device_name_expression),
        When(
            subject_type=Finding.SubjectType.CLIENT,
            then=Coalesce(F("client__display_name"), Value("(unnamed client)")),
        ),
        When(
            subject_type__in=(
                Finding.SubjectType.SOFTWARE_PRODUCT,
                Finding.SubjectType.SOFTWARE_VERSION,
            ),
            then=Coalesce(
                RawSQL("finding_details->>'canonical_name'", []),
                Value("(unnamed software)"),
            ),
        ),
        default=Value(""),
        output_field=CharField(),
    )
    identity_subject_expression = RawSQL(
        """
        COALESCE(
            (
                SELECT d.canonical_hostname
                 FROM operations.devices d
                 WHERE d.tenant_id = 1
                   AND d.deleted_at IS NULL
                   AND d.id::text IN (
                       SELECT jsonb_array_elements_text(
                           COALESCE(finding_details->'candidate_device_ids', '[]'::jsonb)
                       )
                   )
                   AND d.canonical_hostname = COALESCE(
                       finding_details->>'hostname',
                       finding_details->>'canonical_hostname'
                   )
                 ORDER BY d.created_at, d.id
                 LIMIT 1
            ),
            (
                SELECT d.canonical_hostname
                 FROM operations.devices d
                 WHERE d.tenant_id = 1
                   AND d.deleted_at IS NULL
                   AND d.id::text IN (
                       SELECT jsonb_array_elements_text(
                           COALESCE(finding_details->'candidate_device_ids', '[]'::jsonb)
                       )
                   )
                 ORDER BY d.created_at, d.id
                 LIMIT 1
            ),
            '(unnamed device)'
        )
        """,
        [],
    )
    hudu_subject_expression = RawSQL(
        """
        COALESCE(
            (
                SELECT CASE WHEN count(*) = 1 THEN max(d.canonical_hostname) END
                  FROM operations.v_device_source_link link
                  JOIN operations.devices d ON d.id = link.device_id
                  JOIN operations.sources source ON source.id = link.source_id
                 WHERE link.tenant_id = 1
                   AND d.deleted_at IS NULL
                   AND source.name = 'Hudu'
                   AND link.external_id = finding_details->>'asset_id'
            ),
            finding_details->>'name',
            'Hudu record'
        )
        """,
        [],
    )
    subject_label_expression = Case(
        When(finding_type__name="identity_conflict", then=identity_subject_expression),
        When(finding_type__name="cmdb_asset_stale", then=hudu_subject_expression),
        default=subject_label_expression,
        output_field=CharField(),
    )
    platform_suffix = Case(
        When(
            finding_type__name__in=("missing_required_platform", "stale_required_platform"),
            finding_details__platform__gt="",
            then=Concat(Value(": "), RawSQL("finding_details->>'platform'", [])),
        ),
        default=Value(""),
        output_field=CharField(),
    )
    offline_suffix = Case(
        When(
            finding_details__reason_suppressed="device_offline",
            then=Value(" (device offline)"),
        ),
        default=Value(""),
        output_field=CharField(),
    )
    issue_display_expression = Concat(
        issue_label_expression,
        platform_suffix,
        offline_suffix,
        output_field=CharField(),
    )
    detail_expression = RawSQL(
        """
        CASE
          WHEN finding_type_id = (SELECT id FROM operations.finding_types WHERE name = 'missing_required_platform')
            THEN 'missing ' || COALESCE(finding_details->>'platform', '?')
          WHEN finding_type_id = (SELECT id FROM operations.finding_types WHERE name = 'stale_required_platform')
            THEN 'stale ' || COALESCE(finding_details->>'platform', '?')
                 || CASE WHEN COALESCE(finding_details->>'gap_age_hours', finding_details->>'gap_hours') IS NOT NULL
                         THEN ' · ' || (COALESCE(finding_details->>'gap_age_hours', finding_details->>'gap_hours')) || 'h'
                         ELSE '' END
          WHEN finding_type_id = (SELECT id FROM operations.finding_types WHERE name = 'device_unenrolled')
            THEN COALESCE(finding_details->>'power_state', 'unknown')
                 || CASE WHEN finding_details->>'days_since_last_seen' IS NOT NULL
                        THEN ' · ' || (finding_details->>'days_since_last_seen') || 'd' ELSE '' END
                 || ' · via ' || COALESCE(finding_details->>'observed_via', 'tracked')
          WHEN finding_type_id = (SELECT id FROM operations.finding_types WHERE name = 'device_source_record_withdrawn')
            THEN 'removed from ' || COALESCE(finding_details->>'source', 'source')
                 || CASE WHEN finding_details->>'withdrawn_at' IS NOT NULL
                         THEN ' · ' || left(finding_details->>'withdrawn_at', 10) ELSE '' END
          WHEN finding_type_id = (SELECT id FROM operations.finding_types WHERE name = 'device_missing_from_source')
            THEN 'no current sources'
                 || CASE WHEN NULLIF(finding_details->>'last_source', '') IS NOT NULL
                         THEN ' · last: ' || (finding_details->>'last_source') ELSE '' END
                 || CASE WHEN NULLIF(finding_details->>'last_seen_at', '') IS NOT NULL
                         THEN ' · ' || left(finding_details->>'last_seen_at', 10) ELSE '' END
          WHEN finding_type_id IN (SELECT id FROM operations.finding_types WHERE name IN ('device_offline', 'device_long_offline'))
            THEN CASE
                    WHEN COALESCE(
                        finding_details->>'fully_offline_since',
                        finding_details->>'last_contact_at',
                        finding_details->>'last_seen_at'
                    ) IS NOT NULL
                    THEN 'fully offline since ' || left(COALESCE(
                        finding_details->>'fully_offline_since',
                        finding_details->>'last_contact_at',
                        finding_details->>'last_seen_at'
                    ), 10)
                    ELSE 'no source has contact'
                 END
                 || CASE WHEN NULLIF(finding_details->>'last_seen_source', '') IS NOT NULL
                         THEN ' (last: ' || (finding_details->>'last_seen_source') || ')' ELSE '' END
          WHEN finding_type_id = (SELECT id FROM operations.finding_types WHERE name = 'device_role_conflict')
            THEN COALESCE(finding_details->>'previous_role', '?') || ' → '
                 || COALESCE(finding_details->>'new_role', '?')
          WHEN finding_type_id = (SELECT id FROM operations.finding_types WHERE name = 'identity_conflict')
            THEN COALESCE(
                    CASE WHEN NULLIF(finding_details->>'candidate_count', '') IS NOT NULL
                         THEN (finding_details->>'candidate_count') || ' Computer records' END,
                    'possible duplicate Computer'
                 )
                 || CASE WHEN COALESCE(finding_details->>'evidence_summary', finding_details->>'match_signal') IS NOT NULL
                         THEN ' · ' || COALESCE(finding_details->>'evidence_summary', finding_details->>'match_signal') ELSE '' END
          WHEN finding_type_id = (SELECT id FROM operations.finding_types WHERE name = 'cmdb_asset_stale')
            THEN COALESCE(finding_details->>'name', 'Hudu record')
                 || CASE WHEN NULLIF(finding_details->>'layout', '') IS NOT NULL
                         THEN ' · ' || (finding_details->>'layout') ELSE '' END
                 || ' · linked source record is gone'
          WHEN finding_type_id = (SELECT id FROM operations.finding_types WHERE name = 'cross_client_serial')
            THEN CASE WHEN finding_details->>'device_count' IS NOT NULL
                            AND finding_details->>'client_count' IS NOT NULL
                            AND NULLIF(finding_details->>'serial', '') IS NOT NULL
                      THEN (finding_details->>'device_count') || ' devices across '
                           || (finding_details->>'client_count') || ' clients share serial '
                           || (finding_details->>'serial')
                      ELSE 'cross-client serial' END
          WHEN finding_type_id IN (SELECT id FROM operations.finding_types WHERE name LIKE 'windows_servicing_%%')
            THEN concat_ws(' · ',
                    NULLIF(finding_details->>'os_name', ''),
                    'build ' || COALESCE(finding_details->>'os_build_number', finding_details->>'build_number', '?'),
                    NULLIF(finding_details->>'cycle', ''),
                    CASE WHEN NULLIF(finding_details->>'security_support_ends_on', '') IS NOT NULL
                         THEN CASE WHEN finding_type_id IN (
                                  SELECT id FROM operations.finding_types WHERE name LIKE 'windows_servicing_%%_eol'
                              )
                              THEN 'support ended ' ELSE 'ends ' END
                              || (finding_details->>'security_support_ends_on') END
                 )
          WHEN finding_type_id IN (SELECT id FROM operations.finding_types WHERE name IN (
                'unauthorized_av', 'unauthorized_rmm', 'unauthorized_remote_access',
                'suspicious_name', 'install_path_suspicious', 'eol_runtime'
          ))
            THEN CASE WHEN NULLIF(finding_details->>'canonical_name', '') IS NOT NULL
                      THEN finding_details->>'canonical_name'
                           || CASE WHEN NULLIF(finding_details->>'publisher', '') IS NOT NULL
                                  THEN ' (' || (finding_details->>'publisher') || ')' ELSE '' END
                           || CASE WHEN COALESCE(
                                      NULLIF(finding_details->>'location', ''),
                                      NULLIF(finding_details->>'install_path', '')
                                  ) IS NOT NULL
                                   THEN ' @ ' || COALESCE(
                                      NULLIF(finding_details->>'location', ''),
                                      NULLIF(finding_details->>'install_path', '')
                                   ) ELSE '' END
                      ELSE COALESCE(finding_details->>'reason', '') END
          WHEN finding_type_id = (SELECT id FROM operations.finding_types WHERE name = 'multi_av_conflict')
            THEN COALESCE(
                    (SELECT string_agg(value, ', ')
                       FROM jsonb_array_elements_text(COALESCE(finding_details->'av_products', '[]'::jsonb)) value),
                    'multiple AV products'
                 )
          WHEN finding_type_id IN (SELECT id FROM operations.finding_types WHERE name IN ('rare_recent', 'whitelist_suggestion'))
            THEN COALESCE(NULLIF(concat_ws(' · ',
                    NULLIF(finding_details->>'canonical_name', ''),
                    NULLIF(finding_details->>'publisher', ''),
                    CASE WHEN COALESCE(finding_details->>'uncovered_device_count', finding_details->>'fleet_device_count') IS NOT NULL
                         THEN 'on ' || COALESCE(finding_details->>'uncovered_device_count', finding_details->>'fleet_device_count') || ' machine'
                              || CASE WHEN COALESCE(finding_details->>'uncovered_device_count', finding_details->>'fleet_device_count') <> '1' THEN 's' ELSE '' END
                              || CASE WHEN COALESCE((COALESCE(finding_details->>'uncovered_client_count', finding_details->>'client_count'))::int, 0) > 1
                                      THEN ' at ' || COALESCE(finding_details->>'uncovered_client_count', finding_details->>'client_count') || ' clients' ELSE '' END
                              || CASE WHEN (finding_details->>'uncovered_device_count')::int
                                           < (finding_details->>'fleet_device_count')::int
                                      THEN ' (' || (finding_details->>'fleet_device_count') || ' in the fleet)' ELSE '' END
                    END,
                    CASE WHEN finding_details->>'recent' = 'true' THEN 'first seen recently' END,
                    CASE WHEN COALESCE(finding_details->>'suggestion', 'none') <> 'none'
                         THEN 'suggested: ' || /*suggestion_label*/ END,
                    CASE WHEN jsonb_array_length(COALESCE(finding_details->'signals', '[]'::jsonb)) > 0
                         THEN 'signals: ' || replace((
                              SELECT string_agg(value, ', ')
                                FROM jsonb_array_elements_text(finding_details->'signals') value
                         ), '_', ' ') END
                 ), ''), COALESCE(finding_details->>'reason', 'undecided software'))
          WHEN finding_type_id = (SELECT id FROM operations.finding_types WHERE name = 'vulnerable_software')
            THEN COALESCE(finding_details->>'reason', 'matched vulnerability intelligence')
                 || CASE WHEN finding_details->>'worst_cvss' IS NOT NULL
                         THEN ' · CVSS ' || (finding_details->>'worst_cvss') ELSE '' END
                 || CASE WHEN jsonb_array_length(COALESCE(finding_details->'kev_cves', '[]'::jsonb)) > 0
                         THEN ' · KEV: ' || COALESCE((
                              SELECT string_agg(value, ', ')
                                FROM jsonb_array_elements_text(finding_details->'kev_cves') WITH ORDINALITY items(value, ord)
                               WHERE ord <= 3
                         ), '')
                         WHEN jsonb_array_length(COALESCE(finding_details->'high_cves', '[]'::jsonb)) > 0
                         THEN ' · high CVEs: ' || COALESCE((
                              SELECT string_agg(value, ', ')
                                FROM jsonb_array_elements_text(finding_details->'high_cves') WITH ORDINALITY items(value, ord)
                               WHERE ord <= 3
                         ), '')
                         ELSE '' END
          WHEN finding_type_id = (SELECT id FROM operations.finding_types WHERE name = 'known_malicious_hint')
            THEN CASE WHEN finding_details->>'threat_hit_count' IS NOT NULL
                      THEN (finding_details->>'threat_hit_count') || ' community threat-intel hit'
                           || CASE WHEN finding_details->>'threat_hit_count' <> '1' THEN 's' ELSE '' END
                      ELSE COALESCE(finding_details->>'reason', 'community threat-intel accumulation') END
          ELSE COALESCE(finding_details->>'platform', '')
        END
        """.replace("/*suggestion_label*/", _suggestion_label_sql()),
        [],
    )
    context_expression = RawSQL(
        """
        CASE
          WHEN finding_type_id IN (
              SELECT id FROM operations.finding_types WHERE name IN ('identity_conflict', 'cmdb_asset_stale')
          ) THEN COALESCE((SELECT display_name FROM operations.clients WHERE id = client_id), '')
          WHEN subject_type = 'device' THEN concat_ws(' · ',
              COALESCE(
                  (SELECT c.display_name FROM operations.devices d
                    JOIN operations.clients c ON c.id = d.client_id
                   WHERE d.tenant_id = 1 AND d.deleted_at IS NULL AND d.id = subject_id),
                  (SELECT display_name FROM operations.clients WHERE id = client_id)
              ),
              NULLIF(concat_ws(' ',
                  COALESCE(
                      NULLIF(finding_details->>'os_name', ''),
                      (SELECT NULLIF(os_name, '')
                         FROM operations.device_windows_servicing_current
                        WHERE tenant_id = 1 AND device_id = subject_id),
                      (SELECT NULLIF(os_name, '') FROM operations.devices
                        WHERE tenant_id = 1 AND deleted_at IS NULL AND id = subject_id)
                  ),
                  (SELECT NULLIF(os_release_id, '')
                     FROM operations.device_windows_servicing_current
                    WHERE tenant_id = 1 AND device_id = subject_id),
                  COALESCE(
                      NULLIF(finding_details->>'os_build_number', ''),
                      NULLIF(finding_details->>'build_number', ''),
                      (SELECT NULLIF(os_build_number, '')
                         FROM operations.device_windows_servicing_current
                        WHERE tenant_id = 1 AND device_id = subject_id)
                  )
              ), ''),
              (SELECT 'online via ' || array_to_string(online_sources, ', ')
                 FROM operations.device_session_current
                WHERE device_id = subject_id AND array_length(online_sources, 1) > 0)
          )
          WHEN subject_type = 'client' THEN concat_ws(' · ',
              COALESCE((SELECT display_name FROM operations.clients WHERE id = client_id), ''),
              'client-wide'
          )
          WHEN subject_type IN ('software_product', 'software_version') THEN concat_ws(' · ',
              NULLIF(finding_details->>'publisher', ''),
              CASE WHEN subject_type = 'software_version' THEN 'software release' ELSE 'software title' END
          )
          ELSE 'platform or source context'
        END
        """,
        [],
        output_field=CharField(),
    )
    evidence_date_expression = Case(
        When(
            finding_type__name="device_missing_from_source",
            then=RawSQL("NULLIF(finding_details->>'last_seen_at', '')::timestamptz", []),
        ),
        When(
            finding_type__name="device_source_record_withdrawn",
            then=RawSQL("NULLIF(finding_details->>'withdrawn_at', '')::timestamptz", []),
        ),
        default=Value(None),
    )
    evidence_context_expression = Case(
        When(
            finding_type__name="device_missing_from_source",
            then=Concat(
                Value("Last source evidence: "),
                Func(
                    evidence_date_expression,
                    Value("YYYY-MM-DD HH24:MI"),
                    function="TO_CHAR",
                    output_field=CharField(),
                ),
            ),
        ),
        When(
            finding_type__name="device_source_record_withdrawn",
            then=Concat(
                Value("Source withdrawn: "),
                Func(
                    evidence_date_expression,
                    Value("YYYY-MM-DD HH24:MI"),
                    function="TO_CHAR",
                    output_field=CharField(),
                ),
            ),
        ),
        default=Value(""),
        output_field=CharField(),
    )
    # Context is the operator's supporting information: the condition detail,
    # environment/source context, and a relevant source-lifecycle timestamp.
    # Keep this database expression aligned with _display_row below so column
    # filtering and ordering use the text actually displayed in the table.
    display_context_expression = Func(
        Value(" · "),
        Func(detail_expression, Value(""), function="NULLIF"),
        Func(context_expression, Value(""), function="NULLIF"),
        Func(evidence_context_expression, Value(""), function="NULLIF"),
        function="CONCAT_WS",
        output_field=CharField(),
    )
    database_sort_fields = {
        "group": (type_label_expression, issue_display_expression, "id"),
        "severity": (severity_label_expression, "id"),
        "finding": (issue_display_expression, type_label_expression, "id"),
        "subject": (subject_label_expression, "id"),
        "context": (display_context_expression, "id"),
        "status": (status_label_expression, "id"),
    }
    database_annotations = {
        "rendered_group": type_label_expression,
        "rendered_severity": severity_label_expression,
        "rendered_finding": issue_display_expression,
        "rendered_subject": subject_label_expression,
        "rendered_context": display_context_expression,
        "rendered_status": status_label_expression,
    }
    # The display rows below derive these labels in Python. Do not select every
    # expensive rendered expression for a normal page or CSV export: only a
    # requested column filter needs its database annotation. This keeps the
    # full-fleet export from evaluating Context SQL for every row
    # merely to sort by the default group label.
    database_qs = actionable_qs
    for key in table_filter_keys:
        value = table_filters[key]
        if value:
            database_qs = database_qs.annotate(
                **{f"rendered_{key}": database_annotations[f"rendered_{key}"]}
            ).filter(**{f"rendered_{key}__icontains": value})
    database_query_mode = sort_key in database_sort_fields
    database_page_mode = show_finding_rows and not wants_csv(request) and database_query_mode
    database_page = None
    findings = []
    if show_finding_rows:
        if database_page_mode:
            # A single-condition Type (or a selected individual Issue) has
            # the same displayed group and issue label on every row. Ordering
            # those rows by the expensive rendered issue SQL is pure work; a
            # stable ID is the valid tie-breaker and keeps Type drilldowns
            # responsive.
            single_condition_scope = bool(issue_filter) or (
                bool(selected_type) and len(selected_type["types"]) == 1
            )
            fields = (
                ("id",)
                if sort_key == "group" and single_condition_scope
                else database_sort_fields[sort_key]
            )
            order = []
            for field in fields:
                expression = F(field) if isinstance(field, str) else field
                order.append(
                    expression.desc(nulls_last=True)
                    if sort_dir == "desc"
                    else expression.asc(nulls_last=True)
                )
            if (
                sort_key == "group"
                and selected_type
                and set(selected_type["types"]) <= set(_SOFTWARE_DECISION_PROMPT_TYPES)
            ):
                # Undecided software: the most widespread title first.
                order = [
                    Cast(
                        Coalesce(
                            KeyTextTransform("uncovered_device_count", "finding_details"),
                            KeyTextTransform("fleet_device_count", "finding_details"),
                        ),
                        IntegerField(),
                    ).desc(nulls_last=True),
                    F("id").asc(),
                ]
            database_page = Paginator(database_qs.order_by(*order), 50).get_page(
                request.GET.get("page")
            )
            findings = list(database_page.object_list)
        elif database_query_mode:
            order = []
            for field in database_sort_fields[sort_key]:
                expression = F(field) if isinstance(field, str) else field
                order.append(
                    expression.desc(nulls_last=True)
                    if sort_dir == "desc"
                    else expression.asc(nulls_last=True)
                )
            findings = list(database_qs.order_by(*order))
        else:
            # CSV and rendered-cell filters require their complete selected
            # scope; ordinary group browsing uses the database paginator above.
            findings = sorted(
                actionable_qs,
                key=lambda f: (
                    _SEVERITY_ORDER.get(f.severity, 9),
                    -(f.last_detected_at or f.last_seen_at).timestamp(),
                ),
            )

    # Per-device map of platforms whose latest source-reported state is online.
    # Freshness is deliberately separate from this state and remains available
    # on the device detail surface.
    all_display_findings = findings
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
        if name == "device_source_record_withdrawn":
            source = d.get("source") or "source"
            withdrawn_at = d.get("withdrawn_at")
            return f"removed from {source}" + (f" · {withdrawn_at[:10]}" if withdrawn_at else "")
        if name == "device_missing_from_source":
            source = d.get("last_source")
            last_seen_at = d.get("last_seen_at")
            pieces = ["no current sources"]
            if source:
                pieces.append(f"last: {source}")
            if last_seen_at:
                pieces.append(last_seen_at[:10])
            return " · ".join(pieces)
        if name in ("device_offline", "device_long_offline"):
            since = (
                d.get("fully_offline_since") or d.get("last_contact_at") or d.get("last_seen_at")
            )
            last_src = d.get("last_seen_source")
            base = f"fully offline since {since[:10]}" if since else "no source has contact"
            return f"{base} (last: {last_src})" if last_src else base
        if name == "device_role_conflict":
            return f"{d.get('previous_role', '?')} → {d.get('new_role', '?')}"
        if name == "identity_conflict":
            count = d.get("candidate_count")
            signal = d.get("evidence_summary") or d.get("match_signal")
            pieces = [f"{count} Computer records" if count else "possible duplicate Computer"]
            if signal:
                pieces.append(signal)
            return " · ".join(pieces)
        if name == "cmdb_asset_stale":
            asset = d.get("name") or "Hudu record"
            layout = d.get("layout")
            return (
                f"{asset}" + (f" · {layout}" if layout else "") + " · linked source record is gone"
            )
        if name == "cross_client_serial":
            devices = d.get("device_count")
            clients = d.get("client_count")
            serial = d.get("serial")
            if devices and clients and serial:
                return f"{devices} devices across {clients} clients share serial {serial}"
            return "cross-client serial"
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
        if name in ("rare_recent", "whitelist_suggestion"):
            return _software_review_context(d)
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
            device_id: {
                "hostname": hostname,
                "os_name": os_name,
                "client_slug": client_slug,
                "client_name": client_name,
            }
            for device_id, hostname, os_name, client_slug, client_name in Device.objects.filter(
                tenant_id=1,
                id__in=device_subject_ids,
                deleted_at__isnull=True,
            ).values_list(
                "id",
                "canonical_hostname",
                "os_name",
                "client__slug",
                "client__display_name",
            )
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
            "os_name": details.get("os_name")
            or current.get("os_name")
            or device.get("os_name", ""),
            "os_release_id": details.get("os_release_id") or current.get("os_release_id", ""),
            "os_build_number": details.get("os_build_number")
            or details.get("build_number")
            or current.get("os_build_number", ""),
            "client_slug": device.get("client_slug", ""),
            "client_name": device.get("client_name", ""),
        }

    def _subject_display_name(f: Finding) -> str | None:
        return _device_context(f).get("hostname") or None

    # A stale Hudu record has no resolved *external* source link, but its own
    # Hudu source link should still identify the Operations Computer. Use that
    # relationship as the subject link; never substitute a name-only guess.
    stale_asset_ids = {
        str((finding.finding_details or {}).get("asset_id"))
        for finding in all_display_findings
        if finding.finding_type.name == "cmdb_asset_stale"
        and (finding.finding_details or {}).get("asset_id")
    }
    hudu_devices_by_asset: dict[str, list[Device]] = {}
    if stale_asset_ids:
        for link in DeviceSourceLink.objects.filter(
            tenant_id=1,
            source__name="Hudu",
            external_id__in=stale_asset_ids,
            device__deleted_at__isnull=True,
        ).select_related("device", "device__client"):
            hudu_devices_by_asset.setdefault(link.external_id, []).append(link.device)
    may_archive_hudu = ARCHIVE_HUDU_ASSETS in available_finding_actions(request.user)
    client_name_conflict_sources = {
        (finding.finding_details or {}).get("source_id")
        for finding in all_display_findings
        if finding.finding_type.name == "client_name_conflict"
        and (finding.finding_details or {}).get("source_id") is not None
    }
    source_names_by_id = {
        source_id: name
        for source_id, name in Source.objects.filter(
            id__in=client_name_conflict_sources
        ).values_list("id", "name")
    }

    def _display_row(f: Finding) -> dict:
        details = f.finding_details or {}
        device_context = _device_context(f)
        online_sources = online_map.get(str(f.subject_id)) if f.subject_id else None
        subject_label = ""
        subject_url = ""
        context_parts: list[str] = []

        if f.subject_type == Finding.SubjectType.DEVICE:
            subject_label = device_context.get("hostname") or "(unnamed device)"
            if device_context.get("client_slug") and f.subject_id:
                subject_url = reverse(
                    "device_detail",
                    kwargs={"org_slug": device_context["client_slug"], "device_id": f.subject_id},
                )
            if device_context.get("client_name"):
                context_parts.append(device_context["client_name"])
            elif f.client:
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
            if f.finding_type.name == "client_name_conflict":
                source_name = source_names_by_id.get(details.get("source_id"), "Source")
                observed_name = details.get("observed_name") or "(unnamed group)"
                # Each finding is one source group; name it first, then the
                # names the client's other sources use.
                other_names = [
                    str(name).strip()
                    for name in (details.get("peer_source_names") or [])
                    if str(name).strip() and str(name).strip() != observed_name
                ]
                context_parts.append(f"{source_name} reports “{observed_name}”")
                if other_names:
                    context_parts.append("other sources: " + ", ".join(other_names))
            else:
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
        elif f.subject_type in {
            Finding.SubjectType.SOURCE_BINDING,
            Finding.SubjectType.COLLECTOR_INSTANCE,
        }:
            subject_label = "Source health"
            subject_url = reverse("sources_status")
            context_parts.append("platform health")
        else:
            subject_label = f.get_subject_type_display()
            context_parts.append("platform or source context")

        # Identity conflicts are stored against the client because the
        # finding represents a hostname collision, but their evidence names
        # the actual Computers. If a hostname is available, make the visible
        # Computer subject drill into that Computer rather than the client.
        if f.finding_type.name == "identity_conflict" and f.client:
            candidate_ids = details.get("candidate_device_ids") or []
            candidates = list(
                Device.objects.filter(
                    tenant_id=1,
                    client_id=f.client_id,
                    id__in=candidate_ids,
                    deleted_at__isnull=True,
                ).order_by("created_at", "id")
            )
            hostname = details.get("hostname") or details.get("canonical_hostname")
            device = next(
                (item for item in candidates if hostname and item.canonical_hostname == hostname),
                candidates[0] if candidates else None,
            )
            if device:
                subject_label = device.canonical_hostname or "Unnamed Computer"
                subject_url = reverse(
                    "device_detail",
                    kwargs={"org_slug": device.client.slug, "device_id": device.id},
                )
                context_parts = [f.client.display_name]

        related_device = None
        hudu_url = ""
        if f.finding_type.name == "cmdb_asset_stale":
            # The database subject remains the client because Hudu evidence is
            # not a canonical Operations subject. The visible subject is the
            # linked Computer, while the Hudu URL is retained as evidence.
            hudu_url = details.get("url") or ""
            context_parts = [f.client.display_name] if f.client else []
            candidates = hudu_devices_by_asset.get(str(details.get("asset_id")), [])
            if len(candidates) == 1:
                device = candidates[0]
                subject_label = device.canonical_hostname or "Unnamed Computer"
                subject_url = reverse(
                    "device_detail",
                    kwargs={"org_slug": device.client.slug, "device_id": device.id},
                )
                related_device = {
                    "label": device.canonical_hostname,
                    "url": subject_url,
                }
            else:
                subject_label = details.get("name") or "Hudu record"

        evidence_date = None
        if f.finding_type.name == "device_missing_from_source":
            raw_evidence_date = details.get("last_seen_at")
            evidence_label = "Last source evidence"
        elif f.finding_type.name == "device_source_record_withdrawn":
            raw_evidence_date = details.get("withdrawn_at")
            evidence_label = "Source withdrawn"
        else:
            raw_evidence_date = None
            evidence_label = ""
        if isinstance(raw_evidence_date, datetime):
            evidence_date = raw_evidence_date
        elif isinstance(raw_evidence_date, str):
            evidence_date = parse_datetime(raw_evidence_date)
        if detail := _detail_string(f):
            context_parts.insert(0, detail)
        if evidence_date:
            context_parts.append(f"{evidence_label}: {evidence_date.strftime('%Y-%m-%d %H:%M')}")

        return {
            "f": f,
            "online_sources": online_sources,
            "subject_hostname": _subject_display_name(f),
            "device_context": device_context,
            "subject_label": subject_label,
            "subject_url": subject_url,
            "review_url": reverse("finding_review", kwargs={"finding_id": f.id}),
            "related_device": related_device,
            "hudu_url": hudu_url,
            "archive_action": (f.finding_type.name == "cmdb_asset_stale" and may_archive_hudu),
            "context": " · ".join(context_parts),
            "canonical_name": details.get("canonical_name", ""),
            "publisher": details.get("publisher", ""),
            "fleet_device_count": software_coverage.prompt_devices(details),
            "threshold": details.get("threshold"),
            # Undecided software is decided in bulk on the review page, which
            # groups titles by publisher and offers title and publisher options.
            "publisher_review_url": (
                reverse("software_decisions_queue")
                + "?"
                + urlencode({"q": details.get("publisher") or details.get("canonical_name") or ""})
                if f.finding_type.name in ("rare_recent", "whitelist_suggestion")
                else ""
            ),
        }

    operator_states = _condition_operator_states([f.id for f in findings])
    findings_with_detail = [_display_row(f) for f in findings]
    assessments = _condition_assessment_display(
        "entity", (row["f"].id for row in findings_with_detail)
    )
    for row in findings_with_detail:
        row["assessment"] = assessments.get(str(row["f"].id))
        projected = operator_state(
            status=row["f"].status,
            snoozed_until=row["f"].snoozed_until,
            assessment=row["assessment"],
            now=timezone.now(),
        )
        governed_state = operator_states.get(str(row["f"].id))
        row["operator_status"] = governed_state["status"] if governed_state else projected["status"]
        row["operator_status_label"] = OPERATOR_STATUS_LABELS[row["operator_status"]]
        row["operator_attention"] = (
            governed_state["attention"] if governed_state else projected["attention"]
        )
        row["operator_reason"] = (
            governed_state.get("reason", projected["reason"])
            if governed_state
            else projected["reason"]
        )
        if (
            row["operator_attention"] == ATTENTION_PENDING
            and row["operator_reason"] == "Ready for action"
        ):
            row["operator_reason"] = "Pending current assessment"
        elif (
            row["operator_attention"] == ATTENTION_BLOCKED
            and row["operator_reason"] == "Ready for action"
        ):
            row["operator_reason"] = "Blocked by current evidence"
        row["work_status_label"] = (
            OPERATOR_ATTENTION_LABELS.get(row["operator_attention"]) or row["operator_status_label"]
        )
        # The normal state explanation merely repeats the work status (for
        # example, "Needs action — Ready for action"). Keep a note only when
        # it carries additional, operator-useful information.
        row["operator_status_note"] = {
            "Pending current assessment": "Waiting for new information.",
        }.get(
            row["operator_reason"],
            ""
            if row["operator_reason"]
            in {
                "Ready for action",
                "Blocked by current evidence",
                "Paused by operator",
            }
            else row["operator_reason"],
        )
        row["critical_finding_id"] = (
            governed_state.get("critical_finding_id") if governed_state else ""
        )
        row["refresh_available"] = row["operator_attention"] == ATTENTION_PENDING
        row["refresh_title"] = "Refresh the relevant current information for this Issue"
        row["refresh_available"] = row["operator_attention"] == ATTENTION_PENDING
        row["refresh_title"] = "Refresh the most relevant current information for this Issue"

    covered_counts = _covered_counts_by_parent(row["f"].id for row in findings_with_detail)
    for row in findings_with_detail:
        counts = covered_counts.get(str(row["f"].id))
        row["covered_count"] = counts["n"] if counts else 0
        row["covered_high"] = counts["high"] if counts else 0
        # A finding that covers others is shown at the highest severity of what it covers.
        # Display only: the stored severity and the sort order do not change.
        top = counts["top"] if counts else None
        own = row["f"].severity
        row["severity_shown"] = (
            top if top and _SEVERITY_RANK.get(top, 0) > _SEVERITY_RANK.get(own, 0) else ""
        )

    # A duplicate-Computer Finding carries the whole collision group.  Resolve
    # the IDs once here so operators can inspect or compare the actual
    # Computers from the finding, without being sent to a separate queue.
    duplicate_ids: set[uuid.UUID] = set()
    for row in findings_with_detail:
        if row["f"].finding_type.name != "identity_conflict":
            continue
        for candidate_id in (row["f"].finding_details or {}).get("candidate_device_ids", []):
            try:
                duplicate_ids.add(uuid.UUID(str(candidate_id)))
            except (ValueError, TypeError):
                continue
    duplicate_devices = {
        device.id: device
        for device in Device.objects.filter(
            tenant_id=1,
            id__in=duplicate_ids,
            deleted_at__isnull=True,
        ).select_related("client")
    }
    for row in findings_with_detail:
        finding = row["f"]
        if finding.finding_type.name != "identity_conflict":
            continue
        candidates = []
        for candidate_id in (finding.finding_details or {}).get("candidate_device_ids", []):
            try:
                device = duplicate_devices.get(uuid.UUID(str(candidate_id)))
            except (ValueError, TypeError):
                device = None
            if not device or not device.client:
                continue
            candidates.append(
                {
                    "id": device.id,
                    "label": device.canonical_hostname or "Unnamed Computer",
                    "url": reverse(
                        "device_detail",
                        kwargs={"org_slug": device.client.slug, "device_id": device.id},
                    ),
                    "compare_url": (
                        reverse(
                            "device_merge",
                            kwargs={
                                "org_slug": device.client.slug,
                                "device_id": finding.subject_id,
                                "target_id": device.id,
                            },
                        )
                        if device.id != finding.subject_id
                        else ""
                    ),
                }
            )
        row["duplicate_candidates"] = candidates

    patch_activity_threshold = get_device_status_policy()["patch_activity_days"]

    def _patching_inactive_label(details: dict) -> str:
        """Show the age of stale patch evidence without making it policy state."""
        observed_at = details.get("last_patch_seen_at") or details.get("last_patch_activity_at")
        if isinstance(observed_at, str):
            observed_at = parse_datetime(observed_at)
        if isinstance(observed_at, datetime):
            if timezone.is_naive(observed_at):
                observed_at = timezone.make_aware(observed_at, dt_timezone.utc)
            age_days = max(1, (timezone.now() - observed_at).days)
            return f"Patching inactive ({age_days}d)"
        return f"Patching inactive ({patch_activity_threshold}d+)"

    # Resolve operator labels before both HTML and CSV rendering. CSV must
    # use the same taxonomy projection as the page and cannot rely on fields
    # added later in the response path.
    for row in findings_with_detail:
        row["issue_label"] = finding_registry.finding_type_name(row["f"].finding_type.name)
        if row["f"].finding_type.name == "patching_stalled":
            row["issue_label"] = _patching_inactive_label(row["f"].finding_details or {})
        type_group = next(
            (
                group
                for group in issue_type_groups.values()
                if row["f"].finding_type.name in group["types"]
            ),
            None,
        )
        category_group = next(
            (
                category
                for category in issue_categories
                if row["f"].finding_type.name in category["types"]
            ),
            None,
        )
        row["issue_type_key"] = type_group["value"] if type_group else ""
        row["issue_type_label"] = type_group["label"] if type_group else "Unclassified issue"
        row["issue_category_key"] = category_group["key"] if category_group else ""
        row["issue_category_label"] = (
            category_group["label"] if category_group else "Unclassified issue"
        )
        row["issue_display_label"] = row["issue_label"]
        details = row["f"].finding_details or {}
        if details.get("platform") and row["f"].finding_type.name in {
            "missing_required_platform",
            "stale_required_platform",
        }:
            row["issue_display_label"] += f": {details['platform']}"
        if details.get("reason_suppressed") == "device_offline":
            row["issue_display_label"] += " (device offline)"

    def _findings_csv_response():
        return csv_response(
            findings_with_detail,
            columns=[
                ("Severity", lambda r: r["f"].severity),
                ("Type", lambda r: r["issue_type_label"]),
                ("Issue", lambda r: r["issue_label"]),
                ("Category", lambda r: r["issue_category_label"]),
                ("Client", lambda r: (r["f"].client.display_name if r["f"].client else "")),
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
                    lambda r: (r["f"].finding_details or {}).get("security_support_ends_on", ""),
                ),
                ("Context", "context"),
                ("Online sources", "online_sources"),
                ("Status", "work_status_label"),
                ("Details", "operator_status_note"),
                ("Confidence", lambda r: r["f"].confidence),
                ("First seen", lambda r: r["f"].first_seen_at),
                ("Last seen", lambda r: r["f"].last_seen_at),
                ("Last detected", lambda r: r["f"].last_detected_at),
                ("Snoozed until", lambda r: r["f"].snoozed_until),
            ],
            filename_stem="findings",
        )

    # Keep these getters as a parity reference for the database annotations
    # above. Database filtering and ordering must remain equivalent to the
    # operator-visible table text.
    table_filter_specs = (
        ("severity", lambda row: row["f"].get_severity_display()),
        ("finding", lambda row: row["issue_display_label"]),
        ("subject", lambda row: row["subject_label"]),
        ("context", lambda row: row["context"]),
        ("status", lambda row: row["work_status_label"]),
    )
    table_filters = {
        key: (request.GET.get(f"table_{key}") or "").strip() for key, _getter in table_filter_specs
    }

    def _table_value(value):
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.isoformat(sep=" ")
        return str(value)

    if not database_query_mode:
        findings_with_detail = [
            row
            for row in findings_with_detail
            if all(
                not table_filters[key]
                or table_filters[key].casefold() in _table_value(getter(row)).casefold()
                for key, getter in table_filter_specs
            )
        ]
    # A findings CSV needs the fully projected and filtered row set, but not
    # the page-only affected-device summary or collapsed group navigation.
    # Return before those fleet-wide follow-up queries and aggregations.
    if request.GET.get("format") == "csv":
        return _findings_csv_response()
    matching_ids = [row["f"].id for row in findings_with_detail]
    matching_qs = qs.filter(id__in=matching_ids)
    total_matching = (
        database_qs.count()
        if database_query_mode
        else len(findings_with_detail)
        if show_finding_rows
        else qs.count()
    )
    response_matching = total_matching
    actionable_matching = total_matching
    matching_qs = (
        database_qs if database_query_mode else (qs if not show_finding_rows else matching_qs)
    )
    # The collapsed default queue has no rows selected for review. Do not
    # expand its entire Finding population through the software-exposure view
    # merely to calculate an affected-Computer rollup that is not actionable
    # until a Type is opened. A selected Type and the explicit device CSV
    # retain the complete rollup.
    # This fleet-wide expansion is useful only for the explicit device CSV.
    # Do not make routine Type browsing wait for it; the Issue rows themselves
    # are already the actionable review surface.
    needs_affected_devices = request.GET.get("format") == "devices_csv"
    affected_devices = _affected_device_rows(matching_qs) if needs_affected_devices else []
    affected_client_count = len({row["client"] for row in affected_devices if row["client"]})
    result_summary_parts = [f"{total_matching} issue rows"]
    if needs_affected_devices:
        result_summary_parts.extend(
            [
                f"{len(affected_devices)} affected Computers",
                f"{affected_client_count} affected clients",
            ]
        )
    else:
        result_summary_parts.append("choose a Type to review affected Computers")
    current_result_summary = " · ".join(result_summary_parts)

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
    if needs_per_finding_states:
        state_counts_by_type = _state_counts_for(database_qs)
    else:
        state_counts_by_type = {
            finding_type_name: {
                state: counts.get(state, 0) for state in ("needs_action", "blocked", "pending")
            }
            for finding_type_name, counts in fleet_state_counts_by_type.items()
        }
    current_type_counts = {}
    for row in findings_with_detail:
        current_type_counts[row["f"].finding_type.name] = (
            current_type_counts.get(row["f"].finding_type.name, 0) + 1
        )
    if not show_finding_rows or database_query_mode:
        current_type_counts = {
            row["finding_type__name"]: row["n"]
            for row in database_qs.values("finding_type__name").annotate(n=Count("id"))
        }

    # Pending source identities need an explicit human decision. Include them
    # in the same type count as the registered identity-resolution condition
    # so the Issues navigation does not hide an active review queue merely
    # because those records have no invented canonical Finding subject.
    pending_entity_candidate_count = EntityCandidate.objects.filter(
        tenant_id=1,
        status=EntityCandidate.Status.PENDING,
    ).count()
    if pending_entity_candidate_count:
        current_type_counts["identity_resolution_pending"] = (
            current_type_counts.get("identity_resolution_pending", 0)
            + pending_entity_candidate_count
        )
        candidate_state_counts = state_counts_by_type.setdefault(
            "identity_resolution_pending",
            {"needs_action": 0, "blocked": 0, "pending": 0},
        )
        candidate_state_counts["needs_action"] += pending_entity_candidate_count

    # Admin-owned conditions are still Issues.  They retain their separate
    # storage and admin-only controls, but must not disappear from the common
    # operator taxonomy or make a selected policy type appear empty.
    admin_count_qs = AdminFinding.objects.filter(tenant_id=1)
    if status_filter in ("", "active"):
        admin_count_qs = admin_count_qs.filter(status__in=_FINDING_ACTIVE_STATUSES)
    elif status_filter == "open":
        admin_count_qs = admin_count_qs.filter(status="open")
    elif status_filter == "acknowledged":
        admin_count_qs = admin_count_qs.filter(status__in=("acknowledged", "investigating"))
    elif status_filter == "resolved":
        admin_count_qs = admin_count_qs.filter(status__in=("resolved", "suppressed", "wontfix"))
    if severity_filter:
        admin_count_qs = admin_count_qs.filter(severity=severity_filter)
    admin_type_counts = {
        row["finding_type__name"]: row["n"]
        for row in admin_count_qs.values("finding_type__name").annotate(n=Count("id"))
    }
    for finding_type_name, count in admin_type_counts.items():
        current_type_counts[finding_type_name] = (
            current_type_counts.get(finding_type_name, 0) + count
        )

    selected_admin_types = set()
    if category_filter:
        selected_admin_types.update(
            next(
                (item["types"] for item in issue_categories if item["key"] == category_filter),
                set(),
            )
        )
    if type_filter:
        selected_admin_types = set(issue_type_groups.get(type_filter, {}).get("types", set()))
    if issue_filter:
        selected_admin_types = {issue_filter}
    admin_findings = []
    if selected_admin_types:
        admin_rows = (
            admin_count_qs.filter(finding_type__name__in=selected_admin_types)
            .select_related("finding_type")
            .order_by("-last_detected_at")[:200]
        )
        # One client candidate can collect several source groups.  Index its
        # durable evidence keys so the Issue opens the audited match decision,
        # not the old parallel queue.
        client_candidates_by_source_record: dict[tuple[str, str], ClientCandidate] = {}
        if any(finding.finding_type.name == "client_unattached_group" for finding in admin_rows):
            for candidate in ClientCandidate.objects.filter(
                tenant_id=1,
                status=ClientCandidate.Status.OPEN,
            ):
                for source_ref in candidate.source_refs or []:
                    source_id = source_ref.get("source_id")
                    external_id = source_ref.get("external_id")
                    if source_id is not None and external_id:
                        client_candidates_by_source_record[(str(source_id), str(external_id))] = candidate
        source_ids = {
            (finding.subject_ref or {}).get("source_id")
            for finding in admin_rows
            if (finding.subject_ref or {}).get("source_id") is not None
        }
        source_names_by_id = {
            str(source_id): name
            for source_id, name in Source.objects.filter(id__in=source_ids).values_list(
                "id", "name"
            )
        }
        client_ids = {
            ref.get("client_id")
            for finding in admin_rows
            if (ref := (finding.subject_ref or {})).get("client_id")
        }
        clients_by_id = {
            str(client.id): client
            for client in Client.objects.filter(
                tenant_id=1, id__in=client_ids, deleted_at__isnull=True
            ).only("id", "slug", "display_name")
        }
        client_references_by_id: dict[str, list[dict]] = {}
        if any(finding.finding_type.name == "client_name_conflict" for finding in admin_rows):
            for reference in client_source_references():
                client_references_by_id.setdefault(str(reference["client_id"]), []).append(
                    reference
                )
        for finding in admin_rows:
            ref = finding.subject_ref or {}
            details = finding.details or {}
            client = clients_by_id.get(str(ref.get("client_id")))
            source_name = details.get("source") or source_names_by_id.get(
                str(ref.get("source_id")), ""
            )
            source_reference = ref.get("external_id") or " · ".join(
                details.get("external_ids") or []
            )
            if finding.finding_type.name == "source_failure":
                source_reference = details.get("reason") or "Collection needs attention"
            references = client_references_by_id.get(str(ref.get("client_id")), [])
            matching_reference = next(
                (
                    reference
                    for reference in references
                    if reference["source_name"] == source_name
                    and reference["external_id"] == source_reference
                ),
                None,
            )
            reported_name = (
                (matching_reference or {}).get("observed_name")
                or ref.get("observed_name")
                or "(not reported)"
            )

            conflicting_references = [
                reference
                for reference in references
                if matching_reference
                and reference["source_name"] != matching_reference["source_name"]
                and reference["observed_name"]
                and reference["observed_name"] != reported_name
            ]
            candidate = client_candidates_by_source_record.get(
                (str(ref.get("source_id") or ""), str(ref.get("external_id") or ""))
            )
            if finding.finding_type.name == "source_failure":
                resolution_url = reverse("sources_status")
                resolution_label = "View source"
            elif candidate:
                resolution_url = reverse(
                    "client_candidate_detail", kwargs={"candidate_id": candidate.id}
                )
                resolution_label = "Review match"
            elif matching_reference and client is not None:
                # The mapping decision for a known client is made on its page.
                resolution_url = (
                    f"{reverse('org_index', kwargs={'org_slug': client.slug})}#source-references"
                )
                resolution_label = "Decide on the client page"
            elif matching_reference:
                resolution_url = (
                    f"{reverse('client_mappings')}?"
                    f"{urlencode({'source_link_id': matching_reference['source_link_id']})}"
                )
                resolution_label = "Review source record"
            else:
                resolution_url = f"{reverse('findings_admin_health')}?type={finding.finding_type.name}"
                resolution_label = "View technical detail"
            admin_findings.append(
                {
                    "finding": finding,
                    "type_label": next(
                        (
                            group["label"]
                            for group in issue_type_groups.values()
                            if finding.finding_type.name in group["types"]
                        ),
                        finding.finding_type.name,
                    ),
                    "issue_label": finding_registry.finding_type_name(finding.finding_type.name),
                    "client_name": (
                        client.display_name
                        if client
                        else ref.get("client_display_name") or "(unmapped client)"
                    ),
                    "client_url": (
                        reverse("org_index", kwargs={"org_slug": client.slug}) if client else ""
                    ),
                    "observed_name": reported_name,
                    "conflicting_references": conflicting_references,
                    "source_name": source_name,
                    "source_reference": source_reference,
                    "admin_url": resolution_url,
                    "admin_label": resolution_label,
                }
            )

    # A pending generic candidate is a human decision, whereas an
    # ``observed_only`` candidate is simply retained source evidence.  The
    # latter must not become a second, noisy work queue.  Pending candidates
    # have no artificial Finding subject: a source identity is not a
    # canonical entity.  They are nevertheless part of the operator's one
    # Issues inbox and lead to the existing audited decision surface.
    entity_candidate_items = []
    if "identity_resolution_pending" in selected_admin_types:
        candidate_qs = EntityCandidate.objects.filter(
            tenant_id=1,
            status=EntityCandidate.Status.PENDING,
        )
        if client_filter:
            candidate_qs = candidate_qs.filter(client__slug=client_filter)
        for candidate in (
            candidate_qs.select_related("client", "proposed_entity_class", "source_instance__source")
            .order_by("-last_observed_at")[:200]
        ):
            entity_candidate_items.append(
                {
                    "id": candidate.id,
                    "source": candidate.source_instance.source.name,
                    "record_type": candidate.external_namespace,
                    "record_id": candidate.external_id,
                    "entity_class": candidate.proposed_entity_class.display_name,
                    "client": candidate.client,
                    "last_observed_at": candidate.last_observed_at,
                    "review_url": reverse("entity_candidate_detail", kwargs={"candidate_id": candidate.id}),
                }
            )

    def _group_link(category_key: str, type_key: str = "", attention: str = "") -> str:
        params = request.GET.copy()
        params.pop("page", None)
        params["category"] = category_key
        if type_key:
            params["type"] = type_key
        else:
            params.pop("type", None)
        params.pop("issue", None)
        params.pop("response", None)
        if attention:
            params["attention"] = attention
        params["sort"] = "group"
        return "?" + params.urlencode()

    issue_group_headers = []
    for category in issue_categories:
        category_types = []
        for group in issue_type_groups.values():
            if group["category"] != category["key"]:
                continue
            names = set(group["types"])
            current_count = sum(current_type_counts.get(name, 0) for name in names)
            state_counts = {
                state: sum(state_counts_by_type.get(name, {}).get(state, 0) for name in names)
                for state in ("needs_action", "blocked", "pending")
            }
            unresolved_count = sum(state_counts.values())
            if not current_count and not unresolved_count:
                continue
            category_types.append(
                {
                    "key": group["value"],
                    "label": group["label"],
                    "current_count": current_count,
                    "unresolved_count": unresolved_count,
                    "state_counts": state_counts,
                    "state_links": [
                        {
                            "label": label,
                            "value": state,
                            "count": state_counts[state],
                            "href": _group_link(category["key"], group["value"], state),
                        }
                        for state, label in (
                            ("needs_action", "Needs action"),
                            ("blocked", "Blocked"),
                            ("pending", "Pending"),
                        )
                        if state_counts[state]
                    ],
                    "expanded": bool(
                        type_filter == group["value"]
                        or issue_filter in names
                        or active_group_key
                        and names.intersection({type_filter})
                        or device_id_filter
                        or subject_id_filter
                    ),
                    "href": _group_link(category["key"], group["value"]),
                }
            )
        if category_types:
            category_state_counts = {
                state: sum(item["state_counts"][state] for item in category_types)
                for state in ("needs_action", "blocked", "pending")
            }
            issue_group_headers.append(
                {
                    "key": category["key"],
                    "label": category["label"],
                    "current_count": sum(item["current_count"] for item in category_types),
                    "unresolved_count": sum(item["unresolved_count"] for item in category_types),
                    "state_counts": category_state_counts,
                    "state_summary": [
                        {"label": label, "count": category_state_counts[state]}
                        for state, label in (
                            ("needs_action", "Needs action"),
                            ("blocked", "Blocked"),
                            ("pending", "Pending"),
                        )
                        if category_state_counts[state]
                    ],
                    # Keep the default queue compact. A selected Type, Issue,
                    # or Category remains open so a drilldown never appears to
                    # have disappeared.
                    "expanded": bool(
                        category["key"] == category_filter
                        or any(item["expanded"] for item in category_types)
                    ),
                    "href": _group_link(category["key"]),
                    "show_type_rows": len(category_types) > 1,
                    "types": category_types,
                }
            )

    sort_getters = {
        "group": lambda row: (row["issue_type_label"], row["issue_label"]),
        "severity": lambda row: row["f"].get_severity_display(),
        "finding": lambda row: row["issue_display_label"],
        "subject": lambda row: row["subject_label"],
        "context": lambda row: row["context"],
        "status": lambda row: row["operator_status_label"],
    }
    if not database_query_mode:
        findings_with_detail.sort(
            key=lambda row: _table_value(sort_getters[sort_key](row)).casefold(),
            reverse=sort_dir == "desc",
        )
    # Group headers are rendered from the complete filtered set. Findings are
    # paginated only after a Type/Issue/drilldown has opened a group.
    if database_page_mode:
        # ``database_page`` intentionally paginates raw Finding rows in the
        # database. The template, however, must receive the corresponding
        # display dictionaries (labels, state, actions, and links), not those
        # raw model rows. Retain the database paginator's total and page
        # metadata while replacing only its current object list.
        database_page.object_list = findings_with_detail
        page = database_page
    else:
        paginator = Paginator(findings_with_detail if show_finding_rows else [], 50)
        page = paginator.get_page(request.GET.get("page"))

    table_base_params = []
    excluded_table_params = {"page", "sort", "dir"}
    excluded_table_params.update(f"table_{key}" for key, _getter in table_filter_specs)
    for key, values in request.GET.lists():
        if key not in excluded_table_params:
            table_base_params.extend((key, value) for value in values)
    table_clear_query = urlencode(table_base_params)
    sort_links = {}
    for candidate in ("group", "severity", "finding", "subject", "context", "status"):
        params = request.GET.copy()
        params.pop("page", None)
        params["sort"] = candidate
        params["dir"] = "desc" if sort_key == candidate and sort_dir == "asc" else "asc"
        sort_links[candidate] = "?" + params.urlencode()

    # Type dropdown cascades: if category selected, only show types in it.
    ft_qs = FindingType.objects.order_by("name")
    categories = [{"name": item["key"], "label": item["label"]} for item in issue_categories]
    finding_type_groups = _operator_issue_type_groups(
        list(ft_qs), category_filter, issue_categories, issue_type_groups
    )
    issue_choices = []
    if selected_type:
        issue_choices = list(selected_type["issues"])
    taxonomy_filter_data = [
        {
            "value": group["value"],
            "label": group["label"],
            "category": group["category"],
            "issues": list(group["issues"]),
        }
        for group in issue_type_groups.values()
    ]
    clients = Client.objects.filter(tenant_id=1, deleted_at__isnull=True).order_by("display_name")
    os_choices = list(
        Device.objects.filter(tenant_id=1, deleted_at__isnull=True)
        .exclude(os_name="")
        .order_by("os_name")
        .values_list("os_name", flat=True)
        .distinct()
    )

    page_query = request.GET.copy()
    page_query.pop("page", None)
    page_query.pop("format", None)

    return render(
        request,
        "findings_queue.html",
        {
            "page_obj": page,
            "findings": page.object_list,
            "admin_findings": admin_findings,
            "entity_candidate_items": entity_candidate_items,
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
            "condition_policy_available": condition_policy_available,
            "active_severity": severity_filter,
            "active_type": type_filter,
            "active_issue": issue_filter,
            "issue_choices": issue_choices,
            "taxonomy_filter_data": taxonomy_filter_data,
            "active_category": category_filter,
            "active_category_label": next(
                (item["label"] for item in issue_categories if item["key"] == category_filter),
                "",
            ),
            "active_platform": platform_filter,
            "active_os": os_filter,
            "os_choices": os_choices,
            "active_computer_type": computer_type_filter,
            "active_online": online_filter,
            "active_attention": attention_filter,
            "attention_choices": OPERATOR_ATTENTION_CHOICES,
            "operator_status_choices": OPERATOR_STATUS_CHOICES,
            "active_q": q_filter,
            "active_confidence": confidence_filter,
            "active_client": client_filter,
            "active_subject_id": subject_id_filter,
            "active_device_id": device_id_filter,
            "active_group_key": active_group_key,
            "show_snoozed": show_snoozed,
            "fleet_summary_cards": fleet_summary_cards,
            "fleet_policy_count": fleet_policy_count,
            "total_matching": total_matching,
            "actionable_matching": actionable_matching,
            "response_matching": response_matching,
            "current_result_summary": current_result_summary,
            "table_filters": table_filters,
            "table_filter_specs": [key for key, _getter in table_filter_specs],
            "table_base_params": table_base_params,
            "table_clear_query": table_clear_query,
            "sort_links": sort_links,
            "active_table_sort": sort_key,
            "active_table_dir": sort_dir,
            "issue_group_headers": issue_group_headers,
            "affected_device_count": len(affected_devices),
            "page_query": page_query.urlencode(),
            "finding_actions": available_finding_actions(request.user),
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


def _suggestion_label_sql() -> str:
    """SQL CASE that turns finding_details->>'suggestion' into its label.

    Built from the suggestion choices, so the Issues sort and filter text uses
    the same wording as the review page and the Python context line.
    """
    whens = " ".join(
        f"WHEN '{value}' THEN '{label}'" for value, label in SoftwareSuggestionRule.Suggestion.choices
    )
    return f"(CASE finding_details->>'suggestion' {whens} ELSE finding_details->>'suggestion' END)"


def _software_review_context(details: dict) -> str:
    """Issues context line for undecided software; mirrors the SQL branch above."""
    labels = dict(SoftwareSuggestionRule.Suggestion.choices)
    pieces = [details.get("canonical_name") or "", details.get("publisher") or ""]
    # A prompt is about its uncovered installations; the fleet total is context.
    devices = software_coverage.prompt_devices(details)
    if devices is not None:
        text = f"on {devices} machine{'s' if devices != 1 else ''}"
        clients = software_coverage.prompt_clients(details)
        if clients > 1:
            text += f" at {clients} clients"
        fleet = details.get("fleet_device_count")
        if details.get("uncovered_device_count") is not None and fleet and int(fleet) > devices:
            text += f" ({fleet} in the fleet)"
        pieces.append(text)
    if details.get("recent") is True:
        pieces.append("first seen recently")
    suggestion = details.get("suggestion") or "none"
    if suggestion != "none":
        pieces.append(f"suggested: {labels.get(suggestion, suggestion)}")
    evidence = software_review.evidence_labels(details)
    if evidence:
        pieces.append("because: " + ", ".join(evidence))
    signals = [s for s in (details.get("signals") or []) if isinstance(s, str)]
    if signals:
        pieces.append("signals: " + ", ".join(signals).replace("_", " "))
    text = " · ".join(piece for piece in pieces if piece)
    return text or details.get("reason") or "undecided software"


def _software_finding_modules() -> frozenset[str]:
    # The software emitters' registered source modules (code identity, not a
    # domain mapping).
    return frozenset({"platform.software_findings", "platform.capability_match"})


def _queue_ninja_software_refresh(device_id: uuid.UUID) -> tuple[bool, str]:
    """Fetch one linked Computer's software list from Ninja now."""
    link = (
        DeviceSourceLink.objects.filter(
            tenant_id=1,
            device_id=device_id,
            device__deleted_at__isnull=True,
            source__name="Ninja",
            missing_since__isnull=True,
        )
        .exclude(external_id="")
        .order_by("-last_seen_at", "external_id")
        .first()
    )
    if not link:
        return False, "This Issue has no current Ninja Computer record to refresh."
    external_id = link.external_id.strip()
    if not external_id.isascii() or not external_id.isdecimal():
        return False, "The linked Ninja Computer record cannot be refreshed safely."

    query = urlencode({"id": external_id})
    url = f"{_INGEST_BASE_URL.rstrip('/')}/run/software/device?{query}"
    try:
        request_obj = _urllib_request.Request(url, data=b"", method="POST")
        with _urllib_request.urlopen(request_obj, timeout=10) as response:
            response.read(200)
    except HTTPError as exc:
        return False, f"Refresh could not be queued (HTTP {exc.code})."
    except URLError as exc:
        return False, f"Refresh could not reach collection service ({exc.reason})."
    return True, ""


def _source_binding_for_refresh(finding: Finding) -> uuid.UUID | None:
    """Resolve one configured source binding from a finding's evidence."""
    details = finding.finding_details or {}
    raw_binding = str(details.get("source_binding_id") or "")
    try:
        if raw_binding:
            return uuid.UUID(raw_binding)
    except ValueError:
        pass
    source_id = str(details.get("source_id") or "")
    if not source_id:
        domain = str(details.get("domain") or "")
        if domain.startswith("source."):
            source_id = str(
                Source.objects.filter(
                    name__iexact=domain.removeprefix("source.").split(".", 1)[0]
                ).values_list("id", flat=True).first()
                or ""
            )
    if not source_id:
        return None
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """SELECT binding.id FROM operations.source_bindings binding
                 JOIN operations.source_instances instance ON instance.id = binding.source_instance_id
                WHERE binding.tenant_id = 1 AND binding.enabled AND instance.enabled
                  AND instance.source_id::text = %s ORDER BY binding.id LIMIT 2""",
            (source_id,),
        )
        rows = cur.fetchall()
    return rows[0][0] if len(rows) == 1 else None


def _queue_source_refresh(binding_id: uuid.UUID, user_id: int) -> tuple[bool, str]:
    """Request one configured source through the binding-scoped Jobs API."""
    try:
        _run_id, created = _enqueue_operator_job(
            "source-refresh", user_id, scope_identity=f"source-binding:{binding_id}"
        )
    except DatabaseError:
        return False, "Source refresh could not be requested."
    return True, "" if created else "An equivalent source refresh is already active."


def _queue_platform_reevaluation() -> tuple[bool, str]:
    """Reevaluate conditions using the evidence already collected."""
    return _dispatch_job({"endpoint": "run/platform-evaluate"})


def _queue_refresh_for_finding(finding: Finding, user_id: int) -> tuple[bool, str, str]:
    """Use the narrowest registered ingest/evaluator path for an Issue.

    Only a software Issue on a Computer refreshes that Computer's software list;
    any other Issue gains nothing from it.
    """
    detail = ""
    if (
        finding.subject_type == Finding.SubjectType.DEVICE
        and finding.finding_type.source_module in _software_finding_modules()
    ):
        queued, detail = _queue_ninja_software_refresh(finding.subject_id)
        if queued:
            return True, "computer", ""

    if source_binding_id := _source_binding_for_refresh(finding):
        queued, source_detail = _queue_source_refresh(source_binding_id, user_id)
        if queued:
            return True, "source", ""
        detail = source_detail

    queued, evaluation_detail = _queue_platform_reevaluation()
    if queued:
        return True, "reevaluate", ""
    return False, "", evaluation_detail or detail


@login_required
@require_POST
def finding_refresh(request: HttpRequest, finding_id: str) -> HttpResponse:
    """Queue the registered ingest/evaluator refresh for a Pending Issue."""
    finding = get_object_or_404(
        Finding.objects.select_related("finding_type"), id=finding_id, tenant_id=1
    )
    queued, target, detail = _queue_refresh_for_finding(finding, request.user.id)
    if queued and target == "computer":
        messages.success(request, "Computer data refresh queued.")
    elif queued and target == "source":
        messages.success(request, "Source refresh requested.")
    elif queued:
        messages.success(request, "Issue reevaluation queued using current information.")
    else:
        messages.warning(request, detail or "Refresh could not be queued.")
    return redirect(request.POST.get("next") or "findings_queue")


@login_required
def targeted_refresh(request: HttpRequest) -> HttpResponse:
    """Offer the registered targeted ingest/evaluator refresh operations."""
    search = (request.GET.get("q") or "").strip()
    if request.method == "POST":
        target = (request.POST.get("target") or "").strip()
        if target == "computer":
            device_id = request.POST.get("device_id") or ""
            try:
                device = Device.objects.filter(
                    tenant_id=1, id=device_id, deleted_at__isnull=True
                ).first()
            except (ValueError, TypeError):
                device = None
            if not device:
                messages.warning(request, "Choose a current Computer to refresh.")
            else:
                queued, detail = _queue_ninja_software_refresh(device.id)
                if queued:
                    messages.success(request, "Computer data refresh queued.")
                else:
                    messages.warning(request, detail)
        elif target == "source":
            try:
                binding_id = uuid.UUID(request.POST.get("source_binding") or "")
            except ValueError:
                binding_id = None
            if binding_id is None:
                messages.warning(request, "Choose a configured source to refresh.")
            else:
                queued, detail = _queue_source_refresh(binding_id, request.user.id)
                if queued:
                    messages.success(request, "Source refresh requested.")
                else:
                    messages.warning(request, detail or "Source refresh could not be queued.")
        elif target == "reevaluate":
            queued, detail = _queue_platform_reevaluation()
            if queued:
                messages.success(request, "Platform reevaluation queued using current information.")
            else:
                messages.warning(request, detail or "Reevaluation could not be queued.")
        else:
            messages.warning(request, "Choose what to refresh.")
        return redirect("targeted_refresh")

    computers = Device.objects.none()
    if search:
        computers = (
            Device.objects.filter(tenant_id=1, deleted_at__isnull=True)
            .filter(
                Q(canonical_hostname__icontains=search) | Q(client__display_name__icontains=search)
            )
            .select_related("client")
            .order_by("canonical_hostname", "id")[:50]
        )
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """SELECT binding.id, source.name, client.display_name
                 FROM operations.source_bindings binding
                 JOIN operations.source_instances instance ON instance.id = binding.source_instance_id
                 JOIN operations.sources source ON source.id = instance.source_id
                 LEFT JOIN operations.clients client ON client.id = instance.client_id
                WHERE binding.tenant_id = 1 AND binding.enabled AND instance.enabled
                ORDER BY source.name, client.display_name NULLS FIRST, binding.id"""
        )
        source_bindings = [
            {"id": row[0], "name": row[1], "client_name": row[2]} for row in cur.fetchall()
        ]
    return render(
        request,
        "targeted_refresh.html",
        {
            "admin_group": "integrations",
            "admin_tab": "jobs",
            "search": search,
            "computers": computers,
            "source_bindings": source_bindings,
        },
    )


@login_required
@require_POST
def finding_reviewed_distinct(request: HttpRequest, finding_id: str) -> HttpResponse:
    """Approve an identity conflict as distinct for its current evidence."""
    finding = get_object_or_404(
        Finding.objects.select_related("finding_type"),
        id=finding_id,
        tenant_id=1,
        finding_type__name="identity_conflict",
    )
    record_identity_reviewed_distinct(
        actor=request.user,
        tenant_id=1,
        finding_id=finding.id,
        reason=request.POST.get("reason", ""),
    )
    messages.success(request, "Identity conflict reviewed as distinct for the current evidence.")
    return redirect(request.POST.get("next") or "findings_queue")


@login_required
@require_GET
def finding_review(request: HttpRequest, finding_id: str) -> HttpResponse:
    """Show an operator-safe, one-click review path for any Issue."""
    finding = get_object_or_404(
        Finding.objects.select_related("finding_type", "client"),
        id=finding_id,
        tenant_id=1,
    )
    details = finding.finding_details or {}
    subject_label = finding.get_subject_type_display()
    subject_url = ""
    review_links: list[dict[str, str]] = []

    if finding.subject_type == Finding.SubjectType.DEVICE:
        device = (
            Device.objects.filter(
                tenant_id=1,
                id=finding.subject_id,
                deleted_at__isnull=True,
            )
            .select_related("client")
            .first()
        )
        if device and device.client:
            subject_label = device.canonical_hostname or "Unnamed Computer"
            subject_url = reverse(
                "device_detail",
                kwargs={"org_slug": device.client.slug, "device_id": device.id},
            )
            review_links.append(
                {
                    "label": "Open Computer and source records",
                    "url": f"{subject_url}?tab=details#source-records",
                }
            )
    elif finding.subject_type == Finding.SubjectType.CLIENT and finding.client:
        subject_label = finding.client.display_name
        subject_url = reverse("org_index", kwargs={"org_slug": finding.client.slug})
        review_links.append({"label": "Open client", "url": subject_url})
    elif finding.subject_type in {
        Finding.SubjectType.SOFTWARE_PRODUCT,
        Finding.SubjectType.SOFTWARE_VERSION,
        Finding.SubjectType.SOFTWARE_INSTALLATION,
    }:
        canonical_name = details.get("canonical_name") or ""
        if canonical_name:
            subject_label = canonical_name
            subject_url = reverse("software_detail", kwargs={"name": canonical_name})
            review_links.append({"label": "Open software details", "url": subject_url})

    if finding.finding_type.name.startswith("patch_") and finding.client:
        review_links.append(
            {
                "label": "Review patch evidence",
                "url": f"{reverse('patch_evidence_page')}?{urlencode({'client': finding.client.slug})}",
            }
        )
    if finding.finding_type.name == "cmdb_asset_stale" and details.get("url"):
        review_links.append({"label": "Open Hudu record", "url": str(details["url"])})
    if finding.subject_type in {
        Finding.SubjectType.SOURCE_BINDING,
        Finding.SubjectType.COLLECTOR_INSTANCE,
    }:
        review_links.append({"label": "Check source health", "url": reverse("sources_status")})

    if finding.client and not subject_url:
        subject_label = finding.client.display_name
        subject_url = reverse("org_index", kwargs={"org_slug": finding.client.slug})
        review_links.append({"label": "Open client", "url": subject_url})

    if finding.finding_type.name == "identity_conflict" and finding.client:
        candidate_ids = details.get("candidate_device_ids") or []
        candidates = (
            Device.objects.filter(
                tenant_id=1,
                client_id=finding.client_id,
                id__in=candidate_ids,
                deleted_at__isnull=True,
            )
            .select_related("client")
            .order_by("canonical_hostname", "id")
        )
        for index, device in enumerate(candidates, start=1):
            review_links.append(
                {
                    "label": f"Open possible duplicate {index}: {device.canonical_hostname or 'Unnamed Computer'}",
                    "url": reverse(
                        "device_detail",
                        kwargs={"org_slug": device.client.slug, "device_id": device.id},
                    ),
                }
            )

    if not review_links:
        review_links.append({"label": "Check source health", "url": reverse("sources_status")})

    return render(
        request,
        "finding_review.html",
        {
            "finding": finding,
            "subject_label": subject_label,
            "subject_url": subject_url,
            "review_links": review_links,
        },
    )


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
        details = dict(finding.finding_details or {})
        details["resolution"] = {
            "reason": "operator_resolved",
            "detail": "Resolved by an operator; this is not an automated recovery claim.",
        }
        finding.status = Finding.Status.RESOLVED
        finding.closed_at = finding.closed_at or timezone.now()
        finding.finding_details = details
        finding.save(update_fields=["status", "closed_at", "finding_details"])
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
    reason = (request.POST.get("reason") or "").strip()
    if not reason:
        messages.warning(request, "An exclusion reason is required.")
        return redirect(request.POST.get("next") or "findings_queue")
    if len(reason) > _LIFECYCLE_REASON_MAX_LENGTH:
        messages.warning(
            request,
            f"Keep the reason to {_LIFECYCLE_REASON_MAX_LENGTH} characters or fewer.",
        )
        return redirect(request.POST.get("next") or "findings_queue")
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
    messages.info(request, "Issue excluded.")
    return redirect(request.POST.get("next") or "findings_queue")


@login_required
@require_POST
def findings_bulk_action(request: HttpRequest) -> HttpResponse:
    """Apply one action across multiple selected findings."""
    ids = list(dict.fromkeys(request.POST.getlist("ids")))
    action = (request.POST.get("action") or "").strip()
    if not ids:
        messages.warning(request, "Pick an action and at least one issue.")
        return redirect(request.POST.get("next") or "findings_queue")

    registered_action = FINDING_ACTIONS.get(action)
    if registered_action is not None:
        if not can_run_action(request.user, registered_action):
            raise PermissionDenied
        if registered_action.key == BULK_RETIRE_COMPUTERS.key:
            return _retire_selected_computers(request, ids, registered_action)
        if registered_action.key == ARCHIVE_HUDU_ASSETS.key:
            return _queue_selected_hudu_archives(request, ids, registered_action)
        if registered_action.key in (
            APPROVE_REMOTE_ACCESS_ALL.key,
            APPROVE_REMOTE_ACCESS_CLIENT.key,
        ):
            return approve_remote_access(request, ids, registered_action)
        if registered_action.key in (CAPABILITY_CONFIRM.key, CAPABILITY_REJECT.key):
            return decide_capability(request, ids, registered_action)
        if registered_action.key in IDENTITY_ACTIONS:
            return run_identity_action(request, ids, registered_action)
        if decision_for(registered_action.key) is not None:
            return decide_software(request, ids, registered_action)
    if action not in ("refresh", "snooze", "suppress"):
        messages.warning(request, "That action is not available.")
        return redirect(request.POST.get("next") or "findings_queue")

    now = timezone.now()
    qs = Finding.objects.filter(tenant_id=1, id__in=ids)
    policy_count = qs.filter(finding_type__name__in=_SOFTWARE_POLICY_CANDIDATE_TYPES).count()
    qs = qs.exclude(finding_type__name__in=_SOFTWARE_POLICY_CANDIDATE_TYPES)
    if not qs.exists():
        messages.info(
            request,
            "Undecided software is decided with Approve, Reject or Investigate; "
            "pausing or excluding it does not apply, so no issue-state action was applied.",
        )
        return redirect(request.POST.get("next") or "findings_queue")
    if action == "refresh":
        refreshed_device_ids: set[uuid.UUID] = set()
        refreshed = 0
        failures = 0
        for finding in qs.only("subject_type", "subject_id", "finding_details"):
            if (
                finding.subject_type == Finding.SubjectType.DEVICE
                and finding.subject_id in refreshed_device_ids
            ):
                continue
            queued, target, _detail = _queue_refresh_for_finding(finding)
            if queued:
                refreshed += 1
                if target == "computer":
                    refreshed_device_ids.add(finding.subject_id)
            else:
                failures += 1
        if refreshed:
            message = f"Refresh queued for {refreshed} Issue" f"{'s' if refreshed != 1 else ''}."
            if failures:
                message += (
                    f" {failures} issue{'s' if failures != 1 else ''} could not be refreshed."
                )
        else:
            messages.warning(request, "The selected Issues could not be refreshed.")
            return redirect(request.POST.get("next") or "findings_queue")
    elif action == "snooze":
        try:
            days = int(request.POST.get("days") or 7)
        except ValueError:
            days = 7
        days = max(1, min(days, 90))
        until = timezone.now() + timedelta(days=days)
        touched = qs.update(snoozed_until=until)
        message = f"Snoozed {touched} for {days} day{'s' if days != 1 else ''}."
    else:
        reason = (request.POST.get("reason") or "").strip()
        if not reason:
            messages.warning(request, "An exclusion reason is required.")
            return redirect(request.POST.get("next") or "findings_queue")
        if len(reason) > _LIFECYCLE_REASON_MAX_LENGTH:
            messages.warning(
                request,
                f"Keep the reason to {_LIFECYCLE_REASON_MAX_LENGTH} characters or fewer.",
            )
            return redirect(request.POST.get("next") or "findings_queue")
        findings = list(qs.select_related("finding_type"))
        for finding in findings:
            SuppressionRule.objects.create(
                tenant_id=1,
                finding_type=finding.finding_type,
                subject_match={
                    "subject_type": finding.subject_type,
                    "subject_id": str(finding.subject_id),
                },
                reason=reason,
                created_by=request.user,
            )
        touched = qs.update(status=Finding.Status.SUPPRESSED, closed_at=now)
        message = f"Excluded {touched} issue{'s' if touched != 1 else ''}."
    if policy_count:
        message += (
            f" Skipped {policy_count} software policy candidate"
            f"{'s' if policy_count != 1 else ''}."
        )
    messages.info(request, message)
    return redirect(request.POST.get("next") or "findings_queue")


@transaction.atomic
def _retire_selected_computers(request: HttpRequest, ids: list[str], action) -> HttpResponse:
    """Execute the first registered lifecycle action from selected Findings.

    This deliberately validates the complete selection before changing any
    Computer.  A Finding is evidence for a human decision; it is not a blanket
    permission to retire a Computer that has regained a current source record.
    """
    reason = (request.POST.get("reason") or "").strip()
    if action.requires_reason and not reason:
        messages.warning(request, "A retirement reason is required.")
        return redirect(request.POST.get("next") or "findings_queue")
    if len(reason) > _LIFECYCLE_REASON_MAX_LENGTH:
        messages.warning(
            request,
            f"Keep the reason to {_LIFECYCLE_REASON_MAX_LENGTH} characters or fewer.",
        )
        return redirect(request.POST.get("next") or "findings_queue")

    findings = list(
        Finding.objects.select_for_update()
        .select_related("finding_type")
        .filter(tenant_id=1, id__in=ids)
    )
    if len(findings) != len(ids):
        messages.warning(request, "One or more selected issues are no longer available.")
        return redirect(request.POST.get("next") or "findings_queue")
    if any(
        finding.finding_type.name not in action.finding_types
        or finding.subject_type != Finding.SubjectType.DEVICE
        for finding in findings
    ):
        messages.warning(
            request,
            "Retirement can only be started from “No current source record” issues.",
        )
        return redirect(request.POST.get("next") or "findings_queue")

    device_ids = [finding.subject_id for finding in findings]
    devices = list(
        Device.objects.select_for_update().filter(
            tenant_id=1, id__in=device_ids, deleted_at__isnull=True
        )
    )
    devices_by_id = {device.id: device for device in devices}
    if len(devices_by_id) != len(device_ids) or any(
        devices_by_id[device_id].lifecycle_status != Device.LifecycleStatus.PENDING_CLEANUP
        for device_id in device_ids
    ):
        messages.warning(
            request,
            "Every selected Computer must still need review before it can be retired.",
        )
        return redirect(request.POST.get("next") or "findings_queue")

    entity_ids = [device.entity_id for device in devices]
    entities_by_id = {
        entity.id: entity
        for entity in Entity.objects.select_for_update().filter(
            tenant_id=1, id__in=entity_ids, deleted_at__isnull=True
        )
    }
    if len(entities_by_id) != len(entity_ids):
        messages.warning(request, "One or more selected Computers no longer has an active entity.")
        return redirect(request.POST.get("next") or "findings_queue")

    now = timezone.now()
    for device in devices:
        entity = entities_by_id[device.entity_id]
        before = {
            "lifecycle_status": device.lifecycle_status,
            "entity_retired_at": entity.retired_at.isoformat() if entity.retired_at else None,
            "entity_retired_reason": entity.retired_reason,
        }
        device.lifecycle_status = Device.LifecycleStatus.RETIRED
        device.updated_at = now
        device.updated_reason = "operator.finding_action.retire"
        device.save(update_fields=["lifecycle_status", "updated_at", "updated_reason"])
        entity.retired_at = now
        entity.retired_reason = reason
        entity.updated_at = now
        entity.updated_reason = "operator.finding_action.retire"
        entity.save(update_fields=["retired_at", "retired_reason", "updated_at", "updated_reason"])
        _audit(
            request,
            "finding_action.retire_computer",
            device.id,
            before,
            {
                "lifecycle_status": device.lifecycle_status,
                "reason": reason,
                "finding_ids": [
                    str(finding.id) for finding in findings if finding.subject_id == device.id
                ],
            },
            entity_type="device",
        )

    retiring_findings = list(
        Finding.objects.filter(tenant_id=1, id__in=ids)
        .exclude(status=Finding.Status.RESOLVED)
        .only("id", "finding_details")
    )
    Finding.objects.filter(
        tenant_id=1, id__in=[finding.id for finding in retiring_findings]
    ).update(status=Finding.Status.RESOLVED, closed_at=now)
    for finding in retiring_findings:
        details = dict(finding.finding_details or {})
        details["resolution"] = {"reason": "retired", "detail": reason}
        Finding.objects.filter(id=finding.id, tenant_id=1).update(finding_details=details)
    messages.success(
        request,
        f"Retired {len(devices)} Computer{'s' if len(devices) != 1 else ''}. "
        "Source records and history were kept.",
    )
    return redirect(request.POST.get("next") or "findings_queue")


@transaction.atomic
def _queue_selected_hudu_archives(request: HttpRequest, ids: list[str], action) -> HttpResponse:
    """Queue explicit Hudu archive requests for still-eligible findings.

    The Findings action does not call Hudu.  It records an operator request;
    the ingest worker rechecks eligibility and resolves the source credential
    immediately before its API call.
    """
    reason = (request.POST.get("reason") or "").strip()
    if action.requires_reason and not reason:
        messages.warning(request, "A reason is required to archive records in Hudu.")
        return redirect(request.POST.get("next") or "findings_queue")
    if len(reason) > _LIFECYCLE_REASON_MAX_LENGTH:
        messages.warning(
            request,
            f"Keep the reason to {_LIFECYCLE_REASON_MAX_LENGTH} characters or fewer.",
        )
        return redirect(request.POST.get("next") or "findings_queue")

    findings = list(
        Finding.objects.select_for_update()
        .select_related("finding_type")
        .filter(tenant_id=1, id__in=ids)
    )
    if len(findings) != len(ids) or any(
        finding.finding_type.name not in action.finding_types for finding in findings
    ):
        messages.warning(request, "Archive in Hudu requires only Hudu archive-candidate issues.")
        return redirect(request.POST.get("next") or "findings_queue")

    queued = 0
    already_queued = 0
    no_longer_eligible = 0
    with connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        for finding in findings:
            details = finding.finding_details or {}
            source_instance_id = details.get("source_instance_id")
            company_id = details.get("company_id")
            asset_id = details.get("asset_id")
            if not (source_instance_id and company_id and asset_id):
                no_longer_eligible += 1
                continue
            # Queueing is itself a governed response: do not create a pending
            # source mutation for a finding that is already blocked, pending,
            # stale, or missing a required participant assessment. The worker
            # repeats this check immediately before the external API call.
            governed = _condition_operator_states([finding.id]).get(str(finding.id), {})
            if governed.get("attention") != ATTENTION_NEEDS_ACTION:
                no_longer_eligible += 1
                continue
            # Recheck the exact current source record. A Finding is evidence,
            # not authority to mutate a Hudu record that has since recovered.
            cur.execute(
                """
                SELECT eo.source_instance_id, eo.parent_external_id, eo.external_id
                  FROM operations.v_entity_observation_admin_metadata eo
                  JOIN operations.source_instances si ON si.id = eo.source_instance_id
                  JOIN operations.sources s ON s.id = si.source_id
                 WHERE eo.tenant_id = 1
                   AND eo.source_instance_id = %s::uuid
                   AND COALESCE(eo.hudu_company_id, '') = %s
                   AND eo.external_id = %s
                   AND eo.active
                   AND s.name = 'Hudu'
                   AND eo.entity_type = 'cmdb.asset'
                   AND eo.link_verdict = 'stale'
                   AND eo.archived IS FALSE
                """,
                (source_instance_id, str(company_id), str(asset_id)),
            )
            target = cur.fetchone()
            if target is None:
                no_longer_eligible += 1
                continue
            cur.execute(
                """
                INSERT INTO operations.source_action_requests (
                    tenant_id, finding_id, source_instance_id, action_key,
                    parent_external_id, external_id, requested_by_id, reason
                ) VALUES (1, %s, %s, 'archive_hudu_asset', %s, %s, %s, %s)
                ON CONFLICT (tenant_id, action_key, source_instance_id,
                             parent_external_id, external_id)
                    WHERE status IN ('pending', 'processing')
                DO NOTHING
                RETURNING id
                """,
                (finding.id, target[0], target[1], target[2], request.user.pk, reason),
            )
            request_id = cur.fetchone()
            if request_id is None:
                already_queued += 1
                continue
            queued += 1
            _audit(
                request,
                "finding_action.queue_archive_hudu",
                None,
                {"finding_id": str(finding.id), "eligible": True},
                {
                    "request_id": request_id[0],
                    "source_instance_id": str(target[0]),
                    "company_id": target[1],
                    "asset_id": target[2],
                    "reason": reason,
                },
                entity_type="source_action_request",
            )

    message = f"Queued Archive in Hudu for {queued} record{'s' if queued != 1 else ''}."
    if already_queued:
        message += f" {already_queued} already queued."
    if no_longer_eligible:
        message += f" {no_longer_eligible} no longer met the archive rule."
    messages.success(request, message)
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
    is_overview = getattr(getattr(request, "resolver_match", None), "url_name", "") == "software_page"
    is_csv = wants_csv(request)
    decision_filter = request.GET.get("decision", "")  # approved|rejected|pending|any
    category_filter = request.GET.get("category", "")  # av|rmm|remote_access|...|uncategorized
    # Separate axis from `category` above: that one is the security-relevant
    # capability (av/rmm/remote_access). This is the descriptive taxonomy
    # (browser/dev_tools/media/...) from catalog.v_product_category_effective
    # (migration 104) -- distinct table, distinct filter, never conflated.
    product_category_filter = request.GET.get("product_category", "")
    safety_filter = request.GET.get("safety", "")  # high|medium|low|clean
    publisher_filter = (request.GET.get("publisher") or "").strip()
    flagged_filter = request.GET.get("flagged", "").strip().lower() in ("1", "true", "yes", "on")
    min_devices = request.GET.get("min_devices", "").strip()
    try:
        min_devices_int = int(min_devices) if min_devices else 0
    except ValueError:
        min_devices_int = 0

    # Server-side sort + pagination. The page previously fetched only the
    # top 500 rows by device_count DESC and let a client-side JS sort
    # reorder just that fetched slice -- ascending "sort" only ever showed
    # the 500th-highest count, never the fleet's real minimum, and every
    # row past 500 (the majority: 21,600+ of 22,127 titles) was never
    # reachable at all. A whitelist keeps the column expression out of the
    # query string; direction and page are validated the same way.
    _SORT_COLUMNS = {
        "canonical_name": "sic.canonical_name",
        "device_count": "sic.device_count",
        "client_count": "sic.client_count",
        "last_install": "sic.latest_install",
    }
    sort_key = request.GET.get("sort", "device_count")
    if sort_key not in _SORT_COLUMNS:
        sort_key = "device_count"
    sort_dir = request.GET.get("dir", "desc")
    if sort_dir not in ("asc", "desc"):
        sort_dir = "desc"
    sort_sql = f"{_SORT_COLUMNS[sort_key]} {sort_dir.upper()}, sic.canonical_name"

    page_size = 500
    try:
        page_num = max(1, int(request.GET.get("page", "1")))
    except ValueError:
        page_num = 1
    page_offset = (page_num - 1) * page_size

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

    # Capability layer availability probe — the raw SQL migration runner and
    # Django both apply at container startup with no ordering guarantee, so
    # this table can be briefly absent. Same shape as intel_available above:
    # fail closed to "no category data" rather than a hard 500 for every
    # visitor to this page during that window.
    capability_available = False
    try:
        with connection.cursor() as pcur:
            pcur.execute("SELECT to_regclass('catalog.v_product_capability_effective')")
            (regclass,) = pcur.fetchone()
            capability_available = regclass is not None
    except Exception:
        capability_available = False
    if not capability_available and category_filter:
        category_filter = ""

    # Descriptive-category layer availability probe, same fail-closed shape.
    product_category_available = False
    try:
        with connection.cursor() as pcur:
            pcur.execute("SELECT to_regclass('catalog.v_product_category_effective')")
            (regclass,) = pcur.fetchone()
            product_category_available = regclass is not None
    except Exception:
        product_category_available = False
    if not product_category_available and product_category_filter:
        product_category_filter = ""

    # A safety filter or CSV needs the complete matching/exportable set. The
    # ordinary HTML views need safety only for their bounded title page; the
    # Overview's fleet summary is an aggregate read below, not an estate-wide
    # row transfer.
    all_safety_rows: list[tuple] = []
    needs_full_safety_snapshot = bool(safety_filter) or is_csv
    if intel_available and needs_full_safety_snapshot:
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
        safety_filter_names = [r[0] for r in all_safety_rows if r[2] == safety_filter]
        if not safety_filter_names:
            # No products in that band. Force the main query to return
            # zero title rows without scanning the whole fleet.
            safety_filter_names = ["\x00__no_match__\x00"]

    risk_distribution = {"high": 0, "medium": 0, "low": 0, "clean": 0, "unknown": 0}
    if intel_available and is_overview:
        with transaction.atomic(), connection.cursor() as sc:
            sc.execute("SET LOCAL operations.tenant_id = 1")
            sc.execute(
                f"""
                SELECT safety.safety_band, COUNT(*)::int
                FROM operations.v_software_safety safety
                WHERE safety.tenant_id = 1
                  AND EXISTS (
                      SELECT 1
                      FROM operations.software_installations_current sic
                      JOIN operations.devices d
                        ON d.tenant_id = sic.tenant_id AND d.id = sic.device_id
                      WHERE sic.tenant_id = safety.tenant_id
                        AND sic.canonical_name = safety.canonical_name
                        AND sic.deleted_at IS NULL
                        AND sic.stale_since IS NULL
                        AND d.deleted_at IS NULL
                        AND {current_computer_sql("d")}
                  )
                GROUP BY safety.safety_band
                """
            )
            for band, count in sc.fetchall():
                if band in risk_distribution:
                    risk_distribution[band] = count
    high_risk_titles = risk_distribution["high"]

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")

        # Retired reading software_catalog.categories for this page (ADR-0012
        # "retired means stop reading and writing" -- the table itself is not
        # dropped). Measured 2026-08-18: software_catalog held only three
        # values, av/remote_access/rmm, the same three concepts
        # catalog.capability now handles with vetted/candidate tiers and
        # dry-run-verified rules, seeded once by hand and never a general
        # taxonomy. It also had a case-sensitivity bug (mixed-case catalog
        # rows against lowercase installed titles) that made every filter on
        # this page match nothing at all before that was even considered.
        #
        # The capability model reaches 441 distinct titles this way, against
        # 11 through the case-fixed old join -- real, vetted data rather than
        # a bigger version of the same small hand-seed.
        categorized_titles = 0
        category_rows: list = []
        if capability_available:
            cur.execute(
                f"""
                SELECT COUNT(DISTINCT sic.canonical_name)
                FROM operations.software_installations_current sic
                JOIN operations.devices d ON d.id = sic.device_id AND d.tenant_id = sic.tenant_id
                JOIN catalog.software_versions sv ON sv.id = sic.software_version_id
                JOIN catalog.products p ON p.id = sv.product_id
                JOIN catalog.v_product_capability_effective cap ON cap.product_uuid = p.product_uuid
                WHERE sic.tenant_id = 1 AND sic.deleted_at IS NULL AND sic.stale_since IS NULL
                  AND d.deleted_at IS NULL AND {current_computer_sql("d")}
                """
            )
            (categorized_titles,) = cur.fetchone()

            if not is_overview:
                # Capability breakdown, replacing the software_catalog category
                # breakdown this used to read. 'av' is the URL-facing alias for
                # the endpoint_security capability, matching the unauthorized_av
                # finding type name it already drives.
                cur.execute(
                    f"""
                    SELECT CASE cap.capability WHEN 'endpoint_security' THEN 'av' ELSE cap.capability END,
                           COUNT(DISTINCT sic.canonical_name)
                    FROM operations.software_installations_current sic
                    JOIN operations.devices d ON d.id = sic.device_id AND d.tenant_id = sic.tenant_id
                    JOIN catalog.software_versions sv ON sv.id = sic.software_version_id
                    JOIN catalog.products p ON p.id = sv.product_id
                    JOIN catalog.v_product_capability_effective cap ON cap.product_uuid = p.product_uuid
                    WHERE sic.tenant_id = 1 AND sic.deleted_at IS NULL AND sic.stale_since IS NULL
                      AND d.deleted_at IS NULL AND {current_computer_sql("d")}
                    GROUP BY cap.capability
                    ORDER BY 2 DESC
                    """
                )
                category_rows = cur.fetchall()

        # Descriptive category (migration 104) -- same join shape as the
        # capability block above, distinct table, never merged with it.
        descriptive_categorized_titles = 0
        descriptive_category_rows: list = []
        if product_category_available and not is_overview:
            cur.execute(
                f"""
                SELECT pce.category,
                       COUNT(DISTINCT sic.canonical_name),
                       GROUPING(pce.category) AS is_total
                FROM operations.software_installations_current sic
                JOIN operations.devices d ON d.id = sic.device_id AND d.tenant_id = sic.tenant_id
                JOIN catalog.software_versions sv ON sv.id = sic.software_version_id
                JOIN catalog.products p ON p.id = sv.product_id
                JOIN catalog.v_product_category_effective pce ON pce.product_uuid = p.product_uuid
                WHERE sic.tenant_id = 1 AND sic.deleted_at IS NULL AND sic.stale_since IS NULL
                  AND d.deleted_at IS NULL AND {current_computer_sql("d")}
                GROUP BY GROUPING SETS ((pce.category), ())
                """
            )
            for category, count, is_total in cur.fetchall():
                if is_total:
                    descriptive_categorized_titles = count
                else:
                    descriptive_category_rows.append((category, count))
            descriptive_category_rows.sort(key=lambda row: row[1], reverse=True)


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
        # category_filter / product_category_filter are checked against
        # category_by_title / product_category_by_title below -- CTEs joined
        # once into `filtered`, not a per-row correlated EXISTS. That EXISTS
        # shape (still used by the other filters below, on the much smaller
        # operations.software_decisions table) measured ~530ms per outer row
        # against the 530k-row installations table here, because the
        # correlation on sic.canonical_name cannot be pushed into an index in
        # that plan -- 500 rows x 2 columns like this is what produced the
        # Gunicorn worker timeout this replaces.
        if category_filter == "uncategorized":
            where_clauses.append("cbt.categories IS NULL")
        elif category_filter:
            # 'av' is the URL-facing alias for the endpoint_security
            # capability key, matching the unauthorized_av finding type name
            # operators already see.
            capability_key = "endpoint_security" if category_filter == "av" else category_filter
            where_clauses.append("%s = ANY(COALESCE(cbt.categories, ARRAY[]::text[]))")
            params.append(capability_key)
        if product_category_filter == "uncategorized":
            where_clauses.append("pcbt.product_categories IS NULL")
        elif product_category_filter:
            where_clauses.append("%s = ANY(COALESCE(pcbt.product_categories, ARRAY[]::text[]))")
            params.append(product_category_filter)
        # Decision filters read the same per-title status as the overview counts
        # and the Status column (ADR-0039), not raw decision rows.
        status_filter = {
            "approved": "approve",
            "rejected": "reject",
            "pending": "pending",
            "investigating": "investigate",
        }.get(decision_filter)
        if status_filter:
            where_clauses.append(f"{software_review.TITLE_STATUS} = %s")
            params.append(status_filter)
        if safety_filter_names:
            # Filter to the pre-computed canonical set for this risk
            # band — avoids re-evaluating v_software_safety per row.
            where_clauses.append("sic.canonical_name = ANY(%s::text[])")
            params.append(safety_filter_names)

        where_sql = " AND ".join(where_clauses)
        # Both aggregates computed ONCE across the whole fleet, not as a
        # correlated subquery re-run per displayed row. The correlated form
        # (kept until this change) measured ~530ms per canonical_name because
        # the plan starts from the small evidence table outward through a
        # full products scan rather than using the tenant/name correlation as
        # an index lookup -- 500 rows of that is minutes, which is what
        # produced the Gunicorn worker timeout. A single GROUP BY pass here
        # costs about what the category-breakdown queries above already cost.
        # Category filters and CSV need an estate-wide matching/exportable
        # result. An ordinary first view has no category predicate, so defer
        # its category enrichment until after the bounded title page below.
        needs_full_category_snapshot = bool(category_filter or product_category_filter or is_csv)
        title_page_size = 0 if is_overview and not is_csv else (page_size if is_csv else 100)
        category_cte_sql = (
            f"""SELECT sic2.canonical_name,
                      array_agg(DISTINCT
                          CASE cap.capability WHEN 'endpoint_security' THEN 'av' ELSE cap.capability END
                      ) AS categories
                 FROM operations.software_installations_current sic2
                 JOIN operations.devices d ON d.id = sic2.device_id AND d.tenant_id = sic2.tenant_id
                 JOIN catalog.software_versions sv ON sv.id = sic2.software_version_id
                 JOIN catalog.products p ON p.id = sv.product_id
                 JOIN catalog.v_product_capability_effective cap ON cap.product_uuid = p.product_uuid
                WHERE sic2.tenant_id = 1 AND sic2.deleted_at IS NULL AND sic2.stale_since IS NULL
                  AND d.deleted_at IS NULL AND {current_computer_sql("d")}
                GROUP BY sic2.canonical_name"""
            if capability_available and needs_full_category_snapshot
            else "SELECT NULL::text AS canonical_name, NULL::text[] AS categories WHERE FALSE"
        )
        product_category_cte_sql = (
            f"""SELECT sic2.canonical_name,
                      array_agg(DISTINCT pce.category) AS product_categories
                 FROM operations.software_installations_current sic2
                 JOIN operations.devices d ON d.id = sic2.device_id AND d.tenant_id = sic2.tenant_id
                 JOIN catalog.software_versions sv ON sv.id = sic2.software_version_id
                 JOIN catalog.products p ON p.id = sv.product_id
                 JOIN catalog.v_product_category_effective pce ON pce.product_uuid = p.product_uuid
                WHERE sic2.tenant_id = 1 AND sic2.deleted_at IS NULL AND sic2.stale_since IS NULL
                  AND d.deleted_at IS NULL AND {current_computer_sql("d")}
                GROUP BY sic2.canonical_name"""
            if product_category_available and needs_full_category_snapshot
            else "SELECT NULL::text AS canonical_name, NULL::text[] AS product_categories WHERE FALSE"
        )
        cur.execute(
            f"""
            WITH current_titles AS MATERIALIZED (
                SELECT sic.tenant_id,
                       sic.canonical_name,
                       mode() WITHIN GROUP (ORDER BY sic.publisher) AS publisher,
                       COUNT(*)::integer AS installations,
                       COUNT(DISTINCT sic.device_id)::integer AS device_count,
                       COUNT(DISTINCT sic.client_id)::integer AS client_count,
                       MIN(sic.first_observed_at) AS first_observed_at,
                       MAX(sic.last_observed_at) AS last_observed_at,
                       MAX(sic.first_observed_at) AS latest_install
                FROM operations.software_installations_current sic
                JOIN operations.devices d
                  ON d.tenant_id = sic.tenant_id AND d.id = sic.device_id
                WHERE sic.tenant_id = 1
                  AND sic.deleted_at IS NULL
                  AND sic.stale_since IS NULL
                  AND d.deleted_at IS NULL
                  AND {current_computer_sql("d")}
                GROUP BY sic.tenant_id, sic.canonical_name
            ), totals AS (
                SELECT COALESCE(SUM(installations), 0)::bigint AS installations,
                       COUNT(*)::bigint AS unique_titles
                FROM current_titles
                WHERE tenant_id = 1
            ),
            category_by_title AS ({category_cte_sql}),
            product_category_by_title AS ({product_category_cte_sql}),
            {software_review.TITLE_STATUS_CTES},
            filtered AS (
                SELECT sic.canonical_name,
                       sic.publisher,
                       sic.device_count,
                       sic.client_count,
                       sic.latest_install AS last_install,
                       cbt.categories,
                       pcbt.product_categories,
                       {software_review.TITLE_STATUS} AS decision,
                       COUNT(*) OVER ()::bigint AS total_filtered
                FROM current_titles sic
                LEFT JOIN category_by_title cbt ON cbt.canonical_name = sic.canonical_name
                LEFT JOIN product_category_by_title pcbt ON pcbt.canonical_name = sic.canonical_name
                {software_review.TITLE_STATUS_JOINS}
                WHERE {where_sql}
                  AND sic.device_count >= {min_devices_int}
                ORDER BY {sort_sql}
                LIMIT {title_page_size} OFFSET {page_offset}
            )
            SELECT filtered.canonical_name,
                   filtered.publisher,
                   filtered.device_count,
                   filtered.client_count,
                   filtered.last_install,
                   filtered.categories,
                   filtered.product_categories,
                   filtered.decision,
                   totals.installations,
                   totals.unique_titles,
                   filtered.total_filtered
            FROM totals
            LEFT JOIN filtered ON TRUE
            """,
            params,
        )
        software_rows = cur.fetchall()
        installations = software_rows[0][8]
        unique_titles = software_rows[0][9]
        total_filtered = software_rows[0][10] or 0
        title_rows = [row[:8] for row in software_rows if row[0] is not None]

        canonical_names = [row[0] for row in title_rows]

        categories_by_title: dict[str, list[str]] = {}
        product_categories_by_title: dict[str, list[str]] = {}
        if canonical_names and capability_available:
            cur.execute(
                f"""
                SELECT sic.canonical_name,
                       array_agg(DISTINCT CASE cap.capability
                           WHEN 'endpoint_security' THEN 'av' ELSE cap.capability END)
                FROM operations.software_installations_current sic
                JOIN operations.devices d ON d.id = sic.device_id AND d.tenant_id = sic.tenant_id
                JOIN catalog.software_versions sv ON sv.id = sic.software_version_id
                JOIN catalog.products p ON p.id = sv.product_id
                JOIN catalog.v_product_capability_effective cap ON cap.product_uuid = p.product_uuid
                WHERE sic.tenant_id = 1 AND sic.deleted_at IS NULL AND sic.stale_since IS NULL
                  AND d.deleted_at IS NULL AND {current_computer_sql("d")}
                  AND sic.canonical_name = ANY(%s::text[])
                GROUP BY sic.canonical_name
                """,
                [canonical_names],
            )
            categories_by_title = {name: categories for name, categories in cur.fetchall()}
        if canonical_names and product_category_available:
            cur.execute(
                f"""
                SELECT sic.canonical_name, array_agg(DISTINCT pce.category)
                FROM operations.software_installations_current sic
                JOIN operations.devices d ON d.id = sic.device_id AND d.tenant_id = sic.tenant_id
                JOIN catalog.software_versions sv ON sv.id = sic.software_version_id
                JOIN catalog.products p ON p.id = sv.product_id
                JOIN catalog.v_product_category_effective pce ON pce.product_uuid = p.product_uuid
                WHERE sic.tenant_id = 1 AND sic.deleted_at IS NULL AND sic.stale_since IS NULL
                  AND d.deleted_at IS NULL AND {current_computer_sql("d")}
                  AND sic.canonical_name = ANY(%s::text[])
                GROUP BY sic.canonical_name
                """,
                [canonical_names],
            )
            product_categories_by_title = {
                name: categories for name, categories in cur.fetchall()
            }

        if intel_available and not needs_full_safety_snapshot and canonical_names:
            cur.execute(
                """
                SELECT canonical_name, safety_score, safety_band,
                       cve_count, kev_count, osint_hits
                FROM operations.v_software_safety
                WHERE tenant_id = 1 AND canonical_name = ANY(%s::text[])
                """,
                [canonical_names],
            )
            all_safety_rows = list(cur.fetchall())

        # Recent installations — last 24h, first-seen
        cur.execute(
            f"""
            SELECT sic.canonical_name, sic.publisher, c.display_name AS client,
                   sic.first_observed_at
            FROM operations.software_installations_current sic
            JOIN operations.clients c ON c.id = sic.client_id AND c.tenant_id = sic.tenant_id
            JOIN operations.devices d ON d.id = sic.device_id AND d.tenant_id = sic.tenant_id
            WHERE sic.tenant_id = 1 AND sic.deleted_at IS NULL
              AND sic.stale_since IS NULL
              AND d.deleted_at IS NULL AND {current_computer_sql("d")}
              AND sic.first_observed_at >= NOW() - INTERVAL '24 hours'
            ORDER BY sic.first_observed_at DESC
            LIMIT 10
            """
        )
        recent_installs = cur.fetchall()

    # The complete safety snapshot is used only for filtering/export. Both
    # ordinary HTML surfaces now enrich their bounded title page instead.
    safety_by_title: dict[str, dict] = {}
    shown_set = set(canonical_names)
    for cn, score, band, cve_count, kev_count, osint_hits in all_safety_rows:
        if not is_overview and band in risk_distribution:
            risk_distribution[band] += 1
        if not is_overview and band == "high":
            high_risk_titles += 1
        if cn in shown_set:
            safety_by_title[cn] = {
                "score": score,
                "band": band,
                "cve_count": cve_count,
                "kev_count": kev_count,
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
                f"""
                SELECT COUNT(DISTINCT sic.canonical_name)::int
                FROM operations.software_installations_current sic
                JOIN operations.devices d
                  ON d.tenant_id = sic.tenant_id AND d.id = sic.device_id
                WHERE sic.tenant_id = 1
                  AND sic.deleted_at IS NULL
                  AND sic.stale_since IS NULL
                  AND d.deleted_at IS NULL
                  AND {current_computer_sql("d")}
                  AND sic.first_observed_at >= NOW() - INTERVAL '7 days'
                """
            )
            (this_week["new_products"],) = sc.fetchone()
            sc.execute(
                f"""
                SELECT sic.canonical_name,
                       COUNT(DISTINCT sic.device_id)::int AS devices
                FROM operations.software_installations_current sic
                JOIN operations.devices d
                  ON d.tenant_id = sic.tenant_id AND d.id = sic.device_id
                WHERE sic.tenant_id = 1
                  AND sic.deleted_at IS NULL
                  AND sic.stale_since IS NULL
                  AND d.deleted_at IS NULL
                  AND {current_computer_sql("d")}
                  AND sic.first_observed_at >= NOW() - INTERVAL '7 days'
                GROUP BY sic.canonical_name
                ORDER BY devices DESC, sic.canonical_name
                LIMIT 1
                """
            )
            row = sc.fetchone()
            if row:
                this_week["top_new_product"] = {"name": row[0], "devices": row[1]}
        if is_overview and intel_available:
            with transaction.atomic(), connection.cursor() as sc:
                sc.execute("SET LOCAL operations.tenant_id = 1")
                sc.execute(
                    f"""
                    SELECT COUNT(*)::int
                    FROM operations.v_software_safety safety
                    WHERE safety.tenant_id = 1
                      AND safety.safety_band = 'high'
                      AND EXISTS (
                          SELECT 1
                          FROM operations.software_installations_current sic
                          JOIN operations.devices d
                            ON d.tenant_id = sic.tenant_id AND d.id = sic.device_id
                          WHERE sic.tenant_id = safety.tenant_id
                            AND sic.canonical_name = safety.canonical_name
                            AND sic.deleted_at IS NULL
                            AND sic.stale_since IS NULL
                            AND d.deleted_at IS NULL
                            AND {current_computer_sql("d")}
                            AND sic.first_observed_at >= NOW() - INTERVAL '7 days'
                      )
                    """
                )
                (this_week["new_high_risk"],) = sc.fetchone()
    except Exception:
        pass

    try:
        with transaction.atomic(), connection.cursor() as sc:
            sc.execute("SET LOCAL operations.tenant_id = 1")
            # Publishers whose installations an open prompt is about: the
            # publisher those uncovered installations report (ADR-0039).
            sc.execute(software_review.AWAITING_PUBLISHERS_SQL, [1])
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
        finding_type__issue_category=finding_registry.SOFTWARE,
    )
    software_issues = software_open_qs.exclude(finding_type__name="whitelist_suggestion").count()
    # Resolve the registry id before the distinct JSON aggregate.  Filtering
    # through the category/type joins made PostgreSQL abandon the existing
    # partial expression index on `finding_details -> 'canonical_name'`; on
    # production that aggregate then exceeded Gunicorn's 30-second timeout and
    # made the Products page return 500.  The direct predicate is equivalent
    # (the type is itself a software finding) and uses
    # idx_findings_type_canonical.
    prompt_type_ids = list(
        FindingType.objects.filter(name__in=_SOFTWARE_DECISION_PROMPT_TYPES).values_list(
            "id", flat=True
        )
    )
    whitelist_suggestions = (
        Finding.objects.filter(
            tenant_id=1,
            status__in=_FINDING_ACTIVE_STATUSES,
            finding_type_id__in=prompt_type_ids,
        )
        .values("finding_details__canonical_name")
        .distinct()
        .count()
        if prompt_type_ids
        else 0
    )

    # Title status counts from the records the software reconcile keeps per
    # title (ADR-0039), so they agree with Issues and Software review.
    status_counts: dict[str, int] = {}
    with transaction.atomic(), connection.cursor() as sc:
        sc.execute("SET LOCAL operations.tenant_id = 1")
        sc.execute(software_review.title_status_counts_sql(current_computer_sql("d")))
        status_counts = dict(sc.fetchall())
    approved_titles = status_counts.get("approve", 0)
    rejected_titles = status_counts.get("reject", 0)
    investigate_titles = status_counts.get("investigate", 0)
    pending_decisions = status_counts.get("pending", 0)
    classifier = EvaluatorConfig.objects.filter(
        tenant_id=1, evaluator_name="software_classifier"
    ).first()
    prompts_switched_off = software_review.prompt_types_switched_off(
        classifier.config if classifier else {}
    )

    titles = []
    for row in title_rows:
        canonical = row[0]
        safety = safety_by_title.get(canonical, {})
        titles.append(
            {
                "canonical_name": canonical,
                "publisher": row[1] or "",
                "device_count": row[2],
                "client_count": row[3],
                "last_install": row[4],
                "categories": categories_by_title.get(canonical, row[5] or []),
                "product_categories": product_categories_by_title.get(canonical, row[6] or []),
                "decision": row[7],
                "safety_score": safety.get("score"),
                "safety_band": safety.get("band", ""),
                "safety_cve_count": safety.get("cve_count", 0),
                "safety_kev_count": safety.get("kev_count", 0),
                "safety_osint_hits": safety.get("osint_hits", 0),
            }
        )

    return {
        "installations": installations,
        "unique_titles": unique_titles,
        "categorized_titles": categorized_titles,
        "uncategorized_titles": unique_titles - categorized_titles
        if unique_titles > categorized_titles
        else 0,
        "descriptive_categorized_titles": descriptive_categorized_titles,
        "descriptive_uncategorized_titles": unique_titles - descriptive_categorized_titles
        if unique_titles > descriptive_categorized_titles
        else 0,
        "descriptive_category_rows": descriptive_category_rows,
        "active_product_category": product_category_filter,
        # Every active filter, pre-encoded, so sort/page links can reuse it
        # without reconstructing the whole filter set inline in the
        # template -- append &sort=<key>&dir=<asc|desc> or &page=<n>.
        "filter_qs": urlencode(
            {
                k: v
                for k, v in {
                    "q": q_filter,
                    "publisher": publisher_filter,
                    "min_devices": min_devices_int or "",
                    "safety": safety_filter,
                    "decision": decision_filter,
                    "category": category_filter,
                    "product_category": product_category_filter,
                    "flagged": "1" if flagged_filter else "",
                }.items()
                if v
            }
        ),
        "total_filtered": total_filtered,
        "page_num": page_num,
        "page_size": page_size,
        "total_pages": max(1, -(-total_filtered // page_size)),
        "page_offset_display": (page_offset + 1) if total_filtered else 0,
        "page_end_display": min(page_offset + page_size, total_filtered),
        "active_sort": sort_key,
        "active_dir": sort_dir,
        "approved_titles": approved_titles,
        "rejected_titles": rejected_titles,
        "investigate_titles": investigate_titles,
        "pending_decisions": pending_decisions,
        "prompts_switched_off": prompts_switched_off,
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
                ("Type", "product_categories"),
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
    try:
        install_page = max(1, int(request.GET.get("install_page", "1")))
    except ValueError:
        install_page = 1
    install_page_size = 100
    install_offset = (install_page - 1) * install_page_size

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")

        # Fleet-wide install rollup for this title.
        cur.execute(
            f"""
            SELECT COUNT(*)                             AS installations,
                   COUNT(DISTINCT sic.device_id)        AS devices,
                   COUNT(DISTINCT sic.client_id)        AS clients,
                   MIN(sic.first_observed_at)           AS first_observed,
                   MAX(sic.last_observed_at)            AS last_observed,
                   MAX(sic.first_observed_at)           AS latest_install
            FROM operations.software_installations_current sic
            JOIN operations.devices d ON d.id = sic.device_id AND d.tenant_id = sic.tenant_id
            WHERE sic.tenant_id = 1
              AND sic.deleted_at IS NULL
              AND sic.stale_since IS NULL
              AND d.deleted_at IS NULL
              AND {current_computer_sql("d")}
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
            f"""
            SELECT COALESCE(NULLIF(sic.publisher, ''), '(unknown)') AS publisher,
                   COUNT(*)::int AS installs,
                   COUNT(DISTINCT sic.device_id)::int AS devices
            FROM operations.software_installations_current sic
            JOIN operations.devices d ON d.id = sic.device_id AND d.tenant_id = sic.tenant_id
            WHERE sic.tenant_id = 1 AND sic.deleted_at IS NULL AND sic.stale_since IS NULL
              AND d.deleted_at IS NULL AND {current_computer_sql("d")}
              AND LOWER(sic.canonical_name) = LOWER(%s)
            GROUP BY 1
            ORDER BY installs DESC
            """,
            [canonical_name],
        )
        publisher_rows = [
            {"publisher": row[0], "installs": row[1], "devices": row[2]} for row in cur.fetchall()
        ]

        # Version breakdown — one row per distinct version.
        cur.execute(
            f"""
            SELECT COALESCE(NULLIF(sic.version, ''), '(unknown)') AS version,
                   COUNT(*)::int AS installs,
                   COUNT(DISTINCT sic.device_id)::int AS devices,
                   COUNT(DISTINCT sic.client_id)::int AS clients,
                   MAX(sic.last_observed_at) AS last_observed
            FROM operations.software_installations_current sic
            JOIN operations.devices d ON d.id = sic.device_id AND d.tenant_id = sic.tenant_id
            WHERE sic.tenant_id = 1 AND sic.deleted_at IS NULL AND sic.stale_since IS NULL
              AND d.deleted_at IS NULL AND {current_computer_sql("d")}
              AND LOWER(sic.canonical_name) = LOWER(%s)
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
            f"""
            SELECT COALESCE(NULLIF(install_location, ''), '(unknown)') AS location,
                   COUNT(*)::int AS installs
            FROM operations.software_installations_current sic
            JOIN operations.devices d ON d.id = sic.device_id AND d.tenant_id = sic.tenant_id
            WHERE sic.tenant_id = 1 AND sic.deleted_at IS NULL AND sic.stale_since IS NULL
              AND d.deleted_at IS NULL AND {current_computer_sql("d")}
              AND LOWER(sic.canonical_name) = LOWER(%s)
            GROUP BY 1
            ORDER BY installs DESC
            LIMIT 20
            """,
            [canonical_name],
        )
        location_rows = [{"location": row[0], "installs": row[1]} for row in cur.fetchall()]

        # Per-device installation list. Its membership matches the header
        # rollup; pagination limits rendering only, not the selected scope.
        cur.execute(
            f"""
            SELECT sic.device_id, sic.client_id, c.slug, c.display_name,
                   d.canonical_hostname, d.device_role, d.os_group,
                   sic.version, sic.install_location, sic.install_date,
                   sic.first_observed_at, sic.last_observed_at
            FROM operations.software_installations_current sic
            JOIN operations.clients c ON c.id = sic.client_id AND c.tenant_id = sic.tenant_id
            JOIN operations.devices d ON d.id = sic.device_id AND d.tenant_id = sic.tenant_id
            WHERE sic.tenant_id = 1
              AND sic.deleted_at IS NULL
              AND sic.stale_since IS NULL
              AND d.deleted_at IS NULL
              AND {current_computer_sql("d")}
              AND LOWER(sic.canonical_name) = LOWER(%s)
            ORDER BY c.display_name, d.canonical_hostname
            LIMIT %s OFFSET %s
            """,
            [canonical_name, install_page_size, install_offset],
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
                "score": row[0],
                "band": row[1],
                "cve_count": row[2],
                "kev_count": row[3],
                "osint_hits": row[4],
                "publisher_osint_hits": row[5],
                "max_cvss": row[6],
                "max_epss": row[7],
                "title_approved": row[8],
                "title_rejected": row[9],
                "publisher_approved": row[10],
                "publisher_rejected": row[11],
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
            matched_cves.append(
                {
                    "cve_id": r[0],
                    "severity": r[1],
                    "cvss_v3": r[2],
                    "epss_score": r[3],
                    "kev_flag": r[4],
                    "kev_added_at": r[5],
                    "description": (r[6] or "")[:400],
                    "confidence": r[7],
                    "match_kind": r[8],
                }
            )
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
            osint_rows.append(
                {
                    "source": r[0],
                    "signal_type": r[1],
                    "severity": r[2],
                    "details": r[3],
                    "observed_at": r[4],
                }
            )

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
        SoftwareDecision.objects.filter(tenant_id=1, canonical_name__iexact=canonical_name)
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
    all_capabilities = capability_evidence.all_capabilities()
    capability_product_rows = [
        {
            "product_uuid": product_uuid,
            "rows": (rows := capability_by_product.get(product_uuid, [])),
            # A curator may need to assert a capability nothing has ever
            # suggested -- not just react to a machine candidate -- so every
            # key the product has no row for at all is offered separately
            # from the confirm/reject controls above, which only cover keys
            # with existing evidence.
            "missing": [
                (key, label)
                for key, label in all_capabilities
                if key not in {r["capability"] for r in rows}
            ],
        }
        for product_uuid in capability_product_uuids
    ]
    can_curate_capability = request.user.has_perm(capability_evidence.CURATOR_PERMISSION)

    # Descriptive category (migration 104) -- same product-identity shape as
    # capability above, separate table, separate permission, no alertable axis.
    category_schema_ready = category_evidence.schema_ready()
    category_product_uuids = category_evidence.products_for_title(canonical_name)
    category_by_product = category_evidence.effective_for_products(category_product_uuids)
    all_categories = category_evidence.all_categories()
    category_product_rows = [
        {
            "product_uuid": product_uuid,
            "rows": (rows := category_by_product.get(product_uuid, [])),
            "missing": [
                (key, label)
                for key, label in all_categories
                if key not in {r["category"] for r in rows}
            ],
        }
        for product_uuid in category_product_uuids
    ]
    can_curate_category = request.user.has_perm(category_evidence.CURATOR_PERMISSION)

    # Authorizing a product is a different decision from settling what it is,
    # so it carries its own permission and its own control.
    can_authorize_software = request.user.has_perm(capability_evidence.AUTHORIZE_PERMISSION)
    # Authorization is written against a client UUID.  Use the complete
    # current-installation relation here rather than `install_rows`, which is
    # deliberately capped at 500 rows for page rendering.  The counts make a
    # narrow permit/deny intelligible before an operator commits it.
    authorization_clients: list[dict] = []
    if can_authorize_software and capability_product_rows:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                f"""
                SELECT c.id, c.display_name,
                       COUNT(DISTINCT sic.device_id)::int AS device_count,
                       COUNT(*)::int AS installation_count
                FROM operations.software_installations_current sic
                JOIN operations.clients c ON c.id = sic.client_id AND c.tenant_id = sic.tenant_id
                JOIN operations.devices d ON d.id = sic.device_id AND d.tenant_id = sic.tenant_id
                WHERE sic.tenant_id = 1
                  AND sic.deleted_at IS NULL
                  AND sic.stale_since IS NULL
                  AND d.deleted_at IS NULL
                  AND {current_computer_sql("d")}
                  AND LOWER(sic.canonical_name) = LOWER(%s)
                GROUP BY c.id, c.display_name
                ORDER BY LOWER(c.display_name), c.id
                """,
                [canonical_name],
            )
            authorization_clients = [
                {
                    "id": row[0],
                    "display_name": row[1],
                    "device_count": row[2],
                    "installation_count": row[3],
                }
                for row in cur.fetchall()
            ]

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
            "install_page": install_page,
            "install_page_size": install_page_size,
            "install_pages": max(1, -(-installations // install_page_size)),
            "install_has_previous": install_page > 1,
            "install_has_next": install_page * install_page_size < installations,
            "install_previous_page": install_page - 1,
            "install_next_page": install_page + 1,
            "global_decision": global_decision,
            "decision_scope_clients": decision_scope_clients,
            "decision_scope_devices": decision_scope_devices,
            "capability_schema_ready": capability_schema_ready,
            "capability_product_rows": capability_product_rows,
            "can_curate_capability": can_curate_capability,
            "category_schema_ready": category_schema_ready,
            "category_product_rows": category_product_rows,
            "can_curate_category": can_curate_category,
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
        messages.error(
            request, "A product identity, capability, and confirm or reject decision are required."
        )
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
def software_category_decide(request: HttpRequest) -> HttpResponse:
    """Confirm or reject global descriptive category for one product identity.

    Mirrors software_capability_decide exactly. Never touches an
    unauthorized_* finding or any alerting path -- migration 104's
    v_product_category_effective has no alertable axis at all.
    """
    if not request.user.has_perm(category_evidence.CURATOR_PERMISSION):
        messages.error(request, "Platform-curator permission is required for category decisions.")
        return redirect(_safe_next(request, "software_page"))

    product_uuid = (request.POST.get("product_uuid") or "").strip()
    category = (request.POST.get("category") or "").strip()
    decision = (request.POST.get("decision") or "").strip()
    rationale = (request.POST.get("rationale") or "").strip()
    if decision not in {"confirm", "reject"} or not product_uuid or not category:
        messages.error(
            request, "A product identity, category, and confirm or reject decision are required."
        )
        return redirect(_safe_next(request, "software_page"))
    try:
        product_id = uuid.UUID(product_uuid)
    except ValueError:
        messages.error(request, "Invalid product identity.")
        return redirect(_safe_next(request, "software_page"))

    polarity = decision == "confirm"
    try:
        with transaction.atomic():
            category_evidence.confirm(
                str(product_id), category, polarity, request.user.get_username(), rationale
            )
    except (category_evidence.CategorySchemaUnavailable, IntegrityError, ValueError) as exc:
        messages.error(request, str(exc))
        return redirect(_safe_next(request, "software_page"))

    AuditLog.objects.create(
        tenant_id=1,
        actor=request.user,
        actor_kind=AuditLog.ActorKind.USER,
        source=AuditLog.Source.UI,
        action="software_category.confirm" if polarity else "software_category.reject",
        entity_type="catalog.product_category",
        entity_id=product_id,
        before_state={},
        after_state={
            "product_uuid": str(product_id),
            "category": category,
            "polarity": polarity,
            "rationale": rationale,
        },
        ip_address=request.META.get("REMOTE_ADDR") or None,
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:2000],
    )
    messages.success(
        request,
        f"Category {'confirmed' if polarity else 'rejected'} for the selected product identity.",
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
    if not request.user.has_perm(capability_evidence.AUTHORIZE_PERMISSION):
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
        messages.error(
            request, "A product identity, capability, and permit or deny decision are required."
        )
        return redirect(_safe_next(request, "software_page"))
    if not rationale:
        messages.error(
            request, "A rationale is required so the authorization can be reviewed later."
        )
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


def _publisher_decision_vocabulary() -> list[tuple[str, str, str, str]]:
    """(stored decision, action verb, state label, filter key) for publishers.

    One vocabulary for every control on the publishers page: the row buttons
    and the bulk list say the action, the decision column and the filter say
    the resulting state. A publisher-scope decision is approve_publisher,
    reject or investigate; a legacy publisher row stored as approve reads as
    approved.
    """
    return [
        ("approve_publisher", "Approve", "Approved", "approved"),
        ("reject", "Reject", "Rejected", "rejected"),
        ("investigate", "Investigate", "Investigating", "investigate"),
    ]


@login_required
def software_publishers(request: HttpRequest) -> HttpResponse:
    """List publishers with per-publisher install/product counts and
    current publisher-scope decision status. Supports filtering by name
    and by decision state (approved / rejected / investigating / none)."""
    q_filter = (request.GET.get("q") or "").strip()
    decision_filter = (request.GET.get("decision") or "").strip().lower()

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")

        params: list = []
        extra_where = ""
        if q_filter:
            extra_where = "AND sic.publisher ILIKE %s"
            params.append(f"%{q_filter}%")

        cur.execute(
            f"""
            SELECT COALESCE(NULLIF(sic.publisher, ''), '(unknown)') AS publisher,
                   COUNT(*)::int AS installations,
                   COUNT(DISTINCT sic.canonical_name)::int AS titles,
                   COUNT(DISTINCT sic.device_id)::int AS devices,
                   COUNT(DISTINCT sic.client_id)::int AS clients,
                   MAX(sic.last_observed_at) AS last_observed
            FROM operations.software_installations_current sic
            JOIN operations.devices d
              ON d.id = sic.device_id AND d.tenant_id = sic.tenant_id
            WHERE sic.tenant_id = 1
              AND sic.deleted_at IS NULL
              AND sic.stale_since IS NULL
              AND d.deleted_at IS NULL
              AND {current_computer_sql("d")}
              {extra_where}
            GROUP BY 1
            ORDER BY installations DESC, publisher
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

    vocabulary = _publisher_decision_vocabulary()
    state_labels = {value: state for value, _verb, state, _key in vocabulary}
    state_labels["approve"] = state_labels["approve_publisher"]
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
                "decision_label": state_labels.get(dec.decision, dec.decision) if dec else "",
                # PublisherCategory is retired as a competing capability path.
                # Product capability evidence appears on the title detail page,
                # where the stable product identity and its provenance are
                # visible; a publisher-wide label is too broad to be truth.
                "category": "",
            }
        )

    # Filter by decision state after computing all decisions.
    if decision_filter == "approved":
        publishers = [
            p for p in publishers if p["global_decision"] in ("approve", "approve_publisher")
        ]
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
            "decision_choices": [(value, verb) for value, verb, _state, _key in vocabulary],
            "decision_filters": [(key, state) for _value, _verb, state, key in vocabulary]
            + [("pending", "No decision")],
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
    try:
        title_page = max(1, int(request.GET.get("title_page", "1")))
    except ValueError:
        title_page = 1
    title_page_size = 100
    title_offset = (title_page - 1) * title_page_size

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
            f"""
            SELECT COUNT(*)::int AS installations,
                   COUNT(DISTINCT sic.canonical_name)::int AS titles,
                   COUNT(DISTINCT sic.device_id)::int AS devices,
                   COUNT(DISTINCT sic.client_id)::int AS clients,
                   MIN(sic.first_observed_at) AS first_observed,
                   MAX(sic.last_observed_at) AS last_observed
            FROM operations.software_installations_current sic
            JOIN operations.devices d ON d.id = sic.device_id AND d.tenant_id = sic.tenant_id
            WHERE sic.tenant_id = 1 AND sic.deleted_at IS NULL AND sic.stale_since IS NULL
              AND d.deleted_at IS NULL AND {current_computer_sql("d")}
              AND LOWER(sic.publisher) = LOWER(%s)
            """,
            [pub],
        )
        installations, titles, devices, clients, first_observed, last_observed = cur.fetchone()

        # Titles under this publisher. Pagination limits presentation only;
        # the header count remains the complete current-installation scope.
        cur.execute(
            f"""
            SELECT sic.canonical_name,
                   COUNT(*)::int AS installs,
                   COUNT(DISTINCT sic.device_id)::int AS device_count,
                   COUNT(DISTINCT sic.client_id)::int AS client_count,
                   MAX(sic.last_observed_at) AS last_observed
            FROM operations.software_installations_current sic
            JOIN operations.devices d ON d.id = sic.device_id AND d.tenant_id = sic.tenant_id
            WHERE sic.tenant_id = 1 AND sic.deleted_at IS NULL AND sic.stale_since IS NULL
              AND d.deleted_at IS NULL AND {current_computer_sql("d")}
              AND LOWER(sic.publisher) = LOWER(%s)
            GROUP BY sic.canonical_name
            ORDER BY installs DESC, canonical_name
            LIMIT %s OFFSET %s
            """,
            [pub, title_page_size, title_offset],
        )
        title_rows_raw = cur.fetchall()

        # Scope targets are limited to current installations of this publisher.
        # A publisher-wide decision may only be narrowed to a client/device
        # that actually runs one of its products.
        cur.execute(
            f"""
            SELECT DISTINCT ON (sic.device_id)
                   sic.device_id, c.slug, c.display_name, d.canonical_hostname
              FROM operations.software_installations_current sic
              JOIN operations.clients c ON c.id = sic.client_id
              JOIN operations.devices d ON d.id = sic.device_id
             WHERE sic.tenant_id = 1 AND sic.deleted_at IS NULL
               AND sic.stale_since IS NULL
               AND d.deleted_at IS NULL AND {current_computer_sql("d")}
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
    client_pub_decisions = [d for d in pub_decision_rows if d.client_id and not d.device_id]
    device_pub_decisions = [d for d in pub_decision_rows if d.device_id]
    decision_scope_clients, decision_scope_devices = _decision_scope_targets(publisher_scope_rows)

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
            "title_page": title_page,
            "title_page_size": title_page_size,
            "title_pages": max(1, -(-titles // title_page_size)),
            "title_has_previous": title_page > 1,
            "title_has_next": title_page * title_page_size < titles,
            "title_previous_page": title_page - 1,
            "title_next_page": title_page + 1,
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
    is_csv = wants_csv(request)
    try:
        page_number = max(1, int(request.GET.get("page", "1")))
    except ValueError:
        page_number = 1
    # The page presents nested device and item detail for each user.  The
    # deployed 100-user first view transferred 927 KB and took 4.3 s to first
    # response in an authenticated browser check.  Keep the existing complete
    # ranking and totals, but bound that detail more tightly; pagination and
    # CSV remain the deliberate paths to the full filtered result.
    page_size = 25
    page_rank_start = (page_number - 1) * page_size
    q_pattern = q_filter.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    kind_pattern = (
        kind_filter.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
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
        WITH
        device_user AS (
            SELECT last_user_current.device_id AS ops_device_id,
                   last_user_current.last_user,
                   last_user_current.projected_at AS snapshot_at
            FROM operations.v_device_last_user_current last_user_current
        ),
        finding_items AS (
            SELECT d.id AS device_id, d.client_id,
                   e.canonical_name,
                   e.finding_type AS kind
            FROM operations.v_device_software_exposure e
            JOIN operations.devices d ON d.id = e.device_id AND d.deleted_at IS NULL
                                      AND {current_computer_sql("d")}
            WHERE e.tenant_id = 1
              AND e.status IN ('open', 'acknowledged')
              AND e.finding_type <> 'whitelist_suggestion'
              {client_where}
        ),
        -- Split by scope instead of matching with OR. `sd` was joined to
        -- `sic` on the OR of a title match or a publisher match, and the
        -- planner could not use either as an index condition: it built the
        -- full devices x software_decisions cross product (5,453 x 254 rows
        -- measured), hashed that, joined it to all 530k installations, then
        -- applied the OR as a Join Filter removing 44.8 million rows.
        -- `ck_software_decisions_scope_key_xor` guarantees canonical_name and
        -- publisher are never both set, so splitting into two UNION ALL
        -- branches -- each a real equi-join -- cannot double-count. Measured
        -- 2026-08-18: 1.9 s against 38.9 s for identical rows.
        decision_items AS (
            SELECT d.id AS device_id, d.client_id, sic.canonical_name,
                   ('decision_' || sd.decision) AS kind
            FROM operations.software_decisions sd
            JOIN operations.software_installations_current sic
              ON sic.tenant_id = sd.tenant_id
             AND sic.canonical_name = sd.canonical_name
             AND sic.deleted_at IS NULL
             AND sic.stale_since IS NULL
            JOIN operations.devices d ON d.id = sic.device_id AND d.deleted_at IS NULL
                                      AND {current_computer_sql("d")}
            WHERE sd.tenant_id = 1
              AND sd.decision IN ('reject', 'investigate')
              AND sd.canonical_name <> ''
              AND (sd.device_id IS NULL OR sd.device_id = sic.device_id)
              AND (sd.client_id IS NULL OR sd.client_id = sic.client_id)
              {client_where}

            UNION ALL

            SELECT d.id AS device_id, d.client_id, sic.canonical_name,
                   ('decision_' || sd.decision) AS kind
            FROM operations.software_decisions sd
            JOIN operations.software_installations_current sic
              ON sic.tenant_id = sd.tenant_id
             AND LOWER(sic.publisher) = LOWER(sd.publisher)
             AND sic.deleted_at IS NULL
             AND sic.stale_since IS NULL
            JOIN operations.devices d ON d.id = sic.device_id AND d.deleted_at IS NULL
                                      AND {current_computer_sql("d")}
            WHERE sd.tenant_id = 1
              AND sd.decision IN ('reject', 'investigate')
              AND sd.publisher <> ''
              AND (sd.device_id IS NULL OR sd.device_id = sic.device_id)
              AND (sd.client_id IS NULL OR sd.client_id = sic.client_id)
              {client_where}
        ),
        all_items AS (
            SELECT device_id, client_id, canonical_name, kind FROM finding_items
            UNION ALL
            SELECT device_id, client_id, canonical_name, kind FROM decision_items
        )
    """

    if is_csv:
        # CSV is an explicit export request, so it deliberately retains the
        # complete filtered result rather than inheriting the HTML first-view
        # boundary below.
        result_sql = f"""
            SELECT du.last_user,
                   d.id AS device_id,
                   d.canonical_hostname,
                   c.slug AS client_slug,
                   c.display_name AS client_name,
                   ai.canonical_name,
                   ai.kind
            FROM device_user du
            JOIN operations.devices d ON d.id = du.ops_device_id AND d.deleted_at IS NULL
                                      AND {current_computer_sql("d")}
            JOIN operations.clients c ON c.id = d.client_id AND c.deleted_at IS NULL
            JOIN all_items ai ON ai.device_id = d.id
            WHERE d.tenant_id = 1
              {client_where}
              {"AND LOWER(du.last_user) LIKE %s ESCAPE '\\'" if q_filter else ""}
              {"AND LOWER(ai.kind) LIKE %s ESCAPE '\\'" if kind_filter else ""}
            ORDER BY du.last_user, d.canonical_hostname, ai.kind, ai.canonical_name
        """
    else:
        # The operator page renders one bounded page of highest-impact users.
        # Materialising the joined items keeps the existing meaning and totals
        # while selecting the bounded first view before rows cross the
        # application boundary.
        result_sql = f"""
            , joined_items AS MATERIALIZED (
                SELECT du.last_user,
                       d.id AS device_id,
                       d.canonical_hostname,
                       c.slug AS client_slug,
                       c.display_name AS client_name,
                       ai.canonical_name,
                       ai.kind
                FROM device_user du
                JOIN operations.devices d ON d.id = du.ops_device_id AND d.deleted_at IS NULL
                                          AND {current_computer_sql("d")}
                JOIN operations.clients c ON c.id = d.client_id AND c.deleted_at IS NULL
                JOIN all_items ai ON ai.device_id = d.id
                WHERE d.tenant_id = 1
                  {client_where}
                  {"AND LOWER(du.last_user) LIKE %s ESCAPE '\\'" if q_filter else ""}
                  {"AND LOWER(ai.kind) LIKE %s ESCAPE '\\'" if kind_filter else ""}
            ),
            deduplicated_items AS MATERIALIZED (
                SELECT DISTINCT ON (last_user, device_id, canonical_name, kind)
                       last_user, device_id, canonical_hostname, client_slug,
                       client_name, canonical_name, kind
                FROM joined_items
                ORDER BY last_user, device_id, canonical_name, kind
            ),
            ranked_users AS MATERIALIZED (
                SELECT last_user,
                       COUNT(*) AS item_count,
                       COUNT(*) OVER () AS user_count,
                       SUM(COUNT(*)) OVER () AS total_items,
                       ROW_NUMBER() OVER (
                           ORDER BY COUNT(*) DESC, last_user
                       ) AS user_rank
                FROM deduplicated_items
                GROUP BY last_user
            )
            SELECT item.last_user,
                   item.device_id,
                   item.canonical_hostname,
                   item.client_slug,
                   item.client_name,
                   item.canonical_name,
                   item.kind,
                   ranked.item_count,
                   ranked.user_count,
                   ranked.total_items
            FROM deduplicated_items item
            JOIN ranked_users ranked ON ranked.last_user = item.last_user
            WHERE ranked.user_rank > {page_rank_start}
              AND ranked.user_rank <= {page_rank_start + page_size}
            ORDER BY ranked.item_count DESC,
                     item.last_user,
                     item.canonical_hostname,
                     item.kind,
                     item.canonical_name
        """

    sql += result_sql

    # client_where appears 4x in the SQL (finding_items, both decision_items
    # branches, the final WHERE) — client_params must repeat.
    run_params = client_params * 4 if client_params else []
    if q_filter:
        run_params.append(f"%{q_pattern}%")
    if kind_filter:
        run_params.append(f"%{kind_pattern}%")

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(sql, run_params)
        rows = cur.fetchall()

    per_user: dict = {}
    user_count = 0
    total_items = 0
    for row in rows:
        if is_csv:
            last_user, device_id, hostname, client_slug, client_name, canonical, kind = row
            item_count = None
        else:
            (
                last_user,
                device_id,
                hostname,
                client_slug,
                client_name,
                canonical,
                kind,
                item_count,
                user_count,
                total_items,
            ) = row
        entry = per_user.setdefault(
            last_user,
            {
                "last_user": last_user,
                "devices": {},
                "clients": set(),
                "item_count": item_count or 0,
                "item_keys": set() if is_csv else None,
            },
        )
        item_key = (device_id, (canonical or "").lower(), kind)
        if is_csv and item_key in entry["item_keys"]:
            continue
        if is_csv:
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
        entry["device_list"] = sorted(entry["devices"].values(), key=lambda d: d["hostname"] or "")
        entry.pop("devices", None)
        users.append(entry)
    users.sort(key=lambda u: (-u["item_count"], u["last_user"]))

    clients = Client.objects.filter(tenant_id=1, deleted_at__isnull=True).order_by("display_name")

    if is_csv:
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

    # Category is presentational data for the bounded HTML result only.  CSV
    # does not expose it, so avoid the formerly estate-wide catalog lookup.
    all_ur_canonicals = {
        i["canonical_name"].lower()
        for u in users
        for d in u["device_list"]
        for i in d["items"]
        if i["canonical_name"]
    }
    ur_catalog_cats = (
        {
            c.canonical_name.lower(): ", ".join(c.categories or [])
            for c in SoftwareCatalog.objects.filter(canonical_name__in=list(all_ur_canonicals))
        }
        if all_ur_canonicals
        else {}
    )
    for u in users:
        for d in u["device_list"]:
            for item in d["items"]:
                item["category"] = ur_catalog_cats.get((item["canonical_name"] or "").lower(), "")

    return render(
        request,
        "software_user_risk.html",
        {
            "users": users,
            "user_count": user_count,
            "total_items": total_items,
            "clients": clients,
            "active_clients": client_slugs,
            "active_q": q_filter,
            "active_kind": kind_filter,
            "page_number": page_number,
            "page_size": page_size,
            "page_count": max(1, -(-user_count // page_size)),
            "software_tab": "user-risk",
        },
    )


# ─────────────────────────────────────────────────────────────────────
# Jobs — operator-facing catalog of every scheduled ingest / intel /
# evaluator / notifier job with last-run status and a "Run now" button
# that POSTs to the ingest container's /run/<slug> HTTP endpoint.
# ─────────────────────────────────────────────────────────────────────


_INGEST_BASE_URL = os.environ.get("INGEST_BASE_URL", "http://ingest:8090")

# The shared registry is the catalog. Views only project it with live Runs.
validate_registry(catalog_keys=(item.key for item in definitions()))

_OPERATOR_JOB_CATALOG: list[dict] = [
    {
        "id": job.key,
        "group_key": job.group_key,
        "name": job.name,
        "description": job.description,
        "start_description": job.start_description,
        "execution_keys": job.execution_keys,
        "primary_execution_key": job.primary_execution_key,
    }
    for job in operator_job_definitions()
]

_JOBS_DIAGNOSTIC_SECTIONS = (
    ("coverage", "Coverage"),
    ("definition_versions", "Definition revisions"),
    ("schedules", "Schedules"),
    ("schedule_events", "Schedule events"),
    ("requests", "Request aliases"),
    ("runs", "Runs"),
    ("events", "Run events"),
    ("dependencies", "Dependencies"),
    ("domain_attempts", "Domain attempts"),
    ("resource_limits", "Execution limits and data safety"),
    ("resource_claims", "Resource claims"),
    ("recovery_authorities", "Recovery authority"),
    ("recovery_policies", "Recovery policy"),
    ("recovery_assessments", "Recovery evidence"),
    ("runtimes", "Runtime heartbeats"),
)
_JOBS_DIAGNOSTIC_KEYS = frozenset(key for key, _label in _JOBS_DIAGNOSTIC_SECTIONS)
_JOBS_RECOVERY_DIAGNOSTIC_KEYS = frozenset(
    {
        "recovery_authorities",
        "recovery_policies",
        "recovery_assessments",
    }
)

_MANAGED_SCHEDULE_REASON = "Managed by its operation entry point."
# Placeholder older runs recorded as their stage detail; never shown.
_NO_MEASURABLE_TOTAL = "This job does not publish a measurable work total."
_WORKER_RESTART_INTERRUPTION = "Jobs worker shutdown interrupted the handler"


def _software_removal_reason(reason: str) -> str:
    """Plain wording for why an installation left the current inventory."""
    return {
        "ninja.inventory.not_listed": "No longer listed by Ninja",
        "ninja.ingest.complete_snapshot_missing": "Missing from a full Ninja snapshot",
    }.get(reason or "", reason or "Removed")


def _run_progress(done, total, unit) -> dict | None:
    """How far a running Job is, for the progress bar (migration 0287)."""
    if done is None:
        return None
    done = int(done)
    unit = unit or "items"
    if total:
        total = int(total)
        percent = min(100, round(done * 100 / total))
        return {"done": done, "total": total, "unit": unit, "percent": percent,
                "label": f"{done:,} of {total:,} {unit} ({percent}%)"}
    return {"done": done, "total": None, "unit": unit, "percent": None,
            "label": f"{done:,} {unit} so far"}


def _run_summary(result, rows_touched) -> str:
    """What a finished Run did: the Job's own summary, else its item count."""
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except ValueError:
            result = {}
    summary = (result or {}).get("summary") if isinstance(result, dict) else None
    if summary:
        return str(summary)
    return f"{rows_touched:,} updated." if rows_touched is not None else ""


def _running_detail(stage: str, stage_detail: str) -> str:
    return stage if stage_detail in ("", _NO_MEASURABLE_TOTAL) else stage_detail


def _job_has_upstream_trigger(execution_keys: tuple[str, ...]) -> bool:
    """Return whether another registered Job can start this Job."""
    return any(
        successor.successor in execution_keys
        for candidate in definitions()
        for successor in candidate.successors
    )


def _schedule_cadence_label(cadence: dict | None) -> str:
    """Render one persisted cadence without exposing its storage shape."""
    if not cadence:
        return ""
    if cadence.get("kind") == "daily":
        return "Every day"
    minutes = cadence.get("minutes")
    if not isinstance(minutes, int) or minutes < 1:
        return ""
    if minutes == 60:
        return "Every hour"
    if minutes % 1440 == 0:
        days = minutes // 1440
        return "Every day" if days == 1 else f"Every {days} days"
    if minutes % 60 == 0:
        return f"Every {minutes // 60} hours"
    return f"Every {minutes} minutes"


def _interrupted_run_presentation(status: str, error: str) -> tuple[str, str, str] | None:
    """Render a deployment interruption without calling the underlying work failed."""
    if status not in {"failed", "stalled"} or _WORKER_RESTART_INTERRUPTION not in error:
        return None
    return (
        "interrupted",
        "Will retry automatically",
        "The Jobs service restarted before this run finished. It will run again automatically.",
    )


def _job_schedule_presentation(
    execution_keys: tuple[str, ...],
    schedules: list[dict],
    *,
    start_description: str,
    available: bool,
    availability_label: str,
) -> dict:
    """Describe how an operator can expect a Job to start."""
    if not available:
        return {"label": "Disabled", "detail": availability_label, "next_due_at": None}

    enabled = [schedule for schedule in schedules if schedule["enabled"]]
    data_triggered = any(
        schedule["reason"] == _MANAGED_SCHEDULE_REASON for schedule in schedules
    ) or _job_has_upstream_trigger(execution_keys)
    if enabled:
        cadence = _schedule_cadence_label(enabled[0]["cadence"])
        if data_triggered:
            detail = start_description or "After related data changes"
            if cadence:
                detail += f"; full update {cadence.lower()}"
            label = "Runs automatically"
        else:
            detail = ""
            label = cadence or "Runs automatically"
        return {
            "label": label,
            "detail": detail,
            "next_due_at": min(
                (schedule["next_due_at"] for schedule in enabled if schedule["next_due_at"]),
                default=None,
            ),
        }
    if data_triggered:
        return {
            "label": start_description or "After related data changes",
            "detail": "",
            "next_due_at": None,
        }
    if schedules:
        reason = next((schedule["reason"] for schedule in schedules if schedule["reason"]), "")
        if reason.startswith("Waiting for source"):
            return {"label": "Runs when requested", "detail": "", "next_due_at": None}
        return {"label": "Disabled", "detail": reason or "Not available", "next_due_at": None}
    return {"label": "Run manually", "detail": "", "next_due_at": None}


def _source_job_rows() -> list[dict]:
    """Project each configured source into the complete Jobs execution view."""
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """
            SELECT binding.id, source.name, client.display_name, binding.schedule,
                   latest.id, latest.status, latest.requested_at, latest.started_at,
                   latest.completed_at, latest.rows_touched, latest.error,
                   latest.wait_category, latest.wait_reason, latest.stage,
                   latest.stage_detail,
                   terminal.status, terminal.completed_at, terminal.rows_touched,
                   terminal.error,
                   (native_latest.id IS NULL AND legacy_terminal.id IS NOT NULL)
              FROM operations.source_bindings binding
              JOIN operations.source_instances instance
                ON instance.id = binding.source_instance_id
               AND instance.tenant_id = binding.tenant_id
              JOIN operations.sources source ON source.id = instance.source_id
         LEFT JOIN operations.clients client ON client.id = instance.client_id
         LEFT JOIN LATERAL (
                   SELECT run.id, run.status, run.requested_at, run.started_at,
                          run.completed_at, run.rows_touched, run.error,
                          run.wait_category, run.wait_reason, run.stage,
                          run.stage_detail
                     FROM operations.operator_job_runs run
                    WHERE run.tenant_id = binding.tenant_id
                      AND run.job_key = 'source-refresh'
                      AND run.scope_identity = 'source-binding:' || binding.id::text
                    ORDER BY run.requested_at DESC, run.id DESC
                    LIMIT 1
                   ) native_latest ON TRUE
         LEFT JOIN LATERAL (
                   SELECT run.id, run.status, run.requested_at, run.started_at,
                          run.completed_at, run.rows_touched, run.error,
                          run.wait_category, run.wait_reason, run.stage,
                          run.stage_detail
                     FROM operations.operator_job_runs run
                    WHERE run.tenant_id = binding.tenant_id
                      AND run.job_key = instance.config->>'legacy_job_key'
                      AND run.status IN ('completed', 'failed', 'stalled', 'cancelled')
                    ORDER BY COALESCE(run.completed_at, run.started_at, run.requested_at) DESC,
                             run.id DESC
                    LIMIT 1
                   ) legacy_terminal ON TRUE
         LEFT JOIN LATERAL (
                   SELECT run.status, run.completed_at, run.rows_touched, run.error
                     FROM operations.operator_job_runs run
                    WHERE run.tenant_id = binding.tenant_id
                      AND run.job_key = 'source-refresh'
                      AND run.scope_identity = 'source-binding:' || binding.id::text
                      AND run.status IN ('completed', 'failed', 'stalled', 'cancelled')
                    ORDER BY run.completed_at DESC NULLS LAST, run.requested_at DESC, run.id DESC
                    LIMIT 1
                   ) native_terminal ON TRUE
         LEFT JOIN LATERAL (
                   SELECT CASE WHEN native_latest.id IS NOT NULL
                               THEN native_latest.id ELSE legacy_terminal.id END AS id,
                          CASE WHEN native_latest.id IS NOT NULL
                               THEN native_latest.status ELSE legacy_terminal.status END AS status,
                          CASE WHEN native_latest.id IS NOT NULL
                               THEN native_latest.requested_at
                               ELSE legacy_terminal.requested_at END AS requested_at,
                          CASE WHEN native_latest.id IS NOT NULL
                               THEN native_latest.started_at
                               ELSE legacy_terminal.started_at END AS started_at,
                          CASE WHEN native_latest.id IS NOT NULL
                               THEN native_latest.completed_at
                               ELSE legacy_terminal.completed_at END AS completed_at,
                          CASE WHEN native_latest.id IS NOT NULL
                               THEN native_latest.rows_touched
                               ELSE legacy_terminal.rows_touched END AS rows_touched,
                          CASE WHEN native_latest.id IS NOT NULL
                               THEN native_latest.error ELSE legacy_terminal.error END AS error,
                          native_latest.wait_category, native_latest.wait_reason,
                          native_latest.stage, native_latest.stage_detail
                   ) latest ON TRUE
         LEFT JOIN LATERAL (
                   SELECT CASE WHEN native_terminal.status IS NOT NULL
                               THEN native_terminal.status ELSE legacy_terminal.status END AS status,
                          CASE WHEN native_terminal.status IS NOT NULL
                               THEN native_terminal.completed_at
                               ELSE legacy_terminal.completed_at END AS completed_at,
                          CASE WHEN native_terminal.status IS NOT NULL
                               THEN native_terminal.rows_touched
                               ELSE legacy_terminal.rows_touched END AS rows_touched,
                          CASE WHEN native_terminal.status IS NOT NULL
                               THEN native_terminal.error ELSE legacy_terminal.error END AS error
                   ) terminal ON TRUE
             WHERE binding.tenant_id = 1 AND binding.enabled AND instance.enabled
             ORDER BY source.name, client.display_name NULLS FIRST, binding.id
            """
        )
        rows = cur.fetchall()

    now = timezone.now()
    result: list[dict] = []
    for row in rows:
        (
            binding_id,
            source_name,
            client_name,
            schedule,
            run_id,
            status,
            requested_at,
            started_at,
            completed_at,
            rows_touched,
            error,
            wait_category,
            wait_reason,
            stage,
            stage_detail,
            terminal_status,
            terminal_at,
            terminal_rows,
            _terminal_error,
            previous_result,
        ) = row
        active = status in {"queued", "running"}
        if status == "queued":
            state, status_label = _operator_run_lifecycle(status, wait_category)
            status_detail = {
                "dependency": "Waiting for a related update to finish.",
                "workflow": "Waiting for a related update to finish.",
                "resource": "Another update is finishing first.",
                "capacity": "Other updates are using the available capacity.",
            }.get(wait_category, wait_reason or "Starts shortly.")
            latest_at_label = "Waiting since"
        elif status == "running":
            state, status_label = "running", "Running"
            status_detail = stage_detail or stage or f"Refreshing {source_name}"
            latest_at_label = "Running since"
        elif status:
            state = "failed" if status == "stalled" else status
            status_label = {
                "completed": "Completed",
                "failed": "Failed",
                "cancelled": "Cancelled",
            }.get(state, state.title())
            status_detail = (
                f"{rows_touched} updated."
                if state == "completed" and rows_touched is not None
                else (error or "The refresh did not complete.")[:240]
                if state == "failed"
                else ""
            )
            latest_at_label = "Completed at" if state == "completed" else "Finished at"
        else:
            state, status_label, status_detail, latest_at_label = (
                "not_run",
                "Not run yet",
                "",
                "",
            )

        interruption = _interrupted_run_presentation(status or "", error or "")
        if interruption:
            state, status_label, status_detail = interruption
            latest_at_label = "Stopped at"

        schedule_minutes = _source_schedule_minutes(schedule or "")
        schedule_label = (
            _schedule_cadence_label({"minutes": schedule_minutes})
            if schedule_minutes
            else "Runs when requested"
        )
        latest_at = completed_at or started_at or requested_at
        last_result = ""
        if active and terminal_status:
            if terminal_status == "completed":
                last_result = (
                    f"Last completed: {terminal_rows} updated"
                    if terminal_rows is not None
                    else "Last completed"
                )
            elif terminal_status == "cancelled":
                last_result = "Last stopped"
            else:
                last_result = "Last failed"
        result.append(
            {
                "id": f"source-refresh:{binding_id}",
                "group_key": "source-data",
                "name": f"Refresh {source_name}" + (f" · {client_name}" if client_name else ""),
                "description": f"Collect current information from {source_name}.",
                "state": state,
                "status_label": status_label,
                "status_detail": status_detail,
                "capacity_label": "",
                "capacity_blockers": [],
                "resource_blockers": [],
                "latest_at": latest_at,
                "latest_at_label": latest_at_label,
                "last_result": last_result,
                "last_result_at": terminal_at,
                "latest_run_id": run_id,
                "rows_touched": rows_touched,
                "error": (error or "")[:240],
                "active_run": {"id": run_id} if active and run_id else None,
                "needs_attention": state == "failed",
                "schedule_label": schedule_label,
                "schedule_detail": "Managed on Sources",
                "next_due_at": None,
                "run_key": "source-refresh",
                "is_source": True,
                "binding_id": binding_id,
                "detail_url": f"{reverse('sources_status')}?{urlencode({'source': source_name})}",
                "previous_result": bool(previous_result),
                "is_stale": bool(
                    terminal_status == "completed"
                    and terminal_at
                    and _source_is_stale(terminal_at, schedule_minutes, now)
                ),
            }
        )
    return result


def _jobs_diagnostic_query(
    section: str, *, limit: int = 100, offset: int = 0, cursor=None
) -> tuple[int, list[dict]]:
    """Read one bounded diagnostics page through the restricted SQL API."""
    if cursor is None:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            return _jobs_diagnostic_query(section, limit=limit, offset=offset, cursor=cur)
    if section == "resource_limits":
        diagnostic_function = "operations.jobs_resource_policy_diagnostics_v1"
    elif section in _JOBS_RECOVERY_DIAGNOSTIC_KEYS:
        diagnostic_function = "operations.jobs_recovery_diagnostics_v1"
    else:
        diagnostic_function = "operations.jobs_admin_diagnostics_v1"
    cursor.execute(
        f"SELECT total_count, item FROM {diagnostic_function}(%s, %s, %s, %s)",
        (1, section, limit, offset),
    )
    rows = cursor.fetchall()
    return (
        int(rows[0][0]) if rows else 0,
        [json.loads(row[1]) if isinstance(row[1], str) else row[1] or {} for row in rows],
    )


def _jobs_diagnostic_all(section: str, cursor) -> list[dict]:
    """Read a small policy/catalog section completely for health comparison."""
    offset = 0
    rows: list[dict] = []
    while True:
        total, page = _jobs_diagnostic_query(section, limit=100, offset=offset, cursor=cursor)
        rows.extend(page)
        offset += len(page)
        if not page or offset >= total:
            return rows


def _jobs_control_health() -> dict:
    """Compare persisted Jobs state with this Operations registry revision."""
    result = {
        "available": False,
        "ok": False,
        "issues": [],
        "summary": {},
        "runtimes": [],
    }
    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            _count, health_rows = _jobs_diagnostic_query("health", cursor=cur)
            version_rows = _jobs_diagnostic_all("definition_versions", cur)
            schedule_rows = _jobs_diagnostic_all("schedules", cur)
            resource_rows = _jobs_diagnostic_all("resource_limits", cur)
            _count, runtime_rows = _jobs_diagnostic_query("runtimes", cursor=cur)
    except DatabaseError:
        log.exception("Jobs control-plane health query failed")
        result["issues"].append("Jobs diagnostics are unavailable or failed.")
        return result

    result["available"] = True
    result["summary"] = health_rows[0] if health_rows else {}
    result["runtimes"] = runtime_rows
    issues: list[str] = []

    stored_versions = {
        (row.get("definition_key"), row.get("definition_digest")) for row in version_rows
    }
    expected_versions = {(item.key, item.snapshot_digest()) for item in definitions()}
    missing_versions = sorted(
        key for key, digest in expected_versions if (key, digest) not in stored_versions
    )
    if missing_versions:
        issues.append("Missing current definition revisions: " + ", ".join(missing_versions))

    schedules_by_key = {row.get("definition_key"): row for row in schedule_rows}
    expected_schedules = {item.job_key for item in schedule_definitions()}
    missing_schedules = sorted(expected_schedules - schedules_by_key.keys())
    if missing_schedules:
        issues.append("Missing schedule state: " + ", ".join(missing_schedules))
    stale_schedules = sorted(
        key
        for key, row in schedules_by_key.items()
        if key in definition_keys()
        and row.get("enabled")
        and row.get("definition_digest") != definition(key).snapshot_digest()
    )
    if stale_schedules:
        labels = []
        for key in stale_schedules:
            visible_key = operator_job_key_for_execution(key)
            if visible_key:
                try:
                    labels.append(operator_job_definition(visible_key).name)
                    continue
                except Exception:
                    pass
            labels.append(key.replace("-", " ").title())
        issues.append(
            f"{len(labels)} saved schedule{'s' if len(labels) != 1 else ''} use older Job settings: "
            + ", ".join(labels)
            + "."
        )

    pool_rows = {
        row.get("resource_template"): row
        for row in resource_rows
        if row.get("policy_kind") == "execution_pool"
    }
    missing_pools = sorted(set(EXECUTION_POOL_POLICIES) - set(pool_rows))
    if missing_pools:
        issues.append("Missing execution capacity policy: " + ", ".join(missing_pools))
    for key, policy in EXECUTION_POOL_POLICIES.items():
        actual = pool_rows.get(key, {}).get("capacity")
        if actual is not None and not policy["minimum"] <= actual <= policy["maximum"]:
            issues.append(f"Execution capacity for {key} is outside its reviewed range.")
    if any(
        row.get("capacity") != 1 for row in resource_rows if row.get("policy_kind") == "domain_lock"
    ):
        issues.append("A protected data policy is not exclusive.")

    expected_registry = registry_digest()
    now = timezone.now()
    live_kinds: set[str] = set()
    for runtime in runtime_rows:
        heartbeat = parse_datetime(str(runtime.get("heartbeat_at") or ""))
        if runtime.get("stopped_at") or heartbeat is None:
            continue
        if now - heartbeat <= timedelta(minutes=3):
            live_kinds.add(str(runtime.get("runtime_kind")))
            if runtime.get("registry_digest") != expected_registry:
                issues.append(
                    f"Live {runtime.get('runtime_kind')} uses a different registry revision."
                )
    for required_kind in ("scheduler", "worker"):
        if required_kind not in live_kinds:
            issues.append(f"No current Jobs {required_kind} heartbeat.")

    if int(result["summary"].get("contained_claims") or 0):
        contained = int(result["summary"].get("contained_claims") or 0)
        issues.append(
            f"{contained} interrupted Job run{'s' if contained != 1 else ''} still hold protected data. "
            "Review recovery before dependent Jobs can continue."
        )

    result["issues"] = list(dict.fromkeys(issues))
    result["ok"] = not result["issues"]
    return result


@login_required
@require_admin
def admin_jobs_control_plane(request: HttpRequest) -> HttpResponse:
    """Show administrator configuration and complete Jobs diagnostics."""
    section = (request.GET.get("section") or "coverage").strip()
    if section not in _JOBS_DIAGNOSTIC_KEYS:
        section = "definition_versions"
    try:
        page = min(40001, max(1, int(request.GET.get("page") or "1")))
    except ValueError:
        page = 1
    page_size = 25
    offset = (page - 1) * page_size
    unavailable = ""
    if section == "coverage":
        visible_jobs = {
            execution_key: job
            for job in operator_job_definitions()
            for execution_key in job.execution_keys
        }
        service_keys = system_service_definition_keys()
        legacy_keys = legacy_job_definition_keys()
        all_rows = []
        for item in definitions():
            visible_job = visible_jobs.get(item.key)
            classification = (
                "Job"
                if visible_job
                else "System service"
                if item.key in service_keys
                else "Legacy entry"
                if item.key in legacy_keys
                else "Unclassified"
            )
            all_rows.append(
                {
                    "name": visible_job.name if visible_job else item.display_name,
                    "technical_key": item.key,
                    "classification": classification,
                    "schedule": "Configured" if item.schedule_ids else "Triggered as needed",
                    "owner": item.owner,
                }
            )
        total = len(all_rows)
        rows = all_rows[offset : offset + page_size]
    else:
        try:
            total, rows = _jobs_diagnostic_query(section, limit=page_size, offset=offset)
        except DatabaseError:
            log.exception("Jobs configuration query failed: section=%s", section)
            total, rows = 0, []
            unavailable = "Jobs configuration is unavailable or failed."
    if section == "resource_limits":
        for row in rows:
            policy = EXECUTION_POOL_POLICIES.get(str(row.get("resource_template") or ""))
            if policy:
                row["capacity_label"] = policy["label"]
    return render(
        request,
        "admin_jobs_control_plane.html",
        {
            "admin_group": "integrations",
            "admin_tab": "jobs",
            "sections": _JOBS_DIAGNOSTIC_SECTIONS,
            "active_section": section,
            "rows": rows,
            "total": total,
            "page": page,
            "has_previous": page > 1,
            "previous_page": page - 1,
            "has_next": offset + len(rows) < total,
            "next_page": page + 1,
            "unavailable": unavailable,
            "jobs_health": _jobs_control_health(),
        },
    )


@login_required
@require_admin
@require_POST
def admin_jobs_capacity_update(request: HttpRequest) -> HttpResponse:
    """Apply one reviewed Jobs capacity policy change and audit it."""
    kind = (request.POST.get("kind") or "").strip()
    key = (request.POST.get("key") or "").strip()
    reason = (request.POST.get("reason") or "").strip()
    try:
        capacity = int(request.POST.get("capacity") or "")
    except ValueError:
        capacity = 0
    policy = EXECUTION_POOL_POLICIES.get(key)
    if (
        kind != "pool"
        or policy is None
        or not reason
        or not policy["minimum"] <= capacity <= policy["maximum"]
    ):
        messages.error(
            request, "Choose an execution capacity and reason within its reviewed range."
        )
        return redirect("admin_jobs_control_plane")
    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                "SELECT operations.jobs_set_execution_pool_capacity_v1(%s,%s,%s)",
                (1, key, capacity),
            )
        AuditLog.objects.create(
            tenant_id=1,
            actor=request.user,
            actor_kind=AuditLog.ActorKind.USER,
            source=AuditLog.Source.UI,
            action="jobs.capacity.update",
            entity_type="jobs.execution_capacity",
            before_state={},
            after_state={"key": key, "capacity": capacity, "reason": reason},
        )
        messages.success(request, f"Updated {policy['label']} capacity to {capacity}.")
    except DatabaseError:
        log.exception("Jobs capacity update failed")
        messages.error(request, "Capacity policy update failed.")
    return redirect("admin_jobs_control_plane")


@login_required
def admin_jobs(request: HttpRequest) -> HttpResponse:
    """Show one truthful latest status for every administrator Job."""
    status_filter = (request.GET.get("status") or "").strip().lower()
    search_filter = (request.GET.get("q") or "").strip().lower()
    refresh_setting = (request.GET.get("refresh") or "30").strip()
    refresh_seconds = {"off": 0, "15": 15, "30": 30, "60": 60}.get(
        refresh_setting, 30
    )
    if refresh_setting not in {"off", "15", "30", "60"}:
        refresh_setting = "30"
    enabled_capabilities = {
        "always": True,
        "legacy_agent_compliance": os.environ.get("AGENT_COMPLIANCE_ENABLED", "false")
        .strip()
        .lower()
        in {"1", "true", "yes", "on"},
        "intel": os.environ.get("INTEL_ENABLED", "false").strip().lower()
        in {"1", "true", "yes", "on"},
        "notifications": os.environ.get("NOTIFY_ENABLED", "false").strip().lower()
        in {"1", "true", "yes", "on"},
        "notification_digest": os.environ.get("NOTIFY_DIGEST_ENABLED", "false").strip().lower()
        in {"1", "true", "yes", "on"},
        "software_queue": os.environ.get("SOFTWARE_QUEUE_ENABLED", "false").strip().lower()
        in {"1", "true", "yes", "on"},
        # Runs when work is pending; always available to start by hand.
        "pending_work": True,
    }

    latest_by_execution: dict[str, dict] = {}
    latest_terminal_by_execution: dict[str, dict] = {}
    schedule_status: dict[str, dict] = {}
    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                """
                SELECT DISTINCT ON (job_key)
                       job_key, id, status, requested_at, started_at,
                       completed_at, rows_touched, error, wait_category,
                       wait_reason, stage, stage_detail,
                       cancellation_requested_at, result
                  FROM operations.operator_job_runs
                 WHERE tenant_id = 1
                 ORDER BY job_key, requested_at DESC, id DESC
                """
            )
            for r in cur.fetchall():
                latest_by_execution[r[0]] = {
                    "job_key": r[0],
                    "id": r[1],
                    "status": r[2],
                    "requested_at": r[3],
                    "started_at": r[4],
                    "completed_at": r[5],
                    "rows_touched": r[6],
                    "error": (r[7] or "")[:240],
                    "wait_category": r[8],
                    "wait_reason": r[9] or "",
                    "stage": r[10] or "",
                    "stage_detail": r[11] or "",
                    "cancellation_requested_at": r[12],
                    "result": r[13],
                }
            cur.execute(
                """
                SELECT DISTINCT ON (job_key)
                       job_key, status, completed_at, rows_touched, error, result
                  FROM operations.operator_job_runs
                 WHERE tenant_id = 1
                   AND status IN ('completed', 'failed', 'stalled', 'cancelled')
                 ORDER BY job_key, completed_at DESC NULLS LAST, requested_at DESC, id DESC
                """
            )
            for r in cur.fetchall():
                latest_terminal_by_execution[r[0]] = {
                    "status": r[1],
                    "completed_at": r[2],
                    "rows_touched": r[3],
                    "error": (r[4] or "")[:240],
                    "result": r[5],
                }
    except DatabaseError:
        log.exception("Jobs latest-status query failed")
        latest_by_execution = {}
        latest_terminal_by_execution = {}

    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            for row in _jobs_diagnostic_all("schedules", cur):
                next_due_at = row.get("next_due_at")
                if isinstance(next_due_at, str):
                    next_due_at = parse_datetime(next_due_at)
                schedule_status[row["definition_key"]] = {
                    "enabled": bool(row["enabled"]),
                    "reason": row.get("capability_reason") or "",
                    "cadence": row.get("cadence") or {},
                    "next_due_at": next_due_at,
                    "last_consumed_due_at": row.get("last_consumed_due_at"),
                    "last_requested_at": row.get("last_requested_at"),
                    "last_outcome": row.get("last_outcome") or "",
                    "last_run_id": row.get("last_run_id"),
                }
    except DatabaseError:
        log.exception("Jobs schedule query failed")
        schedule_status = {}

    try:
        _active_total, active_queue = _operator_job_runs(
            limit=len(definition_keys()) * 2,
            filters={"statuses": ("queued", "running")},
        )
    except DatabaseError:
        log.exception("Jobs latest-status query failed")
        active_queue = []
    active_by_job: dict[str, list[dict]] = {}
    for active_run in active_queue:
        catalog_key = operator_job_key_for_execution(active_run["job_key"])
        if catalog_key:
            active_by_job.setdefault(catalog_key, []).append(active_run)

    running_by_capacity: dict[str, list[dict]] = {}
    running_by_resource: dict[str, list[dict]] = {}
    for active_run in active_queue:
        if active_run["status"] != "running" or active_run["job_key"] not in definition_keys():
            continue
        for capacity_key in definition(active_run["job_key"]).capacity_keys:
            running_by_capacity.setdefault(capacity_key, []).append(active_run)
        for resource_key in definition(active_run["job_key"]).resource_keys:
            running_by_resource.setdefault(resource_key, []).append(active_run)

    for active_run in active_queue:
        if active_run.get("wait_category") != "capacity" or active_run["job_key"] not in definition_keys():
            continue
        capacity_keys = definition(active_run["job_key"]).capacity_keys
        blockers: list[dict[str, str]] = []
        for capacity_key in capacity_keys:
            for running_run in running_by_capacity.get(capacity_key, []):
                visible_key = operator_job_key_for_execution(running_run["job_key"])
                if visible_key and not any(item["id"] == visible_key for item in blockers):
                    blockers.append(
                        {"id": visible_key, "name": operator_job_definition(visible_key).name}
                    )
        active_run["capacity_label"] = ", ".join(
            EXECUTION_POOL_POLICIES[key]["label"] for key in capacity_keys
        )
        active_run["capacity_blockers"] = blockers
    for active_run in active_queue:
        if active_run.get("wait_category") != "resource" or active_run["job_key"] not in definition_keys():
            continue
        blockers: list[dict[str, str]] = []
        for resource_key in definition(active_run["job_key"]).resource_keys:
            for running_run in running_by_resource.get(resource_key, []):
                visible_key = operator_job_key_for_execution(running_run["job_key"])
                if visible_key and not any(item["id"] == visible_key for item in blockers):
                    blockers.append({"id": visible_key, "name": operator_job_definition(visible_key).name})
        active_run["resource_blockers"] = blockers

    def active_priority(run: dict) -> tuple[int, float]:
        rank = 0 if run["status"] == "running" else 1
        return rank, -run["requested_at"].timestamp()

    jobs: list[dict] = []
    for entry in _OPERATOR_JOB_CATALOG:
        execution_keys = tuple(entry["execution_keys"])
        runs = sorted(active_by_job.get(entry["id"], []), key=active_priority)
        active_run = runs[0] if runs else None
        latest_candidates = [
            latest_by_execution[key] for key in execution_keys if key in latest_by_execution
        ]
        latest = max(
            latest_candidates,
            key=lambda item: item["requested_at"],
            default=None,
        )
        latest_terminal_candidates = [
            latest_terminal_by_execution[key]
            for key in execution_keys
            if key in latest_terminal_by_execution
        ]
        latest_terminal = max(
            latest_terminal_candidates,
            key=lambda item: item["completed_at"] or datetime.min.replace(tzinfo=dt_timezone.utc),
            default=None,
        )
        last_result = ""
        last_result_at = None
        if latest_terminal:
            last_result_at = latest_terminal["completed_at"]
            if latest_terminal["status"] == "completed":
                summary = _run_summary(latest_terminal["result"], latest_terminal["rows_touched"])
                last_result = f"Last completed: {summary}" if summary else "Last completed"
            elif latest_terminal["status"] == "cancelled":
                last_result = "Last stopped"
            else:
                last_result = "Last failed"
        if active_run:
            state = active_run["lifecycle"]
            status_label = {
                "running": "Running",
                "waiting": "Waiting",
                "ready": "Ready to start",
            }.get(state, active_run["status_label"])
            if state == "running":
                status_detail = _running_detail(
                    active_run["stage"] or "", active_run["stage_detail"] or ""
                )
            else:
                status_detail = active_run["status_detail"]
            latest_run_id = active_run["id"]
            latest_at = active_run["started_at"] or active_run["requested_at"]
            latest_at_label = "Running since" if state == "running" else "Waiting since"
            rows_touched = active_run["rows_touched"]
            error = active_run["error"]
        elif latest:
            state = "failed" if latest["status"] == "stalled" else latest["status"]
            status_label = {
                "completed": "Completed",
                "failed": "Failed",
                "cancelled": "Cancelled",
            }.get(state, state.title())
            rows_touched = latest["rows_touched"]
            error = latest["error"]
            status_detail = (
                _run_summary(latest.get("result"), rows_touched)
                if state == "completed"
                else error
                if state == "failed" and error
                else ""
            )
            latest_run_id = latest["id"]
            latest_at = latest["completed_at"] or latest["started_at"] or latest["requested_at"]
            latest_at_label = "Completed at" if state == "completed" else "Finished at"
        else:
            state = "not_run"
            status_label = "Not run yet"
            status_detail = ""
            latest_run_id = None
            latest_at = None
            latest_at_label = ""
            rows_touched = None
            error = ""

        schedules = [schedule_status[key] for key in execution_keys if key in schedule_status]
        primary_definition = definition(entry["primary_execution_key"])
        available, availability_label = capability_state(
            primary_definition.key, enabled_capabilities
        )
        schedule_presentation = _job_schedule_presentation(
            execution_keys,
            schedules,
            start_description=entry["start_description"],
            available=available,
            availability_label=availability_label,
        )
        interruption = _interrupted_run_presentation(
            latest["status"] if latest else "", error
        )
        if interruption:
            state, status_label, status_detail = interruption
            latest_at_label = "Stopped at"
        needs_attention = state == "failed"
        jobs.append(
            {
                "id": entry["id"],
                "group_key": entry["group_key"],
                "name": entry["name"],
                "description": entry["description"],
                "state": state,
                "status_label": status_label,
                "status_detail": status_detail,
                "progress": active_run.get("progress") if active_run else None,
                "capacity_label": active_run.get("capacity_label", "") if active_run else "",
                "capacity_blockers": active_run.get("capacity_blockers", []) if active_run else [],
                "resource_blockers": active_run.get("resource_blockers", []) if active_run else [],
                "latest_at": latest_at,
                "latest_at_label": latest_at_label,
                "last_result": last_result if active_run else "",
                "last_result_at": last_result_at if active_run else None,
                "latest_run_id": latest_run_id,
                "rows_touched": rows_touched,
                "error": error,
                "active_run": active_run,
                "needs_attention": needs_attention,
                "schedule_label": schedule_presentation["label"],
                "schedule_detail": schedule_presentation["detail"],
                "next_due_at": schedule_presentation["next_due_at"],
                "run_key": entry["primary_execution_key"],
            }
        )

    # Sources owns connection configuration; Jobs owns the complete execution
    # view. Each enabled binding is therefore one visible scoped execution row.
    try:
        source_jobs = _source_job_rows()
    except DatabaseError:
        log.exception("Source execution status query failed")
        source_jobs = []
        sources_available = False
    else:
        sources_available = True
        jobs.extend(source_jobs)
    source_summary = {
        "available": sources_available,
        "total": len(source_jobs),
        "current": sum(
            not source["needs_attention"] and not source["is_stale"]
            for source in source_jobs
        ),
    }

    summary = {
        "running": sum(item["state"] == "running" for item in jobs),
        "waiting": sum(item["state"] == "waiting" for item in jobs),
        "ready": sum(item["state"] == "ready" for item in jobs),
        "attention": sum(item["needs_attention"] for item in jobs),
    }
    # Admin Health uses the Jobs diagnostic lifecycle totals.  Use those same
    # totals in this page header so the two pages describe the same Job runs.
    jobs_health = _jobs_control_health()
    control_summary = jobs_health.get("summary", {})
    for state, diagnostic_key in (
        ("running", "running_runs"),
        ("waiting", "waiting_runs"),
        ("ready", "ready_runs"),
    ):
        if diagnostic_key in control_summary:
            summary[state] = int(control_summary[diagnostic_key] or 0)
    live_kinds = {
        str(runtime.get("runtime_kind"))
        for runtime in jobs_health["runtimes"]
        if not runtime.get("stopped_at")
        and (heartbeat := parse_datetime(str(runtime.get("heartbeat_at") or "")))
        and timezone.now() - heartbeat <= timedelta(minutes=3)
    }
    job_system_attention = []
    missing_runtime_kinds = [
        label
        for kind, label in (("scheduler", "the Scheduler"), ("worker", "a Worker"))
        if kind not in live_kinds
    ]
    if missing_runtime_kinds:
        job_system_attention.append(
            {
                "detail": (
                    "Jobs cannot start because "
                    + " and ".join(missing_runtime_kinds)
                    + " is not checking in."
                ),
                "url": f"{reverse('admin_jobs_control_plane')}?section=runtimes",
            }
        )
    if search_filter:
        jobs = [
            item
            for item in jobs
            if search_filter in item["name"].lower() or search_filter in item["description"].lower()
        ]
    if status_filter:
        jobs = [
            item
            for item in jobs
            if item["state"] == status_filter
            or status_filter == "attention"
            and item["needs_attention"]
        ]
    state_order = {"failed": 0, "running": 1, "waiting": 2, "ready": 3}
    for item in jobs:
        item["status_rank"] = state_order.get(item["state"], 4)
    jobs.sort(key=lambda item: (item["status_rank"], item["name"].lower()))
    jobs_by_group: dict[str, list[dict]] = {}
    for job in jobs:
        jobs_by_group.setdefault(job["group_key"], []).append(job)
    job_groups = [
        {"key": key, "label": label, "jobs": jobs_by_group[key]}
        for key, label in operator_job_group_definitions()
        if key in jobs_by_group
    ]

    return render(
        request,
        "admin_jobs.html",
        {
            "admin_group": "integrations",
            "admin_tab": "jobs",
            "job_groups": job_groups,
            "job_count": len(_OPERATOR_JOB_CATALOG),
            "source_job_count": len(source_jobs),
            "source_summary": source_summary,
            "active_status": status_filter,
            "active_search": search_filter,
            "active_refresh": refresh_setting,
            "refresh_seconds": refresh_seconds,
            "job_summary": summary,
            "scheduler_current": "scheduler" in live_kinds,
            "worker_current": "worker" in live_kinds,
            "job_system_attention": job_system_attention,
            "refreshed_at": timezone.now(),
        },
    )


@login_required
@require_admin
def admin_job_detail(request: HttpRequest, job_id: str) -> HttpResponse:
    """Show Latest Run and bounded history for one administrator Job."""
    try:
        job = operator_job_definition(job_id)
    except Exception as exc:
        raise Http404("Unknown Job") from exc
    try:
        page = max(1, min(20001, int(request.GET.get("page") or "1")))
    except ValueError:
        page = 1
    page_size = 25
    run_total, runs = _operator_job_runs(
        limit=page_size,
        offset=(page - 1) * page_size,
        filters={"job_keys": job.execution_keys},
    )
    _active_total, active_runs = _operator_job_runs(
        limit=max(10, len(job.execution_keys) * 2),
        filters={
            "job_keys": job.execution_keys,
            "statuses": ("queued", "running"),
        },
    )
    active_runs.sort(
        key=lambda run: (
            0 if run["status"] == "running" else 1,
            -run["requested_at"].timestamp(),
        )
    )
    latest_run = active_runs[0] if active_runs else (runs[0] if runs else None)

    selected_run = None
    selected_run_id = (request.GET.get("run") or "").strip()
    if selected_run_id:
        _selected_total, selected_runs = _operator_job_runs(
            limit=1,
            run_id=selected_run_id,
            filters={"job_keys": job.execution_keys},
        )
        selected_run = selected_runs[0] if selected_runs else None

    schedules = []
    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            schedules = [
                {
                    "job_key": row["definition_key"],
                    "enabled": bool(row["enabled"]),
                    "cadence": row.get("cadence") or {},
                    "next_due_at": row.get("next_due_at"),
                    "reason": row.get("capability_reason") or "",
                    "last_outcome": row.get("last_outcome") or "",
                }
                for row in _jobs_diagnostic_all("schedules", cur)
                if row.get("definition_key") in job.execution_keys
            ]
    except DatabaseError:
        log.exception("Job schedule query failed: job=%s", job.key)

    primary_definition = definition(job.primary_execution_key)
    available, availability_label = capability_state(
        primary_definition.key,
        {
            "always": True,
            "intel": os.environ.get("INTEL_ENABLED", "false").strip().lower()
            in {"1", "true", "yes", "on"},
            "notifications": os.environ.get("NOTIFY_ENABLED", "false").strip().lower()
            in {"1", "true", "yes", "on"},
            "notification_digest": os.environ.get("NOTIFY_DIGEST_ENABLED", "false")
            .strip()
            .lower()
            in {"1", "true", "yes", "on"},
            "pending_work": True,
        },
    )
    schedule_presentation = _job_schedule_presentation(
        job.execution_keys,
        schedules,
        start_description=job.start_description,
        available=available,
        availability_label=availability_label,
    )

    return render(
        request,
        "admin_job_detail.html",
        {
            "admin_group": "integrations",
            "admin_tab": "jobs",
            "job": job,
            "latest_run": latest_run,
            "selected_run": selected_run,
            "runs": runs,
            "run_total": run_total,
            "page": page,
            "has_previous": page > 1,
            "previous_page": page - 1,
            "has_next": page * page_size < run_total,
            "next_page": page + 1,
            "schedule_presentation": schedule_presentation,
        },
    )


@login_required
@require_admin
@require_POST
def admin_jobs_run(request: HttpRequest, job_id: str) -> HttpResponse:
    try:
        job = operator_job_definition(job_id)
    except Exception:
        messages.error(request, f"Unknown job '{job_id}'.")
        return redirect("admin_jobs")
    run_id, created = _enqueue_operator_job(job.primary_execution_key, request.user.id)
    if created:
        messages.success(request, f"{job.name} was requested.")
    else:
        messages.info(request, f"{job.name} already has an active Run.")
    return redirect("admin_job_detail", job_id=job.key)


@login_required
@require_admin
@require_POST
def admin_jobs_run_all(request: HttpRequest) -> HttpResponse:
    """The former broad Run-all action is intentionally no longer exposed."""
    messages.warning(request, "Run all is unavailable. Start only the Jobs you intend to run.")
    return redirect("admin_jobs")


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


def _enqueue_operator_job(
    job_key: str,
    user_id: int,
    *,
    batch_id: uuid.UUID | None = None,
    retry_of: uuid.UUID | None = None,
    scope_identity: str = "tenant:1",
) -> tuple[uuid.UUID, bool]:
    """Create a v1 operator request through the governed Jobs API."""
    job = definition(job_key)
    request_identity = hashlib.sha256(
        f"operator:{user_id}:{job_key}:{scope_identity}:{batch_id or ''}:{uuid.uuid4()}".encode()
    ).hexdigest()
    request_api = (
        "operations.jobs_request_software_v1"
        if job.supersession_family == "software-classifier"
        else "operations.jobs_request"
    )
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        if retry_of is not None:
            cur.execute(
                """SELECT id FROM operations.operator_job_runs
                     WHERE tenant_id = 1 AND job_key = %s
                       AND status IN ('queued', 'running')
                     ORDER BY requested_at DESC, id DESC LIMIT 1""",
                (job.key,),
            )
            active = cur.fetchone()
            if active is not None:
                return active[0], False
        cur.execute(
            f"SELECT {request_api}(%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)",
            (
                1,
                job.key,
                job.snapshot_digest(),
                scope_identity,
                request_identity,
                "operator",
                user_id,
                "{}",
                "{}",
                batch_id,
            ),
        )
        row = cur.fetchone()
        if row is not None:
            _admit_operator_workflow(cur, job.key, row[0])
        if row is not None and retry_of is not None:
            cur.execute(
                "SELECT operations.jobs_link_retry_v1(%s, %s, %s)",
                (1, row[0], retry_of),
            )
    if row is None:
        raise RuntimeError("Jobs request API did not return a run")
    return row[0], True


def _admit_operator_workflow(cur, root_key: str, root_run_id: uuid.UUID) -> None:
    """Create one declared workflow graph in the root admission transaction."""
    runs = {root_key: root_run_id}
    for edge in workflow_edges(root_key):
        dependent = definition(edge.dependent)
        request_api = (
            "operations.jobs_request_software_v1"
            if dependent.supersession_family == "software-classifier"
            else "operations.jobs_request"
        )
        request_identity = hashlib.sha256(
            f"workflow:{root_run_id}:{edge.dependent}:{edge.revision_name}".encode()
        ).hexdigest()
        cur.execute(
            f"SELECT {request_api}(%s, %s, %s, %s, %s, %s, NULL, %s::jsonb, %s::jsonb, %s)",
            (
                1,
                dependent.key,
                dependent.snapshot_digest(),
                "tenant:1",
                request_identity,
                "dependency",
                "{}",
                "{}",
                root_run_id,
            ),
        )
        dependent_id = cur.fetchone()[0]
        runs[edge.dependent] = dependent_id
        required_revision = hashlib.sha256(
            f"{runs[edge.prerequisite]}:{edge.revision_name}:tenant:1".encode()
        ).hexdigest()
        cur.execute(
            "SELECT operations.jobs_add_revision_dependency_v1(%s, %s, %s, %s, %s, %s)",
            (
                1,
                dependent_id,
                runs[edge.prerequisite],
                edge.revision_name,
                "tenant:1",
                required_revision,
            ),
        )


def _queue_software_rebuild_after_commit(user_id: int) -> None:
    """Queue one full rebuild after a software decision is durable."""

    def enqueue() -> None:
        try:
            _enqueue_operator_job("software-classify-full", user_id)
        except Exception:
            # A decision remains authoritative if the queue is transiently
            # unavailable; the scheduled full rebuild will reconcile it.
            log.exception("Could not queue software full rebuild after decision")

    transaction.on_commit(enqueue)


def _operator_job_name(execution_key: str) -> str:
    """Return the administrator-facing Job name for one execution key."""
    job_key = operator_job_key_for_execution(execution_key)
    if job_key is None:
        return definition(execution_key).display_name if execution_key in definition_keys() else "Retired Job"
    return operator_job_definition(job_key).name


def _operator_run_lifecycle(status: str, wait_category: str | None) -> tuple[str, str]:
    """Return the one operator-facing lifecycle derived from durable run state."""
    if status == "stalled":
        return "failed", "Needs attention"
    if status != "queued":
        return (
            status,
            {
                "running": "Running",
                "completed": "Completed",
                "failed": "Needs attention",
                "cancelled": "Stopped",
            }.get(status, status.replace("_", " ").title()),
        )
    if wait_category:
        return "waiting", "Waiting"
    return "ready", "Ready to start"


def _operator_run_wait_explanation(run: dict) -> str:
    """Explain one waiting cause without exposing execution internals."""
    wait_category = run.get("wait_category")
    if wait_category in {"dependency", "workflow"}:
        relations = (
            run.get("prerequisites", [])
            if wait_category == "dependency"
            else run.get("dependents", [])
        )
        names = list(
            dict.fromkeys(
                _operator_job_name(str(relation["job_key"]))
                for relation in relations
                if str(relation.get("job_key") or "") in definition_keys()
            )
        )
        if names:
            return "Waiting for: " + ", ".join(names) + "."
        return "Waiting for a related update to finish."
    if wait_category == "resource":
        return "Another update is finishing first."
    if wait_category == "capacity":
        return "Other updates are using the available capacity."
    return "Starts shortly."


def _operator_job_runs(
    *,
    limit: int = 50,
    offset: int = 0,
    run_id: str = "",
    batch_id: str = "",
    filters: dict[str, object] | None = None,
) -> tuple[int, list[dict]]:
    clauses = ["job.tenant_id = 1"]
    params: list[object] = []
    if run_id:
        clauses.append("job.id::text = %s")
        params.append(run_id)
    if batch_id:
        clauses.append("job.batch_id::text = %s")
        params.append(batch_id)
    active_filters = filters or {}
    simple_filters = {
        "job_key": "job.job_key = %s",
        "origin": "job.trigger_kind = %s",
        "correlation": "job.correlation_id::text = %s",
        "batch": "job.batch_id::text = %s",
    }
    for key, sql in simple_filters.items():
        if active_filters.get(key):
            clauses.append(sql)
            params.append(active_filters[key])
    if active_filters.get("job_keys"):
        clauses.append("job.job_key = ANY(%s::text[])")
        params.append(list(active_filters["job_keys"]))
    if active_filters.get("status"):
        status = str(active_filters["status"])
        if status == "ready":
            clauses.append("job.status = 'queued' AND job.wait_category IS NULL")
        elif status == "waiting":
            clauses.append("job.status = 'queued' AND job.wait_category IS NOT NULL")
        else:
            clauses.append("job.status = %s")
            params.append(status)
    if active_filters.get("statuses"):
        clauses.append("job.status = ANY(%s::text[])")
        params.append(list(active_filters["statuses"]))
    if active_filters.get("current_only"):
        clauses.append("job.id IN (SELECT run_id FROM operations.jobs_activity_current_v1(1))")
    if active_filters.get("history_only"):
        clauses.append("job.id NOT IN (SELECT run_id FROM operations.jobs_activity_current_v1(1))")
    if active_filters.get("scope"):
        pattern = f"%{active_filters['scope']}%"
        clauses.append(
            "(job.scope_identity ILIKE %s OR "
            "COALESCE(job.request_payload, '{}'::jsonb)::text ILIKE %s)"
        )
        params.extend((pattern, pattern))
    if active_filters.get("owner"):
        owner = str(active_filters["owner"])
        owner_keys = [item.key for item in definitions() if owner == item.owner]
        if owner_keys:
            clauses.append("job.job_key = ANY(%s::text[])")
            params.append(owner_keys)
        else:
            clauses.append("FALSE")
    if active_filters.get("from_at"):
        clauses.append("job.requested_at >= %s")
        params.append(active_filters["from_at"])
    if active_filters.get("to_at"):
        clauses.append("job.requested_at < %s")
        params.append(active_filters["to_at"])
    if active_filters.get("technical"):
        pattern = f"%{active_filters['technical']}%"
        clauses.append(
            "(job.id::text ILIKE %s OR job.job_key ILIKE %s OR "
            "COALESCE(job.definition_digest, '') ILIKE %s OR "
            "COALESCE(job.correlation_id::text, '') ILIKE %s OR "
            "COALESCE(job.batch_id::text, '') ILIKE %s OR "
            "COALESCE(job.parent_run_id::text, '') ILIKE %s OR "
            "COALESCE(job.root_run_id::text, '') ILIKE %s OR "
            "COALESCE(job.retry_of_run_id::text, '') ILIKE %s)"
        )
        params.extend([pattern] * 8)
    where_sql = " AND ".join(clauses)
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            f"SELECT count(*) FROM operations.operator_job_runs job WHERE {where_sql}",
            params,
        )
        total = int(cur.fetchone()[0])
        cur.execute(
            f"""SELECT id, job_key, batch_id, requested_by_id, requested_at, started_at, completed_at,
                        status, attempts, rows_touched, error, stage, stage_detail, stage_updated_at,
                        lane, heartbeat_at,
                        NULL::integer AS queue_position,
                        CASE WHEN status = 'queued' THEN COALESCE(
                            wait_reason, 'Ready to start when a worker is available.'
                        ) END AS queue_reason,
                        contract_version, trigger_kind, wait_category, wait_reason,
                        cancellation_requested_at, cancellation_reason, deadline_at,
                        correlation_id, retry_of_run_id, result, terminal_reason,
                        progress_done, progress_total, progress_unit
                   FROM operations.operator_job_runs
                  AS job
                  WHERE {where_sql}
                  ORDER BY job.requested_at DESC, job.id DESC LIMIT %s OFFSET %s""",
            [*params, limit, offset],
        )
        rows = cur.fetchall()
        job_ids = [row[0] for row in rows]
        events_by_job: dict[uuid.UUID, list[dict]] = {job_id: [] for job_id in job_ids}
        technical_by_job: dict[uuid.UUID, dict] = {}
        prerequisites_by_job: dict[uuid.UUID, list[dict]] = {job_id: [] for job_id in job_ids}
        dependents_by_job: dict[uuid.UUID, list[dict]] = {job_id: [] for job_id in job_ids}
        domain_attempts_by_job: dict[uuid.UUID, list[dict]] = {job_id: [] for job_id in job_ids}
        contained_claims_by_job: dict[uuid.UUID, int] = {}
        recovery_by_job: dict[uuid.UUID, dict] = {}
        if job_ids:
            cur.execute(
                "SELECT run_id, relation_kind, item "
                "FROM operations.jobs_activity_relations_v1(%s, %s::uuid[])",
                (1, job_ids),
            )
            for related_run_id, relation_kind, raw_item in cur.fetchall():
                item = json.loads(raw_item) if isinstance(raw_item, str) else raw_item
                if relation_kind == "event":
                    events_by_job.setdefault(related_run_id, []).append(item)
                elif relation_kind == "dependency":
                    target = (
                        prerequisites_by_job
                        if item["direction"] == "prerequisite"
                        else dependents_by_job
                    )
                    target.setdefault(related_run_id, []).append(
                        {
                            "id": item["id"],
                            "job_key": item["job_key"],
                            "status": item["status"],
                            "state": item["state"],
                            "reason": item["reason"],
                            "contract": item["contract"] or {},
                            "required_revision": item["required_revision"],
                            "failure_rule": item["failure_rule"],
                        }
                    )
                elif relation_kind == "domain_attempt":
                    domain_attempts_by_job.setdefault(related_run_id, []).append(item)
                elif relation_kind == "contained_claims":
                    contained_claims_by_job[related_run_id] = int(item["count"])
                elif relation_kind == "recovery_assessment":
                    recovery_by_job[related_run_id] = item
            cur.execute(
                """SELECT id, definition_digest, scope_identity, input_revisions,
                          output_revisions, request_payload, parent_run_id, root_run_id
                     FROM operations.operator_job_runs
                    WHERE tenant_id = 1 AND id = ANY(%s)""",
                (job_ids,),
            )
            for detail in cur.fetchall():
                technical_by_job[detail[0]] = {
                    "definition_digest": detail[1],
                    "scope_identity": detail[2],
                    "input_revisions": detail[3] or {},
                    "output_revisions": detail[4] or {},
                    "request_payload": detail[5] or {},
                    "parent_run_id": detail[6],
                    "root_run_id": detail[7],
                }
    labels = {item.key: item.display_name for item in definitions()}
    now = timezone.now()

    def result_label(status: str, rows_touched, error: str) -> str:
        if status == "queued":
            return "No work has run yet."
        if status == "cancelled":
            return "Cancelled before work started."
        if error:
            return "Review the recorded error."
        if rows_touched is None:
            return "No item count reported."
        return ""

    def elapsed_label(started_at, completed_at) -> str:
        began = started_at
        ended = completed_at or now
        if began is None:
            return ""
        seconds = max(0, int((ended - began).total_seconds()))
        if seconds < 60:
            return "under a minute"
        if seconds < 3600:
            return f"{seconds // 60}m"
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"

    runs = [
        {
            "id": row[0],
            "job_key": row[1],
            "name": labels.get(row[1], row[1]),
            "batch_id": row[2],
            "origin": {
                "automatic": "Automatic",
                "operator": "Operator",
                "dependency": "Dependency",
                "recovery": "Recovery",
            }.get(row[19], "Automatic" if row[3] is None else "Operator"),
            "requested_at": row[4],
            "started_at": row[5],
            "completed_at": row[6],
            "status": row[7],
            "recovery": recovery_by_job.get(row[0]),
            "status_class": "completed"
            if row[0] in recovery_by_job
            else _operator_run_lifecycle(row[7], row[20])[0],
            "status_label": "Recovered automatically"
            if row[0] in recovery_by_job
            else _operator_run_lifecycle(row[7], row[20])[1],
            "lifecycle": _operator_run_lifecycle(row[7], row[20])[0],
            "attempts": row[8],
            "rows_touched": row[9],
            "error": row[10],
            "stage": row[11],
            "stage_detail": row[12],
            "stage_updated_at": row[13],
            "lane": row[14],
            "heartbeat_at": row[15],
            "queue_position": row[16],
            "queue_reason": row[21] or row[17],
            "wait_category": row[20],
            "contract_version": row[18],
            "cancellation_requested_at": row[22],
            "cancellation_reason": row[23],
            "deadline_at": row[24],
            "correlation_id": row[25],
            "retry_of_run_id": row[26],
            "result": row[27] or {},
            "terminal_reason": row[28],
            "progress": _run_progress(row[29], row[30], row[31]) if row[7] == "running" else None,
            "needs_attention": row[7] in {"failed", "stalled"},
            "owner": definition(row[1]).owner if row[1] in definition_keys() else "",
            "result_label": result_label(row[7], row[9], row[10]),
            "elapsed": elapsed_label(row[5], row[6]),
            "events": events_by_job.get(row[0], []),
            "technical": technical_by_job.get(row[0], {}),
            "prerequisites": prerequisites_by_job.get(row[0], []),
            "dependents": dependents_by_job.get(row[0], []),
            "domain_attempts": domain_attempts_by_job.get(row[0], []),
            "contained_claim_count": contained_claims_by_job.get(row[0], 0),
        }
        for row in rows
    ]
    for run in runs:
        visible_key = operator_job_key_for_execution(run["job_key"])
        if visible_key:
            visible_job = operator_job_definition(visible_key)
            run["operator_job_key"] = visible_key
            run["name"] = visible_job.name
        else:
            run["operator_job_key"] = ""
        if run["status"] == "queued":
            run["status_detail"] = _operator_run_wait_explanation(run)
        elif run["status"] == "running":
            run["status_detail"] = _running_detail(run["stage"] or "", run["stage_detail"] or "")
        elif run["status"] in {"failed", "stalled"}:
            run["status_detail"] = run["error"] or "The Run did not complete."
        else:
            run["status_detail"] = (
                _run_summary(run["result"], run["rows_touched"]) or run["result_label"]
            )
        for relationship in (*run["prerequisites"], *run["dependents"]):
            related_key = operator_job_key_for_execution(relationship["job_key"])
            relationship["operator_job_key"] = related_key or ""
            relationship["name"] = (
                operator_job_definition(related_key).name
                if related_key
                else _operator_job_name(relationship["job_key"])
            )
    return total, runs


@login_required
@require_admin
def admin_job_status(request: HttpRequest) -> HttpResponse:
    """Preserve old Activity links while Jobs history moves to Job detail."""
    run_id = (request.GET.get("run") or "").strip()
    requested_key = (request.GET.get("job") or "").strip()
    execution_key = requested_key
    if run_id:
        try:
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute("SET LOCAL operations.tenant_id = 1")
                cur.execute(
                    """SELECT job_key FROM operations.operator_job_runs
                         WHERE tenant_id = 1 AND id::text = %s""",
                    (run_id,),
                )
                row = cur.fetchone()
                execution_key = row[0] if row else ""
        except DatabaseError:
            execution_key = ""
    if execution_key == "source-refresh":
        return redirect("sources_status")
    visible_key = operator_job_key_for_execution(execution_key) if execution_key else None
    if visible_key:
        target = reverse("admin_job_detail", kwargs={"job_id": visible_key})
        return redirect(target + (f"?run={run_id}" if run_id else ""))
    return redirect("admin_jobs")


@login_required
@require_admin
@require_POST
def admin_job_cancel(request: HttpRequest, run_id: uuid.UUID) -> HttpResponse:
    """Cancel queued work or request cooperative cancellation of a v1 run."""
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            "SELECT operations.jobs_cancel_v1(%s, %s, %s, %s)",
            (1, run_id, request.user.id, "Cancelled by an administrator."),
        )
        outcome = cur.fetchone()[0]
    if outcome == "cancelled":
        messages.success(request, "Queued run cancelled.")
    elif outcome == "requested":
        messages.success(
            request, "Cancellation requested; the worker will stop only at a safe checkpoint."
        )
    else:
        messages.info(request, "This run has already finished or cannot be cancelled.")
    return redirect(request.META.get("HTTP_REFERER") or reverse("admin_jobs"))


@login_required
@require_admin
@require_POST
def admin_job_bulk_cancel(request: HttpRequest) -> HttpResponse:
    """Apply the existing safe cancellation transition to selected active runs."""
    run_ids: list[uuid.UUID] = []
    for raw_id in request.POST.getlist("run_id")[:50]:
        try:
            run_id = uuid.UUID(raw_id)
        except (TypeError, ValueError):
            continue
        if run_id not in run_ids:
            run_ids.append(run_id)
    if not run_ids:
        messages.info(request, "Select queued or running Jobs before applying a bulk action.")
        return redirect(request.META.get("HTTP_REFERER") or reverse("admin_jobs"))

    outcomes = {"cancelled": 0, "requested": 0, "unchanged": 0}
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        for run_id in run_ids:
            cur.execute(
                "SELECT operations.jobs_cancel_v1(%s, %s, %s, %s)",
                (1, run_id, request.user.id, "Bulk action by an administrator."),
            )
            outcome = cur.fetchone()[0]
            outcomes[outcome if outcome in outcomes else "unchanged"] += 1
    detail = []
    if outcomes["cancelled"]:
        detail.append(f"{outcomes['cancelled']} cancelled")
    if outcomes["requested"]:
        detail.append(f"{outcomes['requested']} cancellation request(s) sent")
    if outcomes["unchanged"]:
        detail.append(f"{outcomes['unchanged']} already finished or unavailable")
    messages.success(request, "Bulk Job action: " + "; ".join(detail) + ".")
    return redirect(request.META.get("HTTP_REFERER") or reverse("admin_jobs"))


@login_required
@require_admin
@require_POST
def admin_job_retry(request: HttpRequest, run_id: uuid.UUID) -> HttpResponse:
    """Retry only a terminal run by placing a new durable request."""
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """SELECT job_key FROM operations.operator_job_runs
                 WHERE tenant_id = 1 AND id = %s
                   AND status IN ('failed', 'stalled')""",
            (run_id,),
        )
        row = cur.fetchone()
    if row is None:
        messages.info(request, "Only failed or stalled runs can be retried.")
        return redirect(request.META.get("HTTP_REFERER") or reverse("admin_jobs"))
    new_id, created = _enqueue_operator_job(row[0], request.user.id, retry_of=run_id)
    if created:
        messages.success(request, "Retry requested.")
    else:
        messages.info(request, "An equivalent run is already queued or running.")
    visible_key = operator_job_key_for_execution(row[0])
    if visible_key:
        target = reverse("admin_job_detail", kwargs={"job_id": visible_key})
        return redirect(target + f"?run={new_id}")
    return redirect("admin_jobs_control_plane")


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

    now = datetime.now(dt_timezone.utc)
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
            (canonical_name, source, now, request.user.id, json.dumps(result), summary[:1000]),
        )
    _audit(
        request,
        "software.lookup",
        uuid.uuid4(),
        {},
        {
            "canonical_name": canonical_name,
            "source": source,
            "summary": summary[:400],
        },
    )
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
                                  AND {current_computer_sql("d")}
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
    #
    # Split by scope instead of matching with OR. Measured 2026-08-18: with
    # the OR, the planner could not use either side as an index condition and
    # this statement took 21-38 s -- the dominant cost of the page.
    # `ck_software_decisions_scope_key_xor` guarantees canonical_name and
    # publisher are never both set, so two UNION ALL branches -- each a real
    # equi-join -- cannot double-count. Same fix already proven in the
    # /software/decisions/ queue (de046ee) and /software/user-risk/
    # (c0b932a). Rewritten: 1.3 s for identical rows.
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
        FROM operations.software_decisions sd
        JOIN operations.software_installations_current sic
          ON sic.tenant_id = sd.tenant_id
         AND sic.canonical_name = sd.canonical_name
         AND sic.deleted_at IS NULL
         AND sic.stale_since IS NULL
        JOIN operations.devices d ON d.id = sic.device_id AND d.deleted_at IS NULL
                                  AND {current_computer_sql("d")}
        JOIN operations.clients c ON c.id = d.client_id AND c.deleted_at IS NULL
        WHERE sd.tenant_id = 1
          AND sd.decision IN ('reject', 'investigate')
          AND sd.canonical_name <> ''
          AND (sd.device_id IS NULL OR sd.device_id = sic.device_id)
          AND (sd.client_id IS NULL OR sd.client_id = sic.client_id)
          {client_where}

        UNION ALL

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
        FROM operations.software_decisions sd
        JOIN operations.software_installations_current sic
          ON sic.tenant_id = sd.tenant_id
         AND LOWER(sic.publisher) = LOWER(sd.publisher)
         AND sic.deleted_at IS NULL
         AND sic.stale_since IS NULL
        JOIN operations.devices d ON d.id = sic.device_id AND d.deleted_at IS NULL
                                  AND {current_computer_sql("d")}
        JOIN operations.clients c ON c.id = d.client_id AND c.deleted_at IS NULL
        WHERE sd.tenant_id = 1
          AND sd.decision IN ('reject', 'investigate')
          AND sd.publisher <> ''
          AND (sd.device_id IS NULL OR sd.device_id = sic.device_id)
          AND (sd.client_id IS NULL OR sd.client_id = sic.client_id)
          {client_where}
    """

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(findings_sql, client_params)
        finding_rows = cur.fetchall()
        # decisions_sql now has two UNION ALL branches, each carrying its own
        # {client_where}, so its parameters must repeat once per branch.
        cur.execute(decisions_sql, client_params * 2)
        decision_rows = cur.fetchall()

    per_device: dict = {}
    for row in list(finding_rows) + list(decision_rows):
        (
            client_id,
            slug,
            client_name,
            device_id,
            hostname,
            device_role,
            os_group,
            canonical,
            publisher,
            reason,
            finding_type,
            severity,
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
    devices.sort(key=lambda e: (-e["item_count"], e["client_name"], e["hostname"] or ""))

    # Enrich items with category from SoftwareCatalog (canonical lookup).
    all_canonicals = {
        i["canonical_name"].lower() for e in devices for i in e["items"] if i["canonical_name"]
    }
    catalog_cats = (
        {
            c.canonical_name.lower(): ", ".join(c.categories or [])
            for c in SoftwareCatalog.objects.filter(canonical_name__in=list(all_canonicals))
        }
        if all_canonicals
        else {}
    )
    for entry in devices:
        for item in entry["items"]:
            item["category"] = catalog_cats.get((item["canonical_name"] or "").lower(), "")

    clients = Client.objects.filter(tenant_id=1, deleted_at__isnull=True).order_by("display_name")

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
            if (
                needle not in (entry["hostname"] or "").lower()
                and needle not in (entry["client_name"] or "").lower()
            ):
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

    device_page = Paginator(devices, 100).get_page(request.GET.get("page"))
    page_query = request.GET.copy()
    page_query.pop("page", None)

    return render(
        request,
        "software_tech_checklist.html",
        {
            "devices": device_page.object_list,
            "device_count": len(devices),
            "total_items": sum(e["item_count"] for e in devices),
            "clients": clients,
            "active_clients": client_slugs,
            "active_q": q_filter,
            "active_role": role_filter,
            "active_os": os_filter,
            "active_kind": kind_filter,
            "page_obj": device_page,
            "page_query": page_query.urlencode(),
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
    lifecycle_filter = request.GET.get("lifecycle", "")  # retired | pending_cleanup
    if lifecycle_filter not in ("retired", "pending_cleanup"):
        lifecycle_filter = ""
    # Software drill-through: click a device/client count on a Products,
    # title-detail, or publisher-detail page and land here scoped to exactly
    # that slice, reusing this page's existing device list rather than a new
    # one-off view per number.
    software_filter = (request.GET.get("software") or "").strip()  # canonical_name
    version_filter = (request.GET.get("version") or "").strip()
    software_publisher_filter = (request.GET.get("software_publisher") or "").strip()
    is_csv = wants_csv(request)
    try:
        device_page = max(1, int(request.GET.get("page", "1")))
    except ValueError:
        device_page = 1
    device_page_size = 100

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
            WHERE tenant_id = 1 AND lifecycle_status <> 'retired'
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
              COUNT(DISTINCT f.subject_id) FILTER (WHERE ft.issue_category = 'Agents & reporting')::int,
              COUNT(DISTINCT f.subject_id) FILTER (WHERE ft.issue_category = 'Inventory')::int
            FROM operations.findings f
            JOIN operations.finding_types ft ON ft.id = f.finding_type_id
            WHERE f.tenant_id = 1
              AND f.status IN ('open', 'acknowledged', 'investigating')
              AND f.subject_type = 'device'
            """
        )
        agent_reporting_issues, inventory_issues = cur.fetchone()
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
            WHERE tenant_id = 1 AND lifecycle_status <> 'retired'
            GROUP BY os_group ORDER BY COUNT(*) DESC
            """
        )
        os_rows = cur.fetchall()

        # Device table — v_device + client name. Apply filters. Retired
        # Computers are listed only when asked for (the home Computers card).
        where = [
            "v.tenant_id = 1",
            "v.lifecycle_status = 'retired'"
            if lifecycle_filter == "retired"
            else "v.lifecycle_status <> 'retired'",
        ]
        if lifecycle_filter == "pending_cleanup":
            where.append("v.lifecycle_status = 'pending_cleanup'")
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
        if software_filter or software_publisher_filter:
            software_exists = (
                "EXISTS (SELECT 1 FROM operations.software_installations_current sic "
                " WHERE sic.tenant_id = 1 AND sic.device_id = v.device_id "
                "   AND sic.deleted_at IS NULL AND sic.stale_since IS NULL"
            )
            software_params = []
            if software_filter:
                software_exists += " AND LOWER(sic.canonical_name) = LOWER(%s)"
                software_params.append(software_filter)
            if version_filter:
                software_exists += " AND sic.version = %s"
                software_params.append(version_filter)
            if software_publisher_filter:
                software_exists += " AND LOWER(sic.publisher) = LOWER(%s)"
                software_params.append(software_publisher_filter)
            software_exists += ")"
            where.append(software_exists)
            params.extend(software_params)

        where_sql = " AND ".join(where)
        cur.execute(
            f"SELECT COUNT(*)::int FROM operations.v_device v WHERE {where_sql}",
            params,
        )
        filtered_total = cur.fetchone()[0]
        # The severe-issue counts are aggregated ONCE for the page, not per row.
        #
        # `v_device_software_exposure` builds a `software_findings` CTE that is
        # referenced twice, so PostgreSQL materialises it, and the device
        # predicate applies to the installation join rather than to the
        # findings -- so every per-device call rebuilds the whole fleet's
        # software-finding set. Measured 2026-08-17: 363 ms and ~670 MB of
        # buffer traffic for a single device, x500 rows = 176 s for this one
        # statement, which is what made /devices/ exceed the gunicorn worker
        # timeout. Aggregating over one rendered page in one pass keeps the
        # same bounded query shape.
        cur.execute(
            f"""
            WITH page AS MATERIALIZED (
                SELECT v.device_id, v.canonical_hostname, v.canonical_serial,
                       v.device_role, v.os_group, v.os_name,
                       v.is_online_any, v.online_sources, v.last_contact_at,
                       v.effective_patching_scope, v.client_id
                FROM operations.v_device v
                WHERE {where_sql}
                ORDER BY v.canonical_hostname
                {"" if is_csv else "LIMIT %s OFFSET %s"}
            ),
            device_findings AS (
                SELECT f.subject_id AS device_id, COUNT(*) AS n
                FROM operations.findings f
                JOIN page p ON p.device_id = f.subject_id
                WHERE f.tenant_id = 1
                  AND f.subject_type = 'device'
                  AND f.status IN ('open','acknowledged','investigating')
                  AND f.severity IN ('critical','high')
                GROUP BY f.subject_id
            ),
            device_exposure AS (
                SELECT e.device_id, COUNT(DISTINCT e.finding_id) AS n
                FROM operations.v_device_software_exposure e
                WHERE e.tenant_id = 1
                  AND e.status IN ('open','acknowledged','investigating')
                  AND e.severity IN ('critical','high')
                  AND e.device_id IN (SELECT device_id FROM page)
                GROUP BY e.device_id
            )
            SELECT p.device_id, p.canonical_hostname, p.canonical_serial,
                   p.device_role, p.os_group, p.os_name,
                   p.is_online_any, p.online_sources, p.last_contact_at,
                   p.effective_patching_scope,
                   c.display_name AS client_name, c.slug AS client_slug,
                   COALESCE(df.n, 0) + COALESCE(de.n, 0) AS severe_issues
            FROM page p
            LEFT JOIN operations.clients c ON c.id = p.client_id
            LEFT JOIN device_findings df ON df.device_id = p.device_id
            LEFT JOIN device_exposure de ON de.device_id = p.device_id
            ORDER BY p.canonical_hostname
            """,
            params if is_csv else [*params, device_page_size, (device_page - 1) * device_page_size],
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

    if is_csv:
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
            "filtered_total": filtered_total,
            "device_page": device_page,
            "device_page_size": device_page_size,
            "device_pages": max(1, -(-filtered_total // device_page_size)),
            "device_has_previous": device_page > 1,
            "device_has_next": device_page * device_page_size < filtered_total,
            "device_previous_page": device_page - 1,
            "device_next_page": device_page + 1,
            "page_query": urlencode(
                {
                    key: value
                    for key, value in {
                        "q": q_filter,
                        "os": os_filter,
                        "role": role_filter,
                        "online": online_filter,
                        "state": state_filter,
                        "client": client_filter,
                        "lifecycle": lifecycle_filter,
                        "software": software_filter,
                        "version": version_filter,
                        "software_publisher": software_publisher_filter,
                    }.items()
                    if value
                }
            ),
            "clients": clients,
            "active_q": q_filter,
            "active_os": os_filter,
            "active_role": role_filter,
            "active_online": online_filter,
            "active_state": state_filter,
            "active_lifecycle": lifecycle_filter,
            "active_client": client_filter,
            "active_software": software_filter,
            "active_version": version_filter,
            "active_software_publisher": software_publisher_filter,
            "agent_reporting_issues": agent_reporting_issues,
            "inventory_issues": inventory_issues,
            "delayed_sources": delayed_sources,
        },
    )


@login_required
def software_clients(request: HttpRequest) -> HttpResponse:
    """Clients running a given software title/version/publisher.

    The client-scoped counterpart to devices_page's device-scoped filter --
    a client count on a software page should answer "which clients", not
    dump a device-by-device list the operator has to tally by eye. Each row
    links to org_software_devices (existing, client-scoped) for the actual
    device list at that client.
    """
    software_filter = (request.GET.get("software") or "").strip()
    version_filter = (request.GET.get("version") or "").strip()
    software_publisher_filter = (request.GET.get("software_publisher") or "").strip()
    if not software_filter and not software_publisher_filter:
        return redirect("software_products")

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        where = [
            "sic.tenant_id = 1",
            "sic.deleted_at IS NULL",
            "sic.stale_since IS NULL",
            "d.deleted_at IS NULL",
            current_computer_sql("d"),
        ]
        params: list = []
        if software_filter:
            where.append("LOWER(sic.canonical_name) = LOWER(%s)")
            params.append(software_filter)
        if version_filter:
            where.append("sic.version = %s")
            params.append(version_filter)
        if software_publisher_filter:
            where.append("LOWER(sic.publisher) = LOWER(%s)")
            params.append(software_publisher_filter)
        where_sql = " AND ".join(where)
        cur.execute(
            f"""
            SELECT c.id, c.display_name, c.slug,
                   COUNT(DISTINCT sic.device_id)::int AS device_count
            FROM operations.software_installations_current sic
            JOIN operations.clients c ON c.id = sic.client_id
            JOIN operations.devices d ON d.id = sic.device_id AND d.tenant_id = sic.tenant_id
            WHERE {where_sql}
            GROUP BY c.id, c.display_name, c.slug
            ORDER BY device_count DESC, c.display_name
            """,
            params,
        )
        client_rows = cur.fetchall()

    clients = [
        {"id": cid, "display_name": name, "slug": slug, "device_count": dc}
        for cid, name, slug, dc in client_rows
    ]

    if wants_csv(request):
        return csv_response(
            clients,
            columns=[
                ("Client", "display_name"),
                ("Devices", "device_count"),
            ],
            filename_stem="software_clients",
        )

    return render(
        request,
        "software_clients.html",
        {
            "clients": clients,
            "total_devices": sum(c["device_count"] for c in clients),
            "active_software": software_filter,
            "active_version": version_filter,
            "active_software_publisher": software_publisher_filter,
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

_PATCHING_WORKFLOW = {
    "device_never_patched": {
        "label": "No patch installed yet",
        "note": "Confirm patching is enabled",
    },
    "patching_stalled": {
        "label": "No recent patch activity",
        "note": "Check schedule or reporting",
    },
    "reboot_pending": {
        "label": "Restart required",
        "note": "Schedule a restart",
    },
    "patch_failing_repeatedly": {
        "label": "Update repeatedly failing",
        "note": "Repair the failed update",
    },
    "patch_approval_backlog": {
        "label": "Approved updates not installed",
        "note": "Review the client deployment",
    },
}


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
    device_type_filter = request.GET.get("device_type", "").strip()
    os_family_filter = request.GET.get("os_family", "").strip()
    _ROLE_CHOICES = ("server", "workstation", "unknown")
    if role_filter and role_filter not in _ROLE_CHOICES:
        role_filter = ""
    valid_device_types = {value for value, _label in Device.DeviceType.choices}
    if device_type_filter not in valid_device_types:
        device_type_filter = ""

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
        finding_type__issue_category=finding_registry.PATCHING,
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
            "label": _PATCHING_WORKFLOW[ftname]["label"],
            "value": tile_counts.get(ftname, 0),
            "note": _PATCHING_WORKFLOW[ftname]["note"],
            "href": _type_tile_href(ftname),
        }
        for ftname in _PATCHING_TYPES
    ]

    # Device-population summary — how many devices exist in the
    # filtered slice, how many are in scope (Included). Reads
    # v_device (Track O). Scoped to client + role if filtered.
    pop_where = ["tenant_id = %s", current_computer_sql()]
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
    if device_type_filter:
        pop_where.append("device_type = %s")
        pop_params.append(device_type_filter)
    if os_family_filter:
        pop_where.append("os_family = %s")
        pop_params.append(os_family_filter)
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
    if device_type_filter:
        posture_where.append("v.device_type = %s")
        posture_params.append(device_type_filter)
    if os_family_filter:
        posture_where.append("v.os_family = %s")
        posture_params.append(os_family_filter)
    posture_where_sql = " AND ".join(posture_where)

    posture_cte = f"""
        WITH scoped_devices AS (
            SELECT v.device_id, v.client_id, v.canonical_hostname,
                   v.device_role, v.device_type, v.os_family, v.os_group, v.last_contact_at,
                   v.needs_reboot, v.effective_patching_scope
            FROM operations.v_device v
            WHERE {posture_where_sql}
        ), ninja_links AS (
            SELECT DISTINCT dl.device_id,
                   {_safe_ninja_external_id_integer_sql("dl")} AS ninja_device_id
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

    # Client Patch Review previously showed these two percentages in Metabase.
    # Keep the definition in Operations: an active, in-scope device with
    # current patch activity is fully patched when it has no current missing
    # operating-system patch.  The shared contract keeps this semantic aligned
    # with the temporary legacy reporting surface during retirement.
    compliance_breakdowns: dict[str, list[dict]] = {
        "device_type": [],
        "os_family": [],
    }
    active_client_name = ""
    excluded_categories = list(
        excluded_patch_categories(
            os.environ.get("DASHBOARD_PATCH_CATEGORIES_EXCLUDE", "DRIVER_UPDATES")
        )
    )
    if len(filtered_client_ids) == 1:
        active_client_name = (
            Client.objects.filter(tenant_id=1, id=filtered_client_ids[0])
            .values_list("display_name", flat=True)
            .first()
            or ""
        )
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                posture_cte
                + """
                , patching_devices AS (
                    SELECT dp.*,
                           NOT EXISTS (
                               SELECT 1
                               FROM ninja_links nl
                               JOIN ninja_patches.current_patch_state cs
                                 ON cs.device_id = nl.ninja_device_id
                               WHERE nl.device_id = dp.device_id
                                 AND cs.status = ANY(%s::text[])
                                 AND COALESCE(cs.patch_category, 'UNKNOWN') <> ALL(%s::text[])
                           ) AS fully_patched
                    FROM device_posture dp
                    WHERE dp.is_active
                      AND dp.effective_patching_scope = 'Included'
                      AND dp.ever_installed
                      AND dp.has_recent_patch_activity
                ), dimensions AS (
                    SELECT 'device_type'::text AS dimension,
                           COALESCE(NULLIF(device_type, ''), 'Unknown') AS label,
                           fully_patched
                    FROM patching_devices
                    UNION ALL
                    SELECT 'os_family'::text AS dimension,
                           COALESCE(NULLIF(os_family, ''), 'Unknown') AS label,
                           fully_patched
                    FROM patching_devices
                )
                SELECT dimension, label, COUNT(*)::int AS devices,
                       COUNT(*) FILTER (WHERE fully_patched)::int AS fully_patched_devices,
                       ROUND(
                           100.0 * COUNT(*) FILTER (WHERE fully_patched) / NULLIF(COUNT(*), 0),
                           1
                       ) AS fully_patched_pct
                FROM dimensions
                GROUP BY dimension, label
                ORDER BY dimension, fully_patched_pct ASC NULLS LAST, label
                """,
                posture_params + [list(COMPLIANCE_MISSING_STATUSES), excluded_categories],
            )
            for dimension, label, devices, fully_patched_devices, fully_patched_pct in cur.fetchall():
                compliance_breakdowns[dimension].append(
                    {
                        "label": label,
                        "devices": devices,
                        "fully_patched_devices": fully_patched_devices,
                        "fully_patched_pct": fully_patched_pct,
                        "drilldown": urlencode(
                            {
                                "client": client_filter[0],
                                "posture": "fully-patched",
                                dimension: label,
                            }
                        ),
                    }
                )
    # Device population by scope (drilldown from the summary tiles).
    # Optional "scope" query param drills into a specific bucket.
    scope_filter = request.GET.get("scope", "")
    posture_filter = request.GET.get("posture", "")
    device_rows: list = []
    device_total = 0
    try:
        device_page = max(1, int(request.GET.get("device_page", "1")))
    except ValueError:
        device_page = 1
    device_page_size = 100
    if scope_filter in ("Included", "Excluded", "Unmanaged", "Unknown") or posture_filter in (
        "active",
        "active-in-scope",
        "recent-activity",
        "quiet",
        "never-patched",
        "reboot-pending",
        "fully-patched",
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
            elif posture_filter == "fully-patched":
                base_where.extend(
                    (
                        "is_active",
                        "effective_patching_scope = 'Included'",
                        "ever_installed",
                        "has_recent_patch_activity",
                        "NOT EXISTS (SELECT 1 FROM ninja_links nl JOIN ninja_patches.current_patch_state cs ON cs.device_id = nl.ninja_device_id WHERE nl.device_id = device_posture.device_id AND cs.status = ANY(%s::text[]) AND COALESCE(cs.patch_category, 'UNKNOWN') <> ALL(%s::text[]))",
                    )
                )
            device_row_params = posture_params + ([scope_filter] if scope_filter else [])
            if posture_filter == "fully-patched":
                device_row_params += [list(COMPLIANCE_MISSING_STATUSES), excluded_categories]
            cur.execute(
                posture_cte
                + f"""
                SELECT COUNT(*)::int
                FROM device_posture
                WHERE {' AND '.join(base_where)}
                """,
                device_row_params,
            )
            device_total = cur.fetchone()[0]
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
                LIMIT %s OFFSET %s
                """,
                [*device_row_params, device_page_size, (device_page - 1) * device_page_size],
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
                    + "?tab=history"
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
        qs,
        key=lambda f: (
            _SEV_ORDER.get(f.severity, 9),
            -(f.last_detected_at or f.last_seen_at).timestamp(),
        ),
    )

    def _detail(finding: Finding) -> str:
        d = finding.finding_details or {}
        name = finding.finding_type.name
        if name == "device_never_patched":
            return "No installed patch is recorded"
        if name == "patching_stalled":
            ls = d.get("last_patch_seen_at")
            return f"Last patch activity {ls[:10]}" if ls else "No recent patch activity"
        if name == "reboot_pending":
            lb = d.get("last_boot_at")
            return f"Last restart {lb[:10]}" if lb else "No restart is recorded"
        if name == "patch_failing_repeatedly":
            kbs = d.get("failing_patches") or []
            return f"{len(kbs)} update(s) repeatedly failing"
        if name == "patch_approval_backlog":
            return f"{d.get('backlog_count', '?')} approved updates not installed"
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
    device_page_query = request.GET.copy()
    device_page_query.pop("page", None)
    device_page_query.pop("device_page", None)

    # Preserve current filters as query-string fragment for scope
    # drilldown links.
    filter_qs_parts = []
    if client_filter:
        filter_qs_parts.append(f"client={','.join(client_filter)}")
    if status_filter and status_filter != "active":
        filter_qs_parts.append(f"status={status_filter}")
    if role_filter:
        filter_qs_parts.append(f"role={role_filter}")
    if device_type_filter:
        filter_qs_parts.append(f"device_type={device_type_filter}")
    if os_family_filter:
        filter_qs_parts.append(f"os_family={os_family_filter}")
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
            "label": "In scope — patching expected",
            "value": population["in_scope"],
            "href": _scope_href("Included"),
        },
        {
            "label": "Excluded — do not patch",
            "value": population["excluded"],
            "href": _scope_href("Excluded"),
        },
        {
            "label": "Not managed — no patch service",
            "value": population["unmanaged"],
            "href": _scope_href("Unmanaged"),
        },
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
            "active_device_type": device_type_filter,
            "active_os_family": os_family_filter,
            "role_choices": _ROLE_CHOICES,
            "active_scope": scope_filter,
            "total_active": sum(tile_counts.values()),
            "population": population,
            "patch_status": patch_status,
            "client_posture": client_posture,
            "compliance_breakdowns": compliance_breakdowns,
            "active_client_name": active_client_name,
            "active_device_days": active_device_days,
            "patch_activity_days": patch_activity_days,
            "active_posture": posture_filter,
            "filter_qs": filter_qs,
            "device_rows": device_rows,
            "device_total": device_total,
            "device_page": device_page,
            "device_page_size": device_page_size,
            "device_pages": max(1, -(-device_total // device_page_size)),
            "device_has_previous": device_page > 1,
            "device_has_next": device_page * device_page_size < device_total,
            "device_previous_page": device_page - 1,
            "device_next_page": device_page + 1,
            "device_page_query": device_page_query.urlencode(),
            "page_query": page_query.urlencode(),
        },
    )


@login_required
@require_admin
@require_POST
def client_mapping_decide(request: HttpRequest, source_link_id: str) -> HttpResponse:
    state = (request.POST.get("state") or "").strip()
    reason = (request.POST.get("reason") or "").strip()
    if state not in {"explicit", "automatic", "ignored", "review"} or not reason:
        messages.error(request, "A valid decision and reason are required.")
        return redirect(_safe_next(request, "client_mappings"))
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            "SELECT operations.decide_client_source_mapping_v1(1, %s, %s, %s, %s)",
            [source_link_id, state, reason, request.user.pk],
        )
    messages.success(request, "Client mapping decision recorded.")
    return redirect(_safe_next(request, "client_mappings"))


@login_required
def client_source_reference_detail(request: HttpRequest, source_link_id: str) -> HttpResponse:
    """Evidence and lifecycle history for one client/source attachment."""
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """
            SELECT mapping.source_link_id, client.slug, client.display_name, source.name,
                   mapping.external_id, mapping.external_namespace, mapping.observed_name,
                   mapping.observed_at, mapping.first_seen_at, mapping.last_seen_at,
                   mapping.missing_since, mapping.mapping_state, mapping.provenance,
                   mapping.decision_reason, mapping.decided_at
              FROM operations.v_client_source_mapping_effective mapping
              JOIN operations.clients client ON client.id = mapping.client_id
              JOIN operations.sources source ON source.id = mapping.source_id
             WHERE mapping.tenant_id = 1 AND mapping.source_link_id = %s::uuid
            """,
            [source_link_id],
        )
        row = cur.fetchone()
        if row is None:
            raise Http404("Client source record not found")
        cur.execute(
            """
            SELECT state, provenance, reason, decided_at, superseded_at
              FROM operations.client_source_mapping_decisions
             WHERE tenant_id = 1 AND source_link_id = %s::uuid
             ORDER BY decided_at DESC
            """,
            [source_link_id],
        )
        history = [
            {
                "state": state,
                "provenance": provenance,
                "reason": reason,
                "decided_at": decided_at,
                "superseded_at": superseded_at,
            }
            for state, provenance, reason, decided_at, superseded_at in cur.fetchall()
        ]
    fields = (
        "source_link_id",
        "client_slug",
        "client_name",
        "source_name",
        "external_id",
        "external_namespace",
        "observed_name",
        "observed_at",
        "first_seen_at",
        "last_seen_at",
        "missing_since",
        "state",
        "provenance",
        "reason",
        "decided_at",
    )
    reference = dict(zip(fields, row, strict=True))
    return render(
        request,
        "client_source_reference_detail.html",
        {
            "reference": reference,
            "history": history,
            "admin_group": "integrations" if request.user.is_staff else "",
            "admin_tab": "client-mappings" if request.user.is_staff else "",
        },
    )


def _newest_candidate_name_by_group() -> dict[tuple[int, str], tuple[str, str]]:
    """Map each source group to the candidate name holding its newest reference.

    Candidates are keyed by name while a source group is identified by its id,
    so a group renamed at the source appears under both names.  The newest
    reference shows which name the source uses now.
    """
    newest: dict[tuple[int, str], tuple[datetime, str, str]] = {}
    for candidate in ClientCandidate.objects.filter(tenant_id=1).only(
        "normalized_name", "display_name", "source_refs"
    ):
        for ref in candidate.source_refs or []:
            key = (ref.get("source_id"), str(ref.get("external_id")))
            seen = parse_datetime(ref.get("observed_at") or "") or datetime.min
            if timezone.is_naive(seen):
                seen = seen.replace(tzinfo=dt_timezone.utc)  # noqa: UP017 - module idiom
            if key not in newest or seen > newest[key][0]:
                name = candidate.display_name or candidate.normalized_name
                newest[key] = (seen, candidate.normalized_name, name)
    return {key: (normalized, name) for key, (_, normalized, name) in newest.items()}


def _live_source_group_evidence(
    pairs: set[tuple[int, str]],
) -> tuple[dict[tuple[int, str], bool], dict[tuple[int, str], dict[str, tuple | None]]]:
    """Current org observations (with attachment) and source records per group."""
    reported: dict[tuple[int, str], bool] = {}
    records_by_group: dict[tuple[int, str], dict[str, tuple]] = {}
    if not pairs:
        return reported, records_by_group
    source_ids = [pair[0] for pair in pairs]
    external_ids = [pair[1] for pair in pairs]
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """
            SELECT si.source_id, observation.entity_key,
                   bool_or(observation.client_id IS NOT NULL)
              FROM operations.v_entity_observation_admin_metadata observation
              JOIN operations.source_instances si ON si.id = observation.source_instance_id
             WHERE observation.entity_type = 'org'
               AND observation.active
               AND (si.source_id, observation.entity_key) IN (
                   SELECT * FROM unnest(%s::int[], %s::text[]))
             GROUP BY si.source_id, observation.entity_key
            """,
            (source_ids, external_ids),
        )
        reported = {(source_id, key): attached for source_id, key, attached in cur.fetchall()}
        cur.execute(
            """
            SELECT DISTINCT si.source_id, observation.platform_group_id, observation.entity_key,
                   observation.device_id, client.id, client.display_name
              FROM operations.v_entity_observation_admin_metadata observation
              JOIN operations.source_instances si ON si.id = observation.source_instance_id
              LEFT JOIN operations.devices device
                     ON device.id = observation.device_id AND device.deleted_at IS NULL
              LEFT JOIN operations.clients client ON client.id = device.client_id
             WHERE observation.entity_type <> 'org'
               AND observation.active
               AND (si.source_id, observation.platform_group_id) IN (
                   SELECT * FROM unnest(%s::int[], %s::text[]))
            """,
            (source_ids, external_ids),
        )
        # Records in an unattached group are mostly not yet linked to a
        # Computer, so each source record counts; a linked Computer adds its
        # owning client as evidence.
        for source_id, group_id, entity_key, device_id, client_id, client_name in cur.fetchall():
            records_by_group.setdefault((source_id, group_id), {})[f"{source_id}:{entity_key}"] = (
                str(device_id) if device_id else None,
                (str(client_id), client_name) if client_id else None,
            )
    return reported, records_by_group


def _source_group_state(key, normalized_name, newest_name, reported) -> tuple[str, str]:
    owner = newest_name.get(key)
    if owner and owner[0] != normalized_name:
        return "renamed", owner[1]
    if key not in reported:
        return "gone", ""
    return ("attached" if reported[key] else "reported"), ""


def _candidate_live_groups(candidate) -> tuple[list[tuple[int, str]], dict]:
    """The candidate's source groups the source still reports under this name,
    and the active records in them (renamed, attached, and gone groups excluded).
    """
    refs = candidate.source_refs or []
    pairs = {
        (ref.get("source_id"), str(ref.get("external_id")))
        for ref in refs
        if ref.get("source_id") and ref.get("external_id")
    }
    newest_name = _newest_candidate_name_by_group()
    reported, records_by_group = _live_source_group_evidence(pairs)
    live = [
        key
        for key in pairs
        if _source_group_state(key, candidate.normalized_name, newest_name, reported)[0]
        == "reported"
    ]
    return live, records_by_group


def _candidate_client_overlap(live, records_by_group) -> tuple[list[dict], int]:
    """Existing clients that already own Computers in the candidate's live groups.

    Counts every active record in those groups (not a sample), so the strongest
    map-to-existing signal is complete. Returns the owning clients, largest
    first, and how many Computers in the groups are linked at all.
    """
    devices: dict[str, tuple | None] = {}
    for key in live:
        for device_id, owner in records_by_group.get(key, {}).values():
            if device_id:
                devices[device_id] = owner
    owners = Counter(owner for owner in devices.values() if owner)
    overlap = [
        {"client_id": client_id, "display_name": name, "device_count": count}
        for (client_id, name), count in owners.most_common()
    ]
    return overlap, len(devices)


def _name_matches_by_row(live_by_row: dict[int, list[tuple[int, str]]]) -> dict[int, tuple]:
    """Existing clients whose Computers carry the names of each row's unlinked
    records, for many candidates in one query.

    Weaker evidence than a linked Computer: a record not yet matched to a
    Computer still reports a computer name. A name counts only when exactly one
    client owns a current Computer with it; names many clients use (generic
    images, default names) say nothing about ownership. Returns, per row, the
    matching clients largest first and how many unlinked records report a name.
    """
    groups = [(row, key[0], key[1]) for row, keys in live_by_row.items() for key in keys]
    result: dict[int, tuple] = {row: ([], 0) for row in live_by_row}
    if not groups:
        return result
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """
            WITH live_groups AS (
                SELECT * FROM unnest(%s::int[], %s::int[], %s::text[])
                    AS g(row_index, source_id, external_id)
            ), unlinked AS (
                SELECT DISTINCT g.row_index, si.source_id, observation.entity_key,
                       lower(observation.reported_name) AS name
                  FROM operations.v_entity_observation_admin_metadata observation
                  JOIN operations.source_instances si ON si.id = observation.source_instance_id
                  JOIN live_groups g
                    ON g.source_id = si.source_id AND g.external_id = observation.platform_group_id
                 WHERE observation.entity_type <> 'org' AND observation.active
                   AND observation.device_id IS NULL
                   AND COALESCE(observation.reported_name, '') <> ''
            ), single_owner AS (
                SELECT lower(device.canonical_hostname) AS name, min(device.client_id::text) AS client_id
                  FROM operations.devices device
                 WHERE device.tenant_id = 1 AND device.deleted_at IS NULL
                   AND device.lifecycle_status <> 'retired' AND device.client_id IS NOT NULL
                   AND COALESCE(device.canonical_hostname, '') <> ''
                 GROUP BY 1
                HAVING count(DISTINCT device.client_id) = 1
            ), named AS (
                SELECT row_index, count(*)::int AS named FROM unlinked GROUP BY 1
            )
            SELECT named.row_index, named.named, client.id::text, client.display_name,
                   count(unlinked.entity_key)::int AS records
              FROM named
              LEFT JOIN unlinked ON unlinked.row_index = named.row_index
              LEFT JOIN single_owner ON single_owner.name = unlinked.name
              LEFT JOIN operations.clients client
                ON client.id::text = single_owner.client_id AND client.deleted_at IS NULL
             GROUP BY 1, 2, 3, 4
             ORDER BY 1, 5 DESC, 4
            """,
            (
                [group[0] for group in groups],
                [group[1] for group in groups],
                [group[2] for group in groups],
            ),
        )
        for row_index, named, client_id, name, records in cur.fetchall():
            matches, _ = result[row_index]
            if client_id:
                matches.append(
                    {"client_id": client_id, "display_name": name, "record_count": records}
                )
            result[row_index] = (matches, named)
    return result


def _candidate_name_matches(live) -> tuple[list[dict], int]:
    """Name evidence for one candidate's live groups (see ``_name_matches_by_row``)."""
    return _name_matches_by_row({0: list(live)})[0]


def _client_source_ids(client_ids: set[str]) -> dict[str, set[int]]:
    """Sources in which each client already has its own attached group."""
    if not client_ids:
        return {}
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """
            SELECT DISTINCT client_id::text, source_id
              FROM operations.v_client_source_mapping_effective
             WHERE tenant_id = 1 AND client_id::text = ANY(%s)
               AND mapping_state <> 'ignored'
            """,
            [sorted(client_ids)],
        )
        result: dict[str, set[int]] = {}
        for client_id, source_id in cur.fetchall():
            result.setdefault(client_id, set()).add(source_id)
    return result


def _first_unseparated(options: list[dict], live, separate: dict[str, set[int]]):
    """The strongest suggested client a source does not already keep separate.

    When a source reports the new client as its own group and the suggested
    client has its own, different group in that same source, the source says
    they are separate clients; shared computers then point to a misfiled
    source group, not to the same client (e.g. NYCD Management vs City
    Painting in Hudu, Ninja and SentinelOne).
    """
    own_sources = {key[0] for key in live}
    for option in options:
        if not separate.get(option["client_id"], set()) & own_sources:
            return option
    return None


def _add_candidate_evidence(
    candidates: list[dict], source_names: dict, *, with_likely_client: bool = False
) -> None:
    """Annotate client candidates with live evidence for the list view.

    ``source_refs`` keeps every source group ever seen under the name, so each
    group is checked against current observations: whether the source still
    reports it under this name and the source records currently in it.  Historical groups stay
    listed but marked and contribute no live evidence.

    ``with_likely_client`` adds the existing client the evidence points to,
    strongest first: Computers already linked, then computer names only that
    client has (the same evidence the candidate page shows).
    """
    pairs = {
        (ref.get("source_id"), str(ref.get("external_id")))
        for row in candidates
        for ref in row["refs"]
        if ref.get("source_id") and ref.get("external_id")
    }
    newest_name = _newest_candidate_name_by_group()
    reported, records_by_group = _live_source_group_evidence(pairs)

    live_by_row: dict[int, list[tuple[int, str]]] = {}
    for index, row in enumerate(candidates):
        groups = []
        records: dict[str, tuple] = {}
        live_by_row[index] = []
        for ref in row["refs"]:
            key = (ref.get("source_id"), str(ref.get("external_id")))
            state, renamed_to = _source_group_state(
                key, row["candidate"].normalized_name, newest_name, reported
            )
            groups.append(
                {
                    "source": source_names.get(ref.get("source_id"), "Unknown source"),
                    "external_name": ref.get("external_name") or "",
                    "reported": state == "reported",
                    "state": state,
                    "renamed_to": renamed_to,
                }
            )
            if state == "reported":
                records.update(records_by_group.get(key, {}))
                live_by_row[index].append(key)
        row["groups"] = sorted(groups, key=lambda group: (not group["reported"], group["source"]))
        row["reported_count"] = sum(1 for group in groups if group["reported"])
        row["renamed_to"] = sorted({group["renamed_to"] for group in groups if group["renamed_to"]})
        row["attached_count"] = sum(1 for group in groups if group["state"] == "attached")
        row["record_count"] = len(records)
        devices = {device_id: owner for device_id, owner in records.values() if device_id}
        row["computer_count"] = len(devices)
        row["likely_client"] = None
        owners = Counter(owner for owner in devices.values() if owner)
        row["linked_options"] = [
            {
                "client_id": client_id,
                "display_name": name,
                "basis": "linked",
                "count": count,
                "of": len(devices),
            }
            for (client_id, name), count in owners.most_common()
        ]

    if not with_likely_client:
        return
    name_matches = _name_matches_by_row(live_by_row)
    name_options = {
        index: [
            {
                "client_id": match["client_id"],
                "display_name": match["display_name"],
                "basis": "names",
                "count": match["record_count"],
                "of": named,
            }
            for match in matches
        ]
        for index, (matches, named) in name_matches.items()
    }
    separate = _client_source_ids(
        {option["client_id"] for row in candidates for option in row["linked_options"]}
        | {option["client_id"] for options in name_options.values() for option in options}
    )
    for index, row in enumerate(candidates):
        row["likely_client"] = _first_unseparated(
            row["linked_options"], live_by_row[index], separate
        ) or _first_unseparated(name_options.get(index, []), live_by_row[index], separate)


@login_required
@require_admin
def client_mappings(request: HttpRequest) -> HttpResponse:
    """Complete Operations lifecycle surface for client/source identity.

    This deliberately joins three persisted workflows instead of presenting
    only attached links: effective source-client relationships, unresolved
    source-client candidates, and resolver-detected ambiguity.  A source
    record must never disappear from the admin surface merely because it is
    not attached to a client yet.
    """
    source_link_id = (request.GET.get("source_link_id") or "").strip()
    client_id = (request.GET.get("client_id") or "").strip()
    source_filter = (request.GET.get("source") or "").strip()
    state_filter = (request.GET.get("state") or "all").strip()
    query = (request.GET.get("q") or "").strip()
    valid_states = {
        "all",
        "mapped",
        "review",
        "explicit",
        "automatic",
        "ignored",
        "unattached",
        "ambiguous",
    }
    if state_filter not in valid_states:
        state_filter = "all"

    where = ["mapping.tenant_id = 1"]
    params: list[str] = []
    if source_link_id:
        where.append("mapping.source_link_id = %s::uuid")
        params.append(source_link_id)
    if client_id:
        where.append("mapping.client_id = %s::uuid")
        params.append(client_id)
    if source_filter:
        where.append("source.name = %s")
        params.append(source_filter)
    if query:
        where.append(
            "(client.display_name ILIKE %s OR mapping.observed_name ILIKE %s OR mapping.external_id ILIKE %s)"
        )
        params.extend([f"%{query}%"] * 3)
    if state_filter in {"review", "explicit", "automatic", "ignored"}:
        where.append("mapping.mapping_state = %s")
        params.append(state_filter)

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            f"""
            SELECT mapping.source_link_id, mapping.client_id, client.slug, client.display_name, source.name,
                   mapping.external_id, mapping.observed_name, mapping.observed_at,
                   mapping.mapping_state, mapping.provenance,
                   mapping.decision_reason, mapping.decided_at
              FROM operations.v_client_source_mapping_effective mapping
              JOIN operations.clients client ON client.id = mapping.client_id
              JOIN operations.sources source ON source.id = mapping.source_id
             WHERE {' AND '.join(where)}
             ORDER BY client.display_name, source.name, mapping.external_id
            """,
            params,
        )
        mapped_rows = [
            {
                "source_link_id": row[0],
                "client_id": row[1],
                "client_slug": row[2],
                "client_name": row[3],
                "source_name": row[4],
                "external_id": row[5],
                "observed_name": row[6],
                "observed_at": row[7],
                "state": row[8],
                "provenance": row[9],
                "reason": row[10],
                "decided_at": row[11],
            }
            for row in cur.fetchall()
        ]
        link_ids = [str(row["source_link_id"]) for row in mapped_rows]
        history_by_link: dict[str, list[dict]] = {}
        if link_ids:
            cur.execute(
                """
                SELECT source_link_id, state, provenance, reason, decided_at, superseded_at
                  FROM operations.client_source_mapping_decisions
                 WHERE tenant_id = 1 AND source_link_id = ANY(%s::uuid[])
                 ORDER BY source_link_id, decided_at DESC
                """,
                (link_ids,),
            )
            for link_id, state, provenance, reason, decided_at, superseded_at in cur.fetchall():
                history_by_link.setdefault(str(link_id), []).append(
                    {
                        "state": state,
                        "provenance": provenance,
                        "reason": reason,
                        "decided_at": decided_at,
                        "superseded_at": superseded_at,
                    }
                )

    names_by_client_id: dict[str, set[str]] = {}
    for reference in client_source_references():
        if reference["observed_name"]:
            names_by_client_id.setdefault(str(reference["client_id"]), set()).add(
                reference["observed_name"]
            )
    for row in mapped_rows:
        names = sorted(names_by_client_id.get(str(row["client_id"]), set()))
        row["other_names"] = [name for name in names if name != row["observed_name"]]
        row["history"] = history_by_link.get(str(row["source_link_id"]), [])

    # Candidate history remains visible to administrators as audit evidence;
    # only the unattached filter narrows this to records requiring action.
    candidates = []
    if state_filter in {"all", "unattached"}:
        candidate_qs = ClientCandidate.objects.filter(tenant_id=1)
        if state_filter == "unattached":
            candidate_qs = candidate_qs.filter(status=ClientCandidate.Status.OPEN)
        if query:
            candidate_qs = candidate_qs.filter(
                Q(display_name__icontains=query) | Q(normalized_name__icontains=query)
            )
        source_names = {source.id: source.name for source in Source.objects.all()}
        for candidate in candidate_qs.order_by("display_name"):
            refs = candidate.source_refs or []
            candidate_sources = sorted(
                {source_names.get(ref.get("source_id"), "Unknown source") for ref in refs}
            )
            if source_filter and source_filter not in candidate_sources:
                continue
            candidates.append({"candidate": candidate, "sources": candidate_sources, "refs": refs})
        _add_candidate_evidence(candidates, source_names)

    ambiguity_types = (
        "client_link_collision",
        "client_source_group_merge",
        "client_unattached_group",
        "unnamed_source_group",
        "unmatched_source_group",
    )
    ambiguities = []
    if state_filter in {"all", "ambiguous"}:
        ambiguity_qs = (
            AdminFinding.objects.filter(
                tenant_id=1,
                status__in=("open", "acknowledged"),
                finding_type__name__in=ambiguity_types,
            )
            .select_related("finding_type")
            .order_by("-last_detected_at")
        )
        for finding in ambiguity_qs:
            subject = finding.subject_ref or {}
            details = finding.details or {}
            source_id = subject.get("source_id") or details.get("source_id")
            source = Source.objects.filter(id=source_id).first() if source_id else None
            evidence = (
                subject.get("observed_name")
                or subject.get("external_name_stored")
                or details.get("observed_name")
                or details.get("external_id")
                or "No source name recorded"
            )
            if (
                query
                and query.lower() not in str(evidence).lower()
                and query.lower() not in finding.finding_type.name.lower()
            ):
                continue
            if source_filter and (source is None or source.name != source_filter):
                continue
            ambiguities.append(
                {
                    "finding": finding,
                    "source_name": source.name if source else "Unknown source",
                    "evidence": evidence,
                    "details": details,
                    "subject": subject,
                }
            )

    if state_filter == "mapped":
        mapped_rows = [row for row in mapped_rows if row["state"] != "review"]

    source_options = list(Source.objects.order_by("name").values_list("name", flat=True))
    return render(
        request,
        "client_mappings.html",
        {
            "admin_group": "integrations",
            "admin_tab": "client-mappings",
            "rows": mapped_rows,
            "candidates": candidates,
            "ambiguities": ambiguities,
            "source_options": source_options,
            "active_state": state_filter,
            "active_source": source_filter,
            "query": query,
            "show_mapped": state_filter not in {"unattached", "ambiguous"},
            "show_unattached": state_filter in {"all", "unattached"},
            "show_ambiguous": state_filter in {"all", "ambiguous"},
            "selected_mapping": bool(source_link_id),
        },
    )


@login_required
def inventory_clients(request: HttpRequest) -> HttpResponse:
    """Client inventory: computers and how fully each source covers them.

    Coverage for a source is the number of the client's active (not retired)
    Computers with a current record from that source, out of all its active
    Computers. Source identity detail remains in Admin.
    """
    query = (request.GET.get("q") or "").strip()
    clients = Client.objects.filter(tenant_id=1, deleted_at__isnull=True).order_by("display_name")
    if query:
        clients = clients.filter(display_name__icontains=query)

    rows_by_client: dict[str, dict] = {
        str(client.id): {
            "client": client,
            "computer_count": 0,
            "groups": {},
            "references": [],
            "covered": {},
            "name_difference_count": 0,
        }
        for client in clients
    }
    for reference in client_source_references():
        row = rows_by_client.get(str(reference["client_id"]))
        if row is not None:
            row["references"].append(reference)

    active_computers = current_computers(
        Device.objects.filter(tenant_id=1, deleted_at__isnull=True)
    )
    for item in active_computers.values("client_id").annotate(n=Count("id")):
        row = rows_by_client.get(str(item["client_id"]))
        if row is not None:
            row["computer_count"] = item["n"]

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """
            SELECT device.client_id::text, evidence.source_name, count(DISTINCT device.id)
              FROM operations.v_device_observation_current evidence
              JOIN operations.devices device ON device.id = evidence.device_id
             WHERE evidence.tenant_id = 1 AND evidence.observation_active
               AND device.deleted_at IS NULL AND device.lifecycle_status <> %s
             GROUP BY 1, 2
            """,
            [Device.LifecycleStatus.RETIRED],
        )
        for client_id, source, covered in cur.fetchall():
            row = rows_by_client.get(client_id)
            if row is not None:
                row["covered"][source] = covered

    for item in (
        Finding.objects.filter(
            tenant_id=1,
            status__in=_FINDING_ACTIVE_STATUSES,
            finding_type__name="client_name_conflict",
        )
        .values("client_id")
        .annotate(n=Count("id"))
    ):
        row = rows_by_client.get(str(item["client_id"]))
        if row is not None:
            row["name_difference_count"] = item["n"]

    for row in rows_by_client.values():
        total = row["computer_count"]
        references = row["references"]
        row["first_seen"] = min(
            (r["first_seen_at"] for r in references if r["first_seen_at"]), default=None
        )
        row["last_seen"] = max(
            (r["last_seen_at"] for r in references if r["last_seen_at"]), default=None
        )
        for reference in references:
            source = reference["source_name"]
            row["groups"][source] = row["groups"].get(source, 0) + 1
        row["coverage"] = [
            {
                "source": source,
                "covered": row["covered"].get(source, 0),
                "groups": row["groups"].get(source, 0),
                "last_seen": max(
                    (
                        r["last_seen_at"]
                        for r in references
                        if r["source_name"] == source and r["last_seen_at"]
                    ),
                    default=None,
                ),
                "complete": total > 0 and row["covered"].get(source, 0) >= total,
            }
            for source in sorted(set(row["groups"]) | set(row["covered"]))
        ]

    # New / discovered clients: a view of the same open records Issues lists
    # as unattached client source groups (one Issue per group), so the counts
    # here are the Issues' counts.
    source_names = {source.id: source.name for source in Source.objects.all()}
    new_clients = [
        {"candidate": candidate, "refs": candidate.source_refs or []}
        for candidate in ClientCandidate.objects.filter(
            tenant_id=1, status=ClientCandidate.Status.OPEN
        ).order_by("-last_seen_at", "display_name")
    ]
    _add_candidate_evidence(new_clients, source_names, with_likely_client=True)
    new_group_count = sum(len(row["refs"]) for row in new_clients)
    return render(
        request,
        "inventory_clients.html",
        {
            "active_section": "inventory",
            "rows": list(rows_by_client.values()),
            "query": query,
            "open_candidates": len(new_clients),
            "new_clients": new_clients,
            "new_client_count": len(new_clients),
            "new_group_count": new_group_count,
            "new_clients_issues_url": (
                f"{reverse('findings_queue')}?"
                + urlencode(
                    {
                        "category": "inventory",
                        "type": "client_mapping",
                        "issue": "client_unattached_group",
                    }
                )
            ),
        },
    )


@login_required
@require_admin
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
    findings = list(qs)
    client_ids = {
        (finding.subject_ref or {}).get("client_id")
        for finding in findings
        if (finding.subject_ref or {}).get("client_id")
    }
    clients = {
        str(client.id): client
        for client in Client.objects.filter(
            tenant_id=1,
            id__in=client_ids,
            deleted_at__isnull=True,
        ).only("id", "slug", "display_name")
    }
    source_ids = {
        (finding.subject_ref or {}).get("source_id")
        for finding in findings
        if (finding.subject_ref or {}).get("source_id") is not None
    }
    source_names = {
        str(source_id): name
        for source_id, name in Source.objects.filter(id__in=source_ids).values_list("id", "name")
    }
    assessments = _condition_assessment_display("admin", (finding.id for finding in findings))
    for finding in findings:
        finding.assessment = assessments.get(str(finding.id))
        details = finding.details or {}
        ref = finding.subject_ref or {}
        finding.subject_client = clients.get(str(ref.get("client_id")))
        finding.client_name = ref.get("client_display_name") or ""
        finding.observed_name = ref.get("observed_name") or ""
        finding.source_name = source_names.get(str(ref.get("source_id")), "")
        finding.source_url = (
            reverse("sources_status") + "?" + urlencode({"source": finding.source_name})
            if finding.source_name
            else ""
        )
        if details.get("job_run_id") or details.get("dependent_job_run_id"):
            finding.job_status_url = (
                reverse("admin_job_status")
                + "?"
                + urlencode({"run": details.get("job_run_id") or details["dependent_job_run_id"]})
            )
        elif details.get("job_key"):
            finding.job_status_url = (
                reverse("admin_job_status") + "?" + urlencode({"job": details["job_key"]})
            )
        elif details.get("queue_key") == "operator.jobs":
            finding.job_status_url = reverse("admin_job_status")
        else:
            finding.job_status_url = ""
        finding.control_plane_url = (
            reverse("admin_jobs_control_plane")
            + "?"
            + urlencode({"section": details["control_section"]})
            if details.get("control_section")
            else ""
        )
        finding.health_presentation = _admin_health_finding_presentation(finding)

    finding_types = FindingType.objects.filter(finding_class="admin").order_by("name")
    condition_profile = None
    try:
        condition_profile = load_active_profile()
        condition_policy_available = True
    except (RuntimeError, ValueError):
        condition_policy_available = False

    condition_coverage = _condition_coverage_summary(condition_profile)
    health = _admin_health_snapshot()

    return render(
        request,
        "findings_admin_health.html",
        {
            "admin_group": "health",
            "admin_tab": "health",
            "condition_policy_available": condition_policy_available,
            "findings": findings,
            "finding_types": finding_types,
            "severity_choices": Finding.Severity.choices,
            "active_status": status_filter,
            "active_severity": severity_filter,
            "active_type": type_filter,
            "condition_coverage": condition_coverage,
            "health": health,
        },
    )


def _admin_health_finding_presentation(finding: AdminFinding) -> dict:
    """Present one existing AdminFinding as an administrator intervention.

    The finding and its evidence remain authoritative.  This small read-model
    adapter prevents the Health list from requiring an administrator to infer
    impact and next steps from condition keys, policy digests, or raw payloads.
    """
    finding_type = finding.finding_type.name
    title = finding.finding_type.description or finding_type.replace("_", " ").capitalize()
    impact = "This platform condition needs administrator review."
    action = "Review the related evidence and address the underlying condition."
    if finding_type == "source_failure":
        impact = "Information from this source may be out of date."
        action = "Review the source connection and retry its collection when it is ready."
    elif finding_type in {"jobs_schedule_failure", "jobs_required_disabled"}:
        impact = "Scheduled processing may not run when it is needed."
        action = "Review the Job schedule and correct its configuration."
    elif finding_type == "jobs_queue_backlog":
        impact = "Some processing is taking longer than the configured expectation."
        action = "Review waiting Jobs and the reason they cannot start."
    elif finding_type in {"jobs_repeated_failure", "jobs_timeout"}:
        impact = "Related data may not be current until the Job completes successfully."
        action = "Review the failed Job, its result, and retry safety before retrying."
    elif finding_type == "jobs_unmet_dependency":
        impact = "A Job is waiting for required earlier processing."
        action = "Open the Job to review the required result and its current state."
    elif finding_type == "jobs_registry_mismatch":
        impact = "Jobs configuration and the running service do not agree."
        action = "Review Jobs configuration and current service evidence before changing settings."
    elif finding_type == "software_queue_stalled":
        impact = "Software processing may be behind the current collected data."
        action = "Review the affected Job queue and its waiting or failed Runs."

    links = []
    if getattr(finding, "source_url", ""):
        links.append({"label": "Open source", "url": finding.source_url})
    if getattr(finding, "job_status_url", ""):
        links.append({"label": "Open Job", "url": finding.job_status_url})
    if getattr(finding, "control_plane_url", ""):
        links.append({"label": "Open Job configuration", "url": finding.control_plane_url})
    if finding_type == "source_failure":
        links.append(
            {
                "label": "Open related Issues",
                "url": reverse("findings_queue")
                + "?"
                + urlencode({"category": "data_collection", "type": "collection_and_processing"}),
            }
        )
    if not links:
        links.append({"label": "Open Health evidence", "url": reverse("findings_admin_health")})
    return {"title": title, "impact": impact, "action": action, "links": links}


def _condition_coverage_summary(profile) -> list[dict]:
    """Return fresh assessment coverage for every active policy condition."""
    definitions = profile.definitions if profile else {}
    if not definitions:
        return []
    names = sorted(definitions)
    taxonomy_by_condition = {
        name: {
            "category": finding_registry.slug(category),
            "category_label": category,
            "type": finding_registry.slug(group),
            "type_label": group,
        }
        for name, category, group in FindingType.objects.values_list(
            "name", "issue_category", "issue_group"
        )
    }
    placeholders = ", ".join(["%s"] * len(names))
    with connection.cursor() as cur:
        cur.execute("SELECT to_regclass('operations.condition_assessments') IS NOT NULL")
        if not cur.fetchone()[0]:
            return [
                {
                    "name": name,
                    "label": finding_registry.finding_type_name(name),
                    "category": taxonomy_by_condition.get(name, {}).get(
                        "category_label", definitions[name].get("category", "")
                    ),
                    "category_key": taxonomy_by_condition.get(name, {}).get("category", ""),
                    "type": taxonomy_by_condition.get(name, {}).get(
                        "type_label", definitions[name].get("type", "")
                    ),
                    "type_key": taxonomy_by_condition.get(name, {}).get("type", ""),
                    "retained": 0,
                    "assessed": 0,
                    "missing": 0,
                }
                for name in names
            ]
        cur.execute(
            f"""
            WITH retained AS (
                SELECT 'entity' AS row_kind, f.id AS finding_id, f.condition_key AS name
                  FROM operations.findings f
                 WHERE f.tenant_id = 1
                   AND f.status IN ('open', 'acknowledged', 'investigating')
                   AND f.condition_key IN ({placeholders})
                UNION ALL
                SELECT 'admin', f.id, f.condition_key
                  FROM operations.admin_findings f
                 WHERE f.tenant_id = 1
                   AND f.status IN ('open', 'acknowledged', 'investigating')
                   AND f.condition_key IN ({placeholders})
            ), assessed AS (
                SELECT a.row_kind, a.finding_id,
                       COALESCE(
                           array_agg(DISTINCT
                               a.participant_kind || ':' || a.participant_id::text || ':' || a.participant_role
                               ORDER BY a.participant_kind || ':' || a.participant_id::text || ':' || a.participant_role
                           ) FILTER (WHERE a.participant_kind <> 'condition'
                                   AND a.participant_role <> 'context'),
                           ARRAY[]::text[]
                       ) AS participants,
                       bool_or(a.participant_kind = 'condition') AS condition_assessed
                  FROM operations.condition_assessments a
                  JOIN operations.condition_policy_versions p
                    ON p.version = a.policy_version AND p.active
                 WHERE a.tenant_id = 1
                   AND a.assessed_at >= now() -
                       (p.policy->>'freshness_hours')::integer * interval '1 hour'
                 GROUP BY a.row_kind, a.finding_id
            ), expected AS (
                SELECT row_kind, finding_id,
                       COALESCE(
                           array_agg(DISTINCT
                               participant_kind || ':' || participant_id::text || ':' || participant_role
                               ORDER BY participant_kind || ':' || participant_id::text || ':' || participant_role
                           ),
                           ARRAY[]::text[]
                       ) AS participants
                  FROM operations.condition_participants
                 WHERE participant_role <> 'context'
                 GROUP BY row_kind, finding_id
            )
            SELECT r.name, count(*) AS retained,
                   count(*) FILTER (
                       WHERE (COALESCE(array_length(e.participants, 1), 0) = 0 AND a.condition_assessed)
                          OR (COALESCE(array_length(e.participants, 1), 0) > 0
                              AND a.participants = e.participants)
                   ) AS assessed
              FROM retained r
              LEFT JOIN assessed a
                ON a.row_kind = r.row_kind AND a.finding_id = r.finding_id
              LEFT JOIN expected e
                ON e.row_kind = r.row_kind AND e.finding_id = r.finding_id
             GROUP BY r.name
            """,
            names + names,
        )
        counts = {
            name: (int(retained), int(assessed)) for name, retained, assessed in cur.fetchall()
        }
    return [
        {
            "name": name,
            "label": finding_registry.finding_type_name(name),
            "category": taxonomy_by_condition.get(name, {}).get(
                "category_label", definitions[name].get("category", "")
            ),
            "category_key": taxonomy_by_condition.get(name, {}).get("category", ""),
            "type": taxonomy_by_condition.get(name, {}).get(
                "type_label", definitions[name].get("type", "")
            ),
            "type_key": taxonomy_by_condition.get(name, {}).get("type", ""),
            "retained": counts.get(name, (0, 0))[0],
            "assessed": counts.get(name, (0, 0))[1],
            "missing": max(
                0,
                counts.get(name, (0, 0))[0] - counts.get(name, (0, 0))[1],
            ),
        }
        for name in names
    ]


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

    messages.info(
        request,
        "Mapped source names are evidence, not a required client rename. "
        "Review or exclude the client finding instead.",
    )
    return redirect("findings_admin_health")

    ref = finding.subject_ref or {}
    observed_name = (ref.get("observed_name") or "").strip()
    client_id = ref.get("client_id")
    if not observed_name or not client_id:
        messages.error(
            request,
            "This finding is missing the observed name or client reference; " "cannot apply.",
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
    if win11_filter not in {value for value, _label in _WINDOWS_11_COMPATIBILITY_CHOICES}:
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
    """Compatibility route for the retired duplicate-computer queue."""
    return redirect(f"{reverse('findings_queue')}?type=duplicate_computers")


def _merge_candidates_legacy_queue(request: HttpRequest) -> HttpResponse:
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
    base_where = f"""tenant_id = %s AND client_id = %s AND deleted_at IS NULL
        AND stale_since IS NULL
        AND device_id IN (
            SELECT id FROM operations.devices
            WHERE tenant_id = 1 AND deleted_at IS NULL
              AND {current_computer_sql()}
        )"""
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
                  AND s.deleted_at IS NULL
                  AND s.stale_since IS NULL
                  AND d.deleted_at IS NULL
                  AND {current_computer_sql("d")}{pub_clause}
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
    reason = (request.POST.get("reason") or "").strip()
    problem = software_decision_rules.comment_problem(
        decision, publisher_level=False, comment=reason
    )
    if problem:
        messages.error(request, problem)
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
            "reason": reason,
            "decided_by": request.user,
            "decided_at": timezone.now(),
        },
    )
    _queue_software_rebuild_after_commit(request.user.id)
    # Follow only a relative ``next``; an unvalidated one (and HTTP_REFERER,
    # which is attacker-settable) is an open redirect.
    nxt = request.POST.get("next") or ""
    if nxt.startswith("/") and not nxt.startswith("//"):
        return redirect(nxt)
    return redirect("org_software", org_slug=org_slug)


# ── Inventory / Computers page ───────────────────────────────────────────────

_SEV_RANK = (
    "CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END"
)
# Requirements the evaluator does not apply (ADR-0036), with the reason.
_NOT_APPLIED_STATES = ("N/A — OS unknown", "N/A — Offline", "No agents")
# Record statuses renamed on the page; old bookmarked filter values still work.
_LEGACY_RECORD_STATUSES = {"No status reported": "No status"}
_COVERAGE_STATES = ("Online", "Offline", "Stale", "Missing", *_NOT_APPLIED_STATES)
# Computers summary-card order; any other platform follows alphabetically.
_COMPUTER_CARD_ORDER = ("Ninja", "SentinelOne", "LogMeIn", "R-U-ON", "ScreenConnect", "Hudu")
# Computers Status filter, in display order. "Agent" means every catalogued
# agent (operations.agents with an agent.* entity type), never a fixed list.
_COMPUTER_SCOPE_LABELS = {
    "any_online": "Online in any agent",
    "any_offline": "Offline in any agent",
    "missing_required": "Missing a requirement",
    "stale_required": "A requirement is stale",
    "has_product_record": "Current record in any agent",
    "no_product_records": "No current agent record",
    "no_current_records": "No current record anywhere (agents or Hudu)",
}


def _inventory_record_status(
    platform: str, row: dict, source_status: str | None, observation: dict | None
) -> str:
    """Record fact for one platform on one Computers inventory row."""
    if platform == "Hudu":
        # Hudu assets are cmdb records, read by the dedicated Hudu reader.
        if row.get("hudu_current_count"):
            return "No status"
        return "Withdrawn" if row.get("hudu_archived_count") else "No record"
    if source_status == "Current" or (
        not source_status and observation and observation["state"] == "Current"
    ):
        return "No status"
    if source_status in {"Online", "Offline"}:
        return source_status
    if observation and observation["state"] == "Withdrawn":
        return "Withdrawn"
    return "No record"


def _computer_card_order(card: dict) -> tuple[int, str]:
    platform = card["platform"]
    if platform in _COMPUTER_CARD_ORDER:
        return _COMPUTER_CARD_ORDER.index(platform), ""
    return len(_COMPUTER_CARD_ORDER), platform.casefold()


def _safe_external_http_url(value: str | None) -> str:
    """Return an external Hudu URL only when it has a safe web scheme."""
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value
    return ""


def _coverage_filter_url(**filters: str) -> str:
    """Build a Coverage URL from non-empty filter values."""
    return "?" + urlencode({key: value for key, value in filters.items() if value})


@login_required
def fleet_coverage(request: HttpRequest) -> HttpResponse:
    """Show every known Computer with its product records and required state."""
    compact_source_observations = not wants_csv(request)
    client_filters = list(dict.fromkeys(value for value in request.GET.getlist("client") if value))
    device_query = (request.GET.get("device") or "").strip().lower()
    agents_query = (request.GET.get("agents") or "").strip().lower()
    # ``platform``, ``state``, and ``online_in`` are retained as legacy query
    # parameters for existing drill-through URLs.  New controls express a
    # condition as one source plus that source's selected statuses.
    platform_filters = list(
        dict.fromkeys(value for value in request.GET.getlist("platform") if value)
    )
    online_filters = list(
        dict.fromkeys(value for value in request.GET.getlist("online_in") if value)
    )
    requested_coverage_sources = request.GET.getlist("coverage_source")
    requested_coverage_statuses = request.GET.getlist("coverage_status")
    any_platform_filters = [
        value for value in request.GET.getlist("any_platform_status") if value in _COVERAGE_STATES
    ]
    any_platform_selected = request.GET.get("any_platform") == "1"
    no_platform_selected = request.GET.get("no_platform") == "1"
    computer_scope_filters = list(
        dict.fromkeys(
            value
            for value in request.GET.getlist("computer_scope")
            if value
            in {
                "has_product_record",
                "any_online",
                "any_offline",
                "no_product_records",
                "no_current_records",
                "missing_required",
                "stale_required",
            }
        )
    )
    requested_record_status_filters = request.GET.getlist("record_status")
    requested_rule_status_filters = request.GET.getlist("rule_status")
    hudu_filters = list(
        dict.fromkeys(
            value for value in request.GET.getlist("hudu") if value in {"in_hudu", "not_in_hudu"}
        )
    )
    hudu_record_filter_active = "in_hudu" in hudu_filters
    hudu_link_filters = list(
        dict.fromkeys(
            value
            for value in request.GET.getlist("hudu_links")
            if value in {"has_links", "no_links"}
        )
    )
    hudu_record_filter = request.GET.get("hudu_record_filter")
    if hudu_record_filter not in {
        "any",
        "has_current",
        "has_archived",
        "current_only",
        "archived_only",
        "both",
    }:
        legacy_mode = request.GET.get("hudu_archive")
        if legacy_mode == "archived":
            hudu_record_filter = "has_archived"
        elif legacy_mode == "both" or request.GET.get("show_archived_hudu") == "1":
            hudu_record_filter = "any"
        else:
            hudu_record_filter = "any"
    s1_exemption_filters = list(
        dict.fromkeys(
            value
            for value in request.GET.getlist("s1_exemption")
            if value in {"exempt", "not_exempt"}
        )
    )
    os_family_filters = list(
        dict.fromkeys(value for value in request.GET.getlist("os_family") if value)
    )
    device_type_filters = list(
        dict.fromkeys(value for value in request.GET.getlist("device_type") if value)
    )
    device_role_filters = list(
        dict.fromkeys(value for value in request.GET.getlist("device_role") if value)
    )
    state_filters = [value for value in request.GET.getlist("state") if value in _COVERAGE_STATES]
    requested_platform_status_filters = request.GET.getlist("platform_status")

    with transaction.atomic():  # noqa: SIM117 -- tenant GUC must remain local
        with connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")

            # ADR-0035: the evaluator's coverage pass stores a verdict for every
            # requirement; the page reads it and never re-derives the rule.
            # Online/Offline is source evidence, read live from presence.
            # Exempt requirements are not shown as requirements (SentinelOne
            # exemptions are shown through s1_exempt).
            cur.execute(
                """
                WITH presence AS MATERIALIZED (
                    SELECT presence.device_id, presence.entity_type, presence.platform,
                           BOOL_OR(presence.reported_online) AS online
                    FROM operations.device_agent_presence_current presence
                    WHERE presence.tenant_id = 1
                    GROUP BY presence.device_id, presence.entity_type, presence.platform
                ), presence_by_requirement AS MATERIALIZED (
                    SELECT device_id, entity_type, platform, online FROM presence
                    UNION ALL
                    SELECT device_id, entity_type, 'any' AS platform, BOOL_OR(online)
                    FROM presence
                    GROUP BY device_id, entity_type
                )
                SELECT c.slug AS client_slug,
                       c.display_name AS client_name,
                       d.id AS device_id,
                       COALESCE(d.canonical_hostname, '') AS hostname,
                       COALESCE(d.os_family, '') AS os_family,
                       d.device_type,
                       state.platform,
                       COALESCE(decision.value, '{}'::jsonb) ? 'agent.edr' AS s1_exempt,
                       CASE state.verdict
                           WHEN 'missing' THEN 'Missing'
                           WHEN 'stale' THEN 'Stale'
                           WHEN 'satisfied' THEN
                               CASE WHEN COALESCE(presence.online, FALSE) THEN 'Online'
                                    ELSE 'Offline' END
                           WHEN 'os_unknown' THEN 'N/A — OS unknown'
                           WHEN 'pending_cleanup' THEN 'N/A — Offline'
                           ELSE 'No agents'
                       END AS status,
                       FALSE AS hudu_present,
                       state.evaluated_at
                FROM operations.device_requirement_state state
                JOIN operations.devices d
                  ON d.tenant_id = state.tenant_id
                 AND d.id = state.device_id
                 AND d.deleted_at IS NULL
                 AND d.lifecycle_status <> 'retired'
                JOIN operations.clients c ON c.id = d.client_id
                LEFT JOIN operations.device_operator_decisions decision
                  ON decision.tenant_id = d.tenant_id
                 AND decision.device_id = d.id
                 AND decision.dimension = 'exemptions'
                LEFT JOIN presence_by_requirement presence
                  ON presence.device_id = state.device_id
                 AND presence.entity_type = state.entity_type
                 AND presence.platform = state.platform
                WHERE state.tenant_id = 1
                  AND state.verdict <> 'exempt'
                ORDER BY c.display_name, hostname, state.platform
            """,
            )
            rows = cur.fetchall()
            cur.execute(
                """
                SELECT hudu.observation_id, hudu.device_id, hudu.client_id,
                       hudu.hostname,
                       lifecycle.record_lifecycle = 'archived' AS is_archived,
                       BOOL_OR(hudu.card_source IS NOT NULL AND hudu.card_id IS NOT NULL)
                           AS has_links
                FROM operations.v_hudu_computer_inventory_evidence_current hudu
                LEFT JOIN operations.v_device_source_record_lifecycle_current lifecycle
                  ON lifecycle.tenant_id = hudu.tenant_id
                 AND lifecycle.observation_id = hudu.observation_id
                GROUP BY hudu.observation_id, hudu.device_id, hudu.client_id,
                         hudu.hostname, lifecycle.record_lifecycle
                """,
            )
            hudu_rows = cur.fetchall()
            cur.execute(
                """
                SELECT d.id, d.client_id, c.slug, c.display_name,
                       COALESCE(d.canonical_hostname, ''),
                       COALESCE(d.os_family, ''), d.device_type, d.device_role,
                       d.lifecycle_status,
                       COALESCE(decision.value, '{}'::jsonb) ? 'agent.edr'
                           AS s1_exempt
                FROM operations.devices d
                JOIN operations.clients c ON c.id = d.client_id
                LEFT JOIN operations.device_operator_decisions decision
                  ON decision.tenant_id = d.tenant_id
                 AND decision.device_id = d.id
                 AND decision.dimension = 'exemptions'
                WHERE d.tenant_id = 1
                  AND d.deleted_at IS NULL
                  AND d.lifecycle_status <> 'retired'
                ORDER BY c.display_name, d.canonical_hostname
                """,
            )
            computer_rows = cur.fetchall()
            cur.execute(
                """
                SELECT id, slug, display_name
                FROM operations.clients
                WHERE tenant_id = 1
                  AND deleted_at IS NULL
                """,
            )
            client_rows = cur.fetchall()
            cur.execute(
                """
                SELECT presence.device_id, presence.platform,
                       BOOL_OR(presence.reported_online) AS online
                FROM operations.device_agent_presence_current presence
                WHERE presence.tenant_id = 1
                  AND (presence.entity_type LIKE 'agent.%%' OR presence.entity_type = 'vm.guest')
                GROUP BY presence.device_id, presence.platform
                """,
            )
            source_presence_rows = cur.fetchall()
            # Use the same source-observation state shown on a Computer's
            # Observations tab.  Presence supplies availability; observation
            # state tells the inventory reader whether a record is current or
            # withdrawn.  The source-link timestamp is the actual withdrawal
            # time rather than the older last-seen timestamp.
            if compact_source_observations:
                cur.execute(
                    """
                    SELECT evidence.device_id, evidence.source_name,
                           BOOL_OR(evidence.observation_active) AS has_current_record,
                           NULL::timestamptz AS current_seen_at,
                           NULL::timestamptz AS withdrawn_at
                      FROM operations.v_device_observation_current evidence
                     WHERE evidence.tenant_id = 1
                       AND (evidence.entity_type LIKE 'agent.%%'
                            OR evidence.entity_type = 'vm.guest')
                     GROUP BY evidence.device_id, evidence.source_name
                    """
                )
            else:
                cur.execute(
                    """
                    SELECT evidence.device_id, evidence.source_name,
                           BOOL_OR(evidence.observation_active) AS has_current_record,
                           MAX(evidence.observation_last_seen_at)
                               FILTER (WHERE evidence.observation_active) AS current_seen_at,
                           MAX(COALESCE(link.missing_since, evidence.observation_last_seen_at))
                               FILTER (WHERE NOT evidence.observation_active) AS withdrawn_at
                      FROM operations.v_device_observation_current evidence
                      JOIN operations.source_instances source_instance
                        ON source_instance.tenant_id = evidence.tenant_id
                       AND source_instance.id = evidence.source_instance_id
                      LEFT JOIN operations.v_device_source_link link
                        ON link.tenant_id = evidence.tenant_id
                       AND link.device_id = evidence.device_id
                       AND link.source_id = source_instance.source_id
                       AND link.external_id = evidence.external_id
                     WHERE evidence.tenant_id = 1
                       AND (evidence.entity_type LIKE 'agent.%%'
                            OR evidence.entity_type = 'vm.guest')
                     GROUP BY evidence.device_id, evidence.source_name
                    """
                )
            source_observation_rows = cur.fetchall()
            cur.execute(
                "SELECT name FROM operations.agents WHERE entity_type LIKE 'agent.%%'"
            )
            agent_platforms = {row[0] for row in cur.fetchall()}

    devices_by_id = {
        row[0]: {
            "device_id": row[0],
            "client_id": row[1],
            "client_slug": row[2],
            "client_name": row[3],
            "hostname": row[4],
            "os_family": row[5],
            "device_type": row[6],
            "device_role": row[7],
            "lifecycle_status": row[8],
            "s1_exempt": bool(row[9]),
        }
        for row in computer_rows
    }
    hostnames_by_device = {
        **{row[2]: row[3] for row in rows},
        **{device_id: row["hostname"] for device_id, row in devices_by_id.items()},
    }
    clients_by_id = {row[0]: {"slug": row[1], "name": row[2]} for row in client_rows}
    source_states_by_device: dict = {}
    for device_id, platform, online in source_presence_rows:
        source_states_by_device.setdefault(device_id, {})[platform] = (
            "Online" if online is True else "Offline" if online is False else "Current"
        )
    source_observations_by_device: dict = {}
    for (
        device_id,
        platform,
        has_current_record,
        current_seen_at,
        withdrawn_at,
    ) in source_observation_rows:
        source_observations_by_device.setdefault(device_id, {})[platform] = {
            "state": "Current" if has_current_record else "Withdrawn",
            "current_seen_at": current_seen_at,
            "withdrawn_at": withdrawn_at,
        }

    hudu_by_observation: dict = {}
    for observation_id, device_id, client_id, hostname, is_archived, has_links in hudu_rows:
        hudu_by_observation[observation_id] = {
            "observation_id": observation_id,
            "device_id": device_id,
            "client_id": client_id,
            "hostname": hostname or "",
            "is_archived": bool(is_archived),
            "has_links": bool(has_links),
        }

    hudu_by_device: dict = {}
    for hudu in hudu_by_observation.values():
        if hudu["device_id"] is not None:
            hudu_by_device.setdefault(hudu["device_id"], []).append(hudu)

    coverage_rows = [
        {
            "client_slug": row[0],
            "client_name": row[1],
            "device_id": row[2],
            "hostname": row[3],
            "os_family": row[4],
            "device_type": row[5],
            "platform": row[6],
            "s1_exempt": row[7],
            "status": row[8],
        }
        for row in rows
    ]
    # Every verdict of a coverage pass carries that pass's time (ADR-0035).
    requirements_evaluated_at = max((row[10] for row in rows), default=None)
    # A Computer can have more than one requirement within one platform.  The
    # inventory card must still count that Computer once, using the status an
    # operator should address first.
    coverage_status_rank = {
        "Missing": 0,
        "Stale": 1,
        "N/A — OS unknown": 2,
        "N/A — Offline": 2,
        "No agents": 2,
        "Offline": 3,
        "Online": 4,
    }
    coverage_by_device: dict = {}
    for row in coverage_rows:
        platform_states = coverage_by_device.setdefault(row["device_id"], {})
        existing = platform_states.get(row["platform"])
        if (
            existing is None
            or coverage_status_rank[row["status"]] < coverage_status_rank[existing["status"]]
        ):
            platform_states[row["platform"]] = row

    coverage_platforms = sorted({row["platform"] for row in coverage_rows})
    # Same order as the summary cards: the agreed products, then the rest.
    platforms = sorted(
        set(coverage_platforms)
        | {platform for states in source_states_by_device.values() for platform in states}
        | {
            platform
            for observations in source_observations_by_device.values()
            for platform in observations
        }
        # Hudu's line comes from its own evidence reader, so it is listed
        # whenever Hudu records exist, not only when a verdict mentions it.
        | ({"Hudu"} if hudu_rows else set()),
        key=lambda platform: _computer_card_order({"platform": platform}),
    )
    record_status_filters: dict[str, list[str]] = {}
    rule_status_filters: dict[str, list[str]] = {}
    allowed_record_statuses = {
        "Online",
        "Offline",
        "Withdrawn",
        "No record",
        "No status",
        "Possible match",
    }
    allowed_rule_statuses = {"Required", "Missing", "Stale", *_NOT_APPLIED_STATES, "N/A", "Exempt"}
    for value in requested_record_status_filters:
        product, separator, status = value.partition("|")
        status = _LEGACY_RECORD_STATUSES.get(status, status)
        if separator and product in platforms and status in allowed_record_statuses:
            record_status_filters.setdefault(product, []).append(status)
    for value in requested_rule_status_filters:
        product, separator, status = value.partition("|")
        if separator and product in platforms and status in allowed_rule_statuses:
            rule_status_filters.setdefault(product, []).append(status)

    # Translate bookmarks made by the previous combined column filter.  The
    # new controls keep the record fact separate from the authored rule.
    platform_status_filters: dict[str, list[str]] = {}
    allowed_platform_states = {*_COVERAGE_STATES, "Not applicable", "Possible match"}
    for value in requested_platform_status_filters:
        platform, separator, status = value.partition("|")
        if separator and platform in platforms and status in allowed_platform_states:
            platform_status_filters.setdefault(platform, []).append(status)
            if status in {"Online", "Offline", "Possible match"}:
                record_status_filters.setdefault(platform, []).append(status)
            elif status in {"Missing", "Stale"}:
                rule_status_filters.setdefault(platform, []).append(status)
            elif status == "Not applicable":
                rule_status_filters.setdefault(platform, []).append("N/A")
    coverage_source_filters = {
        platform for platform in requested_coverage_sources if platform in platforms
    }
    # Keep historical required-platform URLs useful during the transition.
    coverage_source_filters.update(
        platform for platform in platform_filters if platform in platforms
    )
    coverage_status_filters: dict[str, list[str]] = {
        platform: [] for platform in coverage_source_filters
    }
    for value in requested_coverage_statuses:
        platform, separator, status = value.partition("|")
        if separator and platform in platforms and status in _COVERAGE_STATES:
            coverage_source_filters.add(platform)
            coverage_status_filters.setdefault(platform, []).append(status)
    for platform in online_filters:
        if platform in platforms:
            coverage_source_filters.add(platform)
            coverage_status_filters.setdefault(platform, []).append("Online")
    for platform in coverage_source_filters:
        coverage_status_filters.setdefault(platform, [])
    for selections in (record_status_filters, rule_status_filters, coverage_status_filters):
        for platform, statuses in selections.items():
            selections[platform] = list(dict.fromkeys(statuses))
    agent_filter_conditions = []
    for index in range(12):
        agent = request.GET.get(f"agent_{index}")
        states = [
            value
            for value in (
                _LEGACY_RECORD_STATUSES.get(raw, raw)
                for raw in request.GET.getlist(f"agent_state_{index}")
            )
            if value in allowed_record_statuses
        ]
        requirements = [
            value
            for value in request.GET.getlist(f"agent_requirement_{index}")
            if value in allowed_rule_statuses
        ]
        if agent not in platforms or not (states or requirements):
            continue
        agent_filter_conditions.append(
            {
                "index": index,
                "agent": agent,
                "states": list(dict.fromkeys(states)),
                "requirements": list(dict.fromkeys(requirements)),
            }
        )
    # Existing links remain valid.  Treat their former per-column selections
    # as builder conditions so old bookmarks retain the same AND semantics.
    legacy_agent_conditions = {
        platform: {
            "agent": platform,
            "states": record_status_filters.get(platform, []),
            "requirements": rule_status_filters.get(platform, []),
        }
        for platform in set(record_status_filters) | set(rule_status_filters)
    }
    all_agent_conditions = agent_filter_conditions + list(legacy_agent_conditions.values())
    agent_filter_forms = agent_filter_conditions or [
        {
            "index": 0,
            "agent": "",
            "states": [],
            "requirements": [],
        }
    ]
    coverage_filter_sources = [
        {
            "name": platform,
            "selected": platform in coverage_source_filters,
            "statuses": coverage_status_filters.get(platform, []),
        }
        for platform in platforms
    ]
    os_families = sorted({row["os_family"] for row in devices_by_id.values() if row["os_family"]})
    device_types = sorted(
        {row["device_type"] for row in devices_by_id.values() if row["device_type"]}
    )
    device_roles = sorted(
        {row["device_role"] for row in devices_by_id.values() if row["device_role"]}
    )
    filter_clients = sorted(
        clients_by_id.values(),
        key=lambda row: row["name"],
    )

    def aggregate_hudu(records: list[dict]) -> dict:
        has_current = any(not record["is_archived"] for record in records)
        has_archived = any(record["is_archived"] for record in records)
        hudu_matches_record_filter = {
            "any": bool(records),
            "has_current": has_current,
            "has_archived": has_archived,
            "current_only": has_current and not has_archived,
            "archived_only": has_archived and not has_current,
            "both": has_current and has_archived,
        }[hudu_record_filter]
        matching_records = (
            records
            if not hudu_record_filter_active
            else [
                record
                for record in records
                if (
                    hudu_record_filter in {"any", "has_current", "current_only", "both"}
                    and not record["is_archived"]
                )
                or (
                    hudu_record_filter in {"any", "has_archived", "archived_only", "both"}
                    and record["is_archived"]
                )
            ]
        )
        hudu = {
            "hudu_present": bool(records),
            "hudu_archived": bool(records) and all(record["is_archived"] for record in records),
            "hudu_has_archived": any(record["is_archived"] for record in records),
            "hudu_observation_ids": [record["observation_id"] for record in records],
            "hudu_links": [],
            "hudu_records": [],
            "hudu_matches_record_filter": hudu_matches_record_filter,
            "hudu_matching_links": any(record["has_links"] for record in matching_records),
        }
        hudu["hudu_current_count"] = sum(not record["is_archived"] for record in records)
        hudu["hudu_archived_count"] = sum(record["is_archived"] for record in records)
        hudu["hudu_status"] = (
            (
                "Archived in Hudu"
                if hudu["hudu_archived"]
                else "In Hudu (also archived)"
                if hudu["hudu_has_archived"]
                else "In Hudu"
            )
            if hudu["hudu_present"]
            else "Not in Hudu"
        )
        return hudu

    inventory_rows = []
    for device_id, computer in devices_by_id.items():
        coverage_states = coverage_by_device.get(device_id, {})
        inventory_rows.append(
            {
                **computer,
                "inventory_key": f"device:{device_id}",
                "hudu_records": hudu_by_device.get(device_id, []),
                "source_states": source_states_by_device.get(device_id, {}),
                "source_observations": source_observations_by_device.get(device_id, {}),
                "platform_states": coverage_states,
                "possible_match": None,
            }
        )

    for row in inventory_rows:
        row.update(aggregate_hudu(row.pop("hudu_records")))
        if row["device_id"] and row["lifecycle_status"] == "pending_cleanup":
            row["review_url"] = (
                f"{reverse('findings_queue')}?"
                f"{urlencode({'type': 'device_missing_from_source', 'status': 'all', 'subject_id': row['device_id']})}"
            )
        else:
            row["review_url"] = ""

    def observation_age_label(at: datetime | None) -> str:
        if at is None:
            return ""
        seconds = max(0, int((timezone.now() - at).total_seconds()))
        if seconds < 3600:
            return f"{max(1, seconds // 60)}m"
        if seconds < 86400:
            return f"{seconds // 3600}h"
        return f"{seconds // 86400}d"

    def agent_filter_url(
        agent: str,
        *,
        state: str = "",
        states: tuple[str, ...] = (),
        requirement: str = "",
    ) -> str:
        params: list[tuple[str, str]] = [("agent_0", agent)]
        params.extend(("agent_state_0", value) for value in states or ((state,) if state else ()))
        if requirement:
            params.append(("agent_requirement_0", requirement))
        return "?" + urlencode(params)

    def inventory_platform_cell(
        row: dict, platform: str, *, presentation: bool = False
    ) -> dict:
        """Return status facts, adding URLs and tooltips only for rendered rows."""
        possible_match = row["possible_match"] if platform == "Ninja" else None
        coverage = row["platform_states"].get(platform)
        source_status = row["source_states"].get(platform)
        observation = row["source_observations"].get(platform)

        record_status = _inventory_record_status(platform, row, source_status, observation)

        record_age = ""
        if record_status == "Withdrawn" and observation:
            record_age = observation_age_label(observation["withdrawn_at"])
        elif record_status == "Offline" and observation:
            record_age = observation_age_label(observation["current_seen_at"])

        if platform == "SentinelOne" and row["s1_exempt"]:
            rule_status = "Exempt"
            rule_label = "Exempt"
        elif coverage:
            rule_status = coverage.get("status")
            if rule_status not in {"Missing", "Stale", *_NOT_APPLIED_STATES}:
                rule_status = "Required"
            rule_label = (
                f"Required · {rule_status}" if rule_status in {"Missing", "Stale"} else rule_status
            )
        else:
            rule_status = "N/A"
            rule_label = "N/A"

        record_tooltip = {
            "Online": f"{platform} currently reports this Computer online.",
            "Offline": f"{platform} has a current record but reports it offline.",
            "Withdrawn": f"{platform} previously reported this Computer but no longer does.",
            "No record": f"No current {platform} record is linked to this Computer.",
            "No status": f"{platform} still lists this Computer but does not say whether it is online.",
        }[record_status]
        rule_tooltip = {
            "Required": f"{platform} is required for this Computer.",
            "Missing": f"{platform} is required, but no qualifying current record was found.",
            "Stale": f"{platform} is required, but its qualifying record is stale.",
            "N/A — OS unknown": (
                f"{platform} is not applied: no source reports this Computer's operating "
                "system, and the requirement is limited to particular operating systems."
            ),
            "N/A — Offline": (
                f"{platform} is not applied: this Computer has been offline past the "
                "retire-review threshold and is awaiting cleanup in Lifecycle."
            ),
            "No agents": (
                f"{platform} is not applied: this Computer has no agent records; it is "
                "tracked only by other sources (see the unenrolled finding)."
            ),
            "N/A": f"{platform} is not required for this Computer.",
            "Exempt": "This Computer has a saved SentinelOne exemption.",
        }[rule_status]
        return {
            "platform": platform,
            "record_status": record_status,
            "record_age": record_age,
            "record_url": agent_filter_url(platform, state=record_status) if presentation else "",
            "record_tooltip": record_tooltip if presentation else "",
            "rule_status": rule_status,
            "rule_label": rule_label,
            "rule_url": agent_filter_url(platform, requirement=rule_status)
            if presentation
            else "",
            "rule_tooltip": rule_tooltip if presentation else "",
            "possible_match": possible_match,
            "attention": rule_status in {"Missing", "Stale"},
        }

    for row in inventory_rows:
        row["platform_cells_by_name"] = {
            platform: inventory_platform_cell(row, platform) for platform in platforms
        }
        row["agents_filter_text"] = " ".join(
            " ".join(
                value
                for value in (
                    cell["platform"],
                    cell["record_status"],
                    cell["record_age"],
                    cell["rule_label"],
                    "Possible match" if cell["possible_match"] else "",
                    (cell["possible_match"].get("hostname", "") if cell["possible_match"] else ""),
                )
                if value
            )
            for cell in row["platform_cells_by_name"].values()
        ).lower()

    def agent_condition_matches(row: dict, condition: dict) -> bool:
        cell = row["platform_cells_by_name"][condition["agent"]]
        states = condition["states"]
        if states and not (
            cell["record_status"] in states
            or ("Possible match" in states and cell["possible_match"])
        ):
            return False
        requirements = condition["requirements"]
        if not requirements:
            return True
        return cell["rule_status"] in requirements or (
            "Required" in requirements
            and cell["rule_status"] in {"Required", "Missing", "Stale"}
        )

    def matches(row: dict) -> bool:
        if client_filters and row["client_slug"] not in client_filters:
            return False
        if device_query and device_query not in row["hostname"].lower():
            return False
        if agents_query and agents_query not in row["agents_filter_text"]:
            return False
        if no_platform_selected and row["source_states"]:
            return False
        if computer_scope_filters:
            named_products = {
                name: cell
                for name, cell in row["platform_cells_by_name"].items()
                if name in agent_platforms
            }
            has_named_record = any(
                cell["record_status"] in {"Online", "Offline", "No status"}
                for cell in named_products.values()
            )
            has_current_record = any(
                cell["record_status"] in {"Online", "Offline", "No status"}
                for cell in row["platform_cells_by_name"].values()
            )
            scope_matches = {
                "has_product_record": has_named_record,
                "any_online": any(
                    cell["record_status"] == "Online" for cell in named_products.values()
                ),
                "any_offline": any(
                    cell["record_status"] == "Offline" for cell in named_products.values()
                ),
                "no_product_records": not has_named_record,
                "no_current_records": (not has_current_record and row["hudu_current_count"] == 0),
                "missing_required": any(
                    item.get("status") == "Missing" for item in row["platform_states"].values()
                ),
                "stale_required": any(
                    item.get("status") == "Stale" for item in row["platform_states"].values()
                ),
            }
            if not any(scope_matches[value] for value in computer_scope_filters):
                return False
        if any_platform_selected or any_platform_filters:
            row_states = {item["status"] for item in row["platform_states"].values()} | set(
                row["source_states"].values()
            )
            if not row_states or (
                any_platform_filters and not row_states.intersection(any_platform_filters)
            ):
                return False
        for platform in coverage_source_filters:
            status = (
                row["platform_states"].get(platform, {}).get("status")
                or row["source_states"].get(platform)
                or "Not applicable"
            )
            selected_statuses = coverage_status_filters[platform]
            if status == "Not applicable" or (
                selected_statuses and status not in selected_statuses
            ):
                return False
        matching_coverage = list(row["platform_states"].values())
        if platform_filters:
            matching_coverage = [
                item for item in matching_coverage if item["platform"] in platform_filters
            ]
            if not matching_coverage:
                return False
        if state_filters and not any(item["status"] in state_filters for item in matching_coverage):
            return False
        if os_family_filters and row["os_family"] not in os_family_filters:
            return False
        if device_type_filters and row["device_type"] not in device_type_filters:
            return False
        if device_role_filters and row["device_role"] not in device_role_filters:
            return False
        if hudu_filters:
            hudu_value = "in_hudu" if row["hudu_present"] else "not_in_hudu"
            if hudu_value not in hudu_filters:
                return False
        if hudu_link_filters:
            if not row["hudu_matches_record_filter"]:
                return False
            hudu_link_value = "has_links" if row["hudu_matching_links"] else "no_links"
            if hudu_link_value not in hudu_link_filters:
                return False
        if s1_exemption_filters:
            s1_value = "exempt" if row["s1_exempt"] else "not_exempt"
            if s1_value not in s1_exemption_filters:
                return False
        if hudu_record_filter_active and not row["hudu_matches_record_filter"]:
            return False
        return all(agent_condition_matches(row, condition) for condition in all_agent_conditions)

    device_rows = [row for row in inventory_rows if matches(row)]
    record_status_order = (
        "Online",
        "Offline",
        "No status",
        "Withdrawn",
        "No record",
    )
    present_record_statuses = tuple(
        status for status in record_status_order if status != "No record"
    )
    platform_cards = []
    for platform in platforms:
        record_counts = {status: 0 for status in record_status_order}
        requirement_total = 0
        requirement_counts = {
            status: 0 for status in ("Missing", "Stale", "Exempt")
        }
        for inventory_row in inventory_rows:
            cell = inventory_row["platform_cells_by_name"][platform]
            record_counts[cell["record_status"]] += 1
            if cell["rule_status"] in {"Required", "Missing", "Stale"}:
                requirement_total += 1
            if cell["rule_status"] in requirement_counts:
                requirement_counts[cell["rule_status"]] += 1
        platform_cards.append(
            {
                "platform": platform,
                "counts": [
                    {
                        "name": status,
                        "count": record_counts[status],
                        "url": agent_filter_url(platform, state=status),
                    }
                    for status in record_status_order
                    # "No status" is a fallback no source produces today; show it only when used.
                    if status != "No status" or record_counts[status]
                ]
                + [
                    {
                        "name": "Total",
                        "count": sum(record_counts[status] for status in present_record_statuses),
                        "url": agent_filter_url(platform, states=present_record_statuses),
                    }
                ],
                "requirement_total": requirement_total,
                "requirement_total_url": agent_filter_url(platform, requirement="Required"),
                "requirement_exceptions": [
                    {
                        "name": status,
                        "count": requirement_counts[status],
                        "url": agent_filter_url(platform, requirement=status),
                    }
                    for status in ("Missing", "Stale", "Exempt")
                    if requirement_counts[status]
                ],
            }
        )

    hudu_counts = {
        "Current only": sum(
            bool(row["hudu_current_count"] and not row["hudu_archived_count"])
            for row in inventory_rows
        ),
        "Current + archived": sum(
            bool(row["hudu_current_count"] and row["hudu_archived_count"]) for row in inventory_rows
        ),
        "Archived only": sum(
            bool(not row["hudu_current_count"] and row["hudu_archived_count"])
            for row in inventory_rows
        ),
        "No record": sum(not row["hudu_present"] for row in inventory_rows),
    }
    hudu_urls = {
        "Current only": _coverage_filter_url(
            hudu="in_hudu",
            hudu_record_filter="current_only",
        ),
        "Current + archived": _coverage_filter_url(
            hudu="in_hudu",
            hudu_record_filter="both",
        ),
        "Archived only": _coverage_filter_url(
            hudu="in_hudu",
            hudu_record_filter="archived_only",
        ),
        "No record": _coverage_filter_url(hudu="not_in_hudu"),
        "Total": _coverage_filter_url(hudu="in_hudu"),
    }

    # One Hudu card: record counts from the Hudu evidence reader plus the
    # requirement counts from the stored verdicts (ADR-0035).
    hudu_card = {
        "platform": "Hudu",
        "counts": [
            {"name": name, "count": count, "url": hudu_urls[name]}
            for name, count in hudu_counts.items()
        ]
        + [
            {
                "name": "Total",
                "count": sum(row["hudu_present"] for row in inventory_rows),
                "url": hudu_urls["Total"],
            }
        ],
        "requirement_total": 0,
        "requirement_total_url": "",
        "requirement_exceptions": [],
    }
    for card in platform_cards:
        if card["platform"] == "Hudu":
            for key in ("requirement_total", "requirement_total_url", "requirement_exceptions"):
                hudu_card[key] = card[key]
    platform_cards = [card for card in platform_cards if card["platform"] != "Hudu"]
    platform_cards.append(hudu_card)
    platform_cards.sort(key=_computer_card_order)

    filtered_summary = {
        "clients": len({row["client_slug"] for row in device_rows}),
        "devices": len(device_rows),
        "in_hudu": sum(row["hudu_present"] for row in device_rows),
        "not_in_hudu": sum(not row["hudu_present"] for row in device_rows),
    }

    filter_logic_parts = []
    filter_summary_parts = []
    if client_filters:
        selected_client_names = [
            client["name"] for client in filter_clients if client["slug"] in client_filters
        ]
        filter_logic_parts.append(
            "(" + " OR ".join(f"Client is {name}" for name in selected_client_names) + ")"
        )
        filter_summary_parts.append("Client: " + " or ".join(selected_client_names))
    if device_query:
        filter_logic_parts.append(f"(Computer name contains “{device_query}”)")
        filter_summary_parts.append(f"Name contains “{device_query}”")
    if agents_query:
        filter_logic_parts.append(f"(Sources contains “{agents_query}”)")
        filter_summary_parts.append(f"Sources contains “{agents_query}”")
    scope_labels = _COMPUTER_SCOPE_LABELS
    if computer_scope_filters:
        filter_logic_parts.append(
            "(" + " OR ".join(scope_labels[value] for value in computer_scope_filters) + ")"
        )
        filter_summary_parts.append(
            " or ".join(scope_labels[value] for value in computer_scope_filters)
        )

    def condition_logic(condition: dict) -> str:
        parts = []
        if condition["states"]:
            states = " OR ".join(
                f"{condition['agent']} state is {state}" for state in condition["states"]
            )
            parts.append(f"({states})" if len(condition["states"]) > 1 else states)
        if condition["requirements"]:
            requirements = " OR ".join(
                f"{condition['agent']} requirement is {requirement}"
                for requirement in condition["requirements"]
            )
            parts.append(
                f"({requirements})" if len(condition["requirements"]) > 1 else requirements
            )
        return "(" + " AND ".join(parts) + ")"

    for condition in all_agent_conditions:
        filter_logic_parts.append(condition_logic(condition))
        selected = [*condition["states"]]
        selected.extend(
            {
                "Missing": "Required · Missing",
                "Stale": "Required · Stale",
            }.get(requirement, requirement)
            for requirement in condition["requirements"]
        )
        filter_summary_parts.append(f"{condition['agent']} — {', '.join(selected)}")
    if hudu_filters:
        labels = {"in_hudu": "In Hudu", "not_in_hudu": "Not in Hudu"}
        filter_logic_parts.append(
            "(" + " OR ".join(f"Hudu is {labels[value]}" for value in hudu_filters) + ")"
        )
        filter_summary_parts.append("Hudu: " + " or ".join(labels[value] for value in hudu_filters))
    if hudu_record_filter_active and hudu_record_filter != "any":
        hudu_record_labels = {
            "has_current": "has a current record",
            "has_archived": "has an archived record",
            "current_only": "current records only",
            "archived_only": "archived records only",
            "both": "has current and archived records",
        }
        filter_logic_parts.append(f"(Hudu {hudu_record_labels[hudu_record_filter]})")
        filter_summary_parts.append("Hudu: " + hudu_record_labels[hudu_record_filter])
    if hudu_link_filters:
        labels = {"has_links": "Has links", "no_links": "No links"}
        filter_logic_parts.append(
            "(" + " OR ".join(f"Hudu links: {labels[value]}" for value in hudu_link_filters) + ")"
        )
        filter_summary_parts.append(
            "Hudu links: " + " or ".join(labels[value] for value in hudu_link_filters)
        )
    if s1_exemption_filters:
        labels = {"exempt": "Exempt", "not_exempt": "Not exempt"}
        filter_logic_parts.append(
            "("
            + " OR ".join(f"SentinelOne is {labels[value]}" for value in s1_exemption_filters)
            + ")"
        )
        filter_summary_parts.append(
            "SentinelOne: " + " or ".join(labels[value] for value in s1_exemption_filters)
        )
    if os_family_filters:
        filter_logic_parts.append(
            "(" + " OR ".join(f"OS is {family}" for family in os_family_filters) + ")"
        )
        filter_summary_parts.append("OS: " + " or ".join(os_family_filters))
    if device_type_filters:
        filter_logic_parts.append(
            "(" + " OR ".join(f"Type is {device_type}" for device_type in device_type_filters) + ")"
        )
        filter_summary_parts.append("Type: " + " or ".join(device_type_filters))
    if device_role_filters:
        filter_logic_parts.append(
            "(" + " OR ".join(f"Role is {role}" for role in device_role_filters) + ")"
        )
        filter_summary_parts.append("Role: " + " or ".join(device_role_filters))
    if not filter_logic_parts:
        filter_logic_parts.append("No filters selected — showing every known Computer")
    filter_logic = " AND ".join(filter_logic_parts)
    filter_summary = "; ".join(filter_summary_parts) if filter_summary_parts else "None"
    filters_active = bool(
        client_filters
        or device_query
        or agents_query
        or computer_scope_filters
        or agent_filter_conditions
        or record_status_filters
        or rule_status_filters
        or any_platform_selected
        or no_platform_selected
        or any_platform_filters
        or coverage_source_filters
        or hudu_filters
        or hudu_link_filters
        or hudu_record_filter != "any"
        or s1_exemption_filters
        or platform_filters
        or state_filters
        or platform_status_filters
        or os_family_filters
        or device_type_filters
        or device_role_filters
    )

    def populate_hudu_presentation(target_rows: list[dict]) -> None:
        """Load display-only Hudu detail after the fleet-level filter pass."""
        observation_ids = [
            observation_id
            for row in target_rows
            for observation_id in row["hudu_observation_ids"]
        ]
        if not observation_ids:
            return
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                """
                SELECT hudu.observation_id, hudu.device_id, hudu.source_layout,
                       hudu.source_url, hudu.card_source, hudu.card_id,
                       hudu.card_resolved_device_id, alias.canonical
                FROM operations.v_hudu_computer_inventory_evidence_current hudu
                LEFT JOIN operations.platform_aliases alias
                  ON alias.alias = LOWER(hudu.card_source)
                WHERE hudu.observation_id = ANY(%s::uuid[])
                """,
                [observation_ids],
            )
            detail_rows = cur.fetchall()
        details: dict = {}
        for (
            observation_id,
            device_id,
            layout,
            hudu_url,
            card_source,
            card_id,
            resolved_device_id,
            canonical,
        ) in detail_rows:
            detail = details.setdefault(
                observation_id,
                {
                    "layout": layout or "Asset",
                    "url": _safe_external_http_url(hudu_url),
                    "links": [],
                    "device_id": device_id if device_id in devices_by_id else None,
                    "device_client_slug": (
                        devices_by_id[device_id]["client_slug"]
                        if device_id in devices_by_id
                        else ""
                    ),
                },
            )
            if card_source is None or card_id is None:
                continue
            linked_hostname = hostnames_by_device.get(device_id)
            if (
                card_source.lower() == "ninja"
                and resolved_device_id == str(device_id)
                and linked_hostname
            ):
                label = f"Ninja — {linked_hostname}"
            else:
                label = f"{canonical or card_source.title()} #{card_id}"
            if label not in detail["links"]:
                detail["links"].append(label)
        for row in target_rows:
            records = []
            links = []
            for observation_id in row["hudu_observation_ids"]:
                detail = details.get(observation_id)
                if detail is None:
                    continue
                records.append(
                    {
                        **detail,
                        "is_archived": hudu_by_observation[observation_id]["is_archived"],
                    }
                )
                for link in detail["links"]:
                    if link not in links:
                        links.append(link)
            row["hudu_records"] = records
            row["hudu_links"] = links

    if wants_csv(request):
        for row in device_rows:
            row["platform_cells_by_name"] = {
                platform: inventory_platform_cell(row, platform, presentation=True)
                for platform in platforms
            }
        populate_hudu_presentation(device_rows)

        def inventory_agent_value(row: dict, platform: str) -> str:
            cell = row["platform_cells_by_name"][platform]
            record = cell["record_status"]
            if cell["record_age"]:
                record = f"{record} ({cell['record_age']})"
            if cell["possible_match"]:
                record += f"; possible match: {cell['possible_match']['hostname']}"
            return f"{platform}: {record}; {cell['rule_label']}"

        return csv_response(
            [
                {
                    "client_name": row["client_name"],
                    "hostname": row["hostname"],
                    "os_family": row["os_family"] or "Unknown",
                    "device_type": row["device_type"],
                    "device_role": row["device_role"],
                    "lifecycle_status": row["lifecycle_status"],
                    "hudu": row["hudu_status"],
                    "hudu_links": ", ".join(row["hudu_links"]),
                    "inventory_row": row,
                }
                for row in device_rows
            ],
            columns=[
                ("Client", "client_name"),
                ("Device", "hostname"),
                ("OS family", "os_family"),
                ("Device type", "device_type"),
                ("Role", "device_role"),
                ("Lifecycle", "lifecycle_status"),
                ("Hudu", "hudu"),
                ("Hudu links", "hudu_links"),
                (
                    "Sources",
                    lambda export_row: " | ".join(
                        inventory_agent_value(export_row["inventory_row"], platform)
                        for platform in platforms
                    ),
                ),
            ],
            filename_stem="inventory_computers",
        )

    paginator = Paginator(device_rows, 100)
    page_obj = paginator.get_page(request.GET.get("page"))
    page_query = request.GET.copy()
    page_query.pop("page", None)
    page_query = page_query.urlencode()
    device_rows = list(page_obj.object_list)

    populate_hudu_presentation(device_rows)

    # The first view already has complete current/withdrawn state for every
    # Computer. Load the withdrawal timestamps only for rows being rendered;
    # CSV retains the complete-detail query above.
    page_device_ids = [row["device_id"] for row in device_rows if row["device_id"]]
    if compact_source_observations and page_device_ids:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                """
                SELECT evidence.device_id, evidence.source_name,
                       BOOL_OR(evidence.observation_active) AS has_current_record,
                       MAX(evidence.observation_last_seen_at)
                           FILTER (WHERE evidence.observation_active) AS current_seen_at,
                       MAX(COALESCE(link.missing_since, evidence.observation_last_seen_at))
                           FILTER (WHERE NOT evidence.observation_active) AS withdrawn_at
                  FROM operations.v_device_observation_current evidence
                  JOIN operations.source_instances source_instance
                    ON source_instance.tenant_id = evidence.tenant_id
                   AND source_instance.id = evidence.source_instance_id
                  LEFT JOIN operations.v_device_source_link link
                    ON link.tenant_id = evidence.tenant_id
                   AND link.device_id = evidence.device_id
                   AND link.source_id = source_instance.source_id
                   AND link.external_id = evidence.external_id
                 WHERE evidence.tenant_id = 1
                   AND evidence.device_id = ANY(%s::uuid[])
                   AND (evidence.entity_type LIKE 'agent.%%'
                        OR evidence.entity_type = 'vm.guest')
                 GROUP BY evidence.device_id, evidence.source_name
                """,
                [page_device_ids],
            )
            for device_id, platform, has_current, current_seen_at, withdrawn_at in cur.fetchall():
                source_observations_by_device.setdefault(device_id, {})[platform] = {
                    "state": "Current" if has_current else "Withdrawn",
                    "current_seen_at": current_seen_at,
                    "withdrawn_at": withdrawn_at,
                }

    for row in device_rows:
        row["source_observations"] = source_observations_by_device.get(row["device_id"], {})
        row["platform_cells_by_name"] = {
            platform: inventory_platform_cell(row, platform, presentation=True)
            for platform in platforms
        }
        row["agent_cells"] = [row["platform_cells_by_name"][platform] for platform in platforms]

    return render(
        request,
        "coverage.html",
        {
            "active_section": "inventory",
            "device_rows": device_rows,
            "page_obj": page_obj,
            "paginator": paginator,
            "page_query": page_query,
            "platform_cards": platform_cards,
            "hudu_card": hudu_card,
            "computer_scope_labels": _COMPUTER_SCOPE_LABELS,
            "filtered_summary": filtered_summary,
            "filter_logic": filter_logic,
            "filter_summary": filter_summary,
            "filters_active": filters_active,
            "platforms": platforms,
            "agent_filter_forms": agent_filter_forms,
            "agent_filter_agents": platforms,
            "agent_filter_states": (*record_status_order, "Possible match"),
            "agent_filter_requirements": (
                "Required",
                "Missing",
                "Stale",
                *_NOT_APPLIED_STATES,
                "N/A",
                "Exempt",
            ),
            "requirements_evaluated_at": requirements_evaluated_at,
            "coverage_filter_sources": coverage_filter_sources,
            "os_families": os_families,
            "device_types": device_types,
            "device_roles": device_roles,
            "filter_clients": filter_clients,
            "states": _COVERAGE_STATES,
            "client_filters": client_filters,
            "device_query": device_query,
            "agents_query": agents_query,
            "platform_filters": platform_filters,
            "online_filters": online_filters,
            "coverage_source_filters": coverage_source_filters,
            "coverage_status_filters": coverage_status_filters,
            "any_platform_filters": any_platform_filters,
            "any_platform_selected": any_platform_selected,
            "no_platform_selected": no_platform_selected,
            "computer_scope_filters": computer_scope_filters,
            "agent_filter_conditions": agent_filter_conditions,
            "hudu_filters": hudu_filters,
            "hudu_link_filters": hudu_link_filters,
            "hudu_record_filter": hudu_record_filter,
            "hudu_record_filter_active": hudu_record_filter_active,
            "s1_exemption_filters": s1_exemption_filters,
            "os_family_filters": os_family_filters,
            "device_type_filters": device_type_filters,
            "device_role_filters": device_role_filters,
            "state_filters": state_filters,
            "platform_status_filters": platform_status_filters,
            "record_status_filters": record_status_filters,
            "rule_status_filters": rule_status_filters,
        },
    )


# ── Source ingest status page ─────────────────────────────────────────────────


@login_required
def sources_status(request: HttpRequest) -> HttpResponse:
    """Registry-driven source-instance health and row-based entity counts."""
    tenant_id = int(getattr(request, "tenant_id", 1))
    source_filter = (request.GET.get("source") or "").strip()
    with transaction.atomic():  # noqa: SIM117 -- matches existing transaction/GUC pattern
        with connection.cursor() as cur:
            cur.execute(
                "SELECT set_config('operations.tenant_id', %s, TRUE)", (str(tenant_id),)
            )
            cur.execute(
                """
                SELECT health.id, health.source_name, health.client_display_name, health.enabled, health.run_platform,
                       last_observed_at, current_record_count, active_record_count,
                       last_run_ok, last_run_ended_at, last_run_rows,
                       last_run_error, last_success_at, last_success_rows,
                       binding.id, binding.schedule, source.kind, source.entity_type, source.capabilities,
                       entity_type.entity_class_id
                  FROM operations.v_source_instance_health health
                  JOIN operations.source_bindings binding
                    ON binding.source_instance_id = health.id
                   AND binding.tenant_id = health.tenant_id AND binding.enabled
                  JOIN operations.source_instances instance ON instance.id = health.id
                  JOIN operations.sources source ON source.id = instance.source_id
                  LEFT JOIN operations.entity_types entity_type ON entity_type.name = source.entity_type
                 WHERE health.tenant_id = %s
                 ORDER BY health.source_name, health.client_display_name NULLS FIRST, health.id
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
                        "entity_type_label": _source_record_type_label(row[1]),
                        "entity_class": row[2],
                        "current_count": row[3],
                        "active_count": row[4],
                        "withdrawn_count": row[5],
                        "last_seen_at": row[6],
                    }
                )

            # The durable Jobs record is the only current source lifecycle.
            cur.execute(
                """
                SELECT substring(scope_identity FROM 16)::uuid, id, status,
                       requested_at, started_at
                  FROM operations.operator_job_runs
                 WHERE tenant_id = %s AND job_key = 'source-refresh'
                   AND status IN ('queued', 'running')
                """,
                (tenant_id,),
            )
            active = {r[0]: r[1:] for r in cur.fetchall()}

            cur.execute(
                """
                SELECT DISTINCT ON (substring(scope_identity FROM 16)::uuid)
                       substring(scope_identity FROM 16)::uuid, status,
                       completed_at, started_at, requested_at, rows_touched, error
                  FROM operations.operator_job_runs
                 WHERE tenant_id = %s AND job_key = 'source-refresh'
                 ORDER BY substring(scope_identity FROM 16)::uuid,
                          requested_at DESC, id DESC
                """,
                (tenant_id,),
            )
            latest_refresh = {row[0]: row[1:] for row in cur.fetchall()}

            # Reference feeds were previously run under individual Job keys.
            # Keep their verified terminal results visible until the first
            # source-managed refresh completes; this is transition history,
            # not a second live lifecycle.
            cur.execute(
                """
                SELECT binding.id,
                       latest.status, latest.completed_at, latest.started_at,
                       latest.requested_at, latest.rows_touched, latest.error,
                       success.status, success.completed_at, success.started_at,
                       success.requested_at, success.rows_touched, success.error
                  FROM operations.source_bindings binding
                  JOIN operations.source_instances instance
                    ON instance.id = binding.source_instance_id
                  LEFT JOIN LATERAL (
                    SELECT run.status, run.completed_at, run.started_at,
                           run.requested_at, run.rows_touched, run.error
                      FROM operations.operator_job_runs run
                     WHERE run.tenant_id = binding.tenant_id
                       AND run.job_key = instance.config->>'legacy_job_key'
                       AND run.status IN ('completed', 'failed', 'stalled', 'cancelled')
                     ORDER BY COALESCE(run.completed_at, run.started_at, run.requested_at) DESC,
                              run.id DESC
                     LIMIT 1
                  ) latest ON TRUE
                  LEFT JOIN LATERAL (
                    SELECT run.status, run.completed_at, run.started_at,
                           run.requested_at, run.rows_touched, run.error
                      FROM operations.operator_job_runs run
                     WHERE run.tenant_id = binding.tenant_id
                       AND run.job_key = instance.config->>'legacy_job_key'
                       AND run.status = 'completed'
                     ORDER BY COALESCE(run.completed_at, run.started_at, run.requested_at) DESC,
                              run.id DESC
                     LIMIT 1
                  ) success ON TRUE
                 WHERE binding.tenant_id = %s
                   AND COALESCE(instance.config->>'legacy_job_key', '') <> ''
                """,
                (tenant_id,),
            )
            legacy_refresh: dict = {}
            legacy_success: dict = {}
            for row in cur.fetchall():
                binding_id, *values = row
                latest, success = values[:6], values[6:]
                if latest[0] is not None:
                    legacy_refresh[binding_id] = tuple(latest)
                if success[0] is not None:
                    legacy_success[binding_id] = tuple(success)

            # Source-refresh runs are the authoritative operational history.
            # The former reference-feed runs remain visible only while a
            # source has not yet completed under its source-managed schedule.
            cur.execute(
                """
                SELECT source, status, started_at, completed_at, rows_touched, error, history_kind
                  FROM (
                    SELECT source.name AS source, run.status, run.started_at, run.completed_at,
                           run.rows_touched, run.error, 'current' AS history_kind,
                           run.requested_at
                      FROM operations.operator_job_runs run
                      JOIN operations.source_bindings binding
                        ON binding.id = substring(run.scope_identity FROM 16)::uuid
                       AND binding.tenant_id = run.tenant_id
                      JOIN operations.source_instances instance ON instance.id = binding.source_instance_id
                      JOIN operations.sources source ON source.id = instance.source_id
                     WHERE run.tenant_id = %s AND run.job_key = 'source-refresh'
                    UNION ALL
                    SELECT source.name AS source, run.status, run.started_at, run.completed_at,
                           run.rows_touched, run.error, 'previous' AS history_kind,
                           run.requested_at
                      FROM operations.operator_job_runs run
                      JOIN operations.source_bindings binding
                        ON binding.tenant_id = run.tenant_id
                      JOIN operations.source_instances instance
                        ON instance.id = binding.source_instance_id
                       AND run.job_key = instance.config->>'legacy_job_key'
                      JOIN operations.sources source ON source.id = instance.source_id
                     WHERE run.tenant_id = %s
                       AND COALESCE(instance.config->>'legacy_job_key', '') <> ''
                       AND NOT EXISTS (
                           SELECT 1
                             FROM operations.operator_job_runs current_run
                            WHERE current_run.tenant_id = binding.tenant_id
                              AND current_run.job_key = 'source-refresh'
                              AND current_run.scope_identity = 'source-binding:' || binding.id::text
                              AND current_run.status = 'completed'
                       )
                  ) AS source_history
                 ORDER BY COALESCE(completed_at, started_at, requested_at) DESC NULLS LAST
                 LIMIT 30
            """,
                (tenant_id, tenant_id),
            )
            recent_runs = [
                {
                    "source": r[0],
                    "status": {"completed": "done", "running": "processing"}.get(r[1], r[1]),
                    "started_at": r[2],
                    "completed_at": r[3],
                    "rows_seen": r[4],
                    "error": r[5] or None,
                    "history_kind": r[6],
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
            last_success_rows, binding_id, schedule, source_kind, entity_type, source_capabilities,
            entity_class,
        ) = row
        act = active.get(binding_id)
        latest = latest_refresh.get(binding_id)
        previous_result = False
        if latest and latest[0] in {"completed", "failed", "stalled", "cancelled"}:
            terminal_at = latest[1] or latest[2] or latest[3]
            last_success = terminal_at if latest[0] == "completed" else last_success
            last_success_rows = latest[4] if latest[0] == "completed" else last_success_rows
            last_fail = terminal_at if latest[0] in {"failed", "stalled"} else None
            last_error = latest[5] if latest[0] in {"failed", "stalled"} else None
        else:
            last_fail = last_run_ended_at if last_run_ok is False else None
            last_error = (last_run_error or None) if last_run_ok is False else None
        if not (latest and latest[0] in {"completed", "failed", "stalled", "cancelled"}):
            legacy_latest = legacy_refresh.get(binding_id)
            legacy_last_success = legacy_success.get(binding_id)
            if legacy_last_success:
                last_success = legacy_last_success[1] or legacy_last_success[2] or legacy_last_success[3]
                last_success_rows = legacy_last_success[4]
                previous_result = True
            if legacy_latest and legacy_latest[0] in {"failed", "stalled"}:
                last_fail = legacy_latest[1] or legacy_latest[2] or legacy_latest[3]
                last_error = legacy_latest[5] or None
        schedule_minutes = _source_schedule_minutes(schedule or "")
        is_stale = _source_is_stale(last_success, schedule_minutes, now)
        sources.append(
            {
                "id": source_instance_id,
                "name": source_name,
                "client_name": client_display_name,
                "enabled": enabled,
                "run_platform": run_platform,
                "binding_id": binding_id,
                "schedule": schedule or "",
                "schedule_minutes": schedule_minutes,
                "source_kind": source_kind,
                "entity_type": entity_type,
                "entity_class": entity_class or "",
                "purpose": (
                    source_capabilities.get("purpose", "")
                    if isinstance(source_capabilities, dict)
                    else ""
                ),
                "is_processing": bool(act and act[1] == "running"),
                "has_pending": bool(act and act[1] == "queued"),
                "active_job_url": (
                    reverse("admin_job_status") + "?" + urlencode({"run": act[0]})
                    if act and act[0]
                    else ""
                ),
                "last_success": last_success,
                "last_result_is_previous": previous_result,
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

    source_options = sorted({source["name"] for source in sources})
    if source_filter:
        sources = [source for source in sources if source["name"] == source_filter]
    source_groups: dict[str, list[dict]] = {
        "Device and client systems": [],
        "Software data": [],
        "Security data": [],
        "Other sources": [],
    }
    for source in sources:
        group = {
            "software": "Software data",
            "security": "Security data",
        }.get(source["purpose"])
        if group is None:
            group = (
                "Device and client systems"
                if source["entity_class"] in {"device", "asset"}
                else "Other sources"
            )
        source_groups[group].append(source)
    source_groups = {key: value for key, value in source_groups.items() if value}
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
            "source_groups": source_groups,
            "source_options": source_options,
            "active_source": source_filter,
            "recent_runs": recent_runs,
            "stale_count": stale_count,
        },
    )


@login_required
def source_records(
    request: HttpRequest, source_instance_id: uuid.UUID | None = None
) -> HttpResponse:
    """List current observations across Inventory, optionally for one source.

    Observations are evidence, not Computers.  The reader deliberately makes
    Computer attachment, client attribution, and a parent source-record
    reference separate relationship facts.  Its distinct filter values come
    from the current observation store, so newly registered types are visible
    without changing this page.
    """
    tenant_id = int(getattr(request, "tenant_id", 1))
    state = (request.GET.get("state") or "all").strip().lower()
    if state not in {"all", "active", "withdrawn"}:
        state = "all"
    entity_type = (request.GET.get("type") or "").strip()
    query = (request.GET.get("q") or "").strip()
    relationship = (request.GET.get("relationship") or "all").strip()
    if relationship not in {
        "all",
        "attached_computer",
        "unlinked_computer",
        "client_attributed",
        "parent_record",
        "has_relationship",
        "no_relationship",
    }:
        relationship = "all"
    source_filter = source_instance_id
    if source_filter is None and request.GET.get("source"):
        try:
            source_filter = uuid.UUID(request.GET["source"])
        except (TypeError, ValueError):
            source_filter = None
    client_filter = (request.GET.get("client") or "").strip()
    try:
        client_filter_id = uuid.UUID(client_filter) if client_filter else None
    except (TypeError, ValueError):
        client_filter_id = None
    try:
        page_number = max(1, int(request.GET.get("page", "1")))
    except ValueError:
        page_number = 1
    page_size = 100

    clauses = ["observation.tenant_id = %s"]
    params: list[object] = [tenant_id]
    if source_filter is not None:
        clauses.append("observation.source_instance_id = %s")
        params.append(source_filter)
    if client_filter_id is not None:
        clauses.append("observation.client_id = %s")
        params.append(client_filter_id)
    if state == "active":
        clauses.append("observation.active")
    elif state == "withdrawn":
        clauses.append("NOT observation.active")
    if entity_type:
        clauses.append("observation.entity_type = %s")
        params.append(entity_type)
    if relationship == "attached_computer":
        clauses.append("observation.device_id IS NOT NULL")
    elif relationship == "unlinked_computer":
        clauses.append("observation.device_id IS NULL")
    elif relationship == "client_attributed":
        clauses.append("observation.client_id IS NOT NULL")
    elif relationship == "parent_record":
        clauses.append("NULLIF(observation.parent_external_id, '') IS NOT NULL")
    elif relationship == "has_relationship":
        clauses.append(
            "(observation.device_id IS NOT NULL OR observation.client_id IS NOT NULL "
            "OR NULLIF(observation.parent_external_id, '') IS NOT NULL)"
        )
    elif relationship == "no_relationship":
        clauses.append(
            "observation.device_id IS NULL AND observation.client_id IS NULL "
            "AND NULLIF(observation.parent_external_id, '') IS NULL"
        )
    if query:
        clauses.append(
            "(observation.external_id ILIKE %s OR observation.parent_external_id ILIKE %s "
            "OR COALESCE(observation.canonical_hostname, '') ILIKE %s "
            "OR COALESCE(observation.reported_name, '') ILIKE %s)"
        )
        params.extend([f"%{query}%"] * 4)
    where_sql = " AND ".join(clauses)

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SELECT set_config('operations.tenant_id', %s, TRUE)", (str(tenant_id),))
        cur.execute(
            """
            SELECT instance.id, source.name, client.display_name
              FROM operations.source_instances instance
              JOIN operations.sources source ON source.id = instance.source_id
              LEFT JOIN operations.clients client
                ON client.id = instance.client_id AND client.tenant_id = instance.tenant_id
             WHERE instance.tenant_id = %s
             ORDER BY source.name, client.display_name NULLS FIRST, instance.id
            """,
            (tenant_id,),
        )
        source_rows = cur.fetchall()
        source_choices = [
            {
                "id": row[0],
                "label": row[1] + (f" · {row[2]}" if row[2] else ""),
            }
            for row in source_rows
        ]
        source_row = next((row for row in source_rows if row[0] == source_filter), None)
        if source_filter is not None and source_row is None:
            raise Http404("Source instance not found")

        cur.execute(
            f"SELECT COUNT(*)::int FROM operations.v_entity_observation_admin_metadata observation WHERE {where_sql}",
            params,
        )
        total = cur.fetchone()[0]
        cur.execute(
            """
            SELECT DISTINCT entity_type
              FROM operations.v_entity_observation_admin_metadata
             WHERE tenant_id = %s
             ORDER BY entity_type
            """,
            (tenant_id,),
        )
        entity_types = [
            {"value": row[0], "label": _source_record_type_label(row[0])}
            for row in cur.fetchall()
        ]
        cur.execute(
            """
            SELECT id, slug, display_name
              FROM operations.clients
             WHERE tenant_id = %s AND deleted_at IS NULL
             ORDER BY display_name
            """,
            (tenant_id,),
        )
        client_choices = [
            {"id": str(row[0]), "slug": row[1], "name": row[2]} for row in cur.fetchall()
        ]

        records_sql = f"""
            SELECT observation.observation_id, source.name, observation.entity_type,
                   observation.external_id, observation.parent_external_id,
                   observation.active, observation.observed_at,
                   observation.last_seen_at, observation.withdrawn_at,
                   observation.device_id, device.canonical_hostname,
                   client.slug, client.display_name,
                   CASE WHEN observation.device_id IS NOT NULL THEN TRUE ELSE FALSE END,
                   CASE WHEN observation.client_id IS NOT NULL THEN TRUE ELSE FALSE END,
                   CASE WHEN NULLIF(observation.parent_external_id, '') IS NOT NULL THEN TRUE ELSE FALSE END
              FROM operations.v_entity_observation_admin_metadata observation
              JOIN operations.source_instances instance
                ON instance.tenant_id = observation.tenant_id AND instance.id = observation.source_instance_id
              JOIN operations.sources source ON source.id = instance.source_id
              LEFT JOIN operations.devices device
                ON device.tenant_id = observation.tenant_id AND device.id = observation.device_id
              LEFT JOIN operations.clients client
                ON client.tenant_id = observation.tenant_id AND client.id = observation.client_id
             WHERE {where_sql}
             ORDER BY observation.last_seen_at DESC NULLS LAST, observation.observation_id
        """
        if wants_csv(request):
            cur.execute(records_sql, params)
        else:
            cur.execute(
                records_sql + " LIMIT %s OFFSET %s",
                [*params, page_size, (page_number - 1) * page_size],
            )
        records = [
            {
                "observation_id": row[0],
                "source_name": row[1],
                "entity_type": row[2],
                "entity_type_label": _source_record_type_label(row[2]),
                "external_id": row[3],
                "parent_external_id": row[4],
                "active": row[5],
                "observed_at": row[6],
                "last_seen_at": row[7],
                "withdrawn_at": row[8],
                "device_id": row[9],
                "hostname": row[10],
                "client_slug": row[11],
                "client_name": row[12],
                "has_computer": row[13],
                "has_client": row[14],
                "has_parent": row[15],
            }
            for row in cur.fetchall()
        ]

    if wants_csv(request):
        return csv_response(
            records,
            columns=[
                ("Observation ID", "observation_id"),
                ("Source", "source_name"),
                ("Entity type", "entity_type"),
                ("External ID", "external_id"),
                ("Parent external ID", "parent_external_id"),
                ("State", lambda row: "active" if row["active"] else "withdrawn"),
                ("Observed", "observed_at"),
                ("Last seen", "last_seen_at"),
                ("Withdrawn", "withdrawn_at"),
                ("Linked Computer", "hostname"),
                ("Client", "client_name"),
            ],
            filename_stem="inventory_source_records",
        )

    page_count = max(1, -(-total // page_size))
    return render(
        request,
        "source_records.html",
        {
            "source_instance_id": source_filter,
            "source_name": source_row[1] if source_row else "",
            "source_client_name": source_row[2] if source_row else "",
            "source_choices": source_choices,
            "client_choices": client_choices,
            "records": records,
            "total": total,
            "state": state,
            "entity_type": entity_type,
            "entity_types": entity_types,
            "query": query,
            "relationship": relationship,
            "client_filter": str(client_filter_id) if client_filter_id else "",
            "page_number": page_number,
            "page_count": page_count,
            "page_size": page_size,
            "has_previous": page_number > 1,
            "has_next": page_number < page_count,
            "previous_page": page_number - 1,
            "next_page": page_number + 1,
            "page_query": urlencode(
                {
                    key: value
                    for key, value in {
                        "source": str(source_filter) if source_filter else "",
                        "client": client_filter,
                        "state": state if state != "all" else "",
                        "type": entity_type,
                        "relationship": relationship if relationship != "all" else "",
                        "q": query,
                    }.items()
                    if value
                }
            ),
        },
    )


def _source_schedule_minutes(value: str) -> int | None:
    prefix, separator, minutes_text = value.strip().partition(":")
    if prefix != "interval" or not separator:
        return None
    try:
        minutes = int(minutes_text)
    except ValueError:
        return None
    return minutes if 1 <= minutes <= 10080 else None


def _source_is_stale(last_success: datetime | None, schedule_minutes: int | None, now: datetime) -> bool:
    """Mark a source stale only after twice its expected cadence (minimum eight hours)."""
    if last_success is None:
        return True
    expected_minutes = max(8 * 60, (schedule_minutes or 8 * 60) * 2)
    return now - last_success > timedelta(minutes=expected_minutes)


@login_required
@require_admin
@require_POST
def source_refresh_run(request: HttpRequest, binding_id: uuid.UUID) -> HttpResponse:
    """Request one configured source refresh through the normal Jobs API."""
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """SELECT source.name FROM operations.source_bindings binding
                 JOIN operations.source_instances instance ON instance.id = binding.source_instance_id
                 JOIN operations.sources source ON source.id = instance.source_id
                WHERE binding.tenant_id = 1 AND binding.id = %s AND binding.enabled""",
            (binding_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise Http404("Configured source is unavailable")
    run_id, created = _enqueue_operator_job(
        "source-refresh", request.user.id, scope_identity=f"source-binding:{binding_id}"
    )
    if created:
        messages.success(request, f"{row[0]} refresh was requested.")
    else:
        messages.info(request, f"{row[0]} already has an active refresh.")
    # A source refresh is a Job Run, but source configuration lives on Sources.
    # Keep the operator on the surface where the action was initiated.
    return redirect("admin_jobs" if request.POST.get("return_to") == "jobs" else "sources_status")


@login_required
@require_admin
@require_POST
def source_schedule_update(request: HttpRequest, binding_id: uuid.UUID) -> HttpResponse:
    """Update a source-owned cadence without exposing Jobs internals."""
    schedule = (request.POST.get("schedule") or "").strip()
    minutes = _source_schedule_minutes(schedule)
    if minutes is None:
        messages.error(request, "Use a refresh interval from 1 minute to 7 days.")
        return redirect("sources_status")
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """UPDATE operations.source_bindings SET schedule = %s
                 WHERE tenant_id = 1 AND id = %s AND enabled
                 RETURNING id""",
            (f"interval:{minutes}", binding_id),
        )
        if cur.fetchone() is None:
            raise Http404("Configured source is unavailable")
    messages.success(request, "Source refresh schedule updated.")
    return redirect("sources_status")


# ── Client candidates (Track C.4 evidence panel) ─────────────────────────────


@login_required
def client_candidates_queue(request: HttpRequest) -> HttpResponse:
    """Compatibility route for the retired parallel client-match queue."""
    return redirect(f"{reverse('findings_queue')}?type=client_mapping")


def _client_candidates_legacy_queue(request: HttpRequest) -> HttpResponse:
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

    live_groups, records_by_group = _candidate_live_groups(candidate)
    device_overlap, linked_total = _candidate_client_overlap(live_groups, records_by_group)
    name_matches, named_total = _candidate_name_matches(live_groups)
    # A client a source already keeps separate from this one is not suggested.
    separate = _client_source_ids(
        {item["client_id"] for item in device_overlap}
        | {item["client_id"] for item in name_matches}
    )
    likely_client = _first_unseparated(device_overlap, live_groups, separate)
    name_match = None if likely_client else _first_unseparated(name_matches, live_groups, separate)
    own_sources = {key[0] for key in live_groups}
    source_names_by_id = {source.id: source.name for source in Source.objects.all()}
    ruled_out = [
        {
            "display_name": item["display_name"],
            "sources": sorted(
                source_names_by_id.get(source_id, "?")
                for source_id in separate.get(item["client_id"], set()) & own_sources
            ),
        }
        for item in (device_overlap[:1] + name_matches[:1])
        if separate.get(item["client_id"], set()) & own_sources
    ]

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

    # Return to the page the operator opened this candidate from: an explicit
    # ``next`` first, else the referring page unless it is this candidate.
    detail_path = reverse("client_candidate_detail", kwargs={"candidate_id": candidate.id})
    return_to = _local_path(request.GET.get("next"))
    referer = urlsplit(request.META.get("HTTP_REFERER") or "")
    if not return_to and referer.netloc == request.get_host() and referer.path != detail_path:
        return_to = referer.path + (f"?{referer.query}" if referer.query else "")
    return render(
        request,
        "client_candidate_detail.html",
        {
            "admin_group": "review",
            "admin_tab": "clients",
            "return_to": return_to,
            "candidate": candidate,
            "per_source": per_source,
            "sample_devices": sample_devices,
            "device_overlap": device_overlap,
            "likely_client": likely_client,
            # Strongest evidence first: linked Computers, then unique computer names.
            "name_match": name_match,
            "ruled_out": {item["display_name"]: item for item in ruled_out}.values(),
            "name_matches": name_matches,
            "named_total": named_total,
            "suggested_client_id": (likely_client or name_match or {}).get("client_id", ""),
            "linked_total": linked_total,
            "fuzzy": fuzzy,
            "all_clients": all_clients,
            "profiles": profiles,
            "default_profile": default_profile,
        },
    )


# ── Candidate actions (Track C.4) — all audited ─────────────────────────────


def _audit(
    request, action: str, entity_id, before, after, *, entity_type: str = "client_candidate"
) -> None:
    AuditLog.objects.create(
        tenant_id=1,
        actor=request.user if request.user.is_authenticated else None,
        actor_kind=AuditLog.ActorKind.USER,
        source=AuditLog.Source.UI,
        action=action,
        entity_type=entity_type,
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
            FROM operations.finding_types ft,
                 operations.condition_assessments assessment,
                 operations.condition_policy_versions policy
            WHERE assessment.tenant_id = af.tenant_id
              AND assessment.row_kind = 'admin'
              AND assessment.finding_id = af.id
              AND (assessment.response->>'may_clear')::boolean IS TRUE
              AND policy.version = assessment.policy_version
              AND policy.active
              AND af.finding_type_id = ft.id
              AND ft.name = 'client_unattached_group'
              AND af.tenant_id = 1
              AND af.condition_key = %s
              AND af.status IN ('open', 'acknowledged')
              AND assessment.assessed_at >= NOW() -
                  (policy.policy->>'freshness_hours')::integer * INTERVAL '1 hour'
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
        FROM operations.finding_types ft,
             operations.condition_assessments assessment,
             operations.condition_policy_versions policy
        WHERE assessment.tenant_id = af.tenant_id
          AND assessment.row_kind = 'admin'
          AND assessment.finding_id = af.id
          AND (assessment.response->>'may_clear')::boolean IS TRUE
          AND policy.version = assessment.policy_version
          AND policy.active
          AND af.finding_type_id = ft.id
          AND ft.name = 'client_unattached_group'
          AND af.tenant_id = 1
          AND af.condition_key = %s
          AND af.status IN ('open', 'acknowledged')
          AND assessment.assessed_at >= NOW() -
              (policy.policy->>'freshness_hours')::integer * INTERVAL '1 hour'
        """,
        (condition_key,),
    )


def _candidate_detail_redirect(request: HttpRequest, candidate) -> HttpResponse:
    """Return to the candidate page, keeping where the operator came from."""
    url = reverse("client_candidate_detail", kwargs={"candidate_id": candidate.id})
    back = _local_path(request.POST.get("next"))
    return redirect(f"{url}?{urlencode({'next': back})}" if back else url)


def _local_path(value: str | None) -> str:
    """``value`` when it is a path on this site (the rule ``_safe_next`` uses)."""
    value = value or ""
    return value if value.startswith("/") and not value.startswith("//") else ""


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
        return _candidate_detail_redirect(request, candidate)
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

    # A client is anchored by a tenant-scoped entity that shares its id
    # (ADR-0012; migration 0120 made the anchor required).
    reason = f"candidate.accept:{candidate.id}"[:120]
    entity = Entity.objects.create(
        tenant_id=1,
        entity_class_id="client",
        scope_kind=Entity.ScopeKind.TENANT,
        created_reason=reason,
        updated_reason=reason,
    )
    client = Client.objects.create(
        id=entity.id,
        entity=entity,
        tenant_id=1,
        slug=slug,
        display_name=display_name,
        requirement_profile=profile,
        created_reason=reason,
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
    return redirect(_safe_next(request, "client_candidates_queue"))


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
        return _candidate_detail_redirect(request, candidate)
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
    return redirect(_safe_next(request, "client_candidates_queue"))


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
    return redirect(_safe_next(request, "client_candidates_queue"))


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
        return _candidate_detail_redirect(request, candidate)
    _audit(
        request,
        "client_candidate.fix_at_source",
        candidate.id,
        {"normalized_name": candidate.normalized_name, "status": "open"},
        {"status": "open", "note": note},
    )
    messages.success(request, "Note recorded — candidate remains open.")
    return _candidate_detail_redirect(request, candidate)


# ── Software findings review (Track 3.3) ────────────────────────────────


@login_required
def software_decisions_queue(request: HttpRequest) -> HttpResponse:
    """Software review: undecided software, grouped by publisher.

    Each undecided installed title is one finding (rare on few devices,
    non-approved above that). Publishers group them, largest decision leverage
    first; every title keeps its own row, signals and suggestion, with two
    remediation options: approve the title or approve the publisher.
    """
    query = (request.GET.get("q") or "").strip()
    kind = (request.GET.get("kind") or "").strip()
    suggestion = (request.GET.get("suggestion") or "").strip()
    publisher_status = (request.GET.get("publisher_status") or "").strip()
    if publisher_status not in {
        value for value, _label in software_review.PUBLISHER_STATUS_CHOICES
    }:
        publisher_status = ""
    try:
        page_number = int(request.GET.get("page") or 1)
    except ValueError:
        page_number = 1
    view_mode = "table" if request.GET.get("view") == "table" else "groups"
    sort_columns = (
        software_review.SORT_COLUMNS if view_mode == "table" else software_review.GROUP_COLUMNS
    )
    sort_key = request.GET.get("sort") or ""
    sort_dir = "asc" if request.GET.get("dir") == "asc" else "desc"
    if sort_key not in {name for name, _label, _numeric in sort_columns}:
        sort_key, sort_dir = ("devices" if view_mode == "table" else "titles"), "desc"
    title_sort = request.GET.get("tsort") or ""
    title_dir = "asc" if request.GET.get("tdir") == "asc" else "desc"
    if title_sort not in {
        name
        for name, _label, _numeric in software_review.SORT_COLUMNS
        if name not in {"publisher", "publisher_status"}
    }:
        title_sort = ""
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(software_review.PROMPTS_SQL, (1,))
        groups = software_review.build_groups(
            cur.fetchall(), query=query, kind=kind, suggestion=suggestion
        )
        # Before sorting and paging, so the Publisher status column sorts and
        # filters across every page and the export agrees.
        software_review.stamp_publisher_status(1, groups)
        if publisher_status:
            groups = software_review.filter_by_publisher_status(groups, publisher_status)
        if view_mode == "groups":
            groups = software_review.sort_groups(groups, sort_key, sort_dir)
        all_titles = software_review.sort_titles(
            [
                {**title, "group_suggestion": group["suggestion_label"]}
                for group in groups
                for title in group["titles"]
            ],
            sort_key,
            sort_dir,
        )
        if wants_csv(request):
            return csv_response(
                all_titles if view_mode == "table" else [
                    {**title, "group_suggestion": group["suggestion_label"]}
                    for group in groups
                    for title in group["titles"]
                ],
                columns=[
                    ("Title", "title"),
                    ("Publisher", "publisher"),
                    ("Publisher status", "publisher_status_label"),
                    ("Type", "type_label"),
                    ("Severity", "severity"),
                    ("Devices", "devices"),
                    ("Clients", "clients"),
                    ("Signals", "signals"),
                    ("Suggested", "suggestion_label"),
                    ("Publisher suggestion", "group_suggestion"),
                ],
                filename_stem="software_review",
            )
        if view_mode == "table":
            page_titles, page_number, pages = software_review.paginate(
                all_titles, page_number, per_page=100
            )
            page_groups = [{"titles": page_titles}]
            software_review.attach_publisher_status(cur, 1, page_groups)
        else:
            page_titles = []
            page_groups, page_number, pages = software_review.paginate(
                groups, page_number, per_page=25
            )
            if title_sort:
                # Sort each publisher's titles before the cap, so the titles
                # shown are the first ones in the chosen order.
                page_groups = [
                    {
                        **group,
                        "titles": software_review.sort_titles(
                            group["titles"], title_sort, title_dir
                        ),
                    }
                    for group in page_groups
                ]
            software_review.attach_publisher_status(cur, 1, page_groups)
            page_groups = software_review.trim_group_titles(page_groups)
        config = EvaluatorConfig.objects.filter(
            tenant_id=1, evaluator_name="software_classifier"
        ).first()
        rare_limit = int(
            software_settings.effective(config.config if config else {})["rare_max_devices"]
        )
        software_review.attach_device_targets(cur, 1, page_groups, rare_limit)

    base_query = request.GET.copy()
    base_query.pop("page", None)

    def _href(**changes: str | None) -> str:
        params = request.GET.copy()
        params.pop("page", None)
        for name, value in changes.items():
            if value is None:
                params.pop(name, None)
            else:
                params[name] = value
        return "?" + params.urlencode()

    columns = []
    for name, label, numeric in sort_columns:
        active = name == sort_key
        if active:
            next_dir = "asc" if sort_dir == "desc" else "desc"
        else:
            next_dir = "desc" if numeric else "asc"
        columns.append({
            "name": name,
            "label": label,
            "numeric": numeric,
            "href": _href(view=view_mode, sort=name, dir=next_dir),
            "mark": (" ▼" if sort_dir == "desc" else " ▲") if active else "",
        })
    title_columns = []
    for name, label, numeric in software_review.SORT_COLUMNS:
        if name in {"publisher", "publisher_status"}:
            continue
        if name == title_sort:
            next_dir = "asc" if title_dir == "desc" else "desc"
        else:
            next_dir = "desc" if numeric else "asc"
        title_columns.append({
            "label": label,
            "numeric": numeric,
            "href": _href(tsort=name, tdir=next_dir),
            "mark": (" ▼" if title_dir == "desc" else " ▲") if name == title_sort else "",
        })
    return render(
        request,
        "software_decisions.html",
        {
            "admin_group": "review",
            "admin_tab": "software",
            "software_tab": "decisions",
            "title_columns": title_columns,
            "view_mode": view_mode,
            "sort_key": sort_key,
            "sort_dir": sort_dir,
            "columns": columns,
            "titles": page_titles,
            "other_view_href": _href(
                view="groups" if view_mode == "table" else "table", sort=None, dir=None
            ),
            "groups": page_groups if view_mode == "groups" else [],
            "group_total": len(groups),
            "title_total": sum(len(group["titles"]) for group in groups),
            "page": page_number,
            "pages": pages,
            "page_query": base_query.urlencode(),
            "active_q": query,
            "active_kind": kind,
            "active_suggestion": suggestion,
            "active_publisher_status": publisher_status,
            "publisher_status_choices": software_review.PUBLISHER_STATUS_CHOICES,
            "suggestion_choices": SoftwareSuggestionRule.Suggestion.choices,
            "decision_choices": SoftwareDecision.Decision.choices,
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
            "scope_label": ("device" if d.device_id else "client" if d.client_id else "global"),
            "target_label": (
                d.canonical_name or (f"publisher: {d.publisher}" if d.publisher else "?")
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
    publishers = [p for p in request.POST.getlist("publisher") if p.strip()]
    if not canonical_names and not publishers:
        messages.error(request, "Select at least one product or publisher.")
        return redirect(_safe_next(request, "software_decisions_queue"))
    reason = (request.POST.get("reason") or "").strip()
    problem = software_decision_rules.comment_problem(
        decision, publisher_level=bool(publishers), comment=reason
    )
    if problem:
        messages.error(request, problem)
        return redirect(_safe_next(request, "software_decisions_queue"))

    created, updated = 0, 0
    for name in canonical_names:
        obj, was_created = SoftwareDecision.objects.update_or_create(
            tenant_id=1,
            canonical_name=name.strip(),
            publisher="",
            client=None,
            device=None,
            defaults={
                "decision": decision,
                "reason": reason,
                "decided_by": request.user,
                "decided_at": timezone.now(),
            },
        )
        _audit(
            request,
            "software_decision.bulk_set",
            obj.id,
            {},
            {"canonical_name": name.strip(), "scope": "global", "decision": decision},
        )
        created += int(was_created)
        updated += int(not was_created)
    for pub in publishers:
        obj, was_created = SoftwareDecision.objects.update_or_create(
            tenant_id=1,
            canonical_name="",
            publisher=pub.strip(),
            client=None,
            device=None,
            defaults={
                "decision": decision,
                "reason": reason,
                "decided_by": request.user,
                "decided_at": timezone.now(),
            },
        )
        _audit(
            request,
            "software_decision.bulk_set",
            obj.id,
            {},
            {"publisher": pub.strip(), "scope": "global", "decision": decision},
        )
        created += int(was_created)
        updated += int(not was_created)
    with connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        closed = software_review.resolve_decided_prompts(
            cur, tenant_id=1, canonical_names=canonical_names, publishers=publishers,
            decision=decision, actor=request.user.get_username(),
            decided_at=timezone.now().isoformat(),
        )
    messages.success(
        request,
        f"{decision}: {created} new, {updated} updated across "
        f"{len(canonical_names)} product(s) + {len(publishers)} publisher(s); "
        f"{closed} review finding(s) closed.",
    )
    # A materialized-view refresh can fail (for example while another refresh
    # owns the relation).  Do not run it inside this decision's atomic write:
    # PostgreSQL marks that transaction aborted even when the helper catches
    # the database exception.  The decision remains the authority; the view
    # refresh is only a post-commit convenience for the next page render.
    transaction.on_commit(_refresh_software_risk_matview)
    _queue_software_rebuild_after_commit(request.user.id)
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
        sorted(
            devices.values(), key=lambda row: (row["client_name"].lower(), row["hostname"].lower())
        ),
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
        messages.error(request, "Provide exactly one of canonical_name or publisher.")
        return redirect("software_decisions_queue")
    problem = software_decision_rules.comment_problem(
        decision, publisher_level=bool(publisher), comment=reason
    )
    if problem:
        messages.error(request, problem)
        return redirect(_safe_next(request, "software_decisions_queue"))

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
                      FROM operations.software_installations_current sic
                      JOIN operations.devices d
                        ON d.id = sic.device_id AND d.tenant_id = sic.tenant_id
                     WHERE sic.tenant_id = 1 AND sic.deleted_at IS NULL AND sic.stale_since IS NULL
                       AND d.deleted_at IS NULL AND {current_computer_sql("d")}
                       AND sic.{target_column} = %s
                       AND LOWER(sic.{match_column}) = LOWER(%s)
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
    if scope == "global":
        with connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            software_review.resolve_decided_prompts(
                cur, tenant_id=1,
                canonical_names=[canonical_name] if canonical_name else [],
                publishers=[publisher] if publisher else [],
                decision=decision, actor=request.user.get_username(),
                decided_at=timezone.now().isoformat(),
            )
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
    # See software_decision_bulk: a failed courtesy refresh must never turn a
    # durable operator decision into a 500 response.
    transaction.on_commit(_refresh_software_risk_matview)
    _queue_software_rebuild_after_commit(request.user.id)
    next_url = request.POST.get("next") or ""
    # Only follow relative URLs to avoid open-redirects.
    if next_url.startswith("/") and not next_url.startswith("//"):
        return redirect(next_url)
    return redirect("software_decisions_queue")


# ── Computer History (ADR-0033) ──────────────────────────────────────────


def _parse_history_before(value: str | None):
    """Keyset paging cursor: an ISO timestamp, or None for the newest page."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt_timezone.utc)

HISTORY_PAGE_SIZE = 100
HISTORY_ORIGINS = {
    "operator": "Operators",
    "process": "Platform",
    "migration": "Upgrades",
    "source": "Sources",
}
_HISTORY_TABLE_LABELS = {
    "devices": "Computer",
    "findings": "Issue",
    "device_operator_decisions": "Decision",
    "computer_merges": "Merge",
}


def _history_computer_ids(cur, device_id) -> list:
    """The Computer and every Computer merged into it (chains followed)."""
    cur.execute(
        """
        WITH RECURSIVE merged(id) AS (
            SELECT %s::uuid
            UNION
            SELECT m.absorbed_id FROM operations.computer_merges m
              JOIN merged ON m.survivor_id = merged.id
             WHERE m.split_at IS NULL
        )
        SELECT id FROM merged
        """,
        (device_id,),
    )
    return [row[0] for row in cur.fetchall()]


def _change_history_events(cur, computer_ids, before, users) -> list[dict]:
    """Recorded changes, one event per action (a merge moving 40 rows is one line)."""
    cur.execute(
        "SELECT * FROM operations.computer_history(%s::uuid[], %s, %s)",
        (computer_ids, before, HISTORY_PAGE_SIZE),
    )
    events: dict = {}
    for (
        recorded_at, table, entity_key, operation, changed, before_values, after_values,
        action_id, action, actor_kind, actor_id, process, reason,
    ) in cur.fetchall():
        event = events.get(action_id)
        if event is None:
            event = events[action_id] = {
                "kind": "change",
                "at": recorded_at,
                "label": action if action != "implicit" else "recorded change",
                "detail": reason,
                "origin": actor_kind,
                "actor": users.get(actor_id) or process or actor_kind,
                "changes": [],
            }
        event["at"] = max(event["at"], recorded_at)
        verb = {"I": "added", "U": "changed", "D": "removed"}[operation]
        fields = ", ".join(changed or [])
        values = ""
        old_values = _raw_json_object(before_values)
        new_values = _raw_json_object(after_values)
        if operation == "U" and changed and len(changed) <= 3:
            values = "; ".join(
                f"{col}: {old_values.get(col)} → {new_values.get(col)}" for col in changed
            )
        event["changes"].append(
            f"{_HISTORY_TABLE_LABELS.get(table, table.replace('_', ' '))} {verb}"
            + (f" ({fields})" if fields and operation == "U" else "")
            + (f" — {values}" if values else "")
        )
    return list(events.values())


def _audit_history_events(cur, computer_ids, before, users) -> list[dict]:
    """Rows from the earlier audit log (lifecycle transitions, operator actions).

    ADR-0033 replaces ``audit_log``; until its writers move to the change
    history, its rows for these Computers are part of the same timeline.
    """
    cur.execute(
        """
        SELECT occurred_at, action, actor_kind, actor_id, before_state, after_state
          FROM operations.audit_log
         WHERE tenant_id = 1 AND entity_type = 'device'
           AND entity_id = ANY(%s::uuid[])
           AND (%s::timestamptz IS NULL OR occurred_at < %s::timestamptz)
         ORDER BY occurred_at DESC
         LIMIT %s
        """,
        (computer_ids, before, before, HISTORY_PAGE_SIZE),
    )
    events = []
    for at, action, actor_kind, actor_id, before_state, after_state in cur.fetchall():
        before_state, after_state = before_state or {}, after_state or {}
        detail = ""
        if action == "lifecycle.transition":
            detail = (
                f"{before_state.get('lifecycle_status', '?')} → "
                f"{after_state.get('lifecycle_status', '?')}"
                + (f" ({after_state['evidence_kind']})" if after_state.get("evidence_kind") else "")
            )
        events.append(
            {
                "kind": "audit",
                "at": at,
                "label": action,
                "detail": detail or after_state.get("reason", ""),
                "origin": "operator" if actor_kind == "user" else "process",
                "actor": users.get(actor_id) or ("Operations" if actor_kind != "user" else ""),
                "changes": [],
            }
        )
    return events


def _record_history_events(cur, computer_ids, before) -> list[dict]:
    """Source records that stopped being listed, with when (ADR-0032 "Withdrawn records")."""
    cur.execute(
        """
        SELECT eo.withdrawn_at, eo.platform, eo.entity_type,
               coalesce(eo.reported_name, eo.external_id)
          FROM operations.v_entity_observation_admin_metadata eo
         WHERE eo.tenant_id = 1 AND eo.device_id = ANY(%s::uuid[])
           AND eo.withdrawn_at IS NOT NULL
           AND eo.entity_key NOT LIKE 'device-health:%%'
           AND (%s::timestamptz IS NULL OR eo.withdrawn_at < %s::timestamptz)
         ORDER BY eo.withdrawn_at DESC
         LIMIT %s
        """,
        (computer_ids, before, before, HISTORY_PAGE_SIZE),
    )
    return [
        {
            "kind": "record_withdrawn",
            "at": at,
            "label": f"{platform} record removed",
            "detail": f"{entity_type.replace('.', ' ')} {name}",
            "origin": "source",
            "actor": platform,
            "changes": [],
        }
        for at, platform, entity_type, name in cur.fetchall()
    ]


# ── Per-source record status (device detail and merge review) ───────────────


def _device_source_records(cur, device_ids) -> dict[str, list[tuple]]:
    """Return each Computer's source records with status and last contact.

    Rows are ``(observation_id, source, entity_type, external_id, source_url,
    active, last_seen, reported_online, last_contact, record_lifecycle)``,
    keyed by device id. The caller sets the tenant on ``cur``.
    """
    cur.execute(
        """
        SELECT evidence.device_id::text,
               evidence.observation_id, evidence.source_name, evidence.entity_type, evidence.external_id,
               CASE
                   WHEN evidence.source_name = 'Ninja'
                   THEN 'https://amrose.rmmservice.com/#/deviceDashboard/'
                        || evidence.external_id || '/overview'
                   ELSE hudu.source_url
               END AS source_url,
               evidence.observation_active, evidence.observation_last_seen_at,
               presence.reported_online, presence.last_contact_at,
               lifecycle.record_lifecycle
          FROM operations.v_device_observation_current evidence
          LEFT JOIN operations.v_device_source_record_lifecycle_current lifecycle
            ON lifecycle.tenant_id = evidence.tenant_id
           AND lifecycle.observation_id = evidence.observation_id
          LEFT JOIN LATERAL (
              SELECT presence.reported_online, presence.last_contact_at
                FROM operations.device_agent_presence_current presence
               WHERE presence.tenant_id = evidence.tenant_id
                 AND presence.device_id = evidence.device_id
                 AND presence.platform = evidence.source_name
                 AND presence.entity_type = evidence.entity_type
               ORDER BY COALESCE(presence.last_contact_at, presence.last_observed_at)
                   DESC NULLS LAST
               LIMIT 1
          ) presence ON TRUE
          LEFT JOIN operations.v_cmdb_inventory_evidence_current hudu
            ON hudu.tenant_id = evidence.tenant_id
           AND hudu.observation_id = evidence.observation_id
           AND hudu.source_name = 'Hudu'
         WHERE evidence.tenant_id = %s AND evidence.device_id = ANY(%s::uuid[])
         ORDER BY evidence.source_name, evidence.entity_type,
                  evidence.observation_last_seen_at DESC
        """,
        [1, [str(device_id) for device_id in device_ids]],
    )
    records: dict[str, list[tuple]] = {}
    for device_id, *row in cur.fetchall():
        records.setdefault(device_id, []).append(tuple(row))
    return records


def _device_process_monitors(cur, device_id) -> dict[str, list[dict]]:
    """Process monitors a source lists on this Computer's records, by record.

    R-U-ON lists each paired ``ProcessOn`` agent on its machine's record.
    Only the safe metadata view is read. The caller sets the tenant on ``cur``.
    """
    cur.execute(
        """
        SELECT observation_id::text, process_monitors
          FROM operations.v_entity_observation_admin_metadata
         WHERE tenant_id = %s AND device_id = %s AND process_monitors IS NOT NULL
        """,
        [1, str(device_id)],
    )
    return {observation_id: monitors for observation_id, monitors in cur.fetchall()}


def _attach_merge_review_evidence(devices) -> None:
    """Give each merge-review Computer its source records and a summary."""
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        records = _device_source_records(cur, [device.id for device in devices])
    retired = {"archived", "retired", "decommissioned"}
    for device in devices:
        device.source_status_rows = records.get(str(device.id), [])
        live = [row for row in device.source_status_rows if row[5] and row[9] not in retired]
        device.is_online_any = any(row[7] is True for row in live)
        device.has_presence = any(row[7] is not None for row in live)
        device.last_contact_any = max((row[8] for row in live if row[8]), default=None)
        device.last_updated_any = max((row[6] for row in live if row[6]), default=None)


# ── Device merge helper (called by device_merge view) ───────────────────


def _merge_devices(cur, survivor_id, loser_id, reason: str, *, actor_id: int | None = None) -> dict:
    """Combine two anchors for one computer without discarding current data.

    ``survivor_id`` is a stable technical anchor, never a winning source. The
    work is ``operations.merge_computers`` (migration 0308), the one merge the
    automatic resolver pass also uses: it moves observations, device findings,
    condition scope and software to the survivor, tombstones the other
    Computer with reason ``merged``, records the merge relation (so it can be
    split later) and writes it to the change history under one action.
    Source links follow the observations on the next sync.
    """
    cur.execute(
        """
        SELECT operations.merge_computers(%s::uuid, %s::uuid, %s::text, '{}'::jsonb,
                                          'operator', %s::bigint, 'operations.ui')
        """,
        (survivor_id, loser_id, reason, actor_id),
    )
    merge_id = cur.fetchone()[0]
    # The survivor's name follows its records at once (ADR-0034 section 6).
    computer_naming.name_now(cur, [survivor_id, loser_id])
    cur.execute(
        """
        SELECT cardinality(moved_observation_ids), cardinality(moved_finding_ids)
          FROM operations.computer_merges WHERE id = %s
        """,
        (merge_id,),
    )
    observations_moved, findings_moved = cur.fetchone()
    return {
        "merge_id": str(merge_id),
        "observations_moved": observations_moved,
        "findings_moved": findings_moved,
        "source_links_converge_on_next_sync": True,
    }


# ── Merge-candidate group review ────────────────────────────────────────────


@login_required
def merge_candidate_group_review(request: HttpRequest, candidate_id) -> HttpResponse:
    """Review and optionally combine every current member of a candidate."""
    candidate = get_object_or_404(
        MergeCandidate.objects.select_related("client"),
        id=candidate_id,
        tenant_id=1,
        status=MergeCandidate.Status.OPEN,
    )
    member_ids = []
    for snapshot in candidate.member_snapshots or []:
        try:
            member_ids.append(uuid.UUID(str(snapshot["device_id"])))
        except (KeyError, TypeError, ValueError):
            messages.error(request, "This merge candidate has invalid member data.")
            return redirect("merge_candidates_queue")
    devices = list(
        Device.objects.select_related("client")
        .prefetch_related("source_links__source")
        .filter(tenant_id=1, id__in=member_ids, deleted_at__isnull=True)
        .order_by("created_at", "id")
    )
    if len(devices) < 2 or len(devices) != len(set(member_ids)):
        messages.error(request, "This merge candidate no longer has all of its active members.")
        return redirect("merge_candidates_queue")
    if len({device.client_id for device in devices}) != 1:
        messages.error(request, "Cross-client group merges are not permitted.")
        return redirect("merge_candidates_queue")

    if request.method == "POST":
        if request.POST.get("confirmation") != "same_computer_group":
            messages.error(request, "Confirm that all records describe the same computer.")
            return redirect("merge_candidate_group_review", candidate_id=candidate.id)
        survivor = devices[0]
        total_counts = {}
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            for loser in devices[1:]:
                counts = _merge_devices(
                    cur,
                    survivor.id,
                    loser.id,
                    "An operator confirmed these records describe one computer.",
                    actor_id=request.user.id,
                )
                for key, value in counts.items():
                    if isinstance(value, int):
                        total_counts[key] = total_counts.get(key, 0) + value
                    else:
                        total_counts[key] = value
            candidate.status = MergeCandidate.Status.MERGED
            candidate.save(update_fields=["status", "version"])
        _audit(
            request,
            "device.group_combine",
            survivor.id,
            {"candidate_id": str(candidate.id), "member_count": len(devices)},
            {"survivor_id": str(survivor.id), "counts": total_counts},
        )
        messages.success(
            request, f"Combined {len(devices)} records into {survivor.canonical_hostname}."
        )
        return redirect("device_detail", org_slug=survivor.client.slug, device_id=survivor.id)

    _attach_merge_review_evidence(devices)
    for device in devices:
        device.source_records = []
        for link in device.source_links.all():
            url = ""
            if link.source.name == "Ninja" and link.external_id:
                url = (
                    "https://amrose.rmmservice.com/#/deviceDashboard/"
                    f"{link.external_id}/overview"
                )
            device.source_records.append(
                {"name": link.source.name, "external_id": link.external_id, "url": url}
            )
    return render(
        request, "merge_candidate_group.html", {"candidate": candidate, "devices": devices}
    )


# ── Device merge (generic entity operation) ─────────────────────────────────


@login_required
def device_merge(
    request: HttpRequest, org_slug: str, device_id: str, target_id: str
) -> HttpResponse:
    """Merge two Devices in the same client. Generic device operation —
    not tied to any Finding type. Invokable from anywhere with two
    Device IDs (identity_conflict Finding evidence, admin manual link,
    future device-detail action, etc.).

    GET asks whether the anchors are observations of one computer. POST keeps
    the older anchor as a stable technical identifier (UUID breaks a timestamp
    tie), moves both evidence sets to it, and redirects to the computer.
    """
    device_a = get_object_or_404(
        Device.objects.select_related("client").prefetch_related("source_links__source"),
        tenant_id=1,
        id=device_id,
        client__slug=org_slug,
        deleted_at__isnull=True,
    )
    device_b = get_object_or_404(
        Device.objects.select_related("client").prefetch_related("source_links__source"),
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
        if request.POST.get("confirmation") != "same_computer":
            messages.error(request, "Confirm that these are the same computer.")
            return redirect(
                "device_merge",
                org_slug=org_slug,
                device_id=device_id,
                target_id=target_id,
            )
        survivor, loser = sorted(
            (device_a, device_b), key=lambda device: (device.created_at, str(device.id))
        )
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            counts = _merge_devices(
                cur,
                survivor.id,
                loser.id,
                "An operator confirmed these records describe one computer.",
                actor_id=request.user.id,
            )
            merged_ids = {str(device_a.id), str(device_b.id)}
            for candidate in MergeCandidate.objects.select_for_update().filter(
                tenant_id=1,
                client_id=survivor.client_id,
                status=MergeCandidate.Status.OPEN,
            ):
                snapshot_ids = {
                    str(member.get("device_id"))
                    for member in (candidate.member_snapshots or [])
                    if member.get("device_id")
                }
                if snapshot_ids == merged_ids:
                    candidate.status = MergeCandidate.Status.MERGED
                    candidate.save(update_fields=["status", "version"])
        _audit(
            request,
            "device.combine",
            survivor.id,
            {"survivor_id": str(survivor.id), "loser_id": str(loser.id)},
            {"counts": counts},
        )
        messages.success(
            request,
            f"Combined observations for {survivor.canonical_hostname}. "
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

    _attach_merge_review_evidence([device_a, device_b])
    return render(
        request,
        "device_merge.html",
        {
            "device_a": device_a,
            "device_b": device_b,
            "devices": [device_a, device_b],
        },
    )


# ── Requirement profiles (Track C.6 admin knob) ─────────────────────────────


@login_required
@require_admin
def admin_services(request: HttpRequest) -> HttpResponse:
    """Preserve the old Services URL after its health moved into Jobs."""
    return redirect("admin_jobs")


@login_required
@require_admin
def admin_settings(request: HttpRequest) -> HttpResponse:
    """Group administrator configuration without mixing it into the main nav."""
    return render(
        request,
        "admin_settings.html",
        {"admin_group": "settings", "admin_tab": "settings"},
    )


def _admin_health_sources(now: datetime) -> tuple[list[dict], bool]:
    """Return source health evidence without making health unavailable."""
    sources = []
    sources_available = True
    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                """
                SELECT platform, last_observed_at, last_run_ok
                  FROM operations.source_health_current
                 WHERE tenant_id = 1
                 ORDER BY platform
                """
            )
            for platform, observed_at, last_run_ok in cur.fetchall():
                needs_attention = (
                    observed_at is None
                    or not last_run_ok
                    or (now - observed_at).total_seconds() > 8 * 3600
                )
                sources.append(
                    {
                        "name": platform,
                        "observed_at": observed_at,
                        "needs_attention": needs_attention,
                    }
                )
    except DatabaseError:
        log.exception("Admin overview source-health query failed")
        sources_available = False
    return sources, sources_available


def _configured_source_data_status(now: datetime) -> tuple[list[dict], bool]:
    """Return binding-level source refresh status for the Dashboard/Admin Data.

    A source binding's current collection lifecycle is the durable
    ``source-refresh`` Job Run.  Reading that small lifecycle projection is
    both more direct than re-aggregating source observations and works for
    reference data sources that do not publish a platform-health row.
    """
    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                """
                WITH latest_run AS (
                    SELECT DISTINCT ON (substring(run.scope_identity FROM 16)::uuid)
                           substring(run.scope_identity FROM 16)::uuid AS binding_id,
                           run.status,
                           COALESCE(run.completed_at, run.started_at, run.requested_at) AS occurred_at
                      FROM operations.operator_job_runs run
                     WHERE run.tenant_id = 1
                       AND run.job_key = 'source-refresh'
                     ORDER BY substring(run.scope_identity FROM 16)::uuid,
                              run.requested_at DESC, run.id DESC
                ), latest_success AS (
                    SELECT DISTINCT ON (substring(run.scope_identity FROM 16)::uuid)
                           substring(run.scope_identity FROM 16)::uuid AS binding_id,
                           COALESCE(run.completed_at, run.started_at, run.requested_at) AS occurred_at
                      FROM operations.operator_job_runs run
                     WHERE run.tenant_id = 1
                       AND run.job_key = 'source-refresh'
                       AND run.status = 'completed'
                     ORDER BY substring(run.scope_identity FROM 16)::uuid,
                              run.requested_at DESC, run.id DESC
                )
                SELECT source.name, client.display_name,
                       COALESCE(success.occurred_at, platform_health.last_success_at),
                       latest.status, binding.schedule
                  FROM operations.source_bindings binding
                  JOIN operations.source_instances instance
                    ON instance.id = binding.source_instance_id
                   AND instance.tenant_id = binding.tenant_id
                  JOIN operations.sources source ON source.id = instance.source_id
             LEFT JOIN operations.clients client ON client.id = instance.client_id
             LEFT JOIN latest_run latest ON latest.binding_id = binding.id
             LEFT JOIN latest_success success ON success.binding_id = binding.id
             LEFT JOIN operations.source_health_current platform_health
                    ON platform_health.tenant_id = binding.tenant_id
                   AND platform_health.platform = COALESCE(
                       NULLIF(instance.config->>'platform', ''), source.name
                   )
                 WHERE binding.tenant_id = 1
                   AND binding.enabled
                   AND instance.enabled
                 ORDER BY source.name, client.display_name NULLS FIRST
                """
            )
            rows = cur.fetchall()
    except DatabaseError:
        log.exception("Admin Data source-status query failed")
        return [], False

    sources = []
    for source_name, client_name, success_at, latest_status, schedule in rows:
        received_at = success_at
        schedule_minutes = _source_schedule_minutes(schedule or "")
        sources.append(
            {
                "name": source_name,
                "client_name": client_name or "",
                "observed_at": received_at,
                "needs_attention": bool(
                    latest_status in {"failed", "stalled"}
                    or _source_is_stale(received_at, schedule_minutes, now)
                ),
            }
        )
    return sources, True


def _admin_health_attention_items(
    *,
    sources: list[dict],
    sources_available: bool,
    jobs_available: bool,
    jobs_issues: list[str],
    services_current: bool,
    system_health_available: bool,
    system_findings: list[AdminFinding],
) -> list[dict]:
    """Summarize only actionable cross-area conditions for the overview."""
    attention_items = []
    if not jobs_available:
        attention_items.append(
            {
                "area": "Jobs",
                "detail": "Jobs health cannot be checked.",
                "url_name": "admin_jobs",
                "url_label": "Review Jobs",
            }
        )
    else:
        for issue in jobs_issues[:2]:
            attention_items.append(
                {
                    "area": "Jobs",
                    "detail": issue,
                    "url_name": "admin_jobs",
                    "url_label": "Review Jobs",
                }
            )
    if not sources_available:
        attention_items.append(
            {
                "area": "Sources",
                "detail": "Source health is unavailable.",
                "url_name": "sources_status",
                "url_label": "Review sources",
            }
        )
    else:
        for source in [source for source in sources if source["needs_attention"]][:2]:
            attention_items.append(
                {
                    "area": "Sources",
                    "detail": source["name"],
                    "observed_at": source["observed_at"],
                    "url_name": "sources_status",
                    "url_label": "Review sources",
                }
            )
    if not system_health_available:
        attention_items.append(
            {
                "area": "Admin Health",
                "detail": "System health cannot be checked.",
                "url_name": "findings_admin_health",
                "url_label": "Review Admin Health",
            }
        )
    else:
        for finding in system_findings[:2]:
            attention_items.append(
                {
                    "area": "Admin Health",
                    "detail": finding.finding_type.description or finding.finding_type.name,
                    "url_name": "findings_admin_health",
                    "url_label": "Review Admin Health",
                }
            )
    return attention_items


def _admin_overview_recent_activity() -> list[dict]:
    """Return recent user-initiated administrator activity, not runtime noise."""
    try:
        # Operator change actions (ADR-0033); audit_log is read-only since 0319.
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT action, max(occurred_at) AS occurred_at, count(*) AS occurrence_count
                  FROM operations.change_actions
                 WHERE tenant_id = 1 AND actor_kind = 'operator'
                 GROUP BY action
                 ORDER BY 2 DESC, 1
                 LIMIT 5
                """
            )
            recent_activity = [
                {"action": a, "occurred_at": at, "occurrence_count": n}
                for a, at, n in cur.fetchall()
            ]
    except DatabaseError:
        log.exception("Admin overview recent-activity query failed")
        return []
    for activity in recent_activity:
        activity["label"] = str(activity["action"]).replace("_", " ").replace(".", " ").capitalize()
        if activity["occurrence_count"] > 1:
            activity["label"] += f" — {activity['occurrence_count']} changes"
    return recent_activity


def _admin_health_system_findings() -> tuple[bool, int, list[AdminFinding]]:
    """Return platform conditions not already owned by Jobs, Sources, or Services."""
    try:
        findings = AdminFinding.objects.filter(
            tenant_id=1,
            status__in=("open", "acknowledged"),
            finding_type__issue_category=finding_registry.COLLECTION,
        ).exclude(finding_type__name__startswith="jobs_").exclude(
            finding_type__name="source_failure"
        )
        return True, findings.count(), list(
            findings.select_related("finding_type").order_by("-severity", "-last_detected_at")[:2]
        )
    except DatabaseError:
        log.exception("Admin overview system-health query failed")
        return False, 0, []


def _admin_health_snapshot(now=None) -> dict:
    """Build the single cross-domain health summary used by Admin surfaces."""
    now = now or timezone.now()
    sources, sources_available = _admin_health_sources(now)
    source_attention_count = sum(source["needs_attention"] for source in sources)
    jobs_health = _jobs_control_health()
    live_runtime_kinds = set()
    latest_service_checkin = None
    for runtime in jobs_health["runtimes"]:
        heartbeat = parse_datetime(str(runtime.get("heartbeat_at") or ""))
        if heartbeat and (latest_service_checkin is None or heartbeat > latest_service_checkin):
            latest_service_checkin = heartbeat
        if heartbeat and not runtime.get("stopped_at") and now - heartbeat <= timedelta(minutes=3):
            live_runtime_kinds.add(str(runtime.get("runtime_kind")))
    services_current = {"scheduler", "worker"}.issubset(live_runtime_kinds)
    jobs_issues = jobs_health["issues"]
    system_health_available, system_health_count, system_findings = (
        _admin_health_system_findings()
    )
    raw_attention_items = _admin_health_attention_items(
        sources=sources,
        sources_available=sources_available,
        jobs_available=jobs_health["available"],
        jobs_issues=jobs_issues,
        services_current=services_current,
        system_health_available=system_health_available,
        system_findings=system_findings,
    )
    unavailable = (
        not sources_available or not jobs_health["available"] or not system_health_available
    )
    domain_counts = (
        source_attention_count,
        len(jobs_issues),
        system_health_count,
    )
    condition_count = sum(domain_counts)
    affected_domain_count = sum(count > 0 for count in domain_counts)
    jobs_summary = jobs_health["summary"]
    waiting_runs = int(jobs_summary.get("waiting_runs") or 0)
    if unavailable:
        overall_state = "unavailable"
        overall_label = "Unavailable"
        overall_detail = "Some health evidence cannot be checked."
    elif condition_count:
        overall_state = "warn"
        overall_label = "Needs attention"
        overall_detail = (
            f"{condition_count} active health condition"
            f"{'s' if condition_count != 1 else ''} across "
            f"{affected_domain_count} area{'s' if affected_domain_count != 1 else ''}."
        )
    else:
        overall_state = "ok"
        overall_label = "Healthy"
        overall_detail = "Current health checks are passing."
    domains = [
        {
            "label": "Jobs",
            "count": len(jobs_issues),
            "available": jobs_health["available"],
            "detail": (
                f"Running {jobs_summary.get('running_runs') or 0} · "
                f"Ready {jobs_summary.get('ready_runs') or 0} · Waiting {waiting_runs}"
            ),
            "url_name": "admin_jobs",
            "url_label": "Review Jobs",
        },
        {
            "label": "Sources",
            "count": source_attention_count,
            "available": sources_available,
            "detail": f"{len(sources)} source{'s' if len(sources) != 1 else ''} reporting to Operations.",
            "url_name": "sources_status",
            "url_label": "Review sources",
        },
        {
            "label": "System checks",
            "count": system_health_count,
            "available": system_health_available,
            "detail": "Conditions not owned by Jobs or Sources.",
            "url_name": "findings_admin_health",
            "url_label": "Review Admin Health",
        },
    ]
    return {
        "at": now,
        "sources": sources,
        "sources_available": sources_available,
        "source_attention_count": source_attention_count,
        "jobs_health": jobs_health,
        "waiting_runs": waiting_runs,
        "jobs_attention_count": len(jobs_issues),
        "services_current": services_current,
        "latest_service_checkin": latest_service_checkin,
        "system_health_available": system_health_available,
        "system_health_count": system_health_count,
        "condition_count": condition_count,
        "domains": domains,
        "overall_state": overall_state,
        "overall_label": overall_label,
        "overall_detail": overall_detail,
        "attention_items": raw_attention_items[:5],
        "hidden_attention_count": max(0, len(raw_attention_items) - 5),
    }


def _operations_admin_overview_snapshot() -> dict:
    """Build the complete overview context once for one tenant-scoped request."""
    now = timezone.now()
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        health = _admin_health_snapshot(now)
        active_issue_count = Finding.objects.filter(
            tenant_id=1, status__in=_FINDING_ACTIVE_STATUSES
        ).count()
        recent_activity = _admin_overview_recent_activity()
    return {
        "health": health,
        "active_issue_count": active_issue_count,
        "recent_activity": recent_activity,
    }


@login_required
@require_admin
def operations_admin_overview(request: HttpRequest) -> HttpResponse:
    """Show the current administration posture and direct links to its evidence."""
    overview = _operations_admin_overview_snapshot()

    return render(
        request,
        "operations_admin_overview.html",
        {
            "admin_group": "overview",
            **overview,
        },
    )


@login_required
@require_admin
def admin_data(request: HttpRequest) -> HttpResponse:
    """Show administrative evidence for the data Operations is using."""
    now = timezone.now()
    active_issue_filter = Q(status__in=_FINDING_ACTIVE_STATUSES) & (
        Q(snoozed_until__isnull=True) | Q(snoozed_until__lt=now)
    )
    sources, sources_available = _configured_source_data_status(now)
    current_source_count = sum(1 for source in sources if not source["needs_attention"])
    source_issue_count = AdminFinding.objects.filter(
        tenant_id=1,
        status__in=_FINDING_ACTIVE_STATUSES,
        finding_type__name="source_failure",
    ).count()
    completeness_issue_count = Finding.objects.filter(active_issue_filter).filter(
        finding_type__name__in=(
            "missing_required_platform",
            "stale_required_platform",
            "device_unenrolled",
            "device_stale_data",
        )
    ).count()
    matching_issue_count = (
        Finding.objects.filter(active_issue_filter)
        .filter(
            finding_type__name__in=(
                "identity_resolution_pending",
                "unlinked_external_identity",
            )
        )
        .count()
        + AdminFinding.objects.filter(
            tenant_id=1,
            status__in=_FINDING_ACTIVE_STATUSES,
            finding_type__name__in=(
                "client_link_collision",
                "client_source_group_merge",
                "client_unattached_group",
                "unnamed_source_group",
                "unmatched_source_group",
            ),
        ).count()
    )
    clients_count = Client.objects.filter(tenant_id=1, deleted_at__isnull=True).count()
    devices_count = current_computers(
        Device.objects.filter(tenant_id=1, deleted_at__isnull=True)
    ).count()

    source_rows = sorted(
        sources,
        key=lambda source: (not source["needs_attention"], source["name"].lower()),
    )
    return render(
        request,
        "admin_data.html",
        {
            "admin_group": "data",
            "admin_tab": "data",
            "as_of": now,
            "sources_available": sources_available,
            "sources_total": len(sources),
            "sources_current": current_source_count,
            "source_issue_count": source_issue_count,
            "clients_count": clients_count,
            "devices_count": devices_count,
            "completeness_issue_count": completeness_issue_count,
            "matching_issue_count": matching_issue_count,
            "source_rows": source_rows,
        },
    )


def _requirements_redirect(anchor: str = "") -> HttpResponse:
    url = reverse("requirement_profiles_list")
    return redirect(f"{url}#{anchor}" if anchor else url)


def _profile_details_form(request: HttpRequest, profile=None) -> tuple[str, str] | None:
    """Validated name and description, or None after reporting the problem."""
    name = (request.POST.get("name") or "").strip()
    description = (request.POST.get("description") or "").strip()
    name_limit = RequirementProfile._meta.get_field("name").max_length
    description_limit = RequirementProfile._meta.get_field("description").max_length
    if not name or len(name) > name_limit or len(description) > description_limit:
        messages.error(
            request,
            f"A profile needs a name of up to {name_limit} characters and a description "
            f"of up to {description_limit}.",
        )
        return None
    taken = RequirementProfile.objects.filter(tenant_id=1, name__iexact=name)
    if profile is not None:
        taken = taken.exclude(id=profile.id)
    if taken.exists():
        messages.error(request, f"A profile named {name} already exists.")
        return None
    return name, description


def _set_new_client_default(profile, is_default: bool) -> None:
    """Make this profile the one preselected for new clients, or stop it being one."""
    if is_default and not profile.is_tenant_default:
        # Only one default may exist; clear the old one first.
        for other in RequirementProfile.objects.filter(tenant_id=1, is_tenant_default=True):
            other.is_tenant_default = False
            other.save(update_fields=["is_tenant_default"])
    if profile.is_tenant_default != is_default:
        profile.is_tenant_default = is_default
        profile.save(update_fields=["is_tenant_default"])


def _profile_audit_state(profile) -> dict:
    return {
        "name": profile.name,
        "description": profile.description,
        "default_for_new_clients": profile.is_tenant_default,
    }


def _create_requirement_profile(request: HttpRequest) -> HttpResponse:
    details = _profile_details_form(request)
    if details is None:
        return _requirements_redirect("new-profile")
    start_from = request.POST.get("start_from") or ""
    if start_from == "global":
        source_rows = list(
            CoverageRequirement.objects.filter(tenant_id=1, client__isnull=True, enabled=True)
        )
    elif start_from:
        source = get_object_or_404(RequirementProfile, id=start_from, tenant_id=1)
        source_rows = list(source.items.all())
    else:
        source_rows = []
    profile = RequirementProfile.objects.create(
        tenant_id=1, name=details[0], description=details[1]
    )
    copied: set[tuple] = set()
    for row in source_rows:
        # Global rows are not unique by service, so copy each shape once.
        shape = (row.entity_type, row.platform, row.device_scope)
        if shape in copied:
            continue
        copied.add(shape)
        RequirementProfileItem.objects.create(
            tenant_id=1,
            profile=profile,
            **{field: getattr(row, field) for field in requirement_baselines.COPIED_FIELDS},
        )
    _audit(
        request,
        "requirement_profile.create",
        profile.id,
        None,
        {
            **_profile_audit_state(profile),
            "start_from": start_from or "empty",
            "items": len(copied),
        },
        entity_type="requirement_profile",
    )
    messages.success(request, f"Profile {profile.name} created with {len(copied)} requirements.")
    return _requirements_redirect(f"profile-{profile.id}")


def _update_requirement_profile(request: HttpRequest, profile) -> HttpResponse:
    details = _profile_details_form(request, profile)
    if details is None:
        return _requirements_redirect(f"profile-{profile.id}")
    before = _profile_audit_state(profile)
    profile.name, profile.description = details
    profile.save(update_fields=["name", "description"])
    _set_new_client_default(profile, request.POST.get("is_tenant_default") == "on")
    after = _profile_audit_state(profile)
    if after != before:
        _audit(
            request,
            "requirement_profile.update",
            profile.id,
            before,
            after,
            entity_type="requirement_profile",
        )
    messages.success(request, f"Profile {profile.name} saved.")
    return _requirements_redirect(f"profile-{profile.id}")


def _delete_requirement_profile(request: HttpRequest, profile) -> HttpResponse:
    # A deleted client still holds its profile (the reference is protected),
    # so every client counts.
    in_use = Client.objects.filter(tenant_id=1, requirement_profile=profile).count()
    if in_use:
        messages.error(
            request,
            f"Profile {profile.name} is assigned to {in_use} client{'s' if in_use != 1 else ''}. "
            "Move them to another baseline on their Configuration page first.",
        )
        return _requirements_redirect(f"profile-{profile.id}")
    before = {
        **_profile_audit_state(profile),
        "items": [
            f"{item.platform}:{item.entity_type}:{item.device_scope}"
            for item in profile.items.all()
        ],
    }
    profile_id = profile.id
    profile.delete()
    _audit(
        request,
        "requirement_profile.delete",
        profile_id,
        before,
        None,
        entity_type="requirement_profile",
    )
    messages.success(request, f"Profile {before['name']} deleted.")
    return _requirements_redirect()


def _set_baseline_requirement(request: HttpRequest) -> HttpResponse:
    """Require or stop requiring one service in the global or a profile baseline."""
    target = request.POST.get("target") or ""
    mode = request.POST.get("mode")
    profile = (
        None
        if target == "global"
        else get_object_or_404(RequirementProfile, id=target, tenant_id=1)
    )
    anchor = "global" if profile is None else f"profile-{profile.id}"
    label = "global requirements" if profile is None else f"{profile.name} profile"
    entity_type = "coverage_requirement" if profile is None else "requirement_profile_item"

    if mode == "required":
        agent = get_object_or_404(Agent, id=request.POST.get("agent_id"))
        if profile is None:
            rows = CoverageRequirement.objects.filter(
                tenant_id=1, client__isnull=True, device_scope=requirement_baselines.ALL_SCOPE
            )
        else:
            rows = profile.items.filter(device_scope=requirement_baselines.ALL_SCOPE)
        existing = next(
            (row for row in rows if requirement_baselines.matches_agent(row, agent)), None
        )
        was_required = existing is not None and (profile is not None or existing.enabled)
        if existing is None:
            model = CoverageRequirement if profile is None else RequirementProfileItem
            extra = {} if profile is None else {"profile": profile}
            row = model.objects.create(
                tenant_id=1, **extra, **requirement_baselines.new_item_values(agent)
            )
        else:
            row = existing
            if not was_required:
                # Re-enable the removed global row so its thresholds come back too.
                row.enabled = True
                row.save(update_fields=["enabled"])
        if not was_required:
            _audit(
                request,
                "requirement_baseline.require",
                row.id,
                {"baseline": label, "service": agent.name, "required": False},
                {"baseline": label, "service": agent.name, "scope": row.device_scope},
                entity_type=entity_type,
            )
        messages.success(request, f"{agent.name} is required in the {label}.")
    elif mode == "not_required":
        item_id = request.POST.get("item_id")
        if profile is None:
            row = get_object_or_404(
                CoverageRequirement, id=item_id, tenant_id=1, client__isnull=True
            )
            row.enabled = False
            row.save(update_fields=["enabled"])
        else:
            row = get_object_or_404(
                RequirementProfileItem, id=item_id, tenant_id=1, profile=profile
            )
            row.delete()
        _audit(
            request,
            "requirement_baseline.remove",
            item_id,
            {"baseline": label, "service": row.platform, "scope": row.device_scope},
            {"baseline": label, "service": row.platform, "required": False},
            entity_type=entity_type,
        )
        messages.success(request, f"{row.platform} is no longer required in the {label}.")
    else:
        messages.error(request, "Choose Required or Not required.")
    return _requirements_redirect(anchor)


@login_required
@transaction.atomic
def requirement_profiles_list(request: HttpRequest) -> HttpResponse:
    """Edit the global requirements and each requirement profile."""
    if request.method == "POST":
        action = request.POST.get("action")
        baseline_actions = {
            "create_profile": _create_requirement_profile,
            "set_requirement": _set_baseline_requirement,
        }
        profile_actions = {
            "update_profile": _update_requirement_profile,
            "delete_profile": _delete_requirement_profile,
        }
        if action in baseline_actions:
            return baseline_actions[action](request)
        if action not in profile_actions:
            messages.error(request, "That change is not recognised.")
            return _requirements_redirect()
        profile = get_object_or_404(
            RequirementProfile, id=request.POST.get("profile_id"), tenant_id=1
        )
        return profile_actions[action](request, profile)

    agents = list(Agent.objects.all().order_by("name"))
    profiles = list(
        RequirementProfile.objects.filter(tenant_id=1)
        .prefetch_related("items")
        .order_by("-is_tenant_default", "name")
    )
    client_counts = dict(
        Client.objects.filter(tenant_id=1, deleted_at__isnull=True)
        .values("requirement_profile_id")
        .annotate(n=Count("id"))
        .values_list("requirement_profile_id", "n")
    )
    global_required = CoverageRequirement.objects.filter(
        tenant_id=1, client__isnull=True, enabled=True
    )
    rows = []
    for p in profiles:
        items = list(p.items.all())
        rows.append(
            {
                "profile": p,
                "items": sorted(items, key=lambda i: (i.device_scope, i.entity_type, i.platform)),
                "service_rows": requirement_baselines.baseline_rows(agents, items),
                "client_count": client_counts.get(p.id, 0),
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
            "profiles": profiles,
            "global_service_rows": requirement_baselines.baseline_rows(agents, global_required),
            "global_client_count": client_counts.get(None, 0),
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
    # Each service can be required everywhere or on servers only; the
    # evaluator applies a role-scoped override on top of an "all" one.
    for agent in Agent.objects.all().order_by("name"):
        for scope in ("all", "server"):
            candidates.setdefault(
                (agent.id, scope),
                {"agent": agent, "scope": scope, "baseline_required": False},
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
        elif action == "offline_after":
            raw_days = (request.POST.get("offline_after_days") or "").strip()
            policy = get_device_status_policy()
            ceiling = policy["retire_review_days"] - 1
            try:
                days = int(raw_days) if raw_days else None
            except ValueError:
                days = -1
            if days is not None and not 1 <= days <= ceiling:
                messages.error(
                    request,
                    f"Offline after must be between 1 and {ceiling} days, or empty to use "
                    f"the default of {policy['active_device_days']}.",
                )
                return redirect("client_requirements_config", org_slug=client.slug)
            before = client.offline_after_days
            if days != before:
                client.offline_after_days = days
                client.save(update_fields=["offline_after_days"])
                _audit(
                    request,
                    "client.offline_after_days.update",
                    client.id,
                    {"offline_after_days": before},
                    {"offline_after_days": days},
                )
            messages.success(request, "Offline threshold updated.")
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
            "device_policy": get_device_status_policy(),
        },
    )


# ── Software classifier config (evaluator knobs, admin-editable) ────────

@login_required
def classifier_config(request: HttpRequest) -> HttpResponse:
    """Edit the software classifier settings.

    Saving merges the submitted fields into the stored object: keys the form
    does not show (or does not know yet) are never dropped. Every change is
    audited with the before and after values.
    """
    row, _ = EvaluatorConfig.objects.get_or_create(
        tenant_id=1,
        evaluator_name="software_classifier",
        defaults={"config": {}, "updated_by": request.user},
    )
    stored = row.config if isinstance(row.config, dict) else {}

    if request.method == "POST":
        merged = software_settings.merge(stored, software_settings.parse_form(request.POST))
        if merged != stored:
            row.config = merged
            row.updated_by = request.user
            row.save(update_fields=["config", "updated_by", "updated_at"])
            _audit(
                request,
                "evaluator_config.update",
                row.id,
                stored,
                merged,
                entity_type="evaluator_config",
            )
            # Settings change what every title's findings should be.
            _queue_software_rebuild_after_commit(request.user.id)
            messages.info(request, "Classifier configuration saved.")
        else:
            messages.info(request, "No classifier settings changed.")
        return redirect("classifier_config")

    effective = software_settings.effective(stored)
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(software_review.DEVICE_COUNTS_SQL, (1,))
        distribution = {int(devices): int(count) for devices, count in cur.fetchall()}
    return render(
        request,
        "classifier_config.html",
        {
            "rare_distribution": distribution,
            "rare_current": int(effective["rare_max_devices"]),
            "admin_group": "config",
            "admin_tab": "classifier",
            "sections": [
                (
                    title,
                    [{"field": field, "value": effective[field.key]} for field in fields],
                )
                for title, fields in software_settings.sections()
            ],
            "updated_at": row.updated_at,
            "updated_by": row.updated_by,
            "severity_choices": [
                (value, value.title()) for value in software_settings.SEVERITIES
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
            "retire_review_days": (2, 365),
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
        # Review for retirement cannot come before a computer is offline.
        new_config["retire_review_days"] = max(
            new_config["retire_review_days"], new_config["active_device_days"] + 1
        )
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
def attribute_visibility_config(request: HttpRequest) -> HttpResponse:
    """Manage which normalized fields are visible without a raw-data reveal."""
    if request.method == "POST":
        definition = get_object_or_404(
            AttributeDefinition,
            id=request.POST.get("definition_id"),
            enabled=True,
        )
        sensitivity = (request.POST.get("sensitivity") or "").strip()
        allowed = set(AttributeDefinition.Sensitivity.values)
        if sensitivity not in allowed:
            messages.error(request, "Choose a valid visibility level.")
            return redirect("attribute_visibility_config")
        before = {"sensitivity": definition.sensitivity}
        definition.sensitivity = sensitivity
        definition.save(update_fields=["sensitivity"])
        _audit(
            request,
            "attribute_definition.visibility.update",
            definition.id,
            before,
            {"sensitivity": sensitivity},
        )
        messages.success(request, f"Visibility saved for {definition.display_name}.")
        return redirect("attribute_visibility_config")

    definitions = AttributeDefinition.objects.filter(enabled=True).select_related("entity_class")
    return render(
        request,
        "attribute_visibility_config.html",
        {
            "admin_group": "config",
            "admin_tab": "fields",
            "definitions": definitions,
            "sensitivity_choices": AttributeDefinition.Sensitivity.choices,
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
        # Since migration 0319 transitions are change actions whose evidence
        # holds the item; earlier ones remain in the read-only audit_log.
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT (item ->> 'entity_id')::uuid, a.occurred_at, item -> 'before', item -> 'after'
                  FROM operations.change_actions a,
                       jsonb_array_elements(coalesce(a.evidence -> 'items', '[]'::jsonb)) item
                 WHERE a.tenant_id = 1 AND item ->> 'action' = 'lifecycle.transition'
                 ORDER BY a.occurred_at DESC
                 LIMIT 100
                """
            )
            transitions = [
                {"entity_id": e, "occurred_at": at, "before_state": b, "after_state": af}
                for e, at, b, af in cur.fetchall()
            ]
        transitions += list(
            AuditLog.objects.filter(tenant_id=1, action="lifecycle.transition")
            .order_by("-occurred_at")
            .values("entity_id", "occurred_at", "before_state", "after_state")[:100]
        )
        transitions = sorted(transitions, key=lambda t: t["occurred_at"], reverse=True)[:100]
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
