"""Track A lifecycle-evidence policy, audit grants, and finding types.

The registry tables and ``sources.entity_type`` column were created as raw SQL
in migration 0092. This migration brings them into Django's state without
recreating them, then adds the one fail-closed lifecycle capability required by
the evaluator. Every row remains at the safe default ``none``; a later,
separately approved activation migration seeds active policy. Runtime policy
editing remains disabled: application roles can read the registries but cannot
mutate them.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations, models

FORWARD_SQL = """
ALTER TABLE operations.entity_types
    ADD COLUMN IF NOT EXISTS lifecycle_evidence_mode varchar(32)
    NOT NULL DEFAULT 'none';

ALTER TABLE operations.entity_types
    DROP CONSTRAINT IF EXISTS ck_entity_types_lifecycle_evidence_mode;
ALTER TABLE operations.entity_types
    ADD CONSTRAINT ck_entity_types_lifecycle_evidence_mode
    CHECK (lifecycle_evidence_mode IN (
        'none', 'direct_contact', 'reported_state', 'direct_then_reported_state'
    ));

REVOKE INSERT, UPDATE, DELETE ON operations.entity_types, operations.platform_aliases
    FROM operations_app;

REVOKE UPDATE, DELETE ON operations.audit_log FROM operations_app;
GRANT SELECT, INSERT ON operations.audit_log TO operations_app;
GRANT INSERT ON operations.audit_log TO ninja_ingest;

INSERT INTO operations.finding_types
    (id, name, default_severity, runbook_path, description,
     finding_class, source_module, auto_resolvable, category_id)
SELECT (SELECT COALESCE(MAX(id), 0) FROM operations.finding_types)
           + row_number() OVER (ORDER BY v.name),
       v.name, v.severity, '', v.description,
       'entity', 'ingest.evaluator', TRUE, fc.id
  FROM (VALUES
    ('lifecycle_unknown_reported_state', 'medium',
     'A lifecycle-capable source reported an unrecognized power or online state. '
     'The evaluator left that evidence out of lifecycle selection until its mapping is reviewed.'),
    ('lifecycle_reported_state_conflict', 'medium',
     'Equally recent reported lifecycle states disagree. The evaluator left the device lifecycle unchanged until a newer or higher-fidelity observation resolves the conflict.')
  ) AS v(name, severity, description)
  JOIN operations.finding_categories fc ON fc.name = 'data_quality'
 WHERE NOT EXISTS (
     SELECT 1 FROM operations.finding_types ft WHERE ft.name = v.name
 );
"""

REVERSE_SQL = """
DELETE FROM operations.finding_types ft
 WHERE ft.name IN (
    'lifecycle_unknown_reported_state',
    'lifecycle_reported_state_conflict'
 )
   AND NOT EXISTS (
       SELECT 1
         FROM operations.findings f
        WHERE f.finding_type_id = ft.id
   );

REVOKE INSERT ON operations.audit_log FROM ninja_ingest;
REVOKE SELECT, INSERT ON operations.audit_log FROM operations_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON operations.audit_log TO operations_app;

GRANT SELECT, INSERT, UPDATE, DELETE
    ON operations.entity_types, operations.platform_aliases TO operations_app;

ALTER TABLE operations.entity_types
    DROP CONSTRAINT IF EXISTS ck_entity_types_lifecycle_evidence_mode;
ALTER TABLE operations.entity_types
    DROP COLUMN IF EXISTS lifecycle_evidence_mode;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0092_entity_types_platform_aliases_source_entity_type"),
    ]

    operations: ClassVar[list] = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)],
            state_operations=[
                migrations.CreateModel(
                    name="EntityType",
                    fields=[
                        (
                            "name",
                            models.CharField(max_length=80, primary_key=True, serialize=False),
                        ),
                        ("is_identity_signal", models.BooleanField(default=False)),
                        (
                            "lifecycle_evidence_mode",
                            models.CharField(
                                choices=[
                                    ("none", "None"),
                                    ("direct_contact", "Direct contact"),
                                    ("reported_state", "Reported state"),
                                    ("direct_then_reported_state", "Direct then reported state"),
                                ],
                                default="none",
                                max_length=32,
                            ),
                        ),
                        ("description", models.TextField(blank=True, default="")),
                    ],
                    options={"db_table": "entity_types", "ordering": ("name",)},
                ),
                migrations.CreateModel(
                    name="PlatformAlias",
                    fields=[
                        (
                            "alias",
                            models.CharField(max_length=80, primary_key=True, serialize=False),
                        ),
                        ("canonical", models.CharField(max_length=80)),
                    ],
                    options={"db_table": "platform_aliases", "ordering": ("alias",)},
                ),
                migrations.AddField(
                    model_name="source",
                    name="entity_type",
                    field=models.CharField(blank=True, default="", max_length=80),
                ),
            ],
        ),
    ]
