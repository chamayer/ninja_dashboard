"""Source records keep first seen and every withdrawal and return (ADR-0045, PLAN-019 Step 4).

Closed history intervals are purged after 90 days (0074) and daily presence was
dropped (0350). This reuses what already lasts:

* ``source_record_subjects`` (one row per record, never purged) gains
  ``first_seen_at`` with its basis. New records get ``first_observation`` (the
  admission time, set when the writer first inserts the record). Existing
  records get ``retained_history_lower_bound``: the earlier of admission and
  the earliest retained history interval, shown as "at least since".
* ``source_record_subjects.presence`` (present/withdrawn) is recorded by the
  existing change history (0306): only real changes of that column are kept,
  and change history is not purged.

Companion data sets (PLAN-038) are never admitted as source records, so they
are not tracked.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
-- Nullable without a default first: no table rewrite, existing rows stay NULL
-- until the backfill below.
ALTER TABLE operations.source_record_subjects
    ADD COLUMN first_seen_at timestamptz,
    ADD COLUMN first_seen_basis text CHECK (first_seen_basis IN (
        'first_observation', 'retained_history_lower_bound'));

UPDATE operations.source_record_subjects s
   SET first_seen_at = LEAST(s.admitted_at, h.first_from),
       first_seen_basis = 'retained_history_lower_bound'
  FROM (SELECT s2.id, min(h2.effective_from) AS first_from
          FROM operations.source_record_subjects s2
          LEFT JOIN operations.entity_observation_history h2
            ON h2.tenant_id = s2.tenant_id AND h2.source_instance_id = s2.source_instance_id
           AND h2.external_namespace = s2.external_namespace
           AND h2.parent_external_namespace = s2.parent_external_namespace
           AND h2.parent_external_id = s2.parent_external_id
           AND h2.external_id = s2.external_id
         WHERE s2.subject_kind = 'record'
         GROUP BY s2.id) h
 WHERE s.id = h.id;

ALTER TABLE operations.source_record_subjects
    ALTER COLUMN first_seen_at SET DEFAULT now(),
    ALTER COLUMN first_seen_basis SET DEFAULT 'first_observation';

UPDATE operations.change_history_registry
   SET classification = 'covered',
       reason = 'presence (withdrawn and returned) is the ADR-0045 long-term trail',
       recorded_columns = ARRAY['presence']::text[],
       key_columns = ARRAY['id']::text[],
       capture = 'trigger'
 WHERE table_name = 'source_record_subjects';
SELECT operations.enable_change_history('source_record_subjects');
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS record_change ON operations.source_record_subjects;
DROP TABLE IF EXISTS operations.source_record_subjects_change_history;
UPDATE operations.change_history_registry
   SET classification = 'exempt',
       reason = 'admission anchor maintained from observations; observation history is ADR-0045 authority',
       recorded_columns = '{}'::text[], key_columns = '{}'::text[], capture = NULL
 WHERE table_name = 'source_record_subjects';
ALTER TABLE operations.source_record_subjects
    DROP COLUMN first_seen_basis,
    DROP COLUMN first_seen_at;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0403_computer_client_operator_actions"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
