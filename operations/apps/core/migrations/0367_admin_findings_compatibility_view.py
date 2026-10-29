"""Admin findings are read from the common ledger (PLAN-003 M4, part 1).

Part of the coordinated M2-M4 artifact.

* The old table is renamed ``admin_findings_legacy`` and kept read-only as the
  retained pre-conversion ledger; its change history stays in
  ``admin_findings_change_history``.
* ``admin_findings`` becomes a read-only, tenant-scoped view over the
  admin-namespace findings with the old columns in the old order. The subject
  reference is the original one (``legacy_ref``), so existing readers see the
  same values.
* ``v_issue_findings`` reads one ledger. Rows keep their old values: admin rows
  still expose no subject or client, so no page changes population or display
  in this release.
* The ``AdminFinding`` model becomes unmanaged; writers use ``findings``.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
ALTER TABLE operations.admin_findings RENAME TO admin_findings_legacy;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.admin_findings_legacy
    FROM operations_app, ninja_ingest, operations_readonly;
INSERT INTO operations.change_history_registry (
    table_name, classification, reason, recorded_columns, secret_columns, key_columns,
    computer_column, computer_condition_column, computer_condition_value, client_column,
    is_global, capture)
VALUES ('admin_findings_legacy', 'exempt',
        'pre-conversion admin ledger, retained read-only; rows live in findings',
        '{}'::text[], '{}'::text[], '{}'::text[], NULL, NULL, NULL, NULL, FALSE, NULL)
ON CONFLICT (table_name) DO NOTHING;

CREATE VIEW operations.admin_findings
WITH (security_barrier = true, security_invoker = true) AS
SELECT f.version,
       f.id,
       f.condition_key,
       f.severity,
       f.status,
       coalesce(f.subject_ref -> 'legacy_ref', f.subject_ref) AS subject_ref,
       f.finding_details AS details,
       f.first_seen_at AS first_detected_at,
       coalesce(f.last_detected_at, f.last_seen_at) AS last_detected_at,
       f.closed_at AS resolved_at,
       f.finding_type_id,
       f.tenant_id
  FROM operations.findings f
 WHERE f.condition_namespace = 'admin';
REVOKE ALL ON operations.admin_findings FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.admin_findings
    FROM operations_app, operations_readonly, ninja_ingest;
GRANT SELECT ON operations.admin_findings TO operations_app, operations_readonly, ninja_ingest;

CREATE OR REPLACE VIEW operations.v_issue_findings
WITH (security_barrier = true, security_invoker = true) AS
SELECT finding.condition_namespace::text AS row_kind,
       finding.id,
       finding.tenant_id,
       finding.finding_type_id,
       finding_type.name AS finding_type_name,
       finding.condition_key,
       finding.severity,
       finding.status,
       CASE WHEN finding.condition_namespace = 'entity' THEN finding.subject_type END::varchar
           AS subject_type,
       CASE WHEN finding.condition_namespace = 'entity' THEN finding.subject_id END
           AS subject_id,
       CASE WHEN finding.condition_namespace = 'entity' THEN finding.client_id END
           AS client_id,
       finding.finding_details AS details,
       finding.first_seen_at AS first_detected_at,
       CASE WHEN finding.condition_namespace = 'entity' THEN finding.last_seen_at
            ELSE coalesce(finding.last_detected_at, finding.last_seen_at) END
           AS last_detected_at,
       finding.closed_at AS resolved_at
  FROM operations.findings finding
  JOIN operations.finding_types finding_type ON finding_type.id = finding.finding_type_id;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.v_issue_findings
    FROM operations_app, operations_readonly, ninja_ingest;
"""

REVERSE_SQL = r"""
CREATE OR REPLACE VIEW operations.v_issue_findings
WITH (security_barrier = true, security_invoker = true) AS
SELECT 'entity'::text AS row_kind,
       finding.id, finding.tenant_id, finding.finding_type_id,
       finding_type.name AS finding_type_name, finding.condition_key, finding.severity,
       finding.status, finding.subject_type, finding.subject_id, finding.client_id,
       finding.finding_details AS details, finding.first_seen_at AS first_detected_at,
       finding.last_seen_at AS last_detected_at, finding.closed_at AS resolved_at
  FROM operations.findings finding
  JOIN operations.finding_types finding_type ON finding_type.id = finding.finding_type_id
 WHERE finding.condition_namespace = 'entity'
UNION ALL
SELECT 'admin'::text, finding.id, finding.tenant_id, finding.finding_type_id,
       finding_type.name, finding.condition_key, finding.severity, finding.status,
       NULL::text, NULL::uuid, NULL::uuid, finding.details, finding.first_detected_at,
       finding.last_detected_at, finding.resolved_at
  FROM operations.admin_findings_legacy finding
  JOIN operations.finding_types finding_type ON finding_type.id = finding.finding_type_id;
DROP VIEW IF EXISTS operations.admin_findings;
DELETE FROM operations.change_history_registry WHERE table_name = 'admin_findings_legacy';
ALTER TABLE operations.admin_findings_legacy RENAME TO admin_findings;
GRANT INSERT, UPDATE, DELETE ON operations.admin_findings TO operations_app, ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0366_finding_cover_rules"),
    ]

    operations: ClassVar[list] = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)],
            state_operations=[
                migrations.AlterModelOptions(name="adminfinding", options={"managed": False}),
            ],
        ),
    ]
