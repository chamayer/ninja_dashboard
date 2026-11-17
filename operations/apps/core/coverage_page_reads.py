"""Candidate metadata and selected-ID hydration for maintained Coverage reads.

Not enabled in serving requests. Retains the current view and bounded protected
detail readers while replacing fleet source queries with prepared facts.
The caller must establish a repeatable-read snapshot and publication readiness.
"""

import json
from datetime import datetime
from uuid import UUID

from django.db import connection


def metadata(*, days):
    """Read availability and the published filter/card directory together."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('operations.coverage_read_publication')")
        if cursor.fetchone()[0] is None:
            return None
        cursor.execute(
            "SELECT p.metadata FROM operations.coverage_read_publication p "
            "JOIN operations.coverage_read_revision r USING(tenant_id) "
            "WHERE p.tenant_id=operations.current_tenant_id() AND p.revision=r.revision "
            "AND p.expires_at>statement_timestamp() AND p.active_device_days=%s",
            [days],
        )
        row = cursor.fetchone()
    if row is None:
        return None
    value = json.loads(row[0]) if isinstance(row[0], str) else row[0]
    value["clients"] = [(UUID(client_id), slug, name) for client_id, slug, name in value["clients"]]
    if value["requirements_evaluated_at"]:
        value["requirements_evaluated_at"] = datetime.fromisoformat(
            value["requirements_evaluated_at"]
        )
    return value


def page_inputs(device_ids):
    """Decode only selected Computers/cells; never transfer a fleet to Python."""
    ids = list(device_ids)
    results = {}
    with connection.cursor() as cursor:
        for name, original_sql in INPUT_QUERIES.items():
            if name == "observations":
                cursor.execute(OBSERVATION_DETAIL_SQL, [ids])
                results[name] = cursor.fetchall()
                continue
            if name in {"requirements", "computers", "hudu"}:
                sql = original_sql.replace(
                    "WHERE stored.tenant_id = operations.current_tenant_id()",
                    "WHERE stored.tenant_id = operations.current_tenant_id() AND stored.device_id=ANY(%s::uuid[])",
                )
            else:
                sql = original_sql + " AND device_id=ANY(%s::uuid[])"
            cursor.execute(sql, [ids])
            results[name] = cursor.fetchall()
    return results


OBSERVATION_DETAIL_SQL = """
SELECT evidence.device_id, evidence.source_name,
       bool_or(evidence.observation_active),
       max(evidence.observation_last_seen_at) FILTER (WHERE evidence.observation_active),
       max(coalesce(link.missing_since, evidence.observation_last_seen_at))
           FILTER (WHERE NOT evidence.observation_active)
FROM operations.v_device_observation_current evidence
JOIN operations.source_instances source_instance
  ON source_instance.tenant_id=evidence.tenant_id AND source_instance.id=evidence.source_instance_id
-- Only withdrawn observations consume a link timestamp. Keep protected link
-- lookups correlated to those selected records instead of scanning the link
-- population for current observations whose aggregates cannot use the result.
LEFT JOIN LATERAL (
    SELECT link.missing_since FROM operations.v_device_source_link link
    WHERE NOT evidence.observation_active
      AND link.tenant_id=evidence.tenant_id AND link.device_id=evidence.device_id
      AND link.source_id=source_instance.source_id AND link.external_id=evidence.external_id
    OFFSET 0
) link ON TRUE
WHERE evidence.tenant_id=operations.current_tenant_id()
  AND evidence.device_id=ANY(%s::uuid[])
  AND (evidence.entity_type LIKE 'agent.%%' OR evidence.entity_type='vm.guest')
GROUP BY evidence.device_id,evidence.source_name
"""


COMPUTERS = """
WITH computers AS (
 SELECT decoded.* FROM operations.coverage_computer_read_current stored
 CROSS JOIN LATERAL jsonb_to_record(stored.computer) AS decoded(
 id uuid, client_id uuid, slug text, display_name text, hostname text,
 sort_hostname text, os_family text, device_type text, device_role text,
 lifecycle_status text, online boolean, last_contact_at timestamptz,
 s1_exempt boolean, offline_days integer, client_offline_days integer)
 WHERE stored.tenant_id = operations.current_tenant_id()
)
"""

INPUT_QUERIES = {
    "requirements": COMPUTERS
    + """
 SELECT computer.slug, computer.display_name, computer.id, computer.hostname,
        computer.os_family, computer.device_type, cell.platform,
        computer.s1_exempt, cell.requirement_status, false,
        cell.requirements_evaluated_at
 FROM operations.coverage_cell_read_current cell
 JOIN computers computer ON computer.id = cell.device_id
 WHERE cell.tenant_id = operations.current_tenant_id()
   AND cell.requirement_status IS NOT NULL
 ORDER BY computer.display_name, computer.hostname, cell.platform
 """,
    "hudu": """
 SELECT record.* FROM operations.coverage_computer_read_current stored
 CROSS JOIN LATERAL jsonb_to_recordset(coalesce(stored.hudu->'records', '[]')) AS record(
 observation_id uuid, device_id uuid, client_id uuid, hostname text,
 is_archived boolean, has_links boolean)
 WHERE stored.tenant_id = operations.current_tenant_id()
 """,
    "computers": COMPUTERS
    + """
 SELECT id, client_id, slug, display_name, hostname, os_family, device_type,
        device_role, lifecycle_status, s1_exempt, online, last_contact_at,
        client_offline_days
 FROM computers ORDER BY display_name, sort_hostname, id
 """,
    "presence": """
 SELECT device_id, platform, source_online, source_contact_at
 FROM operations.coverage_cell_read_current
 WHERE tenant_id = operations.current_tenant_id() AND source_status IS NOT NULL
 """,
    "observations": """
 SELECT device_id, platform, observation_current, NULL::timestamptz, NULL::timestamptz
 FROM operations.coverage_cell_read_current
 WHERE tenant_id = operations.current_tenant_id() AND observation_current IS NOT NULL
 """,
}
