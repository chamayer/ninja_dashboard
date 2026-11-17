"""Domain-owned Patching population and finding readers."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from django.core.exceptions import EmptyResultSet
from django.db import connection, transaction
from django.db.models import Case, F, IntegerField, Q, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone

from . import finding_registry
from .computer_reads import current_computer_sql, finding_has_current_owner
from .device_status import get_device_status_policy, recent_contact_sql
from .models import Finding


def findings_queryset(tenant_id: int):
    """Root Patching selector; device findings must retain their effective owner.

    The correlated predicate avoids enumerating every device finding ID in the
    tenant. Keep this as a root query (the raw correlation names its table);
    page hydration uses concrete IDs rather than nesting this queryset.
    """
    return Finding.objects.filter(
        tenant_id=tenant_id,
        finding_type__issue_category=finding_registry.PATCHING,
    ).filter(~Q(subject_type=Finding.SubjectType.DEVICE) | Q(finding_has_current_owner()))


def ordered_findings(queryset):
    """Keep severity/detection priority, with a stable tie-breaker for paging."""
    return queryset.alias(
        _patching_severity=Case(
            *(
                When(severity=value, then=Value(rank))
                for rank, value in enumerate(("critical", "high", "medium", "low", "info"))
            ),
            default=Value(9),
            output_field=IntegerField(),
        ),
        _patching_detected=Coalesce("last_detected_at", "last_seen_at"),
    ).order_by("_patching_severity", "-_patching_detected", "id")


def finding_page(queryset, type_filter: list[str], page_number):
    """Count tiles and select at most 50 ordered IDs in one statement snapshot.

    The materialized selection carries scalar keys only, never finding details
    or related-object payloads. Type filtering affects the list, not its tiles.
    Match Paginator.get_page: invalid input selects first, out-of-range last.
    """
    try:
        number = int(page_number)
    except (TypeError, ValueError):
        number = 1
    selected = (
        ordered_findings(queryset)
        .annotate(
            _patching_type=F("finding_type__name"),
            _patching_severity=F("_patching_severity"),
            _patching_detected=F("_patching_detected"),
        )
        .order_by()
        .values("id", "_patching_type", "_patching_severity", "_patching_detected")
    )
    try:
        sql, params = selected.query.sql_with_params()
    except EmptyResultSet:
        return {}, 0, []
    # Compiled SQL/parameters come only from the normalized ORM selector.
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            WITH selected AS MATERIALIZED ({sql}),
            tiles AS (
                SELECT _patching_type, count(*) AS total FROM selected
                GROUP BY _patching_type
            ), filtered AS MATERIALIZED (
                SELECT * FROM selected
                WHERE cardinality(%s::text[]) = 0 OR _patching_type = ANY(%s::text[])
            ), totals AS (
                SELECT count(*) AS total FROM filtered
            ), bounds AS (
                SELECT total, CASE WHEN %s::numeric < 1 OR %s::numeric >
                    greatest(1, (total + 49) / 50)
                    THEN greatest(1, (total + 49) / 50) ELSE %s::numeric END AS number
                FROM totals
            )
            SELECT (SELECT coalesce(jsonb_object_agg(_patching_type, total), '{{}}'::jsonb)
                    FROM tiles), bounds.total,
                   ARRAY(SELECT id FROM filtered
                         ORDER BY _patching_severity, _patching_detected DESC, id
                         LIMIT 50 OFFSET (SELECT ((number - 1) * 50)::bigint FROM bounds))
            FROM bounds
            """,
            (*params, type_filter, type_filter, number, number, number),
        )
        tiles, total, ids = cursor.fetchone()
    return json.loads(tiles) if isinstance(tiles, str) else tiles, total, ids


def safe_ninja_device_id_sql(alias: str) -> str:
    """Cast a numeric Ninja source ID without allowing malformed or oversized IDs."""
    return f"""CASE
        WHEN {alias}.external_id ~ '^\\d+$'
         AND (length({alias}.external_id) < 10
              OR (length({alias}.external_id) = 10
                  AND {alias}.external_id <= '2147483647'))
        THEN {alias}.external_id::integer
    END"""


