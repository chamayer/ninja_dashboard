"""Record names, name kinds and shadow Computer naming (ADR-0034, step 1).

Nothing here changes matching or writes a Computer's name:

* ``operations.source_name_kinds`` says, per source and record type, whether a
  record's name is the machine's own name (``os_name``) or a name a person
  gave it elsewhere (``label``), its rank, and an optional strip pattern.
* ``operations.record_name_forms`` is the only normalization of record names,
  applied when names are read (nothing is stored on
  ``entity_observation_current``).
* ``identity_roaming_records`` gains ``basis``: agent records that reported
  five or more names in 90 days with no usable serial and no VM UUID are
  roaming by name. They have neither, so serial and VM UUID matching do not
  change.
* ``operations.computer_names`` computes every Computer's name, rule and
  record (ADR-0034 section 5); ``operations.computer_name_shadow`` compares
  it with the stored name. Both only read.
* ``source_name_kind_unclassified`` (admin finding, policy
  ``conditions-registry-7``) reports a source and record type with names but
  no name kind.

The migration takes no lock on ``entity_observation_current`` and backfills
nothing: the roaming list is refreshed by the resolver within the hour.
"""

from __future__ import annotations

import hashlib
import json
from typing import ClassVar

from django.db import migrations

POLICY_VERSION = "conditions-registry-7"
NEW_TYPE = "source_name_kind_unclassified"

