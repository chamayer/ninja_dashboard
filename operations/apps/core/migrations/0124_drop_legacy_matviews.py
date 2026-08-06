"""Migration 0124 — drop the two superseded `_legacy` materialized views (E6).

``operations.device_agent_presence_current_legacy`` and
``operations.source_health_current_legacy`` were left behind when their
non-``_legacy`` replacements landed. Both are dead:

* No Python, template, shell or SQL outside frozen historical migrations
  references either name.
* No database function references them; the refresh coordinator
  ``operations.refresh_derived()`` drives only the current pair.
* ``device_agent_presence_current_legacy`` holds 0 rows and has stopped being
  refreshed. ``source_health_current_legacy`` holds 4 rows against the current
  ``source_health_current``'s 5, so it is both stale and superseded.

The only dependency is between the two themselves —
``source_health_current_legacy`` reads
``device_agent_presence_current_legacy`` — so they are dropped in that order
rather than with CASCADE, which would hide an unexpected third dependent.

A note on how their emptiness was established, because it caught me out first:
``pg_stat_user_tables.n_live_tup`` covers tables only. Joined against
``pg_class`` it silently reports 0 for every view and materialized view, which
made three heavily populated shadow views look empty as well
(``ninja_device_detail_current_shadow`` 5,499 rows,
``ninja_device_health_current_shadow`` 5,499,
``ninja_device_seen_daily_shadow`` 357,669). Those three are *not* dead — they
present ``entity_observation_current`` under legacy Ninja names so readers
survived the snapshot cutover, and retiring them is a reader cutover for
another change. Count a view before calling it empty.

Not reversible: the definitions are recoverable from migration history, but
the contents are not, and nothing reads them.
"""

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
DO $block$
DECLARE
    v_dependents text;
BEGIN
    -- Fail loudly if anything other than the known pair depends on these,
    -- rather than destroying it with CASCADE.
    SELECT string_agg(DISTINCT dependent.relname, ', ')
      INTO v_dependents
      FROM pg_depend d
      JOIN pg_rewrite r ON r.oid = d.objid
      JOIN pg_class dependent ON dependent.oid = r.ev_class
      JOIN pg_class source_rel ON source_rel.oid = d.refobjid
      JOIN pg_namespace nsp ON nsp.oid = source_rel.relnamespace
     WHERE nsp.nspname = 'operations'
       AND source_rel.relname IN ('device_agent_presence_current_legacy',
                                  'source_health_current_legacy')
       AND dependent.relname NOT IN ('device_agent_presence_current_legacy',
                                     'source_health_current_legacy');

    IF v_dependents IS NOT NULL THEN
        RAISE EXCEPTION
            'unexpected dependents on the legacy matviews: %; refusing to drop',
            v_dependents;
    END IF;
END
$block$;

DROP MATERIALIZED VIEW IF EXISTS operations.source_health_current_legacy;
DROP MATERIALIZED VIEW IF EXISTS operations.device_agent_presence_current_legacy;
"""


class Migration(migrations.Migration):
    atomic = True

    dependencies: ClassVar = [
        ("operations", "0123_retire_client_links"),
    ]

    operations: ClassVar = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
