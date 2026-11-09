"""Domain-owned Home totals from the Patching Computer population."""

from __future__ import annotations

from datetime import datetime, timedelta

from django.db import connection, transaction
from django.utils import timezone

from .computer_reads import current_computer_sql
from .device_status import get_device_status_policy, recent_contact_sql


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
            "ninja_patches.patch_outcome_counts" if has_outcome_counts
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
