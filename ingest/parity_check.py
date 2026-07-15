"""Legacy vs new parity check — Track 6 cutover gate.

Compares `ninja_agent_compliance.compliance_findings` (legacy AC) to
`operations.findings` for the same tenant. Writes per-finding-type
counts into `operations.parity_report` for a daily audit trail; the
Health page card reads the latest run.

BLUEPRINT §6 gate: 1 week of green parity reports before the operator
runs the schema-drop migration.

Report shape per row:
    (tenant, run_at, finding_type, scope_client, legacy_count,
     ops_count, delta, note)
Where delta = ops_count - legacy_count. Negative = ops missing
findings vs legacy; positive = ops emitting extras.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ingest import db

log = logging.getLogger(__name__)

_TENANT_ID = 1


# Legacy AC finding_type → operations FindingType.name.
# When a legacy type has no ops equivalent (superseded / dropped),
# map to None so we still record the legacy count for visibility.
_TYPE_MAP: dict[str, str | None] = {
    "missing_required_platform":  "missing_required_platform",
    "stale_required_platform":    "stale_required_platform",
    "cross_customer_conflict":    None,  # cross_client_conflict retired
    "source_failure":             "source_failure",
    "no_recent_data":             "device_stale_data",
    "device_offline":             "device_offline",
    "duplicate_device":           "duplicate_platform_record",
}


def run(tenant_id: int = _TENANT_ID) -> int:
    """Compute + persist a parity snapshot. Returns rows written."""
    now = datetime.now(timezone.utc)
    written = 0
    try:
        with db.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(f"SET LOCAL operations.tenant_id = {tenant_id}")

            # Legacy: is the schema even here?
            cur.execute(
                "SELECT to_regclass('ninja_agent_compliance.compliance_findings')"
            )
            (legacy_present,) = cur.fetchone()
            if not legacy_present:
                log.info("parity_check: legacy schema absent — nothing to compare")
                return 0

            cur.execute(
                """
                SELECT finding_type, client_id, COUNT(*)
                FROM ninja_agent_compliance.compliance_findings
                WHERE status = 'active'
                GROUP BY finding_type, client_id
                """
            )
            legacy_rows = cur.fetchall()

            # Map legacy client_id → operations client uuid via display_name.
            cur.execute(
                """
                SELECT lc.client_id, oc.id
                FROM ninja_agent_compliance.clients lc
                LEFT JOIN operations.clients oc
                  ON oc.tenant_id = 1
                 AND oc.display_name = lc.client_name
                 AND oc.deleted_at IS NULL
                """
            )
            legacy_to_ops_client = {row[0]: row[1] for row in cur.fetchall()}

            # Ops counts per (finding_type_name, client_id).
            cur.execute(
                """
                SELECT ft.name, f.client_id, COUNT(*)
                FROM operations.findings f
                JOIN operations.finding_types ft ON ft.id = f.finding_type_id
                WHERE f.tenant_id = %s AND f.status IN ('open', 'acknowledged')
                GROUP BY ft.name, f.client_id
                """,
                (tenant_id,),
            )
            ops_by_key: dict[tuple[str, str], int] = {}
            for name, client_id, count in cur.fetchall():
                ops_by_key[(name, str(client_id) if client_id else "")] = count

            for legacy_type, legacy_client_id, legacy_count in legacy_rows:
                ops_type = _TYPE_MAP.get(legacy_type)
                ops_client_id = legacy_to_ops_client.get(legacy_client_id)
                ops_key = (
                    (ops_type or "", str(ops_client_id) if ops_client_id else "")
                )
                ops_count = ops_by_key.pop(ops_key, 0) if ops_type else 0
                delta = ops_count - legacy_count
                note = ""
                if ops_type is None:
                    note = "legacy-only type (superseded / dropped in ops)"
                cur.execute(
                    """
                    INSERT INTO operations.parity_report
                        (tenant_id, run_at, finding_type, scope_client,
                         legacy_count, ops_count, delta, note)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        tenant_id, now,
                        ops_type or f"legacy:{legacy_type}",
                        ops_client_id, legacy_count, ops_count, delta, note,
                    ),
                )
                written += 1

            # Remaining ops-only counts: emit them so the operator sees
            # findings the new pipeline generates that legacy doesn't.
            for (ft_name, client_str), ops_count in ops_by_key.items():
                cur.execute(
                    """
                    INSERT INTO operations.parity_report
                        (tenant_id, run_at, finding_type, scope_client,
                         legacy_count, ops_count, delta, note)
                    VALUES (%s, %s, %s, %s, 0, %s, %s, %s)
                    """,
                    (
                        tenant_id, now, ft_name,
                        client_str or None, ops_count, ops_count,
                        "ops-only type (no legacy equivalent)",
                    ),
                )
                written += 1

            cur.execute(
                """
                INSERT INTO operations.run_log
                    (id, tenant_id, kind, subject_ref, started_at,
                     ended_at, ok, rows, error)
                VALUES (gen_random_uuid(), %s, 'parity_check',
                        '{}'::jsonb, %s, NOW(), TRUE, %s, '')
                """,
                (tenant_id, now, written),
            )
    except Exception:
        log.exception("parity_check failed")
        raise
    log.info("parity_check: wrote %d rows", written)
    return written
