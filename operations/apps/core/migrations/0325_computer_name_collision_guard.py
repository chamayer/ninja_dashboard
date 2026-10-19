"""Name-collision guard for Computer naming (ADR-0034 activation review).

The activation review (2026-10-19, production shadow) found seven renames
that would give a Computer a name another live Computer of the client
already holds: duplicate Hudu assets for lab220-34/21/22, a split R-U-ON
monitor (utaw-82-mgt03), a split LogMeIn record (cp-re01 / donnarullo), a
duplicate cluster (2march2016vm) and a clone fragment taking its image's
name (citrixapp36 / citrixappmcs). Each is identity work, not naming.

``computer_names`` now keeps the current name under the rule
``kept_collision`` when the proposed name key collides, and returns the
rejected name, rule and record and the conflicting Computer IDs as evidence.
Names are compared on the normalized key, within the client, against every
live Computer's current name and every name proposed in the same pass. A
collision ends only by source cleanup, a real merge, or an explicit
name-collision confirmation (``name_collision_confirmed``, registered here
as a device operator decision approving one proposed name;
``collision_confirmed`` on an operator name). "Confirmed separate
machines" does not end it: separate machines can still be misnamed. No
uniqueness constraint: duplicate names can be separate machines or
unresolved identity work.

``operations.computer_name_collisions`` holds the collisions of the latest
shadow pass (``refresh_computer_name_collisions``); identity findings raise a
review-only ``computer_name_collision`` issue per group of Computers, keyed
by their IDs, with no Merge or Confirm-separate action: a collision is not
evidence that the Computers are one machine. Nothing here writes a Computer
name.
"""

from __future__ import annotations

import hashlib
import json
from typing import ClassVar

from django.db import migrations

POLICY_VERSION = "conditions-registry-8"
NEW_TYPE = "computer_name_collision"

