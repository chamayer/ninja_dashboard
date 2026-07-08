"""Migration 0020 — operations.source_run_queue table.

Operator-triggered demand queue for source observation runs.
df = source platform name: 'Ninja', 'SentinelOne', 'ScreenConnect', 'LogMeIn'.
One pending entry per source enforced by partial unique index.
"""

from __future__ import annotations

from django.db import migrations


def create_source_run_queue(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        """
        CREATE TABLE IF NOT EXISTS operations.source_run_queue (
            id           BIGSERIAL    PRIMARY KEY,
            df           TEXT         NOT NULL,
            reason       TEXT         NOT NULL DEFAULT '',
            queued_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
            status       TEXT         NOT NULL DEFAULT 'pending',
            attempts     SMALLINT     NOT NULL DEFAULT 0,
            max_attempts SMALLINT     NOT NULL DEFAULT 3,
            worker_id    TEXT,
            started_at   TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            rows_seen    INTEGER,
            error        TEXT
        );
        """
    )
    schema_editor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_source_run_queue_pending
            ON operations.source_run_queue (df)
            WHERE status = 'pending';
        """
    )
    schema_editor.execute(
        "ALTER TABLE operations.source_run_queue OWNER TO operations_migrate;"
    )
    for role in ("operations_app", "ninja_ingest", "operations_readonly"):
        schema_editor.execute(
            f"GRANT SELECT, INSERT, UPDATE ON operations.source_run_queue TO {role};"
        )
    schema_editor.execute(
        "GRANT USAGE, SELECT ON SEQUENCE operations.source_run_queue_id_seq TO ninja_ingest;"
    )


def drop_source_run_queue(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("DROP TABLE IF EXISTS operations.source_run_queue;")


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0019_identity_candidates"),
    ]

    operations = [
        migrations.RunPython(create_source_run_queue, drop_source_run_queue),
    ]
