"""Install the transactional invalidation foundation for PLAN-045.

This is one part of an unfinished transition. A missing or dirty row is not an
effective owner. In particular, this migration alone does not protect existing
readers and must be shipped together with the projector and reader transition.
It does not backfill existing Computers.
"""

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
CREATE TABLE operations.computer_client_ownership (
    tenant_id bigint NOT NULL,
    device_id uuid NOT NULL,
    state text NOT NULL DEFAULT 'dirty'
        CHECK (state IN ('dirty', 'resolved', 'unknown', 'conflict', 'review', 'decision_protected')),
    effective_client_id uuid,
    evidence_revision bigint NOT NULL DEFAULT 1 CHECK (evidence_revision > 0),
    projected_revision bigint NOT NULL DEFAULT 0 CHECK (projected_revision >= 0),
    contradiction boolean NOT NULL DEFAULT false,
    reason text NOT NULL DEFAULT '',
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, device_id),
    FOREIGN KEY (tenant_id, device_id) REFERENCES operations.devices (tenant_id, id)
        ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, effective_client_id) REFERENCES operations.clients (tenant_id, id),
    CHECK ((state IN ('resolved', 'decision_protected')) = (effective_client_id IS NOT NULL)),
    CHECK ((state = 'dirty' AND projected_revision < evidence_revision)
        OR (state <> 'dirty' AND projected_revision = evidence_revision)),
    CHECK (NOT contradiction OR state = 'decision_protected')
);

ALTER TABLE operations.computer_client_ownership ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.computer_client_ownership FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.computer_client_ownership
    USING (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint)
    WITH CHECK (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint);
REVOKE ALL ON operations.computer_client_ownership FROM PUBLIC, operations_app,
    operations_readonly, ninja_ingest;
GRANT SELECT ON operations.computer_client_ownership TO operations_app,
    operations_readonly, ninja_ingest;
CREATE INDEX computer_client_ownership_dirty_idx
    ON operations.computer_client_ownership (tenant_id, device_id)
    WHERE state = 'dirty';

INSERT INTO operations.change_history_registry (
    table_name, classification, reason, recorded_columns, secret_columns, key_columns,
    computer_column, computer_condition_column, computer_condition_value, client_column,
    is_global, capture
) VALUES (
    'computer_client_ownership', 'exempt',
    'Rebuildable derived ownership projection and invalidation state',
    '{}'::text[], '{}'::text[], '{}'::text[], NULL, NULL, NULL, NULL, false, NULL
);