FORWARD_SQL = r"""
SELECT operations.begin_change(
    'source_name_kind.introduce',
    'ADR-0034: a record''s name is the machine''s own name or a label given elsewhere.',
    '{"migration": "0322_record_names_and_shadow_naming"}'::jsonb,
    'migration', NULL, 'operations.migrations', '0322', NULL, true);

CREATE TABLE operations.source_name_kinds (
    platform varchar(80) NOT NULL,
    record_type varchar(80) NOT NULL,
    kind varchar(8) NOT NULL CHECK (kind IN ('os_name', 'label')),
    rank smallint NOT NULL CHECK (rank > 0),
    strip_pattern text NOT NULL DEFAULT '',
    reason text NOT NULL DEFAULT '',
    PRIMARY KEY (platform, record_type),
    -- Every source has its own rank, so sources never tie.
    CONSTRAINT source_name_kinds_rank_unique UNIQUE (rank),
    -- An invalid regular expression is refused here, not at read time.
    CONSTRAINT source_name_kinds_strip_pattern_valid
        CHECK (strip_pattern = '' OR ('' ~ strip_pattern) IS NOT NULL)
);
REVOKE ALL ON operations.source_name_kinds FROM PUBLIC;
GRANT SELECT ON operations.source_name_kinds TO operations_app, operations_readonly, ninja_ingest;

INSERT INTO operations.change_history_registry (
    table_name, classification, reason, recorded_columns, secret_columns, key_columns,
    computer_column, computer_condition_column, computer_condition_value, client_column,
    is_global, capture
) VALUES (
    'source_name_kinds', 'covered', 'platform or operator decision or state',
    ARRAY['platform', 'record_type', 'kind', 'rank', 'strip_pattern', 'reason']::text[],
    '{}'::text[], ARRAY['platform', 'record_type']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'
) ON CONFLICT (table_name) DO NOTHING;
SELECT operations.enable_change_history('source_name_kinds');

INSERT INTO operations.source_name_kinds (platform, record_type, kind, rank, strip_pattern, reason) VALUES
    ('Ninja', 'agent.rmm', 'os_name', 300, '', 'Agent on the machine reports its hostname'),
    ('SentinelOne', 'agent.edr', 'os_name', 250, '', 'Agent on the machine reports its hostname'),
    ('ScreenConnect', 'agent.remote_access', 'os_name', 225, '', 'Reports the real hostname (user, 2026-10-19)'),
    ('LogMeIn', 'agent.remote_access', 'label', 150, '', 'Host name is editable (user, 2026-10-19)'),
    ('R-U-ON', 'agent.monitoring', 'label', 140, '\s*\([^)]*\)\s*$', 'Monitor name typed by a person'),
    ('Ninja', 'monitor.target', 'label', 130, '', 'Monitor name typed by a person'),
    ('Ninja', 'vm.host', 'label', 125, '', 'Label until shown to report the OS name'),
    ('Ninja', 'network.device', 'label', 120, '', 'Label until shown to report the OS name'),
    ('Ninja', 'vm.guest', 'label', 110, '\s*\([^)]*\)\s*$', 'Name of the VM in the hypervisor'),
    ('Hudu', 'cmdb.asset', 'label', 50, '\s*\([^)]*\)\s*$', 'Documentation asset name');

-- The only normalization of record names (ADR-0034 section 1). SQL, STABLE and
-- without SET clauses so the planner can inline it.
CREATE FUNCTION operations.record_name_forms(
    p_platform text, p_record_type text, p_name text, p_domain text DEFAULT NULL
) RETURNS TABLE (name_short text, name_key text, name_domain text)
LANGUAGE sql STABLE PARALLEL SAFE
AS $fn$
    SELECT s.short,
           nullif(regexp_replace(s.short, '[^a-z0-9]', '', 'g'), ''),
           CASE WHEN s.short IS NOT NULL THEN s.domain END
      FROM (
        SELECT nullif(lower(btrim(split_part(n.v, '.', 1))), '') AS short,
               nullif(lower(btrim(coalesce(nullif(substring(n.v FROM '\.(.+)$'), ''),
                                           p_domain, ''))), '') AS domain
          FROM (
            -- Whitespace runs, non-breaking spaces included, become one space.
            SELECT btrim(regexp_replace(CASE
                       -- An IPv4 address is not a name.
                       WHEN p_name ~ '^\s*\d{1,3}(\.\d{1,3}){3}\s*$' THEN ''
                       WHEN k.strip_pattern <> '' THEN regexp_replace(coalesce(p_name, ''), k.strip_pattern, '')
                       ELSE coalesce(p_name, '')
                   END, '[\s\u00a0]+', ' ', 'g')) AS v
              FROM (SELECT coalesce((SELECT snk.strip_pattern FROM operations.source_name_kinds snk
                                      WHERE snk.platform = p_platform
                                        AND snk.record_type = p_record_type), '') AS strip_pattern) k
          ) n
      ) s
$fn$;

-- A usable serial, exactly as identity matching decides it
-- (ingest/normalize.py is_usable_serial): trimmed and lower case, four or more
-- characters, not one repeated character, not an enabled rejection. NULL when
-- unusable.
CREATE FUNCTION operations.usable_serial(p_serial text) RETURNS text
LANGUAGE sql STABLE PARALLEL SAFE
AS $fn$
    SELECT s.v
      FROM (SELECT lower(btrim(p_serial)) AS v) s
     WHERE length(s.v) >= 4
       AND s.v !~ '^(.)\1*$'
       AND NOT EXISTS (SELECT 1 FROM operations.identity_value_rejections r
                        WHERE r.value_kind = 'serial' AND r.enabled
                          AND r.normalized_value = s.v)
$fn$;

-- Roaming by names (ADR-0034 section 3).
ALTER TABLE operations.identity_roaming_records
    ADD COLUMN basis varchar(8) NOT NULL DEFAULT 'serials'
        CONSTRAINT identity_roaming_records_basis CHECK (basis IN ('serials', 'names'));

CREATE OR REPLACE FUNCTION operations.refresh_identity_roaming_records(p_tenant bigint)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_count integer;
    v_names integer;
BEGIN
    DELETE FROM operations.identity_roaming_records WHERE tenant_id = p_tenant;
    -- 0318: three or more usable serials under three or more names. Serials are
    -- reduced to distinct values per record before usable_serial is applied, so
    -- the rejection check runs once per value, not once per history row.
    INSERT INTO operations.identity_roaming_records
        (tenant_id, source_instance_id, external_id, platform, serial_count, name_count, basis)
    WITH h AS (
        SELECT h.source_instance_id, h.external_id, h.platform, h.material_data
          FROM operations.entity_observation_history h
         WHERE h.tenant_id = p_tenant AND h.entity_type LIKE 'agent.%'
           AND h.entity_key NOT LIKE 'device-health:%'
    ), names AS (
        SELECT source_instance_id, external_id, min(platform) AS platform,
               count(DISTINCT lower(material_data ->> 'hostname')) AS name_count
          FROM h GROUP BY 1, 2
        HAVING count(DISTINCT lower(material_data ->> 'hostname')) >= 3
    ), serials AS (
        SELECT v.source_instance_id, v.external_id,
               count(DISTINCT operations.usable_serial(v.serial)) AS serial_count
          FROM (SELECT DISTINCT source_instance_id, external_id,
                       material_data ->> 'serial_number' AS serial
                  FROM h WHERE coalesce(material_data ->> 'serial_number', '') <> '') v
         GROUP BY 1, 2
    )
    SELECT p_tenant, n.source_instance_id, n.external_id, n.platform, s.serial_count,
           n.name_count, 'serials'
      FROM names n
      JOIN serials s USING (source_instance_id, external_id)
     WHERE s.serial_count >= 3;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    -- ADR-0034: five or more names within 90 days, with no usable serial and no
    -- VM UUID (measured 2026-10-19: clones reach 17 and 38; real renames 3).
    INSERT INTO operations.identity_roaming_records
        (tenant_id, source_instance_id, external_id, platform, serial_count, name_count, basis)
    WITH w AS (
        SELECT h.source_instance_id, h.external_id, h.platform, h.entity_type, h.material_data
          FROM operations.entity_observation_history h
         WHERE h.tenant_id = p_tenant AND h.entity_type LIKE 'agent.%'
           AND h.entity_key NOT LIKE 'device-health:%'
           -- Every interval that overlaps the window, not only those that began in it.
           AND h.effective_from <= now()
           AND (h.effective_to IS NULL OR h.effective_to >= now() - interval '90 days')
    ), raw_names AS (
        -- Distinct reported names per record, normalized once each.
        SELECT DISTINCT source_instance_id, external_id, platform, entity_type,
               coalesce(nullif(material_data ->> 'hostname', ''), material_data ->> 'guest_name') AS name,
               material_data ->> 'domain' AS domain
          FROM w
    ), names AS (
        SELECT r.source_instance_id, r.external_id, min(r.platform) AS platform,
               count(DISTINCT f.name_key) AS name_count
          FROM raw_names r
         CROSS JOIN LATERAL operations.record_name_forms(r.platform, r.entity_type, r.name, r.domain) f
         GROUP BY 1, 2
        HAVING count(DISTINCT f.name_key) >= 5
    ), with_vm_uuid AS (
        SELECT DISTINCT source_instance_id, external_id
          FROM w WHERE coalesce(btrim(material_data ->> 'vm_uuid'), '') <> ''
    ), with_serial AS (
        SELECT DISTINCT v.source_instance_id, v.external_id
          FROM (SELECT DISTINCT source_instance_id, external_id,
                       material_data ->> 'serial_number' AS serial
                  FROM w WHERE coalesce(material_data ->> 'serial_number', '') <> '') v
         WHERE operations.usable_serial(v.serial) IS NOT NULL
    )
    SELECT p_tenant, n.source_instance_id, n.external_id, n.platform, 0, n.name_count, 'names'
      FROM names n
     WHERE NOT EXISTS (SELECT 1 FROM with_serial x
                        WHERE x.source_instance_id = n.source_instance_id
                          AND x.external_id = n.external_id)
       AND NOT EXISTS (SELECT 1 FROM with_vm_uuid x
                        WHERE x.source_instance_id = n.source_instance_id
                          AND x.external_id = n.external_id)
    ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS v_names = ROW_COUNT;
    RETURN v_count + v_names;
END
$fn$;
REVOKE ALL ON FUNCTION operations.refresh_identity_roaming_records(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.refresh_identity_roaming_records(bigint) TO ninja_ingest;

-- Every Computer's name, rule and record (ADR-0034 section 5). Read only.
CREATE FUNCTION operations.computer_names(p_tenant bigint, p_devices uuid[] DEFAULT NULL)
RETURNS TABLE (device_id uuid, name text, name_rule text, observation_id uuid)
LANGUAGE sql STABLE
AS $fn$
WITH dev AS (
    SELECT d.id, d.canonical_hostname::text AS canonical_hostname,
           regexp_replace(lower(d.canonical_hostname), '[^a-z0-9]', '', 'g') AS current_key
      FROM operations.devices d
     WHERE d.tenant_id = p_tenant AND d.deleted_at IS NULL
       AND (p_devices IS NULL OR d.id = ANY (p_devices))
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
    SELECT DISTINCT ON (x.device_id) x.device_id, lower(btrim(x.value ->> 'name')) AS name
      FROM operations.device_operator_decisions x
      JOIN dev ON dev.id = x.device_id
     WHERE x.tenant_id = p_tenant AND x.dimension = 'name'
       AND coalesce(btrim(x.value ->> 'name'), '') <> ''
     ORDER BY x.device_id, x.set_at DESC
)
SELECT dev.id,
       CASE WHEN op.device_id IS NOT NULL THEN op.name
            WHEN st.device_id IS NOT NULL OR b.device_id IS NULL THEN dev.canonical_hostname
            ELSE coalesce(l.name_short, b.name_short) END,
       CASE WHEN op.device_id IS NOT NULL THEN 'operator'
            WHEN st.device_id IS NOT NULL THEN 'stable_os'
            WHEN b.device_id IS NULL THEN 'unconfirmed'
            ELSE (ARRAY['reporting_os', 'silent_os', 'stable_os', 'withdrawn_os',
                        'current_label', 'withdrawn_label'])[b.step] END,
       CASE WHEN op.device_id IS NOT NULL OR (st.device_id IS NULL AND b.device_id IS NULL) THEN NULL
            WHEN st.device_id IS NOT NULL THEN st.observation_id
            ELSE coalesce(l.observation_id, b.observation_id) END
  FROM dev
  LEFT JOIN operator_name op ON op.device_id = dev.id
  LEFT JOIN best b ON b.device_id = dev.id
  LEFT JOIN stable st ON st.device_id = dev.id
  LEFT JOIN longer l ON l.device_id = dev.id
$fn$;

-- The shadow reconciliation: what the writer would change (ADR-0034 section 11
-- step 1). Read only.
CREATE FUNCTION operations.computer_name_shadow(p_tenant bigint)
RETURNS TABLE (device_id uuid, lifecycle_status text, current_name text, shadow_name text,
               name_rule text, observation_id uuid, outcome text)
LANGUAGE sql STABLE
AS $fn$
    SELECT d.id, d.lifecycle_status::text, d.canonical_hostname::text, n.name, n.name_rule,
           n.observation_id,
           CASE WHEN n.name = lower(d.canonical_hostname) THEN 'same'
                WHEN regexp_replace(n.name, '[^a-z0-9]', '', 'g')
                     = regexp_replace(lower(d.canonical_hostname), '[^a-z0-9]', '', 'g') THEN 'same_key'
                ELSE 'rename' END
      FROM operations.computer_names(p_tenant, NULL) n
      JOIN operations.devices d ON d.id = n.device_id
$fn$;

-- Sources and record types that report names but have no name kind.
CREATE FUNCTION operations.source_name_kind_unclassified(p_tenant bigint)
RETURNS TABLE (platform text, record_type text, records bigint)
LANGUAGE sql STABLE
AS $fn$
    SELECT eo.platform::text, eo.entity_type::text, count(*)
      FROM operations.entity_observation_current eo
     WHERE eo.tenant_id = p_tenant AND eo.active
       AND eo.entity_key NOT LIKE 'device-health:%'
       AND coalesce(nullif(eo.canonical_data ->> 'hostname', ''), eo.canonical_data ->> 'guest_name', '') <> ''
       AND NOT EXISTS (SELECT 1 FROM operations.source_name_kinds k
                        WHERE k.platform = eo.platform AND k.record_type = eo.entity_type)
     GROUP BY 1, 2
     ORDER BY 1, 2
$fn$;

REVOKE ALL ON FUNCTION operations.record_name_forms(text, text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.usable_serial(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.computer_names(bigint, uuid[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.computer_name_shadow(bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.source_name_kind_unclassified(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.record_name_forms(text, text, text, text),
                          operations.usable_serial(text),
                          operations.computer_names(bigint, uuid[]),
                          operations.computer_name_shadow(bigint),
                          operations.source_name_kind_unclassified(bigint)
    TO operations_app, operations_readonly, ninja_ingest;
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
            ) VALUES (%s, 'medium', 'admin', 'evaluator', 'global', FALSE, TRUE, FALSE,
                      FALSE, 'global', '', '', %s, %s, 'Data collection',
                      'Collection and processing', 576, FALSE, '[]'::jsonb, '')
            ON CONFLICT (name) DO NOTHING
            """,
            (
                NEW_TYPE,
                "A source reports computer names for a record type that has no name kind, "
                "so those names count as the lowest-ranked label. Classify the record type "
                "as the machine's own name or a label.",
                "Source names not classified",
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
        ("operations", "0321_os_unknown_coverage_cover"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
        migrations.RunPython(register_finding_type, migrations.RunPython.noop),
    ]
