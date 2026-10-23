"""One finding for a Computer linked to more than one client (ADR-0040).

* Finding type ``computer_client_conflict`` (policy ``conditions-registry-10``):
  a Computer whose active records come from another client's source group, or
  whose usable serial a live Computer of another client also reports. One per
  Computer; the producer is ``ingest.identity.findings``. It replaces
  ``cross_client_serial``, whose open findings are closed here with the reason;
  the policy marks it historical.
* Operator decision dimension ``client_conflict_accepted``: the evidence keys an
  operator kept as they are (intended, or different machines). New evidence
  raises the finding again.
* ``operations.accept_computer_client_conflict`` records that decision.
* ``operations.move_computer_to_client`` moves a Computer and every live copy
  of its client: its entity, its OS installation entities and rows (a trigger
  requires them to match), its findings, software installations and
  decisions, Windows servicing state and name collisions. History tables keep
  what they recorded, and source records keep their group's client.
"""

from __future__ import annotations

import hashlib
import json
from typing import ClassVar

from django.db import migrations

POLICY_VERSION = "conditions-registry-10"
NEW_TYPE = "computer_client_conflict"
REPLACED_TYPE = "cross_client_serial"

FORWARD_SQL = r"""
SELECT operations.begin_change(
    'computer_client_conflict.register',
    'ADR-0040: one finding for a Computer linked to more than one client.',
    '{"migration": "0340_computer_client_conflict"}'::jsonb,
    'migration', NULL, 'operations.migrations', '0340', NULL, true);

INSERT INTO operations.operator_decision_dimensions
    (name, entity_type, value_type, allowed_values, description, enabled)
VALUES
    ('client_conflict_accepted', 'device', 'json', NULL,
     'Evidence an operator kept as it is for a Computer linked to another client: a JSON '
     || 'list of keys ("record:platform|entity_key" or "serial:computer id"). New evidence '
     || 'raises the finding again.', TRUE)
ON CONFLICT (name) DO NOTHING;

UPDATE operations.findings
   SET status = 'resolved', closed_at = now(),
       finding_details = finding_details || jsonb_build_object(
           'resolved_reason',
           'Replaced by "Computer under the wrong client?" (ADR-0040, migration 0340).')
 WHERE finding_type_id = (SELECT id FROM operations.finding_types WHERE name = 'cross_client_serial')
   AND status IN ('open', 'acknowledged', 'investigating', 'suppressed');

UPDATE operations.finding_types
   SET description = 'Retired: replaced by "Computer under the wrong client?" '
           || '(computer_client_conflict, ADR-0040).'
 WHERE name = 'cross_client_serial';

CREATE FUNCTION operations.accept_computer_client_conflict(
    p_device uuid,
    p_keys text[],
    p_reason text,
    p_actor_id bigint DEFAULT NULL
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    d operations.devices%ROWTYPE;
    v_existing jsonb;
BEGIN
    SELECT * INTO d FROM operations.devices WHERE id = p_device AND deleted_at IS NULL;
    IF d.id IS NULL THEN
        RAISE EXCEPTION 'accept_computer_client_conflict: unknown or deleted Computer';
    END IF;
    IF p_reason IS NULL OR p_reason = '' THEN
        RAISE EXCEPTION 'accept_computer_client_conflict: a reason is required';
    END IF;
    IF coalesce(cardinality(p_keys), 0) = 0 THEN
        RAISE EXCEPTION 'accept_computer_client_conflict: no evidence to keep';
    END IF;
    PERFORM set_config('operations.tenant_id', d.tenant_id::text, true);
    PERFORM operations.begin_change(
        'computer.accept_client_conflict', p_reason,
        jsonb_build_object('device_id', d.id, 'evidence', to_jsonb(p_keys)),
        'operator', p_actor_id, 'operations.ui', '', d.tenant_id, true);
    SELECT value INTO v_existing FROM operations.device_operator_decisions
     WHERE tenant_id = d.tenant_id AND device_id = d.id AND dimension = 'client_conflict_accepted';
    INSERT INTO operations.device_operator_decisions
        (id, version, tenant_id, device_id, dimension, value, reason, set_by, set_at)
    VALUES (gen_random_uuid(), 1, d.tenant_id, d.id, 'client_conflict_accepted',
            (SELECT jsonb_agg(DISTINCT k) FROM jsonb_array_elements_text(
                 coalesce(v_existing, '[]'::jsonb) || to_jsonb(p_keys)) AS e(k)),
            p_reason, coalesce('user:' || p_actor_id::text, 'operator'), now())
    ON CONFLICT (tenant_id, device_id, dimension) DO UPDATE
       SET value = EXCLUDED.value, reason = EXCLUDED.reason, set_by = EXCLUDED.set_by,
           set_at = EXCLUDED.set_at, version = operations.device_operator_decisions.version + 1;
    RETURN cardinality(p_keys);
END
$fn$;

CREATE FUNCTION operations.move_computer_to_client(
    p_device uuid,
    p_client uuid,
    p_reason text,
    p_actor_id bigint DEFAULT NULL
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    d operations.devices%ROWTYPE;
    v_os_entities uuid[];
BEGIN
    SELECT * INTO d FROM operations.devices WHERE id = p_device AND deleted_at IS NULL FOR UPDATE;
    IF d.id IS NULL THEN
        RAISE EXCEPTION 'move_computer_to_client: unknown or deleted Computer';
    END IF;
    IF p_reason IS NULL OR p_reason = '' THEN
        RAISE EXCEPTION 'move_computer_to_client: a reason is required';
    END IF;
    IF d.client_id = p_client THEN
        RAISE EXCEPTION 'move_computer_to_client: the Computer already belongs to that client';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM operations.clients
                    WHERE id = p_client AND tenant_id = d.tenant_id AND deleted_at IS NULL) THEN
        RAISE EXCEPTION 'move_computer_to_client: unknown or deleted client';
    END IF;
    PERFORM set_config('operations.tenant_id', d.tenant_id::text, true);
    PERFORM operations.begin_change(
        'computer.move_client', p_reason,
        jsonb_build_object('device_id', d.id, 'from_client_id', d.client_id,
                           'to_client_id', p_client),
        'operator', p_actor_id, 'operations.ui', '', d.tenant_id, true);

    UPDATE operations.devices SET client_id = p_client WHERE id = d.id;
    UPDATE operations.entities SET client_id = p_client
     WHERE tenant_id = d.tenant_id AND id = d.entity_id;

    -- OS installations are client-scoped entities of their own; the
    -- installation row must match its entity, so the entity moves first.
    SELECT coalesce(array_agg(r.source_entity_id), '{}') INTO v_os_entities
      FROM operations.entity_relationships r
     WHERE r.tenant_id = d.tenant_id
       AND r.relationship_type_id = 'os_installation_runs_on_computer'
       AND r.target_entity_id = d.entity_id;
    UPDATE operations.entities SET client_id = p_client
     WHERE tenant_id = d.tenant_id AND id = ANY(v_os_entities);
    UPDATE operations.operating_system_installations SET client_id = p_client
     WHERE tenant_id = d.tenant_id AND entity_id = ANY(v_os_entities);

    -- A Computer's findings belong to it; the client inherits them (ADR-0040).
    UPDATE operations.findings SET client_id = p_client
     WHERE tenant_id = d.tenant_id AND subject_type = 'device' AND subject_id = d.id;
    UPDATE operations.software_installations_current SET client_id = p_client
     WHERE tenant_id = d.tenant_id AND device_id = d.id;
    UPDATE operations.software_decisions SET client_id = p_client
     WHERE tenant_id = d.tenant_id AND device_id = d.id;
    UPDATE operations.device_windows_servicing_current SET client_id = p_client
     WHERE tenant_id = d.tenant_id AND device_id = d.id;
    UPDATE operations.computer_name_collisions SET client_id = p_client
     WHERE tenant_id = d.tenant_id AND device_id = d.id;
END
$fn$;

REVOKE ALL ON FUNCTION operations.accept_computer_client_conflict(uuid, text[], text, bigint)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.accept_computer_client_conflict(uuid, text[], text, bigint)
    TO operations_app;
REVOKE ALL ON FUNCTION operations.move_computer_to_client(uuid, uuid, text, bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.move_computer_to_client(uuid, uuid, text, bigint)
    TO operations_app;
"""


