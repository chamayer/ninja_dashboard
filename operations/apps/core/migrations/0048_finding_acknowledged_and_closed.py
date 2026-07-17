"""Migration 0048 — Finding.acknowledged_at + Finding.closed_at.

Closes two real observability gaps that had nothing to do with
trend arrows on their own merit:

- `acknowledged_at`: when did an operator first look at this issue?
  Enables MTTA (mean time to acknowledge) reporting.
- `closed_at`: when did this leave the active set? Set on any
  transition to resolved / suppressed / wontfix. Makes as-of
  queries ("was this active on date D") unambiguous instead of
  the fuzzy `resolved_at`-only view.

Backfill: none possible. `Finding` has never carried a
`resolved_at` column (that field belongs to sibling models like
`AdminFinding` — my earlier "backfill from resolved_at" plan
crash-looped Portainer's redeploy of 0.62.0 until this fix
landed). Pre-existing resolved / suppressed / acknowledged rows
therefore keep NULL `closed_at` and NULL `acknowledged_at` —
history from before 0.62.0 is unrecoverable, but new transitions
populate both fields going forward.

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
        migrations.AddIndex(
            model_name="finding",
            index=models.Index(
                fields=("tenant", "closed_at"),
                name="idx_findings_closed_at",
            ),
        ),
    ]
