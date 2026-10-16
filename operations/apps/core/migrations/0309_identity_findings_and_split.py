"""Identity findings and operator decisions for ADR-0032.

* Finding type ``two_machines_on_one_computer`` (policy
  ``conditions-registry-3``): a Computer whose active agent or VM records
  report two usable serials or VM UUIDs, or two agents of one source online at
  once under different names. The action splits the records the finding
  proposes off the Computer.
* Existing types reused with corrected wording: ``duplicate_device_records``
  now means same-name Computers with nothing linking them (merge, or confirm
  separate); ``identity_conflict`` no longer cites "hostname alone never
  merges"; ``shared_serial`` names what remains after automatic merges.
* The policy makes ``duplicate_device_records`` active again (it was marked
  historical when its producer stopped firing).
* Operator decision dimensions ``identity_separate`` (Computers an operator
  confirmed are different machines) and ``identity_excluded_records`` (records
  an operator split off a Computer; the matcher treats them as a hard
  conflict for that Computer).
* ``operations.split_computer_records`` and
  ``operations.confirm_computers_separate``: the two operator actions, each
  recorded as one change action.
"""

from __future__ import annotations

import hashlib
import json
from typing import ClassVar

from django.db import migrations

POLICY_VERSION = "conditions-registry-3"
NEW_TYPE = "two_machines_on_one_computer"

