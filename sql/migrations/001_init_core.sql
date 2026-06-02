-- =============================================================================
-- 001_init_core.sql
-- Creates ninja_core schema: shared lookups, devices, custom fields,
-- ingest bookkeeping. Applied automatically by ingest.migrations on
-- container startup. Idempotent — uses IF NOT EXISTS throughout.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS ninja_core;

-- ── Lookups ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ninja_core.organizations (
    id                  integer PRIMARY KEY,
    name                text NOT NULL,
    description         text,
    node_approval_mode  text,
    data                jsonb NOT NULL,
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ninja_core.locations (
    id              integer PRIMARY KEY,
    organization_id integer NOT NULL REFERENCES ninja_core.organizations(id),
    name            text NOT NULL,
    address         text,
    data            jsonb NOT NULL,
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ninja_core.policies (
    id                      integer PRIMARY KEY,
    parent_policy_id        integer,
    name                    text NOT NULL,
    node_class              text,
    is_node_class_default   boolean,
    data                    jsonb NOT NULL,
    updated_at              timestamptz NOT NULL DEFAULT now()
);

-- ── Devices: slowly-changing dimension, upserted on every run ────────

CREATE TABLE IF NOT EXISTS ninja_core.devices (
    id                  integer PRIMARY KEY,
    uid                 uuid UNIQUE NOT NULL,
    organization_id     integer NOT NULL REFERENCES ninja_core.organizations(id),
    location_id         integer REFERENCES ninja_core.locations(id),
    policy_id           integer REFERENCES ninja_core.policies(id),
    role_policy_id      integer REFERENCES ninja_core.policies(id),
    node_class          text NOT NULL,
    approval_status     text NOT NULL,
    display_name        text,
    system_name         text,
    dns_name            text,
    netbios_name        text,
    os_name             text,
    os_architecture     text,
    os_build_number     text,
    os_release_id       text,
    serial_number       text,
    manufacturer        text,
    model               text,
    chassis_type        text,
    is_virtual_machine  boolean,
    total_memory_bytes  bigint,
    public_ip           inet,
    ip_addresses        text[],
    mac_addresses       text[],
    tags                text[],
    created_at_ninja    timestamptz,
    data                jsonb NOT NULL,
    first_seen_at       timestamptz NOT NULL DEFAULT now(),
    last_seen_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS devices_org_idx     ON ninja_core.devices (organization_id);
CREATE INDEX IF NOT EXISTS devices_class_idx   ON ninja_core.devices (node_class);
CREATE INDEX IF NOT EXISTS devices_approval_idx ON ninja_core.devices (approval_status);
CREATE INDEX IF NOT EXISTS devices_tags_gin    ON ninja_core.devices USING GIN (tags);
CREATE INDEX IF NOT EXISTS devices_data_gin    ON ninja_core.devices USING GIN (data jsonb_path_ops);

-- ── Device snapshots: append-only observed state ─────────────────────

CREATE TABLE IF NOT EXISTS ninja_core.device_snapshots (
    snapshot_at             timestamptz NOT NULL,
    device_id               integer NOT NULL REFERENCES ninja_core.devices(id),
    offline                 boolean,
    last_contact            timestamptz,
    last_boot               timestamptz,
    needs_reboot            boolean,
    needs_reboot_reasons    text[],                  -- e.g. {WINDOWS_UPDATE, COMPONENT_BASED_SERVICING, PENDING_FILE_RENAME}
    last_user               text,
    maintenance_status      text,
    maintenance_start       timestamptz,
    maintenance_end         timestamptz,
    data                    jsonb NOT NULL,
    PRIMARY KEY (snapshot_at, device_id)
);

CREATE INDEX IF NOT EXISTS device_snapshots_device_time_idx
    ON ninja_core.device_snapshots (device_id, snapshot_at DESC);
CREATE INDEX IF NOT EXISTS device_snapshots_needs_reboot_idx
    ON ninja_core.device_snapshots (needs_reboot) WHERE needs_reboot;
CREATE INDEX IF NOT EXISTS device_snapshots_reboot_reasons_gin
    ON ninja_core.device_snapshots USING GIN (needs_reboot_reasons);

-- ── Custom fields ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ninja_core.custom_field_definitions (
    id          integer PRIMARY KEY,
    name        text NOT NULL,
    label       text,
    scope       text NOT NULL,
    field_type  text NOT NULL,
    data        jsonb NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS custom_field_definitions_scope_name_idx
    ON ninja_core.custom_field_definitions (scope, name);

-- SCD-2: insert on hash change, update last_observed_at otherwise.
-- Querying "current value": DISTINCT ON (entity, field) ORDER BY last_observed_at DESC.
CREATE TABLE IF NOT EXISTS ninja_core.custom_field_values (
    id                  bigserial PRIMARY KEY,
    entity_type         text NOT NULL,            -- DEVICE | ORGANIZATION | LOCATION
    entity_id           integer NOT NULL,
    field_name          text NOT NULL,
    value_text          text,
    value_number        numeric,
    value_date          timestamptz,
    value_bool          boolean,
    raw_value           jsonb,
    content_hash        text NOT NULL,            -- hash of the value_* columns + raw_value
    first_observed_at   timestamptz NOT NULL,
    last_observed_at    timestamptz NOT NULL,
    UNIQUE (entity_type, entity_id, field_name, content_hash)
);

CREATE INDEX IF NOT EXISTS custom_field_values_entity_idx
    ON ninja_core.custom_field_values (entity_type, entity_id);
CREATE INDEX IF NOT EXISTS custom_field_values_field_idx
    ON ninja_core.custom_field_values (field_name);
CREATE INDEX IF NOT EXISTS custom_field_values_last_observed_idx
    ON ninja_core.custom_field_values (entity_type, entity_id, field_name, last_observed_at DESC);

-- Pivoted views (v_device_custom_fields, v_organization_custom_fields,
-- v_location_custom_fields) are regenerated dynamically by
-- ingest.core.custom_fields after each definitions refresh.

-- ── Ingest bookkeeping ───────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ninja_core.run_log (
    run_id          bigserial PRIMARY KEY,
    domain          text NOT NULL,
    started_at      timestamptz NOT NULL,
    finished_at     timestamptz,
    status          text NOT NULL,
    rows_upserted   integer,
    rows_inserted   integer,
    error_text      text,
    duration_ms     integer
);

CREATE INDEX IF NOT EXISTS run_log_domain_time_idx
    ON ninja_core.run_log (domain, started_at DESC);

CREATE TABLE IF NOT EXISTS ninja_core.schema_migrations (
    version     text PRIMARY KEY,
    applied_at  timestamptz NOT NULL DEFAULT now()
);
