"""Migration 0048 — Finding.acknowledged_at + Finding.closed_at.

Closes two real observability gaps that had nothing to do with
trend arrows on their own merit:

- `acknowledged_at`: when did an operator first look at this issue?
  Enables MTTA (mean time to acknowledge) reporting.
- `closed_at`: when did this leave the active set? Set on any
  transition to resolved / suppressed / wontfix. Makes as-of
  queries ("was this active on date D") unambiguous instead of
  the fuzzy `resolved_at`-only view.

Backfill: `closed_at = resolved_at` where resolved_at was set on
existing rows. Pre-existing acks are unrecoverable — those rows
keep NULL acknowledged_at.

Wave UI-2 follow-up (G2.1) — trend matview (G2.2) reads these.
"""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0047_rename_agent_presence_current"),
    ]

    operations = [
        migrations.AddField(
            model_name="finding",
            name="acknowledged_at",
            field=models.DateTimeField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="finding",
            name="closed_at",
            field=models.DateTimeField(null=True, blank=True),
        ),
        migrations.RunSQL(
            # Backfill closed_at for any row that already has
            # resolved_at — best signal we have for historical
            # close time. Non-destructive.
            sql=(
                "UPDATE operations.findings "
                "SET closed_at = resolved_at "
                "WHERE resolved_at IS NOT NULL AND closed_at IS NULL;"
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AddIndex(
            model_name="finding",
            index=models.Index(
                fields=("tenant", "closed_at"),
                name="idx_findings_closed_at",
            ),
        ),
    ]
