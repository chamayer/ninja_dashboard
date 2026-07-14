"""Migration 0034 — remove cross_client_conflict finding.

The finding was a legacy-AC port; blueprint spec inherited it in §1.7.
Design reality of the ops resolver invalidates the premise:

  * The resolver merges cross-source records with matching hardware
    (serial / vm_uuid / MAC) into ONE canonical device at resolve time.
  * Therefore two devices with the same hostname across different
    clients can ONLY exist if they have different (or unknown) hardware
    IDs — i.e., they are DIFFERENT machines that happen to share a
    generic hostname (`dc`, `sql`, `fileserver`, …).
  * On this fleet: 0 of 1,685 cross-client hostname pairs had hardware
    corroboration. 282 open findings — 100% naming coincidence.

Migration:
  * Resolve every open / acknowledged `cross_client_conflict` finding.
  * Leave the finding_type row in place (deprecated, no emitter). Any
    historical resolved findings remain queryable.
"""

from __future__ import annotations

from django.db import connection, migrations


def resolve_open_findings(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with connection.cursor() as cur:
        cur.execute(
            """
            UPDATE operations.findings f
            SET status = 'resolved', last_seen_at = NOW()
            FROM operations.finding_types ft
            WHERE ft.id = f.finding_type_id
              AND ft.name = 'cross_client_conflict'
              AND f.status IN ('open', 'acknowledged')
            """
        )


def noop_reverse(apps, schema_editor):
    # No reverse — reopening these findings would recreate the noise.
    return


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0033_agent_universe"),
    ]

    operations = [
        migrations.RunPython(resolve_open_findings, noop_reverse),
    ]
