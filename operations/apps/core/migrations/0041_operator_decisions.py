"""Migration 0041 — operator decisions layer (Track O batch O2).

Per DESIGN.md §3.8. Adds:

- `operations.operator_decision_dimensions` — registry of valid
  dimensions for the polymorphic operator-decision tables.
- `operations.device_operator_decisions` — polymorphic per-device
  standalone decisions (exemptions, notes, suppress-finding).
- BEFORE trigger validating `value` shape against the dimension's
  `value_type` + `allowed_values`.
- RLS + grants on `device_operator_decisions` (regular table — RLS
  works). Registry is global reference; readable by all app roles.
- Seed `exemptions` dimension (value_type=json).
- Data migration: copy every non-empty `Device.exemptions` into
  `device_operator_decisions` rows with dimension='exemptions'.

Column retirement (Device.exemptions) is deferred to O3 after
`v_device` is in place and consumers read via the view.
"""

from __future__ import annotations

import uuid

import django.db.models.deletion
from django.db import migrations, models


_DIMENSIONS_SEED = [
    (
        "exemptions",
        "device",
        "json",
        None,
        "Per-device exemption flags — {entity_type: reason}. Evaluator "
        "skips coverage requirements whose entity_type is present.",
    ),
]


def seed_dimensions_and_migrate_exemptions(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    Dimension = apps.get_model("operations", "OperatorDecisionDimension")
    Device = apps.get_model("operations", "Device")
    Decision = apps.get_model("operations", "DeviceOperatorDecision")

    for name, entity_type, value_type, allowed_values, description in _DIMENSIONS_SEED:
        Dimension.objects.get_or_create(
            name=name,
            defaults={
                "entity_type": entity_type,
                "value_type": value_type,
                "allowed_values": allowed_values,
                "description": description,
                "enabled": True,
            },
        )

    # Copy every non-empty Device.exemptions → device_operator_decisions
    # row under dimension='exemptions'. One row per device (device_id is
    # PK on Device → unique on (tenant, device, 'exemptions')).
    devices = (
        Device.objects.filter(deleted_at__isnull=True)
        .exclude(exemptions={})
        .exclude(exemptions__isnull=True)
    )
    migrated = 0
    for dev in devices.iterator(chunk_size=500):
        if not dev.exemptions:
            continue
        Decision.objects.update_or_create(
            tenant=dev.tenant,
            device=dev,
            dimension="exemptions",
            defaults={
                "value": dev.exemptions,
                "reason": "migrated from Device.exemptions (Track O batch O2)",
                "set_by": "system.migration",
            },
        )
        migrated += 1
    print(f"[0041] migrated {migrated} exemptions rows into device_operator_decisions")


def unseed(apps, schema_editor):
    Dimension = apps.get_model("operations", "OperatorDecisionDimension")
    Decision = apps.get_model("operations", "DeviceOperatorDecision")
    Decision.objects.all().delete()
    Dimension.objects.filter(name="exemptions").delete()


_VALIDATOR_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION operations.validate_operator_decision()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    dim operations.operator_decision_dimensions%ROWTYPE;
BEGIN
    SELECT * INTO dim
    FROM operations.operator_decision_dimensions
    WHERE name = NEW.dimension;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown operator decision dimension: %', NEW.dimension
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    IF NOT dim.enabled THEN
        RAISE EXCEPTION 'Operator decision dimension is disabled: %', NEW.dimension
            USING ERRCODE = 'check_violation';
    END IF;

    -- Shape validation per value_type
    IF dim.value_type = 'boolean' THEN
        IF jsonb_typeof(NEW.value) NOT IN ('boolean') THEN
            RAISE EXCEPTION 'Dimension % expects JSON boolean, got %',
                NEW.dimension, jsonb_typeof(NEW.value)
                USING ERRCODE = 'check_violation';
        END IF;
    ELSIF dim.value_type = 'text' THEN
        IF jsonb_typeof(NEW.value) NOT IN ('string') THEN
            RAISE EXCEPTION 'Dimension % expects JSON string, got %',
                NEW.dimension, jsonb_typeof(NEW.value)
                USING ERRCODE = 'check_violation';
        END IF;
    ELSIF dim.value_type = 'enum' THEN
        IF jsonb_typeof(NEW.value) NOT IN ('string') THEN
            RAISE EXCEPTION 'Dimension % expects enum (JSON string), got %',
                NEW.dimension, jsonb_typeof(NEW.value)
                USING ERRCODE = 'check_violation';
        END IF;
        IF dim.allowed_values IS NULL
           OR NOT (dim.allowed_values @> jsonb_build_array(NEW.value)) THEN
            RAISE EXCEPTION 'Dimension % value % not in allowed_values %',
                NEW.dimension, NEW.value::text, dim.allowed_values::text
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    -- value_type='json' accepts any shape.

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_operator_decision
    ON operations.device_operator_decisions;

CREATE TRIGGER trg_validate_operator_decision
    BEFORE INSERT OR UPDATE ON operations.device_operator_decisions
    FOR EACH ROW EXECUTE FUNCTION operations.validate_operator_decision();
"""

_VALIDATOR_TRIGGER_REVERSE_SQL = """
DROP TRIGGER IF EXISTS trg_validate_operator_decision
    ON operations.device_operator_decisions;
DROP FUNCTION IF EXISTS operations.validate_operator_decision();
"""


_RLS_SQL = """
-- Registry: global reference, readable by all app roles.
GRANT SELECT ON operations.operator_decision_dimensions
    TO operations_app, ninja_ingest, operations_readonly, metabase_ro;

-- Polymorphic decisions: tenant-scoped table, standard RLS + grants.
ALTER TABLE operations.device_operator_decisions ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.device_operator_decisions
    USING (tenant_id = current_setting('operations.tenant_id', true)::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE
    ON operations.device_operator_decisions
    TO operations_app;
GRANT SELECT ON operations.device_operator_decisions
    TO operations_readonly, metabase_ro;
GRANT INSERT ON operations.device_operator_decisions
    TO ninja_ingest;
"""

_RLS_REVERSE_SQL = """
DROP POLICY IF EXISTS tenant_isolation ON operations.device_operator_decisions;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0040_device_session_current"),
    ]

    operations = [
        migrations.CreateModel(
            name="OperatorDecisionDimension",
            fields=[
                ("name", models.CharField(max_length=80, primary_key=True, serialize=False)),
                ("entity_type", models.CharField(
                    max_length=16,
                    choices=[("device", "Device"), ("client", "Client")],
                )),
                ("value_type", models.CharField(
                    max_length=16,
                    choices=[
                        ("enum", "Enum (JSON string in allowed_values)"),
                        ("boolean", "Boolean (JSON true/false)"),
                        ("text", "Text (JSON string)"),
                        ("json", "JSON (any shape)"),
                    ],
                )),
                ("allowed_values", models.JSONField(blank=True, null=True)),
                ("description", models.TextField(blank=True, default="")),
                ("enabled", models.BooleanField(default=True)),
            ],
            options={
                "db_table": "operator_decision_dimensions",
                "ordering": ("name",),
            },
        ),
        migrations.CreateModel(
            name="DeviceOperatorDecision",
            fields=[
                ("version", models.PositiveIntegerField(default=1)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("dimension", models.CharField(max_length=80)),
                ("value", models.JSONField()),
                ("reason", models.TextField(blank=True, default="")),
                ("set_by", models.CharField(blank=True, default="", max_length=120)),
                ("set_at", models.DateTimeField(auto_now=True)),
                ("tenant", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    to="operations.tenant",
                )),
                ("device", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="operator_decisions",
                    to="operations.device",
                )),
            ],
            options={"db_table": "device_operator_decisions"},
        ),
        migrations.AddConstraint(
            model_name="deviceoperatordecision",
            constraint=models.UniqueConstraint(
                fields=("tenant", "device", "dimension"),
                name="uq_device_operator_decisions_tenant_device_dim",
            ),
        ),
        migrations.RunSQL(_VALIDATOR_TRIGGER_SQL, _VALIDATOR_TRIGGER_REVERSE_SQL),
        migrations.RunSQL(_RLS_SQL, _RLS_REVERSE_SQL),
        migrations.RunPython(seed_dimensions_and_migrate_exemptions, unseed),
    ]
