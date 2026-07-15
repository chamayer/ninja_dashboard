"""Migration 0043 — Patching scope layer (Track O batch O4).

Per BLUEPRINT.md Track O + DESIGN.md §3.8. First per-domain application
of the standing storage-separation principle:

- Config: `patching_scope_signal` (documentation of rules),
  `patching_scope_default` (fallback per device_role),
  `patching_scope_policy_allowlist` (Ninja policies that flip server
  default to Included).
- Derived: `device_patching_scope_current` matview (per ops device).
- Operator override: `device_patching_override` typed table
  (CHECK scope IN Included/Excluded).
- Effective: `v_device` extended with `patching_scope_derived`,
  `patching_scope_reason`, `patching_scope_override`,
  `effective_patching_scope`.

Refresh: `operations.refresh_patching_scope_current()`. Called from
`ingest/core/devices.py::_refresh_agent_presence_current` (extended
in this batch) after Ninja custom_field_values + device roles/os_group
land.

Parity target (measured 2026-07-15 on prod):
  * ninja_core.v_active_devices: 4083 Windows devices in scope
    (1663 Excluded + 2420 Included).
  * ops target: matching Included/Excluded count for Ninja-linked
    Windows devices; non-Windows or non-Ninja → 'Unmanaged'.
"""

from __future__ import annotations

import uuid

import django.db.models.deletion
from django.db import migrations, models


_SIGNALS_SEED = [
    # priority, field_name, entity_type, device_role_filter, effect, description
    (10, "patchingDisabled", "device", "", "Excluded",
     "Explicit device-level exclusion — highest priority."),
    (20, "patchingDisabled", "organization", "", "Excluded",
     "Client-level exclusion."),
    (30, "patchingDisabled", "location", "", "Excluded",
     "Location-level exclusion."),
    (40, "patchingEnabled", "device", "", "Included",
     "Device-level operator opt-in overriding server-default exclusion."),
    (50, "workstationPatchingDisabled", "device", "workstation", "Excluded",
     "Workstation-scoped device exclusion."),
    (60, "workstationPatchingDisabled", "organization", "workstation", "Excluded",
     "Workstation-scoped client exclusion."),
    (70, "workstationPatchingDisabled", "location", "workstation", "Excluded",
     "Workstation-scoped location exclusion."),
    (80, "serverPatchingDisabled", "device", "server", "Excluded",
     "Server-scoped device exclusion."),
    (90, "serverPatchingDisabled", "organization", "server", "Excluded",
     "Server-scoped client exclusion."),
    (100, "serverPatchingDisabled", "location", "server", "Excluded",
     "Server-scoped location exclusion."),
]


_DEFAULTS_SEED = [
    # device_role, effect, description
    ("workstation", "Included",
     "Windows workstations default to Included unless explicitly disabled."),
    ("server", "Excluded",
     "Windows servers default to Excluded unless assigned a policy in the "
     "allowlist, or device.patchingEnabled is set."),
    ("unknown", "Unmanaged",
     "Devices without a resolved role are unmanaged for patching."),
]


