"""Index observation history by record identity (ADR-0034 section 4, tier 4).

Name matching's record-history tier and the naming function's ``stable_os``
rule look up the history of specific records by (source instance, external
id). Without this index each lookup scanned the history table (measured
2026-10-19: about 582,000 rows). Built concurrently so collection keeps
writing; the migration is therefore not atomic.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


class Migration(migrations.Migration):
    atomic = False

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0326_identity_finding_keys_by_computers"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_obs_hist_record_identity "
            "ON operations.entity_observation_history (tenant_id, source_instance_id, external_id)",
            "DROP INDEX CONCURRENTLY IF EXISTS operations.idx_obs_hist_record_identity",
        ),
    ]
