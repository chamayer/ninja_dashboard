"""One writer for Computer names, enforced in the database (ADR-0034 section 6).

* ``devices.name_rule``, ``name_observation_id`` and ``name_decided_at``
  record why a Computer has its name. Existing Computers start with no rule
  (NULL: not yet decided by the writer); the first resolver reconciliation
  decides every one. A new Computer is inserted ``pending`` and a deferred
  constraint trigger refuses a commit that leaves it so.
* ``operations.write_computer_names(p_devices, p_tenant)`` is the only writer
  of those columns and of ``canonical_hostname``. It writes only where the
  decision of ``computer_names`` differs from the stored one; a rename is an
  explicit ``computer.rename`` change whose evidence names the rule and the
  record.
* It is SECURITY DEFINER, owned by the no-login role ``operations_naming``,
  and a guard trigger refuses any change to the four columns by any other
  role. A session setting is not used: runtime roles can set any custom
  setting.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
SELECT operations.begin_change(
    'computer.name_writer',
    'ADR-0034: Computer names have one writer, enforced in the database.',
    '{"migration": "0328_computer_name_writer"}'::jsonb,
    'migration', NULL, 'operations.migrations', '0328', NULL, true);

DO $block$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'operations_naming') THEN
        CREATE ROLE operations_naming NOLOGIN NOBYPASSRLS;
    END IF;
END
$block$;

ALTER TABLE operations.devices
    ADD COLUMN name_rule varchar(20) NULL,
    ADD COLUMN name_observation_id uuid NULL,
    ADD COLUMN name_decided_at timestamptz NULL;
ALTER TABLE operations.devices ALTER COLUMN name_rule SET DEFAULT 'pending';
ALTER TABLE operations.devices ADD CONSTRAINT devices_name_rule_known CHECK (
    name_rule IS NULL OR name_rule IN (
        'pending', 'operator', 'reporting_os', 'silent_os', 'stable_os', 'withdrawn_os',
        'current_label', 'withdrawn_label', 'unconfirmed', 'kept_collision'));

-- A tenant-safe reference to the record behind the name (backed by the
-- existing unique index uq_obs_current_tenant_observation).
ALTER TABLE operations.devices
    ADD CONSTRAINT devices_name_observation_fk
    FOREIGN KEY (tenant_id, name_observation_id)
    REFERENCES operations.entity_observation_current (tenant_id, observation_id)
    ON DELETE SET NULL (name_observation_id);

UPDATE operations.change_history_registry
   SET recorded_columns = recorded_columns
       || ARRAY['name_rule', 'name_observation_id', 'name_decided_at']::text[]
 WHERE table_name = 'devices'
   AND NOT ('name_rule' = ANY (recorded_columns));

-- Only the naming role changes a name or its provenance; anything else is refused.
CREATE FUNCTION operations.guard_computer_name() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, operations
AS $fn$
BEGIN
    IF current_user = 'operations_naming' THEN
        RETURN NEW;
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.name_rule IS DISTINCT FROM 'pending' OR NEW.name_observation_id IS NOT NULL
           OR NEW.name_decided_at IS NOT NULL THEN
            RAISE EXCEPTION 'A new Computer starts pending; only operations.write_computer_names names it'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.canonical_hostname IS DISTINCT FROM OLD.canonical_hostname
       OR NEW.name_rule IS DISTINCT FROM OLD.name_rule
       OR NEW.name_observation_id IS DISTINCT FROM OLD.name_observation_id
       OR NEW.name_decided_at IS DISTINCT FROM OLD.name_decided_at THEN
        RAISE EXCEPTION 'Computer names are written only by operations.write_computer_names (ADR-0034)'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END
$fn$;
CREATE TRIGGER devices_guard_computer_name
    BEFORE INSERT OR UPDATE OF canonical_hostname, name_rule, name_observation_id, name_decided_at
    ON operations.devices
    FOR EACH ROW EXECUTE FUNCTION operations.guard_computer_name();

-- Creation names the Computer in the same transaction.
CREATE FUNCTION operations.check_computer_named() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, operations
AS $fn$
BEGIN
    IF EXISTS (SELECT 1 FROM operations.devices d WHERE d.id = NEW.id AND d.name_rule = 'pending') THEN
        RAISE EXCEPTION 'Computer % was created without a name decision; call operations.write_computer_names', NEW.id;
    END IF;
    RETURN NULL;
END
$fn$;
CREATE CONSTRAINT TRIGGER devices_named_at_commit
    AFTER INSERT OR UPDATE OF name_rule ON operations.devices
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION operations.check_computer_named();

-- The writer. p_devices NULL reconciles the whole tenant.
CREATE FUNCTION operations.write_computer_names(p_devices uuid[], p_tenant bigint)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_prev text := current_setting('operations.change_action_id', true);
    v_count integer := 0;
    v_quiet_started boolean := false;
    r record;
BEGIN
    IF p_tenant IS NULL
       OR p_tenant IS DISTINCT FROM nullif(current_setting('operations.tenant_id', true), '')::bigint THEN
        RAISE EXCEPTION 'write_computer_names needs the session tenant';
    END IF;
    IF p_devices IS NOT NULL AND cardinality(p_devices) = 0 THEN
        RETURN 0;
    END IF;

    -- Renames first, each its own explicit change naming the rule and record;
    -- then decisions that keep the name (new rule or record, a kept
    -- collision) under one change.
    FOR r IN
        SELECT n.device_id, d.canonical_hostname AS old_name, n.name, n.name_rule, n.observation_id,
               n.name IS DISTINCT FROM d.canonical_hostname AS renamed
          FROM operations.computer_names(p_tenant, p_devices) n
          JOIN operations.devices d ON d.id = n.device_id AND d.tenant_id = p_tenant
         WHERE n.name IS DISTINCT FROM d.canonical_hostname
            OR n.name_rule IS DISTINCT FROM d.name_rule
            OR n.observation_id IS DISTINCT FROM d.name_observation_id
         ORDER BY 6 DESC, 1
    LOOP
        IF r.renamed THEN
            PERFORM operations.begin_change(
                'computer.rename',
                format('Named by %s', r.name_rule),
                jsonb_build_object('device_id', r.device_id, 'from', r.old_name, 'to', r.name,
                                   'rule', r.name_rule, 'observation_id', r.observation_id),
                'process', NULL, 'operations.write_computer_names', '0328', p_tenant, true);
        ELSIF NOT v_quiet_started THEN
            PERFORM operations.begin_change(
                'computer.name_decision', 'Name kept; rule or record changed', '{}'::jsonb,
                'process', NULL, 'operations.write_computer_names', '0328', p_tenant, false);
            v_quiet_started := true;
        END IF;
        UPDATE operations.devices
           SET canonical_hostname = r.name, name_rule = r.name_rule,
               name_observation_id = r.observation_id, name_decided_at = now()
         WHERE id = r.device_id AND tenant_id = p_tenant;
        v_count := v_count + 1;
    END LOOP;

    -- The caller's own change action continues after the names are written.
    PERFORM set_config('operations.change_action_id', coalesce(v_prev, ''), true);
    RETURN v_count;
END
$fn$;
ALTER FUNCTION operations.write_computer_names(uuid[], bigint) OWNER TO operations_naming;

GRANT USAGE ON SCHEMA operations TO operations_naming;
GRANT SELECT ON ALL TABLES IN SCHEMA operations TO operations_naming;
GRANT UPDATE (canonical_hostname, name_rule, name_observation_id, name_decided_at)
    ON operations.devices TO operations_naming;
GRANT EXECUTE ON FUNCTION operations.computer_names(bigint, uuid[]),
                          operations.record_name_forms(text, text, text, text),
                          operations.begin_change(text, text, jsonb, text, bigint, text, text, bigint, boolean)
    TO operations_naming;

REVOKE ALL ON FUNCTION operations.write_computer_names(uuid[], bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.write_computer_names(uuid[], bigint) TO operations_app, ninja_ingest;
REVOKE ALL ON FUNCTION operations.guard_computer_name() FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.check_computer_named() FROM PUBLIC;
"""



class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0327_observation_history_record_index"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