def home_summary(*, now: datetime | None = None, policy: dict[str, int] | None = None) -> dict:
    """Return scope, recent-activity, and in-scope outcome totals for Home.

    Recent activity follows the Patching page: current, owned, in-scope,
    active Computers with activity inside the configured patch window.
    """
    now = now or timezone.now()
    policy = policy if policy is not None else get_device_status_policy(1)
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL operations.tenant_id = 1")
        # Operations and ingest start independently. During deployment the old
        # fact query remains available until ingest applies its migration.
        cursor.execute("SELECT to_regclass('ninja_patches.patch_outcome_counts') IS NOT NULL")
        has_outcome_counts = cursor.fetchone()[0]
        outcome_source = (
            "ninja_patches.patch_outcome_counts"
            if has_outcome_counts
            else "ninja_patches.patch_facts"
        )
        outcome_count = "fact.outcome_count" if has_outcome_counts else "1"
        outcome_filter = "" if has_outcome_counts else "AND fact.fact_type = 'install_outcome'"
        cursor.execute(
            f"""
            WITH current_computers AS (
                SELECT device.device_id, device.client_id, device.last_contact_at,
                       device.effective_patching_scope,
                       owner.device_id IS NOT NULL AS has_owner
                  FROM operations.v_device device
                  LEFT JOIN operations.computer_client_ownership owner
                    ON owner.tenant_id = device.tenant_id
                   AND owner.device_id = device.device_id
                   AND owner.effective_client_id = device.client_id
                   AND owner.state IN ('resolved', 'decision_protected')
                 WHERE device.tenant_id = 1
                   AND {current_computer_sql('device')}
            ), ninja_links AS (
                SELECT DISTINCT link.device_id,
                       {safe_ninja_device_id_sql('link')} AS ninja_device_id
                  FROM operations.v_device_source_link link
                  JOIN current_computers computer ON computer.device_id = link.device_id
                   AND computer.has_owner
                  JOIN operations.sources source ON source.id = link.source_id
                 WHERE link.tenant_id = 1 AND lower(source.name) = 'ninja'
            ), patch_activity AS (
                SELECT DISTINCT link.device_id
                  FROM ninja_links link
                  JOIN ninja_patches.device_patch_activity activity
                    ON activity.device_id = link.ninja_device_id
                   AND activity.last_patch_activity_at >= %s
            ), posture AS (
                SELECT computer.*,
                       {recent_contact_sql('computer.last_contact_at', 'computer.client_id', policy['active_device_days'])} AS is_active,
                       activity.device_id IS NOT NULL AS has_recent_activity
                  FROM current_computers computer
                  LEFT JOIN patch_activity activity USING (device_id)
            ), included_ninja_devices AS (
                SELECT DISTINCT link.ninja_device_id
                  FROM posture computer
                  JOIN ninja_links link USING (device_id)
                 WHERE computer.has_owner AND computer.effective_patching_scope = 'Included'
                   AND link.ninja_device_id IS NOT NULL
            ), outcomes AS (
                SELECT COALESCE(SUM({outcome_count}) FILTER (WHERE lower(fact.status) = 'installed'), 0)::bigint AS installed,
                       COALESCE(SUM({outcome_count}) FILTER (WHERE lower(fact.status) = 'failed'), 0)::bigint AS failed,
                       MAX(fact.installed_at) AS latest
                  FROM included_ninja_devices device
                  JOIN {outcome_source} fact ON fact.device_id = device.ninja_device_id
                 WHERE fact.installed_at >= %s {outcome_filter}
            )
            SELECT COUNT(*)::int AS current_total,
                   COUNT(*) FILTER (WHERE has_owner AND effective_patching_scope = 'Included')::int AS included,
                   COUNT(*) FILTER (WHERE has_owner AND effective_patching_scope = 'Excluded')::int AS excluded,
                   COUNT(*) FILTER (WHERE has_owner AND effective_patching_scope = 'Unmanaged')::int AS unmanaged,
                   COUNT(*) FILTER (WHERE NOT has_owner)::int AS unresolved,
                   COUNT(*) FILTER (WHERE has_owner AND
                       COALESCE(effective_patching_scope, '') NOT IN ('Included', 'Excluded', 'Unmanaged'))::int AS unspecified,
                   COUNT(*) FILTER (
                       WHERE has_owner AND is_active AND effective_patching_scope = 'Included'
                         AND has_recent_activity
                   )::int AS actively_patching,
                   COALESCE(MAX(outcomes.installed), 0)::int,
                   COALESCE(MAX(outcomes.failed), 0)::int,
                   MAX(outcomes.latest)
              FROM posture CROSS JOIN outcomes
            """,
            [
                now - timedelta(days=policy["patch_activity_days"]),
                now - timedelta(days=30),
            ],
        )
        row = cursor.fetchone()
    (
        current_total,
        included,
        excluded,
        unmanaged,
        unresolved,
        unspecified,
        actively_patching,
        installed,
        failed,
        latest,
    ) = row
    return {
        "current_total": current_total,
        "included": included,
        "excluded": excluded,
        "unmanaged": unmanaged,
        "unresolved": unresolved,
        "unspecified": unspecified,
        "actively_patching": actively_patching,
        "actively_patching_percent": (
            round(100 * actively_patching / current_total, 1) if current_total else 0.0
        ),
        "installed_30d": installed,
        "failed_30d": failed,
        "latest": latest,
    }