FORWARD_SQL = r"""
SELECT operations.begin_change(
    'operator_decision_dimension.add',
    'ADR-0034 5a: an operator may confirm one proposed name for one Computer despite a collision.',
    '{"migration": "0325_computer_name_collision_guard"}'::jsonb,
    'migration', NULL, 'operations.migrations', '0325', NULL, true);

-- Approves one normalized proposed name for one Computer: {"name": "<name>"}.
-- It ends that Computer's collision for that name only; any other proposed
-- name is still guarded.
INSERT INTO operations.operator_decision_dimensions
    (name, entity_type, value_type, allowed_values, description, enabled)
VALUES
    ('name_collision_confirmed', 'device', 'json', NULL,
     'An operator confirmed this Computer may take one proposed name although another live '
     || 'Computer of the client has it: {"name": "<proposed name>"}. Applies to that name '
     || 'only (compared on the normalized key); it does not confirm the Computers are one '
     || 'machine or separate machines.', TRUE),
    ('name', 'device', 'json', NULL,
     'The operator''s name for this Computer: {"name": "<short name>"}, optionally '
     || '"collision_confirmed": true when another live Computer of the client has that name. '
     || 'Clearing it returns the Computer to its automatic name.', TRUE)
ON CONFLICT (name) DO NOTHING;

DROP FUNCTION operations.computer_name_shadow(bigint);
DROP FUNCTION operations.computer_names(bigint, uuid[]);

CREATE FUNCTION operations.computer_names(p_tenant bigint, p_devices uuid[] DEFAULT NULL)
RETURNS TABLE (device_id uuid, name text, name_rule text, observation_id uuid,
               rejected_name text, rejected_rule text, rejected_observation_id uuid,
               conflicting_device_ids uuid[])
LANGUAGE sql STABLE
AS $fn$
WITH scope AS (
    -- Collisions are judged within a client, so a scoped call computes the
    -- whole client of each requested Computer.
    SELECT DISTINCT d.client_id
      FROM operations.devices d
     WHERE d.tenant_id = p_tenant AND d.deleted_at IS NULL AND d.id = ANY (p_devices)
), dev AS (
    SELECT d.id, d.client_id, d.lifecycle_status::text AS lifecycle_status,
           d.canonical_hostname::text AS canonical_hostname,
           regexp_replace(lower(d.canonical_hostname), '[^a-z0-9]', '', 'g') AS current_key
      FROM operations.devices d
     WHERE d.tenant_id = p_tenant AND d.deleted_at IS NULL
       AND (p_devices IS NULL OR d.client_id IN (SELECT client_id FROM scope))
), rec AS (
    SELECT eo.device_id, eo.observation_id, eo.source_instance_id, eo.external_id,
           eo.entity_type, eo.last_seen_at,
           coalesce(k.kind, 'label') AS kind, coalesce(k.rank, 0) AS rank,
           f.name_short, f.name_key,
           eo.active AND coalesce(lc.record_lifecycle, '') <> 'archived' AS is_current,
           -- The record's own online, power and contact evidence (not the
           -- per-source aggregate of device_agent_presence_current, which
           -- would let one live record make a stale duplicate look reporting).
           eo.active AND coalesce(lc.record_lifecycle, '') <> 'archived' AND (
               lower(coalesce(eo.canonical_data ->> 'is_online', '')) IN ('true', 't', '1', 'yes', 'online')
               OR lower(coalesce(eo.canonical_data ->> 'power_state', '')) = 'poweredon'
               OR (eo.canonical_data ->> 'last_seen_at')::timestamptz > now() - interval '30 days') AS reporting
      FROM dev
      JOIN operations.entity_observation_current eo
        ON eo.tenant_id = p_tenant AND eo.device_id = dev.id
      LEFT JOIN operations.source_name_kinds k
        ON k.platform = eo.platform AND k.record_type = eo.entity_type
      LEFT JOIN operations.v_device_source_record_lifecycle_current lc
        ON lc.observation_id = eo.observation_id
     CROSS JOIN LATERAL operations.record_name_forms(
          eo.platform, eo.entity_type,
          coalesce(nullif(eo.canonical_data ->> 'hostname', ''), eo.canonical_data ->> 'guest_name'),
          eo.canonical_data ->> 'domain') f
     WHERE eo.entity_key NOT LIKE 'device-health:%'
       AND f.name_short IS NOT NULL
       -- Roaming records carry no name (ADR-0034 section 3).
       AND NOT EXISTS (SELECT 1 FROM operations.identity_roaming_records rr
                        WHERE rr.tenant_id = eo.tenant_id
                          AND rr.source_instance_id = eo.source_instance_id
                          AND rr.external_id = eo.external_id)
), ruled AS (
    -- 1 reporting_os, 2 silent_os, 4 withdrawn_os, 5 current_label, 6 withdrawn_label;
    -- 3 (stable_os) is decided below.
    SELECT rec.*,
           CASE WHEN kind = 'os_name' AND reporting THEN 1
                WHEN kind = 'os_name' AND is_current THEN 2
                WHEN kind = 'os_name' THEN 4
                WHEN is_current THEN 5
                ELSE 6 END AS step
      FROM rec
), best AS (
    -- Current records by rank; withdrawn records most recently seen first.
    SELECT DISTINCT ON (ruled.device_id) ruled.*
      FROM ruled
     ORDER BY ruled.device_id, ruled.step,
              CASE WHEN ruled.step IN (4, 6) THEN ruled.last_seen_at END DESC NULLS LAST,
              ruled.rank DESC, ruled.last_seen_at DESC NULLS LAST, ruled.observation_id
), longer AS (
    -- The Windows 15-character cut gives way to the one longer current OS name
    -- of the same Computer that starts with it.
    SELECT b.device_id, min(o.name_short) AS name_short,
           (array_agg(o.observation_id ORDER BY o.rank DESC, o.observation_id))[1] AS observation_id
      FROM best b
      JOIN ruled o ON o.device_id = b.device_id AND o.step IN (1, 2)
       AND length(o.name_short) > 15 AND left(o.name_short, 15) = b.name_short
     WHERE b.step IN (1, 2) AND length(b.name_short) = 15
     GROUP BY b.device_id
    HAVING count(DISTINCT o.name_short) = 1
), stable AS (
    -- With no current OS record, the current name stays when one of the
    -- Computer's OS records ever reported it.
    SELECT DISTINCT ON (dev.id) dev.id AS device_id, r.observation_id
      FROM dev
      JOIN best b ON b.device_id = dev.id AND b.step >= 4 AND b.name_key <> dev.current_key
      JOIN ruled r ON r.device_id = dev.id AND r.kind = 'os_name'
      JOIN operations.entity_observation_history h
        ON h.tenant_id = p_tenant AND h.source_instance_id = r.source_instance_id
       AND h.external_id = r.external_id AND h.entity_type = r.entity_type
     CROSS JOIN LATERAL operations.record_name_forms(
          h.platform, h.entity_type,
          coalesce(nullif(h.material_data ->> 'hostname', ''), h.material_data ->> 'guest_name'),
          h.material_data ->> 'domain') hf
     WHERE hf.name_key = dev.current_key
     ORDER BY dev.id, r.last_seen_at DESC NULLS LAST, r.observation_id
), operator_name AS (
    SELECT DISTINCT ON (x.device_id) x.device_id, lower(btrim(x.value ->> 'name')) AS name,
           -- An operator name that collides needs an explicit confirmation.
           coalesce((x.value ->> 'collision_confirmed')::boolean, false) AS collision_confirmed
      FROM operations.device_operator_decisions x
      JOIN dev ON dev.id = x.device_id
     WHERE x.tenant_id = p_tenant AND x.dimension = 'name'
       AND coalesce(btrim(x.value ->> 'name'), '') <> ''
     ORDER BY x.device_id, x.set_at DESC
), proposed AS (
SELECT dev.id AS device_id, dev.client_id, dev.lifecycle_status,
       dev.canonical_hostname AS current_name, dev.current_key,
       coalesce(op.collision_confirmed, false) AS collision_confirmed,
       CASE WHEN op.device_id IS NOT NULL THEN op.name
            WHEN st.device_id IS NOT NULL OR b.device_id IS NULL THEN dev.canonical_hostname
            ELSE coalesce(l.name_short, b.name_short) END AS proposed_name,
       CASE WHEN op.device_id IS NOT NULL THEN 'operator'
            WHEN st.device_id IS NOT NULL THEN 'stable_os'
            WHEN b.device_id IS NULL THEN 'unconfirmed'
            ELSE (ARRAY['reporting_os', 'silent_os', 'stable_os', 'withdrawn_os',
                        'current_label', 'withdrawn_label'])[b.step] END AS proposed_rule,
       CASE WHEN op.device_id IS NOT NULL OR (st.device_id IS NULL AND b.device_id IS NULL) THEN NULL
            WHEN st.device_id IS NOT NULL THEN st.observation_id
            ELSE coalesce(l.observation_id, b.observation_id) END AS proposed_observation_id
  FROM dev
  LEFT JOIN operator_name op ON op.device_id = dev.id
  LEFT JOIN best b ON b.device_id = dev.id
  LEFT JOIN stable st ON st.device_id = dev.id
  LEFT JOIN longer l ON l.device_id = dev.id
), keyed AS (
    SELECT proposed.*, regexp_replace(proposed.proposed_name, '[^a-z0-9]', '', 'g') AS proposed_key
      FROM proposed
), collision_confirmed AS (
    -- An operator's explicit confirmation that this Computer may take this
    -- name although another live Computer has it. "Keep separate" is not
    -- such a confirmation: separate machines can still be misnamed.
    SELECT x.device_id,
           regexp_replace(lower(btrim(x.value ->> 'name')), '[^a-z0-9]', '', 'g') AS name_key
      FROM operations.device_operator_decisions x
     WHERE x.tenant_id = p_tenant AND x.dimension = 'name_collision_confirmed'
       AND coalesce(btrim(x.value ->> 'name'), '') <> ''
), collisions AS (
    -- Name-collision guard (ADR-0034): a rename never gives a Computer a name
    -- key another live Computer of the client holds now or is proposed in the
    -- same pass. Live: not retired, not merged (deleted_at), pending cleanup
    -- included. Judged on the whole set, so order cannot change the result.
    SELECT p.device_id, array_agg(DISTINCT y.device_id ORDER BY y.device_id) AS conflicting
      FROM keyed p
      JOIN keyed y
        ON y.client_id = p.client_id AND y.device_id <> p.device_id
       AND y.lifecycle_status <> 'retired'
       AND (y.current_key = p.proposed_key OR y.proposed_key = p.proposed_key)
     WHERE p.proposed_key <> p.current_key
       AND NOT (p.proposed_rule = 'operator' AND p.collision_confirmed)
       AND NOT EXISTS (SELECT 1 FROM collision_confirmed cc
                        WHERE cc.device_id = p.device_id AND cc.name_key = p.proposed_key)
     GROUP BY p.device_id
)
SELECT k.device_id,
       CASE WHEN c.device_id IS NULL THEN k.proposed_name ELSE k.current_name END,
       CASE WHEN c.device_id IS NULL THEN k.proposed_rule ELSE 'kept_collision' END,
       CASE WHEN c.device_id IS NULL THEN k.proposed_observation_id END,
       CASE WHEN c.device_id IS NOT NULL THEN k.proposed_name END,
       CASE WHEN c.device_id IS NOT NULL THEN k.proposed_rule END,
       CASE WHEN c.device_id IS NOT NULL THEN k.proposed_observation_id END,
       c.conflicting
  FROM keyed k
  LEFT JOIN collisions c ON c.device_id = k.device_id
 WHERE p_devices IS NULL OR k.device_id = ANY (p_devices)
$fn$;

-- The shadow reconciliation: what the writer would change. Read only.
CREATE FUNCTION operations.computer_name_shadow(p_tenant bigint)
RETURNS TABLE (device_id uuid, lifecycle_status text, current_name text, shadow_name text,
               name_rule text, observation_id uuid, outcome text)
LANGUAGE sql STABLE
AS $fn$
    SELECT d.id, d.lifecycle_status::text, d.canonical_hostname::text, n.name, n.name_rule,
           n.observation_id,
           CASE WHEN n.name_rule = 'kept_collision' THEN 'collision'
                WHEN n.name = lower(d.canonical_hostname) THEN 'same'
                WHEN regexp_replace(n.name, '[^a-z0-9]', '', 'g')
                     = regexp_replace(lower(d.canonical_hostname), '[^a-z0-9]', '', 'g') THEN 'same_key'
                ELSE 'rename' END
      FROM operations.computer_names(p_tenant, NULL) n
      JOIN operations.devices d ON d.id = n.device_id
$fn$;

CREATE TABLE operations.computer_name_collisions (
    tenant_id bigint NOT NULL,
    device_id uuid NOT NULL,
    client_id uuid NOT NULL,
    proposed_name text NOT NULL,
    rejected_rule text NOT NULL,
    rejected_observation_id uuid NULL,
    conflicting_device_ids uuid[] NOT NULL,
    computed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, device_id)
);
ALTER TABLE operations.computer_name_collisions ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_read ON operations.computer_name_collisions FOR SELECT
    USING (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint);
REVOKE ALL ON operations.computer_name_collisions FROM PUBLIC;
GRANT SELECT ON operations.computer_name_collisions TO operations_app, operations_readonly, ninja_ingest;

INSERT INTO operations.change_history_registry (
    table_name, classification, reason, recorded_columns, secret_columns, key_columns,
    computer_column, computer_condition_column, computer_condition_value, client_column,
    is_global, capture
) VALUES (
    'computer_name_collisions', 'exempt', 'derived from the hourly shadow naming pass; rebuildable',
    '{}'::text[], '{}'::text[], '{}'::text[], NULL, NULL, NULL, NULL, FALSE, NULL
) ON CONFLICT (table_name) DO NOTHING;

-- Replaces the session tenant's collisions with those of a fresh pass.
CREATE FUNCTION operations.refresh_computer_name_collisions(p_tenant bigint)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_count integer;
BEGIN
    IF p_tenant IS NULL
       OR p_tenant IS DISTINCT FROM nullif(current_setting('operations.tenant_id', true), '')::bigint THEN
        RAISE EXCEPTION 'refresh_computer_name_collisions needs the session tenant';
    END IF;
    DELETE FROM operations.computer_name_collisions WHERE tenant_id = p_tenant;
    INSERT INTO operations.computer_name_collisions
        (tenant_id, device_id, client_id, proposed_name, rejected_rule, rejected_observation_id,
         conflicting_device_ids)
    SELECT p_tenant, n.device_id, d.client_id, n.rejected_name, n.rejected_rule,
           n.rejected_observation_id, n.conflicting_device_ids
      FROM operations.computer_names(p_tenant, NULL) n
      JOIN operations.devices d ON d.id = n.device_id
     WHERE n.name_rule = 'kept_collision';
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END
$fn$;

REVOKE ALL ON FUNCTION operations.computer_names(bigint, uuid[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.computer_name_shadow(bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.refresh_computer_name_collisions(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.computer_names(bigint, uuid[]),
                          operations.computer_name_shadow(bigint)
    TO operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.refresh_computer_name_collisions(bigint) TO ninja_ingest;
"""


def build_policy(active: dict) -> dict:
    policy = json.loads(json.dumps(active))
    policy["version"] = POLICY_VERSION
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
            ) VALUES (%s, 'medium', 'entity', 'identity.findings', 'device', FALSE, TRUE, FALSE,
                      FALSE, 'global', '', '', %s, %s, 'Inventory', 'Duplicate computers', 55,
                      FALSE, '[]'::jsonb, '')
            ON CONFLICT (name) DO NOTHING
            """,
            (
                NEW_TYPE,
                "A Computer's records name it like another live Computer of the client, so it "
                "keeps its current name. This is not evidence that they are one machine. Clean "
                "up the source record, merge the Computers if they are one machine, or confirm "
                "the name.",
                "Name already used by another Computer",
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
        ("operations", "0324_retire_undeclared_schedules"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
        migrations.RunPython(register_finding_type, migrations.RunPython.noop),
    ]