CREATE FUNCTION operations.invalidate_computer_client_ownership(p_tenant bigint, p_device uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
BEGIN
    IF p_tenant IS NULL OR p_device IS NULL THEN
        RETURN;
    END IF;
    -- A device may already be gone when a cascading delete reaches an input.
    INSERT INTO operations.computer_client_ownership AS ownership
        (tenant_id, device_id)
    SELECT d.tenant_id, d.id FROM operations.devices d
     WHERE d.tenant_id = p_tenant AND d.id = p_device
    ON CONFLICT (tenant_id, device_id) DO UPDATE
       SET state = 'dirty', effective_client_id = NULL,
           evidence_revision = ownership.evidence_revision + 1,
           contradiction = false, reason = '', updated_at = now();
END
$fn$;

CREATE FUNCTION operations.invalidate_computer_client_observation() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    target record;
BEGIN
    IF TG_OP = 'UPDATE'
       AND (OLD.tenant_id, OLD.device_id, OLD.client_id, OLD.active, OLD.material_hash,
            OLD.entity_type, OLD.entity_key, OLD.external_namespace, OLD.external_id,
            OLD.source_instance_id)
           IS NOT DISTINCT FROM
           (NEW.tenant_id, NEW.device_id, NEW.client_id, NEW.active, NEW.material_hash,
            NEW.entity_type, NEW.entity_key, NEW.external_namespace, NEW.external_id,
            NEW.source_instance_id) THEN
        RETURN NULL;
    END IF;
    -- A reattachment invalidates both owners. Stable ordering prevents the
    -- common two-device reattachment from locking the two rows in reverse.
    FOR target IN
        SELECT DISTINCT tenant_id, device_id FROM (
            SELECT OLD.tenant_id, OLD.device_id WHERE TG_OP <> 'INSERT'
            UNION ALL
            SELECT NEW.tenant_id, NEW.device_id WHERE TG_OP <> 'DELETE'
        ) affected WHERE device_id IS NOT NULL ORDER BY tenant_id, device_id
    LOOP
        PERFORM operations.invalidate_computer_client_ownership(target.tenant_id, target.device_id);
    END LOOP;
    RETURN NULL;
END
$fn$;

CREATE TRIGGER computer_client_observation_dirty
AFTER INSERT OR UPDATE OR DELETE ON operations.entity_observation_current
FOR EACH ROW EXECUTE FUNCTION operations.invalidate_computer_client_observation();

CREATE FUNCTION operations.invalidate_computer_client_device() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
BEGIN
    IF TG_OP = 'INSERT' OR OLD.client_id IS DISTINCT FROM NEW.client_id THEN
        PERFORM operations.invalidate_computer_client_ownership(NEW.tenant_id, NEW.id);
    END IF;
    RETURN NULL;
END
$fn$;

CREATE TRIGGER computer_client_device_dirty
AFTER INSERT OR UPDATE OF client_id ON operations.devices
FOR EACH ROW EXECUTE FUNCTION operations.invalidate_computer_client_device();

CREATE FUNCTION operations.invalidate_computer_client_decision() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    target record;
BEGIN
    IF TG_OP = 'UPDATE'
       AND (OLD.tenant_id, OLD.device_id, OLD.dimension, OLD.value, OLD.version)
           IS NOT DISTINCT FROM
           (NEW.tenant_id, NEW.device_id, NEW.dimension, NEW.value, NEW.version) THEN
        RETURN NULL;
    END IF;
    FOR target IN
        SELECT DISTINCT tenant_id, device_id FROM (
            SELECT OLD.tenant_id, OLD.device_id
             WHERE TG_OP <> 'INSERT'
               AND OLD.dimension IN ('client_conflict_accepted', 'client_ownership_choice')
            UNION ALL
            SELECT NEW.tenant_id, NEW.device_id
             WHERE TG_OP <> 'DELETE'
               AND NEW.dimension IN ('client_conflict_accepted', 'client_ownership_choice')
        ) affected WHERE device_id IS NOT NULL ORDER BY tenant_id, device_id
    LOOP
        PERFORM operations.invalidate_computer_client_ownership(target.tenant_id, target.device_id);
    END LOOP;
    RETURN NULL;
END
$fn$;

CREATE TRIGGER computer_client_decision_dirty
AFTER INSERT OR UPDATE OR DELETE ON operations.device_operator_decisions
FOR EACH ROW EXECUTE FUNCTION operations.invalidate_computer_client_decision();

CREATE FUNCTION operations.invalidate_computer_client_roaming() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    target record;
BEGIN
    FOR target IN
        SELECT DISTINCT observation.tenant_id, observation.device_id
          FROM operations.entity_observation_current observation
          JOIN (
              SELECT OLD.tenant_id, OLD.source_instance_id, OLD.external_id
               WHERE TG_OP <> 'INSERT'
              UNION
              SELECT NEW.tenant_id, NEW.source_instance_id, NEW.external_id
               WHERE TG_OP <> 'DELETE'
          ) roaming ON roaming.tenant_id = observation.tenant_id
                   AND roaming.source_instance_id = observation.source_instance_id
                   AND roaming.external_id = observation.external_id
         WHERE observation.device_id IS NOT NULL
         ORDER BY observation.tenant_id, observation.device_id
    LOOP
        PERFORM operations.invalidate_computer_client_ownership(target.tenant_id, target.device_id);
    END LOOP;
    RETURN NULL;
END
$fn$;

CREATE TRIGGER computer_client_roaming_dirty
AFTER INSERT OR UPDATE OR DELETE ON operations.identity_roaming_records
FOR EACH ROW EXECUTE FUNCTION operations.invalidate_computer_client_roaming();

REVOKE ALL ON FUNCTION operations.invalidate_computer_client_ownership(bigint, uuid),
    operations.invalidate_computer_client_observation(),
    operations.invalidate_computer_client_device(),
    operations.invalidate_computer_client_decision(),
    operations.invalidate_computer_client_roaming() FROM PUBLIC, operations_app,
    operations_readonly, ninja_ingest;
"""

REVERSE_SQL = r"""
DROP TRIGGER computer_client_roaming_dirty ON operations.identity_roaming_records;
DROP TRIGGER computer_client_decision_dirty ON operations.device_operator_decisions;
DROP TRIGGER computer_client_observation_dirty ON operations.entity_observation_current;
DROP TRIGGER computer_client_device_dirty ON operations.devices;
DROP FUNCTION operations.invalidate_computer_client_roaming();
DROP FUNCTION operations.invalidate_computer_client_decision();
DROP FUNCTION operations.invalidate_computer_client_observation();
DROP FUNCTION operations.invalidate_computer_client_device();
DROP FUNCTION operations.invalidate_computer_client_ownership(bigint, uuid);
DROP TABLE operations.computer_client_ownership;
DELETE FROM operations.change_history_registry WHERE table_name = 'computer_client_ownership';
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0400_association_refreshes_computer_values"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
