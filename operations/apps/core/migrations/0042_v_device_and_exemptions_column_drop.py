"""Migration 0042 — v_device effective view + retire Device.exemptions
(Track O batch O3).

Per DESIGN.md §3.8. Wraps canonical `operations.devices` +
`device_session_current` (O1) + `device_operator_decisions` (O2 —
pivoted for `dimension='exemptions'`) behind a single read surface
`operations.v_device`. Consumers stop reading `devices.exemptions`
directly (evaluator, resolver INSERTs, Ninja no_av_exempt writer all
swapped to the new storage in this batch's code changes).

Column drop uses SeparateDatabaseAndState so Django's model state
loses the field cleanly; the DB drop is a plain ALTER TABLE.
"""

from __future__ import annotations

from django.db import migrations


_V_DEVICE_SQL = """
CREATE OR REPLACE VIEW operations.v_device
WITH (security_invoker = true) AS
SELECT
    -- Canonical (from operations.devices)
    d.tenant_id,
    d.id                AS device_id,
    d.client_id,
    d.version,
    d.canonical_hostname,
    d.canonical_serial,
    d.canonical_vm_uuid,
    d.device_type,
    d.device_role,
    d.lifecycle_status,
    d.os_name,
    d.os_family,
    d.os_group,
    d.created_at,
    d.created_reason,
    d.updated_at,
    d.updated_reason,
    d.stale_since,
    d.stale_reason,
    d.deleted_at,
    d.deleted_reason,

    -- Session state (from device_session_current, O1)
    ds.last_contact_at,
    ds.last_observed_at,
    COALESCE(ds.is_online_any, FALSE)             AS is_online_any,
    COALESCE(ds.online_sources, ARRAY[]::text[])  AS online_sources,
    COALESCE(ds.source_count_active, 0)           AS source_count_active,
    ds.needs_reboot,
    ds.last_boot_at,
    ds.last_power_state,
    ds.computed_at                                AS session_computed_at,

    -- Operator decisions (from device_operator_decisions, O2 —
    -- pivoted per known dimension).
    COALESCE(op_exemptions.value, '{}'::jsonb)    AS exemptions
FROM operations.devices d
LEFT JOIN operations.device_session_current ds
       ON ds.tenant_id = d.tenant_id
      AND ds.device_id = d.id
LEFT JOIN operations.device_operator_decisions op_exemptions
       ON op_exemptions.tenant_id = d.tenant_id
      AND op_exemptions.device_id = d.id
      AND op_exemptions.dimension = 'exemptions'
WHERE d.deleted_at IS NULL;
"""

_V_DEVICE_REVERSE_SQL = "DROP VIEW IF EXISTS operations.v_device;"

_V_DEVICE_GRANTS_SQL = """
GRANT SELECT ON operations.v_device
    TO operations_app, ninja_ingest, operations_readonly, metabase_ro;
"""

_V_DEVICE_GRANTS_REVERSE_SQL = ""

_DROP_EXEMPTIONS_SQL = "ALTER TABLE operations.devices DROP COLUMN exemptions;"
_DROP_EXEMPTIONS_REVERSE_SQL = (
    "ALTER TABLE operations.devices "
    "ADD COLUMN exemptions JSONB NOT NULL DEFAULT '{}'::jsonb;"
)


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0041_operator_decisions"),
    ]

    operations = [
        migrations.RunSQL(_V_DEVICE_SQL, _V_DEVICE_REVERSE_SQL),
        migrations.RunSQL(_V_DEVICE_GRANTS_SQL, _V_DEVICE_GRANTS_REVERSE_SQL),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="device",
                    name="exemptions",
                ),
            ],
            database_operations=[
                migrations.RunSQL(_DROP_EXEMPTIONS_SQL, _DROP_EXEMPTIONS_REVERSE_SQL),
            ],
        ),
    ]