FORWARD_SQL = r"""
-- compute_finding_state runs once per assessed finding when a policy version
-- changes. JIT compilation made every call cost about 3.5 s against 74 ms
-- without it (production 2026-10-16), so the first evaluator run after 0306
-- took hours and held its locks. The new policy below would repeat it.
DO $jit$
BEGIN
    IF to_regprocedure('operations.compute_finding_state(uuid[])') IS NOT NULL THEN
        ALTER FUNCTION operations.compute_finding_state(uuid[]) SET jit = off;
    END IF;
END
$jit$;

SELECT operations.begin_change(
    'identity_findings.register',
    'ADR-0032: identity findings and the split and confirm-separate actions.',
    '{"migration": "0309_identity_findings_and_split"}'::jsonb,
    'migration', NULL, 'operations.migrations', '0309', NULL, true);

-- The duplicate record check now groups per Computer (ADR-0032). Rows keyed
-- the old way (per client and name) were never assessed as measured, so they
-- could not clear; they are closed here with the reason, and any duplicate
-- still present is raised again under its per-Computer key on the next run.
UPDATE operations.admin_findings
   SET status = 'resolved', resolved_at = now(),
       details = details || jsonb_build_object(
           'resolved_reason',
           'Replaced by the per-Computer duplicate record check (ADR-0032, migration 0309).')
 WHERE finding_type_id = (SELECT id FROM operations.finding_types
                           WHERE name = 'duplicate_platform_record')
   AND condition_key LIKE 'duplicate\_record:%%'
   AND status IN ('open', 'acknowledged', 'investigating', 'suppressed');

INSERT INTO operations.operator_decision_dimensions
    (name, entity_type, value_type, allowed_values, description, enabled)
VALUES
    ('identity_separate', 'device', 'json', NULL,
     'Computers an operator confirmed are different machines: a JSON list of Computer ids. '
     || 'They are never proposed as duplicates of each other again.', TRUE),
    ('identity_excluded_records', 'device', 'json', NULL,
     'Source records an operator split off this Computer: a JSON list of "platform|entity_key". '
     || 'Matching treats them as a hard conflict for this Computer.', TRUE)
ON CONFLICT (name) DO NOTHING;

UPDATE operations.finding_types
   SET display_name = 'Computers that look like one machine',
       description = 'Two or more Computers in a client share a name and nothing links or '
           || 'separates them (no shared or conflicting serial number or VM UUID). Merge '
           || 'them, or confirm they are different machines.',
       issue_group = 'Duplicate computers',
       source_module = 'identity.findings'
 WHERE name = 'duplicate_device_records';
UPDATE operations.finding_types
   SET description = 'Two or more Computers in the same client share a name but their serial '
           || 'numbers or VM UUIDs show they are different machines. Rename one at the '
           || 'source, or confirm they are separate.'
 WHERE name = 'identity_conflict';
UPDATE operations.finding_types
   SET description = 'Two or more Computers in the same client report the same serial number '
           || 'but could not be merged automatically: two live installs of one source (a '
           || 'cloned machine) or a Computer that already holds two machines. Review them.'
 WHERE name = 'shared_serial';

CREATE FUNCTION operations.split_computer_records(
    p_device uuid,
    p_observation_ids uuid[],
    p_reason text,
    p_actor_id bigint DEFAULT NULL
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    d operations.devices%ROWTYPE;
    v_keys jsonb;
    v_existing jsonb;
    v_rows integer;
BEGIN
    SELECT * INTO d FROM operations.devices WHERE id = p_device AND deleted_at IS NULL FOR UPDATE;
    IF d.id IS NULL THEN
        RAISE EXCEPTION 'split_computer_records: unknown or deleted Computer';
    END IF;
    IF p_reason IS NULL OR p_reason = '' THEN
        RAISE EXCEPTION 'split_computer_records: a reason is required';
    END IF;
    PERFORM set_config('operations.tenant_id', d.tenant_id::text, true);
    SELECT coalesce(jsonb_agg(DISTINCT eo.platform || '|' || eo.entity_key), '[]'::jsonb)
      INTO v_keys
      FROM operations.entity_observation_current eo
     WHERE eo.tenant_id = d.tenant_id AND eo.device_id = d.id
       AND eo.observation_id = ANY(p_observation_ids);
    IF jsonb_array_length(v_keys) = 0 THEN
        RAISE EXCEPTION 'split_computer_records: none of the records belong to this Computer';
    END IF;
    PERFORM operations.begin_change(
        'computer.split_records', p_reason,
        jsonb_build_object('device_id', d.id, 'records', v_keys),
        'operator', p_actor_id, 'operations.ui', '', d.tenant_id, true);

    SELECT value INTO v_existing FROM operations.device_operator_decisions
     WHERE tenant_id = d.tenant_id AND device_id = d.id AND dimension = 'identity_excluded_records';
    INSERT INTO operations.device_operator_decisions
        (id, version, tenant_id, device_id, dimension, value, reason, set_by, set_at)
    VALUES (gen_random_uuid(), 1, d.tenant_id, d.id, 'identity_excluded_records',
            (SELECT jsonb_agg(DISTINCT k) FROM jsonb_array_elements_text(
                 coalesce(v_existing, '[]'::jsonb) || v_keys) AS e(k)),
            p_reason, coalesce('user:' || p_actor_id::text, 'operator'), now())
    ON CONFLICT (tenant_id, device_id, dimension) DO UPDATE
       SET value = EXCLUDED.value, reason = EXCLUDED.reason, set_by = EXCLUDED.set_by,
           set_at = EXCLUDED.set_at, version = operations.device_operator_decisions.version + 1;

    -- Detached records are matched again by the resolver; the decision above
    -- keeps them off this Computer, so they join another Computer or a new one.
    UPDATE operations.entity_observation_current
       SET device_id = NULL
     WHERE tenant_id = d.tenant_id AND device_id = d.id
       AND observation_id = ANY(p_observation_ids);
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END
$fn$;

CREATE FUNCTION operations.confirm_computers_separate(
    p_device_ids uuid[],
    p_reason text,
    p_actor_id bigint DEFAULT NULL
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_tenant bigint;
    v_clients integer;
    v_device uuid;
    v_existing jsonb;
    v_count integer := 0;
BEGIN
    IF cardinality(p_device_ids) < 2 THEN
        RAISE EXCEPTION 'confirm_computers_separate: at least two Computers are required';
    END IF;
    IF p_reason IS NULL OR p_reason = '' THEN
        RAISE EXCEPTION 'confirm_computers_separate: a reason is required';
    END IF;
    SELECT min(tenant_id), count(DISTINCT client_id) INTO v_tenant, v_clients
      FROM operations.devices WHERE id = ANY(p_device_ids) AND deleted_at IS NULL;
    IF v_tenant IS NULL OR v_clients <> 1 THEN
        RAISE EXCEPTION 'confirm_computers_separate: current Computers of one client are required';
    END IF;
    PERFORM set_config('operations.tenant_id', v_tenant::text, true);
    PERFORM operations.begin_change(
        'computer.confirm_separate', p_reason,
        jsonb_build_object('device_ids', to_jsonb(p_device_ids)),
        'operator', p_actor_id, 'operations.ui', '', v_tenant, true);
    FOREACH v_device IN ARRAY p_device_ids LOOP
        SELECT value INTO v_existing FROM operations.device_operator_decisions
         WHERE tenant_id = v_tenant AND device_id = v_device AND dimension = 'identity_separate';
        INSERT INTO operations.device_operator_decisions
            (id, version, tenant_id, device_id, dimension, value, reason, set_by, set_at)
        VALUES (gen_random_uuid(), 1, v_tenant, v_device, 'identity_separate',
                (SELECT jsonb_agg(DISTINCT k) FROM jsonb_array_elements_text(
                     coalesce(v_existing, '[]'::jsonb)
                     || (SELECT jsonb_agg(x::text) FROM unnest(p_device_ids) x
                          WHERE x <> v_device)) AS e(k)),
                p_reason, coalesce('user:' || p_actor_id::text, 'operator'), now())
        ON CONFLICT (tenant_id, device_id, dimension) DO UPDATE
           SET value = EXCLUDED.value, reason = EXCLUDED.reason, set_by = EXCLUDED.set_by,
               set_at = EXCLUDED.set_at, version = operations.device_operator_decisions.version + 1;
        v_count := v_count + 1;
    END LOOP;
    RETURN v_count;
END
$fn$;

REVOKE ALL ON FUNCTION operations.split_computer_records(uuid, uuid[], text, bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.split_computer_records(uuid, uuid[], text, bigint) TO operations_app;
REVOKE ALL ON FUNCTION operations.confirm_computers_separate(uuid[], text, bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.confirm_computers_separate(uuid[], text, bigint) TO operations_app;
"""


def build_policy(active: dict) -> dict:
    policy = json.loads(json.dumps(active))
    policy["version"] = POLICY_VERSION
    names = {item.get("name") for item in policy["definitions"]}
    # conditions-registry-1 retired duplicate_device_records; ADR-0032 produces it again.
    for item in policy["definitions"]:
        if item.get("name") == "duplicate_device_records":
            item["lifecycle"] = "active"
    if NEW_TYPE not in names:
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
            ) VALUES (%s, 'high', 'entity', 'identity.findings', 'device', TRUE, TRUE, FALSE,
                      FALSE, 'global', '', '', %s, %s, 'Inventory', 'Computer identity', 75,
                      FALSE, '[]'::jsonb, '')
            ON CONFLICT (name) DO NOTHING
            """,
            (
                NEW_TYPE,
                "One Computer holds records of two machines: its agent or VM records report "
                "two serial numbers or VM UUIDs, or two agents of one source are online under "
                "different names. Split the proposed records off.",
                "Two machines on one Computer",
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
        ("operations", "0308_computer_merge_and_split"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
        migrations.RunPython(register_finding_type, migrations.RunPython.noop),
    ]
