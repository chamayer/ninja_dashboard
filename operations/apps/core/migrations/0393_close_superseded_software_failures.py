"""Close failed software refreshes that a later successful refresh superseded.

From 0.139.0, failed rows in a registered queue open the stalled-queue health
finding, and the software worker closes a computer's failed entries when a
refresh of it succeeds. Apply that rule once to the entries that failed before
it existed (the 0.138.x duplicate-history failures and one older connection
error), keeping their original error.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
UPDATE ninja_core.software_activity_queue f
   SET status = 'done', completed_at = now(),
       error = 'Superseded by a later successful refresh of this computer. Error was: '
               || COALESCE(f.error, '')
 WHERE f.status = 'failed'
   AND EXISTS (
       SELECT 1 FROM ninja_core.software_activity_queue s
        WHERE s.df = f.df AND s.status = 'done' AND s.error IS NULL
          AND s.completed_at > f.completed_at);
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0392_requeue_failed_software_refreshes"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