def build_policy(active: dict) -> dict:
    policy = json.loads(json.dumps(active))
    policy["version"] = POLICY_VERSION
    for item in policy["definitions"]:
        if item.get("name") == REPLACED_TYPE:
            item["lifecycle"] = "historical"
    if NEW_TYPE not in {item.get("name") for item in policy["definitions"]}:
        policy["definitions"].append(
            {"name": NEW_TYPE, "rules": ["parent_open"], "lifecycle": "active"}
        )
    return policy


def digest(policy: dict) -> str:
    return hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()


def register_finding_type(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        # Every NOT NULL column without a default (production 2026-10-16).
        cursor.execute(
            """
            INSERT INTO operations.finding_types (
                name, default_severity, finding_class, source_module, subject_scope,
                creates_device_exposure, auto_resolvable, suppressed_by_approval,
                concern_signal, default_decision_scope, drilldown_evidence_key, runbook_path,
                description, display_name, issue_category, issue_group, sort_order,
                alertable, covered_by, cover_note
            ) VALUES (%s, 'high', 'entity', 'identity.findings', 'device', FALSE, TRUE, FALSE,
                      FALSE, 'global', '', '', %s, %s, 'Inventory', 'Computer identity', 70,
                      FALSE, '[]'::jsonb, '')
            ON CONFLICT (name) DO NOTHING
            """,
            (
                NEW_TYPE,
                "A source files this Computer under another client, or a Computer of another "
                "client reports the same serial number. Move the Computer, correct the source, "
                "or keep it as it is when that is intended.",
                "Computer under the wrong client?",
            ),
        )
        cursor.execute(
            "SELECT 1 FROM operations.condition_policy_versions WHERE version = %s",
            (POLICY_VERSION,),
        )
        if cursor.fetchone() is not None:
            return
        cursor.execute(
            "SELECT policy FROM operations.condition_policy_versions WHERE active "
            "ORDER BY version DESC LIMIT 1"
        )
        active = cursor.fetchone()
        if active is None:
            return
        current = json.loads(active[0]) if isinstance(active[0], str) else active[0]
        policy = build_policy(current)
        cursor.execute(
            "SELECT operations.create_condition_policy_version(%s, %s, %s::jsonb)",
            (POLICY_VERSION, digest(policy), json.dumps(policy, separators=(",", ":"))),
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0339_defer_client_mapping_supersession"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
        migrations.RunPython(register_finding_type, migrations.RunPython.noop),
    ]
