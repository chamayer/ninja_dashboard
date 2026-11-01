"""Recorded outcomes of the association reassessment (user decision 2026-11-01).

Every reassessment row that does not simply re-attach the same way gets one
durable disposition with its class and reason, so nothing is left for row-by-row
review: ``keep`` (nothing strong contradicts the attachment, design §5
continuity), ``move`` (a corroborated serial/VM UUID points to exactly one other
Computer; applied through ``set_source_association`` and undoable from the
source-record page) or ``identity_review`` (left to the standing identity rule).
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE TABLE operations.source_record_dispositions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id bigint NOT NULL REFERENCES operations.tenants (id),
    run_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    outcome text NOT NULL CHECK (outcome IN ('keep', 'move', 'identity_review')),
    disposition_class text NOT NULL,
    reason text NOT NULL CHECK (reason > ''),
    previous_device_id uuid,
    proposed_device_id uuid,
    applied boolean NOT NULL DEFAULT false,
    undone_at timestamptz,
    undone_by_id bigint,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    decided_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, run_id, subject_id),
    FOREIGN KEY (tenant_id, subject_id)
        REFERENCES operations.source_record_subjects (tenant_id, id)
);
CREATE INDEX idx_source_record_dispositions_subject
    ON operations.source_record_dispositions (tenant_id, subject_id);
ALTER TABLE operations.source_record_dispositions ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.source_record_dispositions FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.source_record_dispositions
    USING (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint)
    WITH CHECK (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint);
REVOKE ALL ON operations.source_record_dispositions FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.source_record_dispositions
    FROM operations_app, ninja_ingest, operations_readonly;
GRANT SELECT ON operations.source_record_dispositions
    TO operations_app, operations_readonly, ninja_ingest;
GRANT UPDATE (undone_at, undone_by_id) ON operations.source_record_dispositions
    TO operations_app;
INSERT INTO operations.change_history_registry (
    table_name, classification, reason, recorded_columns, secret_columns, key_columns,
    computer_column, computer_condition_column, computer_condition_value, client_column,
    is_global, capture
) VALUES ('source_record_dispositions', 'covered', 'platform or operator decision or state',
          ARRAY['id', 'outcome', 'disposition_class', 'reason', 'applied', 'undone_at',
                'undone_by_id']::text[], '{}'::text[], ARRAY['id']::text[],
          NULL, NULL, NULL, NULL, FALSE, 'trigger')
ON CONFLICT (table_name) DO NOTHING;
SELECT operations.enable_change_history('source_record_dispositions');
"""

REVERSE_SQL = r"""
DROP TABLE IF EXISTS operations.source_record_dispositions_change_history;
DELETE FROM operations.change_history_registry WHERE table_name = 'source_record_dispositions';
DROP TABLE IF EXISTS operations.source_record_dispositions;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0390_source_record_cleanup"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
