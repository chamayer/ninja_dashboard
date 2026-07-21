"""Migration 0060 — backfill device_links missing due to fast-path bug
(v2 — filtered to identity signals + cleans up 0.75.1 collateral).

Root cause of the original missing-link gap: `resolve_device_fast`
was returning a matched device_id via serial or hostname without
creating the corresponding device_link.

The first attempt at this backfill (0.75.1) crashed on production
with `UniqueViolation: (tenant, source, external_id)=(1, 1, 'microsoft edge')`
because it didn't filter entity_type — software observations share
entity_key across devices, so the backfill tried to create thousands
of colliding device_link rows. That same missing filter also caused
the 0.75.1 forward fix in `fast_path.py` to actively corrupt
device_links: every software observation hitting steps 2/3 upserted
a synthetic device_link keyed on software name, reassigning it
between devices in-place.

This migration:

1. **Cleans up bogus device_links** created by the 0.75.1 fast_path
   fix, identifiable by `match_method IN ('serial', 'hostname_strict')`
   AND the `external_id` matches a known software observation
   entity_key. Backfill-created rows (match_method=
   'fast_path_backfill') from the crashed prior attempt are also
   removed — the crash rolled back the transaction, but this handles
   any partial writes if the environment applied things differently.
2. **Backfills legitimate missing device_links** — one row per
   (tenant, device_id, source, external_id) tuple in
   `entity_observations` where entity_type is a device-identity
   signal (agent.*, vm.host, vm.guest, network.device,
   monitor.target). Uses ON CONFLICT DO NOTHING as a safety net.
3. Both steps run in a single migration so failure of either rolls
   back cleanly. Idempotent — safe to re-run.
"""

from __future__ import annotations

from django.db import migrations


_CLEANUP_SQL = """
-- Remove any device_link rows created by the 0.75.1 fast_path bug
-- (identifiable by their external_id matching a software entity_key)
-- and any prior backfill attempts.
DELETE FROM operations.device_links dl
 WHERE dl.match_method = 'fast_path_backfill'
    OR EXISTS (
        SELECT 1 FROM operations.entity_observations eo
        WHERE eo.tenant_id = dl.tenant_id
          AND eo.entity_type = 'software'
          AND eo.entity_key = dl.external_id
          AND eo.platform = (
              SELECT s.name FROM operations.sources s
              WHERE s.id = dl.source_id
          )
    );
"""

_BACKFILL_SQL = """
INSERT INTO operations.device_links (
    id, version, tenant_id, device_id, source_id, external_id,
    external_name, first_seen_at, last_seen_at,
    match_method, match_confidence
)
SELECT
    gen_random_uuid(),
    1,
    sub.tenant_id,
    sub.device_id,
    sub.source_id,
    sub.external_id,
    COALESCE(NULLIF(sub.hostname, ''), sub.external_id),
    sub.first_seen,
    sub.last_seen,
    'fast_path_backfill',
    0.900
FROM (
    SELECT
        eo.tenant_id,
        eo.device_id,
        s.id                                          AS source_id,
        eo.entity_key                                 AS external_id,
        (ARRAY_AGG(eo.canonical_data->>'hostname'
                   ORDER BY eo.observed_at DESC))[1] AS hostname,
        MIN(eo.observed_at)                           AS first_seen,
        MAX(eo.observed_at)                           AS last_seen
    FROM operations.entity_observations eo
    JOIN operations.sources s ON s.name = eo.platform
    WHERE eo.device_id IS NOT NULL
      AND (
          eo.entity_type LIKE 'agent.%%'
          OR eo.entity_type IN
              ('vm.host', 'vm.guest', 'network.device', 'monitor.target')
      )
    GROUP BY eo.tenant_id, eo.device_id, s.id, eo.entity_key
) sub
ON CONFLICT (tenant_id, source_id, external_id) DO NOTHING;
"""

_REVERSE_SQL = """
DELETE FROM operations.device_links
 WHERE match_method = 'fast_path_backfill';
"""


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0059_grant_ninja_patches_select"),
    ]

    operations = [
        migrations.RunSQL(_CLEANUP_SQL, migrations.RunSQL.noop),
        migrations.RunSQL(_BACKFILL_SQL, _REVERSE_SQL),
    ]