def seed_and_import(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    Signal = apps.get_model("operations", "PatchingScopeSignal")
    Default = apps.get_model("operations", "PatchingScopeDefault")
    Allow = apps.get_model("operations", "PatchingScopePolicyAllowlist")

    for priority, field_name, entity_type, role_filter, effect, description in _SIGNALS_SEED:
        Signal.objects.get_or_create(
            priority=priority,
            field_name=field_name,
            entity_type=entity_type,
            defaults={
                "device_role_filter": role_filter,
                "effect": effect,
                "enabled": True,
                "description": description,
            },
        )

    for device_role, effect, description in _DEFAULTS_SEED:
        Default.objects.update_or_create(
            device_role=device_role,
            defaults={"effect": effect, "enabled": True, "description": description},
        )

    # Import ninja_core.patching_enabled_policies via raw SQL — ninja_core
    # isn't in Django's ORM state.
    with schema_editor.connection.cursor() as cur:
        cur.execute(
            "SELECT to_regclass('ninja_core.patching_enabled_policies') IS NOT NULL"
        )
        (present,) = cur.fetchone()
        if not present:
            print("[0043] ninja_core.patching_enabled_policies not present — skipping import")
            return
        cur.execute("SELECT policy_name FROM ninja_core.patching_enabled_policies")
        rows = cur.fetchall()
        imported = 0
        for (policy_name,) in rows:
            _, created = Allow.objects.get_or_create(
                policy_name=policy_name,
                defaults={"enabled": True,
                          "notes": "imported from ninja_core.patching_enabled_policies"},
            )
            if created:
                imported += 1
        print(f"[0043] imported {imported} policy names into patching_scope_policy_allowlist "
              f"(of {len(rows)} legacy rows)")


def unseed(apps, schema_editor):
    for name in ("PatchingScopeSignal", "PatchingScopeDefault", "PatchingScopePolicyAllowlist"):
        apps.get_model("operations", name).objects.all().delete()


_MATVIEW_SQL = """
CREATE MATERIALIZED VIEW operations.device_patching_scope_current AS
WITH ninja_linked AS (
    -- One row per ops device (multi-link collapse via DISTINCT ON: prefer
    -- the freshest Ninja link). E.3 gotcha handled — same as O1/O3.
    SELECT DISTINCT ON (d.id)
        d.tenant_id,
        d.id             AS device_id,
        d.device_role,
        d.os_group,
        nd.id            AS ninja_device_id,
        nd.organization_id,
        nd.location_id,
        COALESCE(pol.name, rpol.name) AS effective_policy_name
    FROM operations.devices d
    JOIN operations.device_links dl
      ON dl.device_id = d.id AND dl.tenant_id = d.tenant_id
    JOIN operations.sources s
      ON s.id = dl.source_id AND s.name = 'Ninja'
    JOIN ninja_core.devices nd
      ON nd.id::text = dl.external_id
    LEFT JOIN ninja_core.policies pol  ON pol.id  = nd.policy_id
    LEFT JOIN ninja_core.policies rpol ON rpol.id = nd.role_policy_id
    WHERE d.deleted_at IS NULL
    ORDER BY d.id, dl.last_seen_at DESC NULLS LAST
),
-- Latest custom field per (entity_id, field_name) — uses
-- custom_field_values_last_observed_idx (entity_type, entity_id,
-- field_name, last_observed_at DESC).
device_cf AS (
    SELECT DISTINCT ON (entity_id, field_name)
        entity_id, field_name, value_bool
    FROM ninja_core.custom_field_values
    WHERE entity_type = 'DEVICE'
      AND field_name IN ('patchingDisabled','patchingEnabled',
                         'serverPatchingDisabled','workstationPatchingDisabled')
    ORDER BY entity_id, field_name, last_observed_at DESC
),
organization_cf AS (
    SELECT DISTINCT ON (entity_id, field_name)
        entity_id, field_name, value_bool
    FROM ninja_core.custom_field_values
    WHERE entity_type = 'ORGANIZATION'
      AND field_name IN ('patchingDisabled',
                         'serverPatchingDisabled','workstationPatchingDisabled')
    ORDER BY entity_id, field_name, last_observed_at DESC
),
location_cf AS (
    SELECT DISTINCT ON (entity_id, field_name)
        entity_id, field_name, value_bool
    FROM ninja_core.custom_field_values
    WHERE entity_type = 'LOCATION'
      AND field_name IN ('patchingDisabled',
                         'serverPatchingDisabled','workstationPatchingDisabled')
    ORDER BY entity_id, field_name, last_observed_at DESC
),
signals AS (
    SELECT
        nl.tenant_id, nl.device_id,
        BOOL_OR(dcf.value_bool)  FILTER (WHERE dcf.field_name = 'patchingDisabled')            AS d_disabled,
        BOOL_OR(dcf.value_bool)  FILTER (WHERE dcf.field_name = 'patchingEnabled')             AS d_enabled,
        BOOL_OR(dcf.value_bool)  FILTER (WHERE dcf.field_name = 'workstationPatchingDisabled') AS d_ws_disabled,
        BOOL_OR(dcf.value_bool)  FILTER (WHERE dcf.field_name = 'serverPatchingDisabled')      AS d_sv_disabled,
        BOOL_OR(ocf.value_bool)  FILTER (WHERE ocf.field_name = 'patchingDisabled')            AS o_disabled,
        BOOL_OR(ocf.value_bool)  FILTER (WHERE ocf.field_name = 'workstationPatchingDisabled') AS o_ws_disabled,
        BOOL_OR(ocf.value_bool)  FILTER (WHERE ocf.field_name = 'serverPatchingDisabled')      AS o_sv_disabled,
        BOOL_OR(lcf.value_bool)  FILTER (WHERE lcf.field_name = 'patchingDisabled')            AS l_disabled,
        BOOL_OR(lcf.value_bool)  FILTER (WHERE lcf.field_name = 'workstationPatchingDisabled') AS l_ws_disabled,
        BOOL_OR(lcf.value_bool)  FILTER (WHERE lcf.field_name = 'serverPatchingDisabled')      AS l_sv_disabled,
        MAX(nl.effective_policy_name) AS effective_policy_name
    FROM ninja_linked nl
    LEFT JOIN device_cf       dcf ON dcf.entity_id = nl.ninja_device_id
    LEFT JOIN organization_cf ocf ON ocf.entity_id = nl.organization_id
    LEFT JOIN location_cf     lcf ON lcf.entity_id = nl.location_id
    GROUP BY nl.tenant_id, nl.device_id
)
SELECT
    d.tenant_id,
    d.id AS device_id,
    d.device_role,
    CASE
        -- Non-Ninja-linked devices are unmanaged (no source of scope truth today).
        WHEN nl.ninja_device_id IS NULL THEN 'Unmanaged'
        -- Non-Windows devices — Ninja can't patch them via current ops path.
        WHEN d.os_group <> 'Windows' THEN 'Unmanaged'
        -- Priority 10-30: any patchingDisabled → Excluded
        WHEN COALESCE(sig.d_disabled, sig.o_disabled, sig.l_disabled, FALSE) THEN 'Excluded'
        -- Priority 40: device.patchingEnabled → Included
        WHEN COALESCE(sig.d_enabled, FALSE) THEN 'Included'
        -- Priority 50-70: workstation-scoped disable
        WHEN d.device_role = 'workstation'
             AND COALESCE(sig.d_ws_disabled, sig.o_ws_disabled, sig.l_ws_disabled, FALSE)
             THEN 'Excluded'
        -- Priority 80-100: server-scoped disable
        WHEN d.device_role = 'server'
             AND COALESCE(sig.d_sv_disabled, sig.o_sv_disabled, sig.l_sv_disabled, FALSE)
             THEN 'Excluded'
        -- Priority 110: server + policy in allowlist → Included
        WHEN d.device_role = 'server'
             AND sig.effective_policy_name IS NOT NULL
             AND EXISTS (
                 SELECT 1 FROM operations.patching_scope_policy_allowlist a
                 WHERE a.enabled AND a.policy_name = sig.effective_policy_name
             )
             THEN 'Included'
        -- Fallback: per device_role default table
        ELSE COALESCE(
            (SELECT def.effect FROM operations.patching_scope_default def
             WHERE def.device_role = d.device_role AND def.enabled),
            'Unmanaged'
        )
    END AS scope_derived,
    CASE
        WHEN nl.ninja_device_id IS NULL              THEN 'no-ninja-link'
        WHEN d.os_group <> 'Windows'                 THEN 'os-group-not-windows'
        WHEN COALESCE(sig.d_disabled, FALSE)         THEN 'device.patchingDisabled'
        WHEN COALESCE(sig.o_disabled, FALSE)         THEN 'organization.patchingDisabled'
        WHEN COALESCE(sig.l_disabled, FALSE)         THEN 'location.patchingDisabled'
        WHEN COALESCE(sig.d_enabled, FALSE)          THEN 'device.patchingEnabled'
        WHEN d.device_role = 'workstation' AND COALESCE(sig.d_ws_disabled, FALSE) THEN 'device.workstationPatchingDisabled'
        WHEN d.device_role = 'workstation' AND COALESCE(sig.o_ws_disabled, FALSE) THEN 'organization.workstationPatchingDisabled'
        WHEN d.device_role = 'workstation' AND COALESCE(sig.l_ws_disabled, FALSE) THEN 'location.workstationPatchingDisabled'
        WHEN d.device_role = 'server' AND COALESCE(sig.d_sv_disabled, FALSE)      THEN 'device.serverPatchingDisabled'
        WHEN d.device_role = 'server' AND COALESCE(sig.o_sv_disabled, FALSE)      THEN 'organization.serverPatchingDisabled'
        WHEN d.device_role = 'server' AND COALESCE(sig.l_sv_disabled, FALSE)      THEN 'location.serverPatchingDisabled'
        WHEN d.device_role = 'server'
             AND sig.effective_policy_name IS NOT NULL
             AND EXISTS (SELECT 1 FROM operations.patching_scope_policy_allowlist a
                         WHERE a.enabled AND a.policy_name = sig.effective_policy_name)
             THEN 'policy-allowlist:' || sig.effective_policy_name
        ELSE 'default:' || COALESCE(NULLIF(d.device_role, ''), 'unknown')
    END AS scope_reason,
    NOW() AS computed_at
FROM operations.devices d
LEFT JOIN ninja_linked nl
       ON nl.device_id = d.id AND nl.tenant_id = d.tenant_id
LEFT JOIN signals sig
       ON sig.device_id = d.id AND sig.tenant_id = d.tenant_id
WHERE d.deleted_at IS NULL
WITH DATA;
"""

_MATVIEW_INDEXES_SQL = """
CREATE UNIQUE INDEX idx_device_patching_scope_current_pk
    ON operations.device_patching_scope_current (tenant_id, device_id);
CREATE INDEX idx_device_patching_scope_current_scope
    ON operations.device_patching_scope_current (tenant_id, scope_derived);
"""

_REFRESH_FN_SQL = """
CREATE OR REPLACE FUNCTION operations.refresh_patching_scope_current()
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY operations.device_patching_scope_current;
END;
$$;
"""

_MATVIEW_REVERSE_SQL = """
DROP FUNCTION IF EXISTS operations.refresh_patching_scope_current();
DROP MATERIALIZED VIEW IF EXISTS operations.device_patching_scope_current;
"""

_GRANTS_SQL = """
-- Config tables — global reference, read for all app roles.
GRANT SELECT ON operations.patching_scope_signal, operations.patching_scope_default,
                operations.patching_scope_policy_allowlist
    TO operations_app, ninja_ingest, operations_readonly, metabase_ro;

-- Matview grants (RLS not supported on matviews; scoping via joins to
-- ops.devices which has RLS).
GRANT SELECT ON operations.device_patching_scope_current
    TO operations_app, ninja_ingest, operations_readonly, metabase_ro;
ALTER MATERIALIZED VIEW operations.device_patching_scope_current
    OWNER TO operations_migrate;
GRANT EXECUTE ON FUNCTION operations.refresh_patching_scope_current()
    TO operations_app, ninja_ingest;

-- Override table — tenant-scoped, RLS on.
ALTER TABLE operations.device_patching_override ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.device_patching_override
    USING (tenant_id = current_setting('operations.tenant_id', true)::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE
    ON operations.device_patching_override TO operations_app;
GRANT SELECT ON operations.device_patching_override
    TO operations_readonly, metabase_ro;

-- Typed CHECK constraint on override scope (defense in depth vs Django
-- validation).
ALTER TABLE operations.device_patching_override
    ADD CONSTRAINT ck_device_patching_override_scope
    CHECK (scope IN ('Included', 'Excluded'));
"""

_GRANTS_REVERSE_SQL = """
DROP POLICY IF EXISTS tenant_isolation ON operations.device_patching_override;
"""

# v_device gets patching_scope columns. Uses CREATE OR REPLACE so we
# don't drop-and-recreate (no dependents to break).
_V_DEVICE_SQL = """
CREATE OR REPLACE VIEW operations.v_device
WITH (security_invoker = true) AS
SELECT
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

    ds.last_contact_at,
    ds.last_observed_at,
    COALESCE(ds.is_online_any, FALSE)            AS is_online_any,
    COALESCE(ds.online_sources, ARRAY[]::text[]) AS online_sources,
    COALESCE(ds.source_count_active, 0)          AS source_count_active,
    ds.needs_reboot,
    ds.last_boot_at,
    ds.last_power_state,
    ds.computed_at                               AS session_computed_at,

    COALESCE(op_exemptions.value, '{}'::jsonb)   AS exemptions,

    -- Patching scope layer (O4)
    ps.scope_derived                             AS patching_scope_derived,
    ps.scope_reason                              AS patching_scope_reason,
    ps.computed_at                               AS patching_scope_computed_at,
    op_patching.scope                            AS patching_scope_override,
    op_patching.reason                           AS patching_scope_override_reason,
    COALESCE(op_patching.scope, ps.scope_derived, 'Unmanaged')
                                                 AS effective_patching_scope
FROM operations.devices d
LEFT JOIN operations.device_session_current ds
       ON ds.tenant_id = d.tenant_id
      AND ds.device_id = d.id
LEFT JOIN operations.device_operator_decisions op_exemptions
       ON op_exemptions.tenant_id = d.tenant_id
      AND op_exemptions.device_id = d.id
      AND op_exemptions.dimension = 'exemptions'
LEFT JOIN operations.device_patching_scope_current ps
       ON ps.tenant_id = d.tenant_id
      AND ps.device_id = d.id
LEFT JOIN operations.device_patching_override op_patching
       ON op_patching.tenant_id = d.tenant_id
      AND op_patching.device_id = d.id
WHERE d.deleted_at IS NULL;
"""

_V_DEVICE_REVERSE_SQL = """
-- Restore the O3 v_device shape (no patching_scope columns).
CREATE OR REPLACE VIEW operations.v_device
WITH (security_invoker = true) AS
SELECT
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
    ds.last_contact_at,
    ds.last_observed_at,
    COALESCE(ds.is_online_any, FALSE)            AS is_online_any,
    COALESCE(ds.online_sources, ARRAY[]::text[]) AS online_sources,
    COALESCE(ds.source_count_active, 0)          AS source_count_active,
    ds.needs_reboot,
    ds.last_boot_at,
    ds.last_power_state,
    ds.computed_at                               AS session_computed_at,
    COALESCE(op_exemptions.value, '{}'::jsonb)   AS exemptions
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


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0042_v_device_and_exemptions_column_drop"),
    ]

    operations = [
        # ── Config tables ────────────────────────────────────────────
        migrations.CreateModel(
            name="PatchingScopeSignal",
            fields=[
                ("id", models.SmallAutoField(primary_key=True, serialize=False)),
                ("field_name", models.CharField(max_length=80)),
                ("entity_type", models.CharField(
                    max_length=16,
                    choices=[("device", "Device"),
                             ("organization", "Organization"),
                             ("location", "Location")],
                )),
                ("device_role_filter", models.CharField(blank=True, default="", max_length=32)),
                ("effect", models.CharField(
                    max_length=16,
                    choices=[("Included", "Included"), ("Excluded", "Excluded")],
                )),
                ("priority", models.PositiveIntegerField(default=100)),
                ("enabled", models.BooleanField(default=True)),
                ("description", models.TextField(blank=True, default="")),
            ],
            options={"db_table": "patching_scope_signal",
                     "ordering": ("priority", "id")},
        ),
        migrations.CreateModel(
            name="PatchingScopeDefault",
            fields=[
                ("device_role", models.CharField(max_length=32, primary_key=True, serialize=False)),
                ("effect", models.CharField(
                    max_length=16,
                    choices=[("Included", "Included"),
                             ("Excluded", "Excluded"),
                             ("Unmanaged", "Unmanaged")],
                )),
                ("enabled", models.BooleanField(default=True)),
                ("description", models.TextField(blank=True, default="")),
            ],
            options={"db_table": "patching_scope_default",
                     "ordering": ("device_role",)},
        ),
        migrations.CreateModel(
            name="PatchingScopePolicyAllowlist",
            fields=[
                ("id", models.SmallAutoField(primary_key=True, serialize=False)),
                ("policy_name", models.CharField(max_length=240, unique=True)),
                ("enabled", models.BooleanField(default=True)),
                ("notes", models.TextField(blank=True, default="")),
            ],
            options={"db_table": "patching_scope_policy_allowlist",
                     "ordering": ("policy_name",)},
        ),

        # ── Override table (typed per-domain per DESIGN §3.8) ────────
        migrations.CreateModel(
            name="DevicePatchingOverride",
            fields=[
                ("version", models.PositiveIntegerField(default=1)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False,
                                        primary_key=True, serialize=False)),
                ("scope", models.CharField(
                    max_length=16,
                    choices=[("Included", "Included"), ("Excluded", "Excluded")],
                )),
                ("reason", models.TextField(blank=True, default="")),
                ("set_by", models.CharField(blank=True, default="", max_length=120)),
                ("set_at", models.DateTimeField(auto_now=True)),
                ("tenant", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    to="operations.tenant",
                )),
                ("device", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="patching_override",
                    to="operations.device",
                )),
            ],
            options={"db_table": "device_patching_override"},
        ),

        # ── Seeds (config tables must exist first; ninja_core allowlist
        # imported here to have data in the matview build).
        migrations.RunPython(seed_and_import, unseed),

        # ── Matview + refresh function + grants + RLS on override ────
        migrations.RunSQL(_MATVIEW_SQL, _MATVIEW_REVERSE_SQL),
        migrations.RunSQL(_MATVIEW_INDEXES_SQL, ""),
        migrations.RunSQL(_REFRESH_FN_SQL, ""),
        migrations.RunSQL(_GRANTS_SQL, _GRANTS_REVERSE_SQL),

        # ── v_device extended with patching_scope columns ────────────
        migrations.RunSQL(_V_DEVICE_SQL, _V_DEVICE_REVERSE_SQL),
    ]
