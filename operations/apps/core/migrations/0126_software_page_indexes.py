"""Migration 0126 — indexes for the software page (T1, page load times).

Measured end-to-end against production, logged in over HTTP: `/software/`
took 3.19 s and `/software/products/` 3.54 s. Per-query profiling inside the
container showed 3,524 ms of the 3,954 ms render was SQL, in three queries:

===============================================================  ========
`COUNT(DISTINCT ...) FILTER (WHERE EXISTS (software_decisions))`  1,484 ms
`COUNT(DISTINCT finding_details -> 'canonical_name')`             1,015 ms
new-in-24h installations join                                       718 ms
===============================================================  ========

The first is fixed in `views._software_page_data` by pre-aggregating the
decisions and hash-joining rather than running three correlated subqueries per
title — 1,484 ms to 83 ms. The other two need indexes, added here.

**`idx_sw_install_first_observed`** — the "new in the last 24 hours" panel
filtered `first_observed_at` with no index on it, so it scanned all 481,365
installation rows. Measured 718 ms to 0.18 ms.

**`idx_findings_type_canonical`** — the whitelist-suggestion tile counts
distinct titles across **131,073** findings, half of every finding in the
system. An expression index on the JSON key lets the scan read the index
rather than the heap: 1,015 ms to roughly 273 ms. It does not go lower because
PostgreSQL has no index skip-scan for `DISTINCT`, so all 131,073 entries are
read whichever path is chosen. The remaining cost is a symptom worth its own
look — a finding type that fires 131,073 times is not an actionable queue —
and that is recorded in the backlog rather than papered over here.

Both are created `CONCURRENTLY`, so this migration is non-atomic. `findings`
and `software_installations_current` take continuous ingest writes, and a
plain `CREATE INDEX` holds a lock that blocks them for the duration.
"""

from typing import ClassVar

from django.db import migrations


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction block.
    atomic = False

    dependencies: ClassVar = [
        ("operations", "0125_merge_candidate_open_unique"),
    ]

    operations: ClassVar = [
        migrations.RunSQL(
            sql="""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sw_install_first_observed
                ON operations.software_installations_current
                   (tenant_id, first_observed_at DESC)
                WHERE deleted_at IS NULL;
            """,
            reverse_sql="""
            DROP INDEX CONCURRENTLY IF EXISTS operations.idx_sw_install_first_observed;
            """,
        ),
        migrations.RunSQL(
            sql="""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_findings_type_canonical
                ON operations.findings
                   (tenant_id, finding_type_id, (finding_details -> 'canonical_name'))
                WHERE status IN ('open', 'acknowledged');
            """,
            reverse_sql="""
            DROP INDEX CONCURRENTLY IF EXISTS operations.idx_findings_type_canonical;
            """,
        ),
    ]
