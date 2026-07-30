"""Finding types produced by CMDB sources (Hudu today).

Named for the source class rather than the vendor, matching `cmdb.asset` and
the `cmdb` source kind: a second CMDB reuses these without a migration.

* ``cmdb_asset_stale`` — the CMDB page carries links to a managing source
  (Ninja), and none of them resolve any more. Either the machine was retired
  and the page should be archived, or the machine vanished from the managing
  source unexpectedly. 430 at time of writing.
* ``cmdb_link_incorrect`` — the page is linked to two machines that are
  demonstrably different hardware (different serials). Observed cause is the
  CMDB's own integration matching on a name prefix: `ADH-READY17` picked up
  both `adh-ready17` and `adh-ready1`. 37 at time of writing.
* ``duplicate_device_records`` — the page links to two Operations devices
  sharing one hostname, one with a serial and one without. Not a CMDB defect:
  Operations holds two records for one machine and the CMDB merely made it
  visible. `operations.merge_candidates` is empty and unpopulated, so nothing
  else surfaces this. 25 at time of writing.
* ``unintegrated_source_observed`` — an aggregator relays records from a
  vendor Operations does not ingest directly. Kept deliberately generic: it is
  a detector for *future* second-hand sources, not a note about Auvik. Its
  condition key includes the vendor name so each one raises separately.

`id` is a plain smallint with no sequence, so ids are assigned from MAX+1.
Insert is guarded by NOT EXISTS on name, making this safely re-runnable.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
INSERT INTO operations.finding_types
    (id, name, default_severity, runbook_path, description,
     finding_class, source_module, auto_resolvable, category_id)
SELECT (SELECT COALESCE(MAX(id), 0) FROM operations.finding_types)
           + row_number() OVER (ORDER BY v.name),
       v.name, v.severity, '', v.description,
       'entity', 'cmdb.evaluator', TRUE, fc.id
  FROM (VALUES
    ('cmdb_asset_stale', 'low', 'data_quality',
     'A CMDB page links to a managing source, but none of those links resolve '
     'any more. Archive the page, or investigate why the machine left the '
     'managing source.'),
    ('cmdb_link_incorrect', 'medium', 'data_quality',
     'A CMDB page is linked to two machines with different serials. One link '
     'is wrong -- typically the CMDB integration matched on a name prefix. '
     'Unlink the incorrect one in the CMDB.'),
    ('duplicate_device_records', 'medium', 'identity',
     'Two Operations device records share one hostname and appear to be the '
     'same machine. Not a CMDB fault -- the CMDB linked to both because both '
     'exist. Merge them.'),
    ('unintegrated_source_observed', 'info', 'platform_health',
     'An aggregator relays records from a vendor Operations does not ingest '
     'directly. That data is second-hand and only as complete as the '
     'aggregator syncs. Consider integrating the vendor directly.')
  ) AS v(name, severity, category, description)
  JOIN operations.finding_categories fc ON fc.name = v.category
 WHERE NOT EXISTS (
     SELECT 1 FROM operations.finding_types ft WHERE ft.name = v.name
 );
"""

REVERSE_SQL = """
DELETE FROM operations.finding_types
 WHERE name IN ('cmdb_asset_stale', 'cmdb_link_incorrect',
                'duplicate_device_records', 'unintegrated_source_observed');
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0090_device_fk_indexes_and_cmdb_source_kind"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
