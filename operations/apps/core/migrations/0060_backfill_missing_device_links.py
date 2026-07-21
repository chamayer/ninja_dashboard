"""Migration 0060 — backfill device_links missing due to fast-path bug.

Root cause: `ingest/identity/fast_path.py::resolve_device_fast` was
returning a matched device_id (via serial or hostname) without
creating the corresponding `device_link` row. Result:
`entity_observations` had `device_id` set and derived matviews like
`device_agent_presence_current` showed the source on the device, but
the `device_links` table (which powers the Device Detail "Source
identities" panel and other consumers) was missing the row entirely.

At the time of the fix (0.75.1), 21 devices were affected — visible
on device detail as "presence but no source identity". Field example:
cl-15 in Chartwell Pharma showed SentinelOne presence + no
SentinelOne source identity.

The code fix in `fast_path.py` upserts the link at match time so no
new missing rows accumulate. This migration backfills the existing
gap by deriving the missing links from `entity_observations`.

**Backfill logic:** for every (tenant, device_id, source, external_id)
tuple that appears in `entity_observations` with `device_id IS NOT NULL`
and has no matching `device_links` row, insert one with
`match_method='fast_path_backfill'`, confidence 0.900, and
first/last_seen derived from the observations. Idempotent — safe to
re-run.
"""

from __future__ import annotations

from django.db import migrations


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
      AND eo.entity_type <> 'org'
    GROUP BY eo.tenant_id, eo.device_id, s.id, eo.entity_key
) sub
WHERE NOT EXISTS (
    SELECT 1 FROM operations.device_links dl
    WHERE dl.tenant_id  = sub.tenant_id
      AND dl.source_id  = sub.source_id
      AND dl.external_id = sub.external_id
);
"""

# Reverse deletes only backfill-created rows (identified by
# match_method='fast_path_backfill'). Preserves any downgrade
# hand-tracking.
_REVERSE_SQL = """
DELETE FROM operations.device_links
 WHERE match_method = 'fast_path_backfill';
"""


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0059_grant_ninja_patches_select"),
    ]

    operations = [
        migrations.RunSQL(_BACKFILL_SQL, _REVERSE_SQL),
    ]
