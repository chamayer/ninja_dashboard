"""Match requirement episodes at their full tenant/entity/platform/key identity.

Preserve raw drift and existing cover semantics. No historical finding is
rewritten or closed by this migration. The evaluator repairs through normal
scoped evaluation; deployment and recalculation need separate approval.
"""

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION operations.device_requirement_state_disagreements(p_tenant bigint)
RETURNS TABLE (device_id uuid, entity_type text, platform text, disagreement text,
               verdict text, finding_id uuid, finding_type text)
LANGUAGE sql STABLE
SET search_path = pg_catalog, operations
AS $fn$
    WITH active AS (
        SELECT f.id, f.subject_id AS device_id,
               COALESCE(f.finding_details->>'entity_type', '') AS entity_type,
               COALESCE(f.finding_details->>'platform', '') AS platform,
               t.name::text AS finding_type, f.condition_key,
               CASE t.name WHEN 'missing_required_platform' THEN 'missing' ELSE 'stale' END
                   AS expected_verdict,
               COALESCE(fs.attention = 'covered', false) AS covered
          FROM operations.findings f
          JOIN operations.finding_types t ON t.id = f.finding_type_id
          LEFT JOIN operations.finding_state fs
            ON fs.finding_id = f.id AND fs.tenant_id = f.tenant_id
         WHERE f.tenant_id = p_tenant
           AND f.subject_type = 'device'
           AND t.name IN ('missing_required_platform', 'stale_required_platform')
           AND f.status IN ('open', 'acknowledged', 'investigating', 'suppressed')
    )
    SELECT s.device_id, s.entity_type::text, s.platform::text,
           s.verdict || '_without_finding', s.verdict, NULL::uuid, NULL::text
      FROM operations.device_requirement_state s
     WHERE s.tenant_id = p_tenant
       AND s.verdict IN ('missing', 'stale')
       AND NOT EXISTS (SELECT 1 FROM active a
                        WHERE a.device_id = s.device_id AND a.entity_type = s.entity_type
                          AND a.platform = s.platform AND a.condition_key = s.condition_key
                          AND a.expected_verdict = s.verdict)
    UNION ALL
    SELECT a.device_id, COALESCE(NULLIF(a.entity_type, ''), s.entity_type::text, ''),
           a.platform, 'finding_without_verdict', s.verdict, a.id, a.finding_type
      FROM active a
      LEFT JOIN operations.device_requirement_state s
        ON s.tenant_id = p_tenant AND s.device_id = a.device_id AND s.entity_type = a.entity_type
         AND s.platform = a.platform
     WHERE (s.verdict IS DISTINCT FROM a.expected_verdict
            OR (s.verdict IN ('missing', 'stale')
                AND s.condition_key IS DISTINCT FROM a.condition_key))
       -- A requirement that stopped applying keeps its finding, covered.
       AND NOT (a.covered AND COALESCE(s.verdict IN ('os_unknown', 'pending_cleanup'), false))
$fn$;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [("operations", "0355_entity_candidate_withdrawal")]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
