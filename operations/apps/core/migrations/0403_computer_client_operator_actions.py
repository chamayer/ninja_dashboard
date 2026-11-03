"""Record scoped human ownership choices and queue source-group changes.

The remaining reader transition is required before these migrations ship.
"""

import importlib
from typing import ClassVar

from django.db import migrations


def _function(sql: str, start: str, end: str) -> str:
    begin = sql.index(start)
    return sql[begin : sql.index(end, begin) + len(end)]


def _replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"Computer ownership action contract changed: {old[:80]}")
    return text.replace(old, new)


def _old_actions() -> tuple[str, str, str]:
    actions = importlib.import_module("apps.core.migrations.0340_computer_client_conflict").FORWARD_SQL
    group = importlib.import_module("apps.core.migrations.0374_source_association_authority").CONVERTED_SQL
    accept = _function(actions, "CREATE FUNCTION operations.accept_computer_client_conflict(", "$fn$;")
    move = _function(actions, "CREATE FUNCTION operations.move_computer_to_client(", "$fn$;")
    source_group = _function(
        group, "CREATE OR REPLACE FUNCTION operations.move_client_source_group_v1(", "$function$;"
    )
    return accept.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1), (
        move.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
    ), source_group


CHOICE_SQL = r"""
CREATE FUNCTION operations.record_computer_client_choice(
    p_tenant bigint, p_device uuid, p_client uuid, p_reason text, p_actor bigint,
    p_record_keys text[] DEFAULT NULL
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_evidence jsonb;
BEGIN
    IF p_tenant IS DISTINCT FROM nullif(current_setting('operations.tenant_id', true), '')::bigint
       OR NOT EXISTS (SELECT 1 FROM operations.devices
                       WHERE tenant_id = p_tenant AND id = p_device AND deleted_at IS NULL)
       OR NOT EXISTS (SELECT 1 FROM operations.clients
                       WHERE tenant_id = p_tenant AND id = p_client AND deleted_at IS NULL)
       OR length(btrim(coalesce(p_reason, ''))) = 0 THEN
        RAISE EXCEPTION 'record_computer_client_choice: invalid decision';
    END IF;
    SELECT coalesce(jsonb_agg(jsonb_build_object(
               'observation_id', observation.observation_id,
               'client_id', operations.computer_client_independent_evidence(
                   observation.tenant_id, observation.observation_id))
               ORDER BY observation.observation_id), '[]'::jsonb)
      INTO v_evidence FROM operations.entity_observation_current observation
     WHERE observation.tenant_id = p_tenant AND observation.device_id = p_device
       AND observation.active AND observation.entity_type <> 'org'
       AND (p_record_keys IS NULL OR
            'record:' || observation.platform || '|' || observation.entity_key = ANY(p_record_keys))
       AND NOT operations.is_companion_stream(observation.tenant_id,
               observation.source_instance_id, observation.external_namespace)
       AND NOT EXISTS (SELECT 1 FROM operations.identity_roaming_records roaming
                        WHERE roaming.tenant_id = observation.tenant_id
                          AND roaming.source_instance_id = observation.source_instance_id
                          AND roaming.external_id = observation.external_id);
    INSERT INTO operations.device_operator_decisions
        (id, version, tenant_id, device_id, dimension, value, reason, set_by, set_at)
    VALUES (gen_random_uuid(), 1, p_tenant, p_device, 'client_ownership_choice',
            jsonb_build_object('client_id', p_client, 'evidence', v_evidence),
            p_reason, coalesce('user:' || p_actor::text, 'operator'), now())
    ON CONFLICT (tenant_id, device_id, dimension) DO UPDATE
       SET value = CASE
               WHEN operations.device_operator_decisions.value ->> 'client_id' = p_client::text
                    AND p_record_keys IS NOT NULL
               THEN jsonb_build_object('client_id', p_client, 'evidence',
                    coalesce((SELECT jsonb_agg(saved)
                                FROM jsonb_array_elements(coalesce(
                                    operations.device_operator_decisions.value -> 'evidence', '[]'::jsonb)) saved
                               WHERE NOT EXISTS (
                                   SELECT 1 FROM jsonb_array_elements(v_evidence) current_evidence
                                    WHERE current_evidence ->> 'observation_id' = saved ->> 'observation_id'
                               )), '[]'::jsonb) || v_evidence)
               ELSE EXCLUDED.value END,
           reason = EXCLUDED.reason, set_by = EXCLUDED.set_by, set_at = EXCLUDED.set_at,
           version = operations.device_operator_decisions.version + 1;
END
$fn$;
REVOKE ALL ON FUNCTION operations.record_computer_client_choice(bigint, uuid, uuid, text, bigint, text[])
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
"""


def _forward() -> str:
    accept, move, source_group = _old_actions()
    accept = _replace_once(
        accept,
        "    RETURN cardinality(p_keys);",
        """    IF EXISTS (SELECT 1 FROM unnest(p_keys) key WHERE key LIKE 'record:%') THEN
        PERFORM operations.record_computer_client_choice(
            d.tenant_id, d.id, d.client_id, p_reason, p_actor_id, p_keys);
    END IF;
    RETURN cardinality(p_keys);""",
    )
    move = _replace_once(
        move,
        "    UPDATE operations.computer_name_collisions SET client_id = p_client\n"
        "     WHERE tenant_id = d.tenant_id AND device_id = d.id;",
        "    UPDATE operations.computer_name_collisions SET client_id = p_client\n"
        "     WHERE tenant_id = d.tenant_id AND device_id = d.id;\n"
        "    PERFORM operations.record_computer_client_choice(\n"
        "        d.tenant_id, d.id, p_client, p_reason, p_actor_id, NULL);",
    )
    old_loop = """        IF EXISTS (SELECT 1 FROM operations.entity_observation_current o
                    WHERE o.tenant_id = p_tenant_id AND o.device_id = v_device AND o.active
                      AND o.client_id IS DISTINCT FROM p_client_id
                      AND o.client_id IS NOT NULL) THEN
            v_mixed := v_mixed + 1;
        ELSE
            PERFORM operations.move_computer_to_client(v_device, p_client_id, p_reason, p_actor_id);
            v_moved := v_moved + 1;
        END IF;"""
    source_group = _replace_once(
        source_group,
        old_loop,
        """        -- Observation triggers have invalidated this Computer. The shared
        -- projector runs in the resolver with its findings guard.
        v_mixed := v_mixed + 1;""",
    )
    return CHOICE_SQL + "\n" + accept + "\n" + move + "\n" + source_group + "\n"


def _reverse() -> str:
    accept, move, source_group = _old_actions()
    return (
        "DO $reverse$ BEGIN IF EXISTS (SELECT 1 FROM operations.device_operator_decisions "
        "WHERE dimension = 'client_ownership_choice') THEN RAISE EXCEPTION "
        "'Cannot reverse Computer ownership while explicit choices exist'; END IF; END $reverse$;\n"
        + accept + "\n" + move + "\n" + source_group + "\n"
        + "DROP FUNCTION operations.record_computer_client_choice(bigint, uuid, uuid, text, bigint, text[]);\n"
    )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0402_computer_client_projector"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(_forward(), _reverse())]
