"""Bounded, repeatable-read snapshot. Only explicit SELECTs, no source payloads.

SQL fanout is deliberately a candidate association, not a replacement for the
software exposure view's eligibility semantics. The report labels that limit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db import transaction

from .policy import Profile

MAX_SHADOW_ROWS = 1_000_000
MAX_QUERY_TIMEOUT_MS = 60_000


@dataclass(frozen=True)
class Snapshot:
    tenant_id: int
    now: datetime
    registry: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    devices: list[dict[str, Any]]
    presence: list[dict[str, Any]]
    associations: list[dict[str, Any]]
    collections: list[dict[str, Any]]
    consumers: list[dict[str, Any]]


REGISTRY_SQL = """
SELECT name, finding_class, subject_scope, creates_device_exposure
FROM operations.finding_types ORDER BY name
"""

FINDINGS_SQL = """
SELECT 'entity' AS row_kind, f.id::text AS row_id, ft.name AS type_name,
       f.condition_key, f.status, f.subject_type, f.subject_id::text,
       f.client_id::text, f.snoozed_until,
       f.finding_details -> %s AS candidate_ids,
       f.finding_details ->> 'source_instance_id' AS source_instance_id,
       f.finding_details ->> 'snapshot_scope' AS snapshot_scope
FROM operations.findings f
JOIN operations.finding_types ft ON ft.id=f.finding_type_id
WHERE f.tenant_id=%s AND f.status IN ('open','acknowledged','investigating','suppressed','wontfix')
UNION ALL
SELECT 'admin', f.id::text, ft.name, f.condition_key, f.status,
       'admin_context', f.id::text, NULL, NULL, NULL,
       f.subject_ref ->> 'source_instance_id', f.subject_ref ->> 'snapshot_scope'
FROM operations.admin_findings f
JOIN operations.finding_types ft ON ft.id=f.finding_type_id
WHERE f.tenant_id=%s AND f.status IN ('open','acknowledged','investigating','suppressed','wontfix')
"""

DEVICES_SQL = """
SELECT id::text AS device_id, client_id::text, lifecycle_status
FROM operations.devices WHERE tenant_id=%s AND deleted_at IS NULL
"""

PRESENCE_SQL = """
SELECT p.device_id::text,
       max(coalesce(p.last_contact_at,p.last_observed_at)) AS last_contact,
       bool_or(p.reported_online IS TRUE) AS any_reported_online
FROM operations.device_agent_presence_current p
WHERE p.tenant_id=%s AND p.entity_type LIKE 'agent.%%'
GROUP BY p.device_id
"""

ASSOCIATIONS_SQL = """
WITH active AS (
 SELECT f.id, f.tenant_id, f.subject_type, f.subject_id, ft.creates_device_exposure
 FROM operations.findings f JOIN operations.finding_types ft ON ft.id=f.finding_type_id
 WHERE f.tenant_id=%s AND f.status IN ('open','acknowledged','investigating','suppressed','wontfix')
), versions AS (
 SELECT f.id, f.tenant_id, v.id AS version_id
 FROM active f JOIN catalog.software_versions v ON v.version_uuid=f.subject_id
 WHERE f.subject_type='software_version' AND f.creates_device_exposure
 UNION ALL
 SELECT f.id, f.tenant_id, v.id
 FROM active f JOIN catalog.products p ON p.product_uuid=f.subject_id
 JOIN catalog.software_versions v ON v.product_id=p.id
 WHERE f.subject_type='software_product' AND f.creates_device_exposure
)
SELECT DISTINCT f.id::text AS row_id, s.device_id::text,
       'candidate_software_exposure' AS association_kind
FROM versions f JOIN operations.software_installations_current s
 ON s.tenant_id=f.tenant_id AND s.software_version_id=f.version_id
WHERE s.stale_since IS NULL AND s.deleted_at IS NULL
UNION
SELECT DISTINCT f.id::text, s.device_id::text, 'installation_subject'
FROM active f JOIN operations.software_installations_current s
 ON s.tenant_id=f.tenant_id AND s.installation_uuid=f.subject_id
WHERE f.subject_type='software_installation' AND s.deleted_at IS NULL
"""

COLLECTIONS_SQL = """
SELECT DISTINCT ON (source_instance_id,snapshot_scope)
       source_instance_id::text, snapshot_scope, status, is_complete_snapshot,
       expected_rows, written_rows, failed_rows, completed_at, run_started_at
FROM operations.observation_snapshot_runs
WHERE tenant_id=%s
ORDER BY source_instance_id,snapshot_scope,run_started_at DESC,run_id DESC
"""

CONSUMERS_SQL = """
SELECT 'enabled_notification_rules' AS name, count(*) AS count
FROM operations.notification_rules WHERE tenant_id=%s AND enabled
UNION ALL
SELECT 'digest_routes',count(*) FROM operations.notification_routes WHERE tenant_id=%s AND mode='digest'
UNION ALL
SELECT 'pending_source_actions',count(*) FROM operations.source_action_requests
WHERE tenant_id=%s AND status IN ('pending','processing')
"""


def _rows(cur, statement: str, params: tuple, max_rows: int) -> list[dict]:
    cur.execute(statement, params)
    names = [item[0] for item in cur.description]
    rows = cur.fetchmany(max_rows + 1)
    if len(rows) > max_rows:
        raise ValueError("Shadow row limit exceeded; no partial report was produced")
    return [dict(zip(names, row, strict=True)) for row in rows]


def read_snapshot(
    connection,
    tenant_id: int,
    profile: Profile,
    *,
    max_rows: int = 250_000,
    timeout_ms: int = 30_000,
) -> Snapshot:
    if type(tenant_id) is not int or tenant_id <= 0:
        raise ValueError("An explicit positive tenant ID is required")
    if not 1 <= max_rows <= MAX_SHADOW_ROWS or not 1 <= timeout_ms <= MAX_QUERY_TIMEOUT_MS:
        raise ValueError("Invalid shadow query bounds")
    if connection.vendor != "postgresql" or connection.in_atomic_block:
        raise ValueError("Shadow comparison requires PostgreSQL outside an existing transaction")
    with transaction.atomic(using=connection.alias), connection.cursor() as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        cur.execute("SELECT set_config('operations.tenant_id', %s, true)", (str(tenant_id),))
        cur.execute("SELECT set_config('statement_timeout', %s, true)", (str(timeout_ms),))
        cur.execute("SELECT id FROM operations.tenants WHERE id=%s", (tenant_id,))
        if cur.fetchone() is None:
            raise ValueError("Tenant not found")
        cur.execute("SELECT CURRENT_TIMESTAMP")
        now = cur.fetchone()[0]
        registry = _rows(cur, REGISTRY_SQL, (), max_rows)
        findings = _rows(
            cur, FINDINGS_SQL, (profile.identity_member_field, tenant_id, tenant_id), max_rows
        )
        devices = _rows(cur, DEVICES_SQL, (tenant_id,), max_rows)
        presence = _rows(cur, PRESENCE_SQL, (tenant_id,), max_rows)
        associations = _rows(cur, ASSOCIATIONS_SQL, (tenant_id,), max_rows)
        collections = _rows(cur, COLLECTIONS_SQL, (tenant_id,), max_rows)
        consumers = _rows(cur, CONSUMERS_SQL, (tenant_id, tenant_id, tenant_id), max_rows)
        # Even a successful read-only report leaves no transaction state behind.
        transaction.set_rollback(True, using=connection.alias)
    return Snapshot(
        tenant_id, now, registry, findings, devices, presence, associations, collections, consumers
    )
