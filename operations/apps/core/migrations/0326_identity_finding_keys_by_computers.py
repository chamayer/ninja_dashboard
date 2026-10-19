"""Identity findings are keyed by the Computers involved, not by a name (ADR-0034 section 8).

``duplicate_device_records`` and ``identity_conflict`` were keyed by a
hostname, so a rename would have closed a finding and opened a new one. The
producers now build the key from the sorted Computer IDs; this migration
rekeys the open findings in place, keeping their IDs, acknowledgements,
snoozes, assessments and history. A finding whose new key another open
finding already holds keeps its old key; the producer resolves it on its
next run.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
SELECT operations.begin_change(
    'finding.rekey_by_computers',
    'ADR-0034: identity findings are keyed by the Computers involved, not by a name.',
    '{"migration": "0326_identity_finding_keys_by_computers"}'::jsonb,
    'migration', NULL, 'operations.migrations', '0326', NULL, true);

-- duplicate_device_records: ingest.identity.findings._key(tenant, type, client, *ids),
-- sha256 of the parts joined by ':' (64 hex characters).
WITH open_dup AS (
    SELECT f.id, f.tenant_id,
           encode(sha256(convert_to(
               f.tenant_id::text || ':duplicate_device_records:' || f.client_id::text || ':'
               || (SELECT string_agg(m ->> 'device_id', ':' ORDER BY (m ->> 'device_id') COLLATE "C")
                     FROM jsonb_array_elements(f.finding_details -> 'computers') m),
               'UTF8')), 'hex') AS new_key
      FROM operations.findings f
      JOIN operations.finding_types ft ON ft.id = f.finding_type_id
     WHERE ft.name = 'duplicate_device_records'
       AND f.status IN ('open', 'acknowledged', 'investigating', 'suppressed')
       AND f.client_id IS NOT NULL
       AND jsonb_typeof(f.finding_details -> 'computers') = 'array'
), identity AS (
    SELECT f.id, f.tenant_id,
           'identity_conflict:' || md5(f.client_id::text || ':'
               || (SELECT string_agg(v, ',' ORDER BY v COLLATE "C")
                     FROM jsonb_array_elements_text(f.finding_details -> 'candidate_device_ids') v)) AS new_key
      FROM operations.findings f
      JOIN operations.finding_types ft ON ft.id = f.finding_type_id
     WHERE ft.name = 'identity_conflict'
       AND f.status IN ('open', 'acknowledged', 'investigating', 'suppressed')
       AND f.client_id IS NOT NULL
       AND jsonb_typeof(f.finding_details -> 'candidate_device_ids') = 'array'
), rekey AS (
    SELECT * FROM open_dup UNION ALL SELECT * FROM identity
), unique_keys AS (
    -- Two open findings must not end up with one key.
    SELECT r.* FROM rekey r
     WHERE r.new_key IS NOT NULL
       AND (SELECT count(*) FROM rekey o WHERE o.tenant_id = r.tenant_id AND o.new_key = r.new_key) = 1
)
UPDATE operations.findings f
   SET condition_key = u.new_key
  FROM unique_keys u
 WHERE f.id = u.id
   AND f.condition_key IS DISTINCT FROM u.new_key
   AND NOT EXISTS (
       SELECT 1 FROM operations.findings other
        WHERE other.tenant_id = f.tenant_id AND other.id <> f.id
          AND other.condition_key = u.new_key
          AND other.status IN ('open', 'acknowledged', 'investigating', 'suppressed'));
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0325_computer_name_collision_guard"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
