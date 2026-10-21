"""Requirements apply only to known, live Computers (PLAN-014, ADR-0036).

The coverage pass now applies an agent requirement only when the Computer's
operating system is known and supported, and never to a Computer in
``pending_cleanup``. This migration supports that change:

* the verdicts ``os_unknown`` and ``pending_cleanup`` replace
  ``not_evaluated``. Existing rows are relabelled here, and the next coverage
  pass rewrites them all;
* missing and stale findings that stop applying are covered, not closed.
  ``missing_required_platform`` gains ``device_offline`` (stale already has
  it), and both gain ``os_unknown_coverage``. Cover is live, so a finding
  uncovers when the Computer returns or its operating system becomes known;
* ``os_unknown_coverage`` is reworded: requirements are not applied, rather
  than not evaluated;
* the drift check treats a covered finding next to an ``os_unknown`` or
  ``pending_cleanup`` verdict as agreement.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
ALTER TABLE operations.device_requirement_state
    DROP CONSTRAINT device_requirement_state_verdict_check;
UPDATE operations.device_requirement_state
   SET verdict = 'os_unknown'
 WHERE verdict = 'not_evaluated';
ALTER TABLE operations.device_requirement_state
    ADD CONSTRAINT device_requirement_state_verdict_check CHECK (verdict IN (
        'satisfied', 'missing', 'stale', 'exempt', 'outside_coverage',
        'os_unknown', 'pending_cleanup'));

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
               t.name::text AS finding_type,
               CASE t.name WHEN 'missing_required_platform' THEN 'missing' ELSE 'stale' END
                   AS expected_verdict,
               COALESCE(fs.attention = 'covered', false) AS covered
          FROM operations.findings f
          JOIN operations.finding_types t ON t.id = f.finding_type_id
          LEFT JOIN operations.finding_state fs ON fs.finding_id = f.id
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
                        WHERE a.device_id = s.device_id AND a.platform = s.platform
                          AND a.expected_verdict = s.verdict)
    UNION ALL
    SELECT a.device_id, COALESCE(NULLIF(a.entity_type, ''), s.entity_type::text, ''),
           a.platform, 'finding_without_verdict', s.verdict, a.id, a.finding_type
      FROM active a
      LEFT JOIN operations.device_requirement_state s
        ON s.tenant_id = p_tenant AND s.device_id = a.device_id AND s.platform = a.platform
     WHERE s.verdict IS DISTINCT FROM a.expected_verdict
       -- A requirement that stopped applying keeps its finding, covered.
       AND NOT (a.covered AND s.verdict IN ('os_unknown', 'pending_cleanup'))
$fn$;

SELECT operations.begin_change(
    'finding_type.cover',
    'PLAN-014: agent requirements apply only to known, live Computers; findings that stop applying are covered.',
    '{"migration": "0333_requirement_applicability"}'::jsonb,
    'migration', NULL, 'operations.migrations', '0333', NULL, true);

UPDATE operations.finding_types
   SET covered_by = '["device_offline", "device_missing_from_source", "os_unknown_coverage"]'::jsonb,
       cover_note = 'A required agent is not checked on a computer that is offline, that no source reports, or whose operating system is unknown.'
 WHERE name = 'missing_required_platform';
UPDATE operations.finding_types
   SET covered_by = '["device_offline", "device_missing_from_source", "os_unknown_coverage"]'::jsonb,
       cover_note = 'A stale agent is expected on a computer that is offline or that no source reports, and is not checked when its operating system is unknown.'
 WHERE name = 'stale_required_platform';
UPDATE operations.finding_types
   SET display_name = 'Operating system unknown: agent requirements not applied',
       description = 'No source reports an operating system for this Computer, so agent requirements limited to particular operating systems are not applied. Get the operating system reported to restore coverage checks.'
 WHERE name = 'os_unknown_coverage';

SELECT set_config('operations.tenant_id', '1', TRUE);
SELECT operations.refresh_finding_state((
    SELECT array_agg(f.id)
      FROM operations.findings f
      JOIN operations.finding_types ft ON ft.id = f.finding_type_id
     WHERE ft.name IN ('missing_required_platform', 'stale_required_platform')
       AND f.status IN ('open', 'acknowledged', 'investigating')));
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0332_device_requirement_state"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
