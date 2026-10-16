"""Record every platform and operator change (ADR-0033): the history foundation.

* ``operations.change_actions``: one row per change: when, who (operator, or
  process and version), the action, a reason a person can read, evidence.
* ``operations.begin_change(...)``: opens an action for the transaction. Every
  history row written in the same transaction belongs to it.
* ``operations.change_history_registry``: every table in the ``operations``
  schema with its classification (``covered``, ``own_history``,
  ``history_store``, ``exempt``) and reason; for covered tables the recorded
  columns (an allowlist), secret columns (recorded only as changed), the key,
  and how to find the Computer and client a row belongs to. Generated from the
  production column inventory of 2026-10-16 (155 tables, 78 covered).
* ``<table>_change_history``: one history table per covered table, stored with
  the entity it describes. Row-level security for readers mirrors the entity;
  only ``operations.record_change()`` (SECURITY DEFINER) writes it.
* ``operations.record_change()``: the trigger on every covered table whose
  capture is ``trigger``. It records only the allowlisted columns, skips an
  update that changed none of them, writes ``[secret]`` for secret columns, and
  uses the transaction's action; when a writer has not opened one yet it opens
  an implicit action naming the database role and application, so nothing is
  lost while writers are moved to explicit actions. ``enforce_action`` in the
  registry turns that fallback into an error per table once its writers use
  ``begin_change``.
* ``operations.change_history_unclassified()``: tables that are in the schema
  but not in the registry; the evaluator raises the admin finding
  ``change_history_unclassified`` for each, so a new table cannot silently go
  unrecorded.

``cve_match`` is covered with capture ``writer``: the matcher rebuilds the
table by delete and re-insert, so a row trigger would record every rebuild; the
matcher writes the real differences into ``cve_match_change_history`` instead.
"""

from __future__ import annotations

import hashlib
import json
from typing import ClassVar

from django.db import migrations

POLICY_VERSION = "conditions-registry-2"

FOUNDATION_SQL = r"""
CREATE TABLE operations.change_actions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id bigint NULL,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    actor_kind varchar(16) NOT NULL
        CHECK (actor_kind IN ('operator', 'process', 'migration', 'system')),
    actor_id bigint NULL,
    process varchar(160) NOT NULL DEFAULT '',
    process_version varchar(64) NOT NULL DEFAULT '',
    action varchar(120) NOT NULL,
    reason text NOT NULL DEFAULT '',
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    explicit boolean NOT NULL
);
CREATE INDEX change_actions_tenant_time ON operations.change_actions (tenant_id, occurred_at);
ALTER TABLE operations.change_actions ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_read ON operations.change_actions FOR SELECT
    USING (tenant_id IS NULL
           OR tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint);

CREATE TABLE operations.change_history_registry (
    table_name text PRIMARY KEY,
    classification text NOT NULL
        CHECK (classification IN ('covered', 'own_history', 'history_store', 'exempt')),
    reason text NOT NULL CHECK (reason <> ''),
    recorded_columns text[] NOT NULL,
    secret_columns text[] NOT NULL,
    key_columns text[] NOT NULL,
    computer_column text NULL,
    computer_condition_column text NULL,
    computer_condition_value text NULL,
    client_column text NULL,
    is_global boolean NOT NULL,
    capture text NULL CHECK (capture IN ('trigger', 'writer')),
    enforce_action boolean NOT NULL DEFAULT false,
    CHECK ((classification = 'covered') = (capture IS NOT NULL)),
    CHECK (classification = 'covered' OR cardinality(recorded_columns) = 0),
    CHECK (classification <> 'covered' OR cardinality(key_columns) > 0)
);

CREATE FUNCTION operations.begin_change(
    p_action text,
    p_reason text DEFAULT '',
    p_evidence jsonb DEFAULT '{}'::jsonb,
    p_actor_kind text DEFAULT 'process',
    p_actor_id bigint DEFAULT NULL,
    p_process text DEFAULT '',
    p_process_version text DEFAULT '',
    p_tenant_id bigint DEFAULT NULL,
    p_explicit boolean DEFAULT true
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_id uuid;
BEGIN
    IF p_action IS NULL OR p_action = '' THEN
        RAISE EXCEPTION 'A change action needs a name';
    END IF;
    INSERT INTO operations.change_actions
        (tenant_id, actor_kind, actor_id, process, process_version, action, reason,
         evidence, explicit)
    VALUES (coalesce(p_tenant_id,
                     nullif(current_setting('operations.tenant_id', true), '')::bigint),
            p_actor_kind, p_actor_id, left(coalesce(p_process, ''), 160),
            left(coalesce(p_process_version, ''), 64), left(p_action, 120),
            coalesce(p_reason, ''), coalesce(p_evidence, '{}'::jsonb), p_explicit)
    RETURNING id INTO v_id;
    PERFORM set_config('operations.change_action_id', v_id::text, true);
    RETURN v_id;
END
$fn$;

CREATE FUNCTION operations.record_change() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    r operations.change_history_registry%ROWTYPE;
    old_j jsonb;
    new_j jsonb;
    row_j jsonb;
    before_v jsonb := '{}'::jsonb;
    after_v jsonb := '{}'::jsonb;
    changed text[] := '{}';
    col text;
    v_action uuid;
    v_tenant bigint;
    v_client uuid;
    v_computer uuid;
    v_key text;
BEGIN
    SELECT * INTO r FROM operations.change_history_registry WHERE table_name = TG_TABLE_NAME;
    IF NOT FOUND OR r.classification <> 'covered' OR r.capture <> 'trigger' THEN
        RETURN NULL;
    END IF;
    IF TG_OP <> 'INSERT' THEN old_j := to_jsonb(OLD); END IF;
    IF TG_OP <> 'DELETE' THEN new_j := to_jsonb(NEW); END IF;

    FOREACH col IN ARRAY r.recorded_columns LOOP
        IF TG_OP <> 'UPDATE' OR (old_j -> col) IS DISTINCT FROM (new_j -> col) THEN
            changed := changed || col;
        END IF;
        IF old_j IS NOT NULL THEN before_v := before_v || jsonb_build_object(col, old_j -> col); END IF;
        IF new_j IS NOT NULL THEN after_v := after_v || jsonb_build_object(col, new_j -> col); END IF;
    END LOOP;
    FOREACH col IN ARRAY r.secret_columns LOOP
        IF TG_OP <> 'UPDATE' OR (old_j -> col) IS DISTINCT FROM (new_j -> col) THEN
            changed := changed || col;
            IF old_j IS NOT NULL THEN before_v := before_v || jsonb_build_object(col, '[secret]'); END IF;
            IF new_j IS NOT NULL THEN after_v := after_v || jsonb_build_object(col, '[secret]'); END IF;
        END IF;
    END LOOP;
    IF TG_OP = 'UPDATE' AND cardinality(changed) = 0 THEN
        RETURN NULL;
    END IF;

    row_j := coalesce(new_j, old_j);
    SELECT string_agg(coalesce(row_j ->> k, ''), '|' ORDER BY ord)
      INTO v_key
      FROM unnest(r.key_columns) WITH ORDINALITY AS keys(k, ord);
    IF row_j ? 'tenant_id' THEN
        v_tenant := (row_j ->> 'tenant_id')::bigint;
    ELSIF NOT r.is_global THEN
        v_tenant := nullif(current_setting('operations.tenant_id', true), '')::bigint;
    END IF;
    IF r.client_column IS NOT NULL THEN
        v_client := nullif(row_j ->> r.client_column, '')::uuid;
    END IF;
    IF r.computer_column IS NOT NULL
       AND (r.computer_condition_column IS NULL
            OR row_j ->> r.computer_condition_column = r.computer_condition_value) THEN
        v_computer := nullif(row_j ->> r.computer_column, '')::uuid;
    END IF;

    v_action := nullif(current_setting('operations.change_action_id', true), '')::uuid;
    IF v_action IS NULL THEN
        IF r.enforce_action THEN
            RAISE EXCEPTION 'Change to operations.% needs an action (operations.begin_change)',
                TG_TABLE_NAME;
        END IF;
        v_action := operations.begin_change(
            'implicit',
            'Recorded automatically: the writer did not name an action.',
            '{}'::jsonb, 'process', NULL,
            -- current_user is this function's owner (SECURITY DEFINER); the writer
            -- is the role the session acts as.
            coalesce(nullif(current_setting('role', true), 'none'), session_user)
                || coalesce('/' || nullif(current_setting('application_name', true), ''), ''),
            '', v_tenant, false);
    END IF;

    EXECUTE format(
        'INSERT INTO operations.%I (action_id, tenant_id, client_id, computer_id, entity_key,
                                    operation, changed_columns, before_values, after_values)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)',
        TG_TABLE_NAME || '_change_history')
    USING v_action, v_tenant, v_client, v_computer, v_key, left(TG_OP, 1), changed,
          CASE WHEN old_j IS NULL THEN NULL ELSE before_v END,
          CASE WHEN new_j IS NULL THEN NULL ELSE after_v END;
    RETURN NULL;
END
$fn$;

CREATE FUNCTION operations.enable_change_history(p_table text) RETURNS void
LANGUAGE plpgsql
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    r operations.change_history_registry%ROWTYPE;
    h text := p_table || '_change_history';
BEGIN
    SELECT * INTO r FROM operations.change_history_registry WHERE table_name = p_table;
    IF NOT FOUND OR r.classification <> 'covered' THEN
        RAISE EXCEPTION 'operations.% is not a covered table', p_table;
    END IF;
    EXECUTE format($sql$
        CREATE TABLE IF NOT EXISTS operations.%1$I (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            action_id uuid NOT NULL REFERENCES operations.change_actions(id),
            tenant_id bigint NULL,
            client_id uuid NULL,
            computer_id uuid NULL,
            entity_key text NOT NULL,
            operation char(1) NOT NULL CHECK (operation IN ('I', 'U', 'D')),
            changed_columns text[] NOT NULL,
            before_values jsonb NULL,
            after_values jsonb NULL,
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
        )$sql$, h);
    EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON operations.%I (entity_key, recorded_at)',
                   left(h, 50) || '_key', h);
    EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON operations.%I (action_id)',
                   left(h, 50) || '_act', h);
    EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON operations.%I (computer_id, recorded_at)
                    WHERE computer_id IS NOT NULL', left(h, 50) || '_cmp', h);
    EXECUTE format('ALTER TABLE operations.%I ENABLE ROW LEVEL SECURITY', h);
    EXECUTE format('DROP POLICY IF EXISTS tenant_read ON operations.%I', h);
    EXECUTE format($sql$CREATE POLICY tenant_read ON operations.%I FOR SELECT
        USING (tenant_id IS NULL
               OR tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint)$sql$, h);
    EXECUTE format('REVOKE ALL ON operations.%I FROM PUBLIC', h);
    EXECUTE format('GRANT SELECT ON operations.%I TO operations_app, operations_readonly, ninja_ingest', h);
    IF r.capture = 'trigger' THEN
        EXECUTE format('DROP TRIGGER IF EXISTS record_change ON operations.%I', p_table);
        EXECUTE format('CREATE TRIGGER record_change AFTER INSERT OR UPDATE OR DELETE
                        ON operations.%I FOR EACH ROW EXECUTE FUNCTION operations.record_change()',
                       p_table);
    END IF;
END
$fn$;

CREATE FUNCTION operations.change_history_unclassified() RETURNS SETOF text
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
    SELECT c.relname::text
      FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'operations' AND c.relkind IN ('r', 'p') AND NOT c.relispartition
       AND c.relname NOT LIKE '%\_change\_history'
       AND c.relname NOT IN ('change_actions', 'change_history_registry')
       AND NOT EXISTS (SELECT 1 FROM operations.change_history_registry r
                        WHERE r.table_name = c.relname)
     ORDER BY 1
$fn$;

-- The intel matcher rebuilds cve_match by delete and re-insert inside one
-- transaction, after copying the previous set into pg_temp.cve_match_before.
-- This records only the real differences (match added or removed) by its
-- natural key: product, version, CVE.
CREATE FUNCTION operations.record_cve_match_changes(p_tenant_id bigint) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_action uuid;
    v_rows integer;
BEGIN
    IF to_regclass('pg_temp.cve_match_before') IS NULL THEN
        RAISE EXCEPTION 'record_cve_match_changes needs pg_temp.cve_match_before';
    END IF;
    v_action := nullif(current_setting('operations.change_action_id', true), '')::uuid;
    IF v_action IS NULL THEN
        v_action := operations.begin_change(
            'cve_match.refresh',
            'Vulnerability matches recomputed from the intelligence data.',
            '{}'::jsonb, 'process', NULL, 'ingest.intel.matcher', '', p_tenant_id, true);
    END IF;
    WITH after_set AS (
        SELECT canonical_name, software_version_id, cve_id, match_kind, version_range, confidence
          FROM operations.cve_match WHERE tenant_id = p_tenant_id
    ), before_set AS (
        SELECT canonical_name, software_version_id, cve_id, match_kind, version_range, confidence
          FROM pg_temp.cve_match_before
    ), added AS (
        SELECT * FROM after_set EXCEPT SELECT * FROM before_set
    ), removed AS (
        SELECT * FROM before_set EXCEPT SELECT * FROM after_set
    ), changes AS (
        SELECT 'I'::char(1) AS op, to_jsonb(added.*) AS row_j FROM added
        UNION ALL
        SELECT 'D'::char(1), to_jsonb(removed.*) FROM removed
    )
    INSERT INTO operations.cve_match_change_history
        (action_id, tenant_id, entity_key, operation, changed_columns, before_values, after_values)
    SELECT v_action, p_tenant_id,
           concat_ws('|', row_j->>'canonical_name', coalesce(row_j->>'software_version_id', ''),
                     row_j->>'cve_id'),
           op,
           ARRAY['canonical_name','software_version_id','cve_id','match_kind','version_range','confidence'],
           CASE WHEN op = 'D' THEN row_j END,
           CASE WHEN op = 'I' THEN row_j END
      FROM changes;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END
$fn$;
REVOKE ALL ON FUNCTION operations.record_cve_match_changes(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.record_cve_match_changes(bigint) TO ninja_ingest;

REVOKE ALL ON operations.change_actions, operations.change_history_registry FROM PUBLIC;
GRANT SELECT ON operations.change_actions, operations.change_history_registry
    TO operations_app, operations_readonly, ninja_ingest;
REVOKE ALL ON FUNCTION operations.begin_change(text, text, jsonb, text, bigint, text, text, bigint, boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.begin_change(text, text, jsonb, text, bigint, text, text, bigint, boolean)
    TO operations_app, ninja_ingest;
REVOKE ALL ON FUNCTION operations.enable_change_history(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.change_history_unclassified() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.change_history_unclassified() TO operations_app, ninja_ingest;

INSERT INTO operations.change_history_registry (
    table_name, classification, reason, recorded_columns, secret_columns, key_columns,
    computer_column, computer_condition_column, computer_condition_value, client_column,
    is_global, capture
) VALUES
    ('admin_findings', 'covered', 'platform or operator decision or state', ARRAY['id','condition_key','severity','status','subject_ref','details','resolved_at','finding_type_id','tenant_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('agent_instance_field_history', 'history_store', 'stores history or run records', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('agent_instances', 'own_history', 'agent_instance_field_history (trigger)', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('agents', 'covered', 'platform or operator decision or state', ARRAY['id','name','entity_type','supported_os_groups','default_severity','default_gap_after_hours','default_confidence_probable','default_confidence_confirmed']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('asset_field_history', 'history_store', 'stores history or run records', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('assets', 'own_history', 'asset_field_history (trigger)', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('attribute_authority_policies', 'covered', 'platform or operator decision or state', ARRAY['id','native_record_type','eligible','authority_tier','priority','enabled','reason','source_instance_id','tenant_id','attribute_definition_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('attribute_definitions', 'covered', 'platform or operator decision or state', ARRAY['id','key','display_name','description','value_type','cardinality','sensitivity','validation','canonical_projection_eligible','single_value_conflict_policy','set_merge_policy','definition_version','enabled','entity_class_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('audit_log', 'history_store', 'stores history or run records', '{}'::text[], '{}'::text[], ARRAY['audit_id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('auth_group', 'covered', 'platform or operator decision or state', ARRAY['id','name']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('auth_group_permissions', 'covered', 'platform or operator decision or state', ARRAY['id','group_id','permission_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('auth_permission', 'exempt', 'created by migrations', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, TRUE, NULL),
    ('client_candidates', 'covered', 'platform or operator decision or state', ARRAY['id','normalized_name','display_name','status','first_seen_at','source_refs','resolved_at','resolved_by','resolved_reason','resolved_client_id','tenant_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('client_name_aliases', 'covered', 'platform or operator decision or state', ARRAY['id','alias','normalized_name','tier','enabled','created_at','created_by','created_reason','client_id','tenant_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, 'client_id', FALSE, 'trigger'),
    ('client_org_excludes', 'covered', 'platform or operator decision or state', ARRAY['id','external_id','normalized_name','reason','enabled','created_at','created_by','source_id','tenant_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('client_policies', 'covered', 'platform or operator decision or state', ARRAY['id','category','approved_products','agent_sla_days','client_id','tenant_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, 'client_id', FALSE, 'trigger'),
    ('client_source_mapping_decisions', 'covered', 'platform or operator decision or state', ARRAY['id','tenant_id','source_link_id','state','provenance','reason','decided_by_id','decided_at','superseded_at','superseded_by_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('client_user_links', 'covered', 'platform or operator decision or state', ARRAY['id','external_id','external_name','client_user_id','tenant_id','source_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('client_users', 'covered', 'platform or operator decision or state', ARRAY['id','canonical_email','canonical_username','display_name','deleted_at','client_id','tenant_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, 'client_id', FALSE, 'trigger'),
    ('clients', 'covered', 'platform or operator decision or state', ARRAY['id','slug','display_name','timezone','deleted_at','tenant_id','created_at','created_reason','updated_reason','stale_since','stale_reason','deleted_reason','requirement_profile_id','entity_id','offline_after_days']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, 'id', FALSE, 'trigger'),
    ('collector_instances', 'covered', 'platform or operator decision or state', ARRAY['id','name','kind','capabilities','tenant_id']::text[], ARRAY['token_hash']::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('collectors', 'covered', 'platform or operator decision or state', ARRAY['id','name','kind','capabilities']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('condition_assessments', 'exempt', 'assessment of a finding (as readiness)', '{}'::text[], '{}'::text[], ARRAY['tenant_id','row_kind','finding_id','participant_kind','participant_id','participant_role']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('condition_participants', 'exempt', 'assessment participants (as readiness)', '{}'::text[], '{}'::text[], ARRAY['tenant_id','row_kind','finding_id','participant_kind','participant_id','participant_role']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('condition_policies', 'own_history', 'immutable policy versions', '{}'::text[], '{}'::text[], ARRAY['policy_version','finding_type_id']::text[], NULL, NULL, NULL, NULL, TRUE, NULL),
    ('condition_policy_reviews', 'own_history', 'immutable review records', '{}'::text[], '{}'::text[], ARRAY['version']::text[], NULL, NULL, NULL, NULL, TRUE, NULL),
    ('condition_policy_versions', 'own_history', 'immutable policy versions', '{}'::text[], '{}'::text[], ARRAY['version']::text[], NULL, NULL, NULL, NULL, TRUE, NULL),
    ('condition_reviewed_distinct', 'exempt', 'derived review counter', '{}'::text[], '{}'::text[], ARRAY['tenant_id','condition_identity']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('coverage_requirements', 'covered', 'platform or operator decision or state', ARRAY['id','entity_type','platform','device_scope','severity','gap_after_hours','confidence_probable','confidence_confirmed','enabled','created_at','client_id','tenant_id','agent_id','applicable_os_groups']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('cve_match', 'covered', 'platform or operator decision or state', ARRAY['id','tenant_id','canonical_name','cve_id','match_kind','version_range','confidence','software_version_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'writer'),
    ('dead_letter_observations', 'exempt', 'work queue', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('device_operator_decisions', 'covered', 'platform or operator decision or state', ARRAY['id','dimension','value','reason','set_by','set_at','tenant_id','device_id']::text[], '{}'::text[], ARRAY['id']::text[], 'device_id', NULL, NULL, NULL, FALSE, 'trigger'),
    ('device_patching_override', 'covered', 'platform or operator decision or state', ARRAY['id','scope','reason','set_by','set_at','tenant_id','device_id']::text[], '{}'::text[], ARRAY['id']::text[], 'device_id', NULL, NULL, NULL, FALSE, 'trigger'),
    ('device_windows_servicing_current', 'exempt', 'decided 2026-10-16: findings and OS evidence carry it', '{}'::text[], '{}'::text[], ARRAY['tenant_id','device_id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('devices', 'covered', 'platform or operator decision or state', ARRAY['id','canonical_hostname','canonical_serial','canonical_vm_uuid','device_type','deleted_at','client_id','tenant_id','created_at','created_reason','updated_reason','stale_since','stale_reason','deleted_reason','device_role','os_name','os_family','lifecycle_status','os_group','entity_id']::text[], '{}'::text[], ARRAY['id']::text[], 'id', NULL, NULL, 'client_id', FALSE, 'trigger'),
    ('django_admin_log', 'history_store', 'stores history or run records', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, TRUE, NULL),
    ('django_content_type', 'exempt', 'schema bookkeeping', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, TRUE, NULL),
    ('django_migrations', 'exempt', 'schema bookkeeping', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, TRUE, NULL),
    ('django_session', 'exempt', 'login sessions', '{}'::text[], '{}'::text[], ARRAY['session_key']::text[], NULL, NULL, NULL, NULL, TRUE, NULL),
    ('entities', 'covered', 'platform or operator decision or state', ARRAY['id','scope_kind','created_at','created_reason','updated_reason','retired_at','retired_reason','deleted_at','deleted_reason','client_id','tenant_id','entity_class_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('entity_attribute_claim_current', 'own_history', 'entity_attribute_claim_history (source evidence)', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('entity_attribute_claim_history', 'history_store', 'stores history or run records', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('entity_attribute_conflict_claim_support', 'exempt', 'derived support rows', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('entity_attribute_conflict_current', 'exempt', 'derived from claims; conflicts surface as findings', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('entity_attribute_decision_current', 'own_history', 'audit trigger (audit_and_queue_attribute_decision)', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('entity_attribute_decision_member_current', 'own_history', 'audit trigger (audit_and_queue_attribute_decision_member)', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('entity_attribute_effective_claim_support', 'exempt', 'derived support rows', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('entity_attribute_effective_current', 'covered', 'platform or operator decision or state', ARRAY['id','value_type','cardinality','status','selection_reason','value_text','value_number','value_boolean','value_timestamp','value_json','value_fingerprint','selected_authority_tier','selected_authority_priority','conflict','attribute_definition_id','entity_id','entity_class_id','tenant_id','value_entity_id']::text[], '{}'::text[], ARRAY['id']::text[], 'entity_id', 'entity_class_id', 'device', NULL, FALSE, 'trigger'),
    ('entity_attribute_effective_dirty', 'exempt', 'work queue', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('entity_attribute_effective_member_current', 'exempt', 'derived member rows', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('entity_attribute_projection_state', 'exempt', 'projection progress', '{}'::text[], '{}'::text[], ARRAY['observation_id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('entity_attribute_withheld_current', 'exempt', 'derived', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('entity_candidate_events', 'history_store', 'stores history or run records', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('entity_candidates', 'own_history', 'entity_candidate_events', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('entity_class_scopes', 'covered', 'platform or operator decision or state', ARRAY['id','scope_kind','entity_class_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('entity_classes', 'covered', 'platform or operator decision or state', ARRAY['name','display_name','description']::text[], '{}'::text[], ARRAY['name']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('entity_observation_current', 'own_history', 'entity_observation_history (source evidence)', '{}'::text[], '{}'::text[], ARRAY['observation_id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('entity_observation_history', 'history_store', 'stores history or run records', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('entity_observations', 'history_store', 'stores history or run records', '{}'::text[], '{}'::text[], ARRAY['observation_id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('entity_relationship_decision_current', 'own_history', 'audit trigger (audit_and_queue_relationship_decision)', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('entity_relationship_dirty', 'exempt', 'work queue', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('entity_relationship_evidence_current', 'own_history', 'entity_relationship_evidence_history (source evidence)', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('entity_relationship_evidence_history', 'history_store', 'stores history or run records', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('entity_relationship_evidence_support', 'exempt', 'derived support rows', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('entity_relationships', 'covered', 'platform or operator decision or state', ARRAY['id','status','selection_reason','selected_authority_tier','selected_authority_priority','source_entity_id','target_entity_id','tenant_id','relationship_type_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('entity_source_link_history', 'history_store', 'stores history or run records', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('entity_source_links', 'own_history', 'entity_source_link_history; gains the action reference', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('entity_types', 'covered', 'platform or operator decision or state', ARRAY['name','is_identity_signal','description','lifecycle_evidence_mode','consumes_license','requirement_eligible','entity_class_id']::text[], '{}'::text[], ARRAY['name']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('eol_product_map', 'covered', 'platform or operator decision or state', ARRAY['id','tenant_id','raw_pattern','eol_product','priority','notes','created_at','version_pattern','eol_cycle']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('evaluator_config', 'covered', 'platform or operator decision or state', ARRAY['id','evaluator_name','config','tenant_id','updated_by_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('finding_state', 'exempt', 'derived from findings and assessments', '{}'::text[], '{}'::text[], ARRAY['finding_id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('finding_state_drift', 'history_store', 'stores history or run records', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('finding_types', 'covered', 'platform or operator decision or state', ARRAY['id','name','default_severity','runbook_path','description','finding_class','source_module','auto_resolvable','subject_scope','creates_device_exposure','suppressed_by_approval','drilldown_evidence_key','concern_signal','default_decision_scope','alertable','display_name','issue_category','issue_group','sort_order','covered_by','cover_note']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('findings', 'covered', 'platform or operator decision or state', ARRAY['id','subject_type','subject_id','finding_details','severity','status','sla_due_at','last_reviewed_at','finding_type_id','owner_id','tenant_id','client_id','condition_key','confidence','snoozed_until','acknowledged_at','closed_at','subject_layer','subject_layer_entity_id']::text[], '{}'::text[], ARRAY['id']::text[], 'subject_id', 'subject_type', 'device', 'client_id', FALSE, 'trigger'),
    ('identity_authority_policies', 'covered', 'platform or operator decision or state', ARRAY['id','native_record_type','may_establish_identity','may_create_canonical','enabled','reason','resulting_entity_type_id','source_instance_id','tenant_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('identity_match_policies', 'covered', 'platform or operator decision or state', ARRAY['id','matcher','display_name','description','priority','requires_client_scope','requires_unique_candidate','avoid_same_stream_duplicates','blocking_signal_keys','confidence','enabled','reason','tenant_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('identity_value_rejections', 'covered', 'platform or operator decision or state', ARRAY['id','value_kind','normalized_value','reason','enabled','provenance','created_at']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('intel_ingest_status', 'exempt', 'ingest progress', '{}'::text[], '{}'::text[], ARRAY['connector']::text[], NULL, NULL, NULL, NULL, TRUE, NULL),
    ('intel_matcher_hints', 'covered', 'platform or operator decision or state', ARRAY['id','kind','pattern','enabled','note','created_at']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('job_definition_versions', 'own_history', 'immutable definition versions', '{}'::text[], '{}'::text[], ARRAY['definition_key','definition_digest']::text[], NULL, NULL, NULL, NULL, TRUE, NULL),
    ('job_dependencies', 'exempt', 'job graph bookkeeping', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('job_domain_attempts', 'own_history', 'immutable attempts', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('job_lane_limits', 'covered', 'platform or operator decision or state', ARRAY['tenant_id','lane','capacity','policy_revision']::text[], '{}'::text[], ARRAY['tenant_id','lane']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('job_recovery_assessments', 'exempt', 'derived', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('job_recovery_policies', 'covered', 'platform or operator decision or state', ARRAY['tenant_id','definition_key','definition_digest','recovery_mode','evidence_summary','reviewed_at']::text[], '{}'::text[], ARRAY['tenant_id','definition_key','definition_digest']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('job_recovery_policy_authorities', 'covered', 'platform or operator decision or state', ARRAY['tenant_id','definition_key','recovery_mode','evidence_summary','reviewed_at']::text[], '{}'::text[], ARRAY['tenant_id','definition_key']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('job_requests', 'own_history', 'immutable job requests', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('job_resource_claims', 'exempt', 'capacity locks', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('job_resource_limits', 'covered', 'platform or operator decision or state', ARRAY['resource_template','capacity','policy_revision','policy_kind']::text[], '{}'::text[], ARRAY['resource_template']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('job_runtime_heartbeats', 'exempt', 'heartbeats', '{}'::text[], '{}'::text[], ARRAY['tenant_id','runtime_kind','runtime_identity']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('job_schedule_events', 'history_store', 'stores history or run records', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('job_schedules', 'covered', 'platform or operator decision or state', ARRAY['id','tenant_id','definition_key','definition_digest','scope_identity','enabled','capability_reason','cadence','anchor_at','time_zone','configuration_revision']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('merge_candidates', 'covered', 'platform or operator decision or state', ARRAY['id','entity_type','canonical_key','member_snapshots','member_observation_ids','match_reason','confidence','status','client_id','tenant_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, 'client_id', FALSE, 'trigger'),
    ('node_class_mappings', 'covered', 'platform or operator decision or state', ARRAY['id','pattern','entity_type','form_factor','priority']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('notification_events', 'history_store', 'stores history or run records', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('notification_routes', 'covered', 'platform or operator decision or state', ARRAY['id','severity_min','channel','mode','client_id','finding_type_id','tenant_id']::text[], ARRAY['target']::text[], ARRAY['id']::text[], NULL, NULL, NULL, 'client_id', FALSE, 'trigger'),
    ('notification_rules', 'covered', 'platform or operator decision or state', ARRAY['id','finding_class','min_severity','min_confidence','match_criteria','urgency_hours','cooldown_hours','enabled','client_id','finding_type_id','route_id','tenant_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, 'client_id', FALSE, 'trigger'),
    ('notification_state', 'exempt', 'delivery bookkeeping', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('observation_snapshot_runs', 'history_store', 'stores history or run records', '{}'::text[], '{}'::text[], ARRAY['run_id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('operating_system_installation_source_identities', 'exempt', 'derived identity map', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('operating_system_installations', 'covered', 'platform or operator decision or state', ARRAY['id','first_observed_at','retired_at','retired_reason','client_id','entity_id','tenant_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('operator_decision_dimensions', 'covered', 'platform or operator decision or state', ARRAY['name','entity_type','value_type','allowed_values','description','enabled']::text[], '{}'::text[], ARRAY['name']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('operator_job_events', 'history_store', 'stores history or run records', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('operator_job_runs', 'history_store', 'stores history or run records', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('os_family_mappings', 'covered', 'platform or operator decision or state', ARRAY['id','pattern','os_family','priority']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('os_group_mappings', 'covered', 'platform or operator decision or state', ARRAY['id','pattern','os_group','priority']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('os_instance_field_history', 'history_store', 'stores history or run records', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('os_instances', 'own_history', 'os_instance_field_history (trigger)', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('parity_report', 'history_store', 'stores history or run records', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('patch_evaluation_reconciliation', 'exempt', 'derived', '{}'::text[], '{}'::text[], ARRAY['tenant_id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('patch_evaluation_state', 'exempt', 'derived; patch findings carry it', '{}'::text[], '{}'::text[], ARRAY['tenant_id','device_id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('patching_scope_default', 'covered', 'platform or operator decision or state', ARRAY['device_role','effect','enabled','description']::text[], '{}'::text[], ARRAY['device_role']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('patching_scope_policy_allowlist', 'covered', 'platform or operator decision or state', ARRAY['id','policy_name','enabled','notes']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('patching_scope_signal', 'covered', 'platform or operator decision or state', ARRAY['id','field_name','entity_type','device_role_filter','effect','priority','enabled','description']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('placeholder_org_names', 'covered', 'platform or operator decision or state', ARRAY['id','normalized_name','note','created_at','tenant_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('platform_aliases', 'covered', 'platform or operator decision or state', ARRAY['alias','canonical']::text[], '{}'::text[], ARRAY['alias']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('platform_product_map', 'covered', 'platform or operator decision or state', ARRAY['id','agent_id','product_uuid','capability','component_role','provenance','enabled','created_at']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('product_authorizations', 'covered', 'platform or operator decision or state', ARRAY['id','tenant_id','client_id','product_uuid','capability','polarity','rationale','authorized_by_id','authorized_at','withdrawn_at','withdrawn_reason']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('publisher_aliases', 'covered', 'platform or operator decision or state', ARRAY['id','raw_pattern','canonical_publisher','is_regex','enabled','note','created_at']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('publisher_categories', 'covered', 'platform or operator decision or state', ARRAY['id','publisher_pattern','categories','is_regex','enabled','note','priority','created_at']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('queue_registry', 'covered', 'platform or operator decision or state', ARRAY['queue_key','queue_type','table_name','owner','enabled','max_pending_age_m','max_failure_count','max_depth','description']::text[], '{}'::text[], ARRAY['queue_key']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('relationship_authority_policies', 'covered', 'platform or operator decision or state', ARRAY['id','native_record_type','eligible','authority_tier','priority','enabled','reason','source_instance_id','tenant_id','relationship_type_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('relationship_types', 'covered', 'platform or operator decision or state', ARRAY['key','display_name','description','source_cardinality','target_cardinality','directed','enabled','source_entity_class_id','target_entity_class_id']::text[], '{}'::text[], ARRAY['key']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('requirement_profile_items', 'covered', 'platform or operator decision or state', ARRAY['id','entity_type','platform','device_scope','severity','gap_after_hours','confidence_probable','confidence_confirmed','profile_id','tenant_id','agent_id','applicable_os_groups']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('requirement_profiles', 'covered', 'platform or operator decision or state', ARRAY['id','name','description','is_tenant_default','created_at','tenant_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('run_log', 'history_store', 'stores history or run records', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('safety_signal', 'exempt', 'derived from intelligence', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('secrets', 'covered', 'platform or operator decision or state', ARRAY['id','name','created_by_id','tenant_id']::text[], ARRAY['encrypted_value']::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('software_catalog', 'covered', 'platform or operator decision or state', ARRAY['id','canonical_name','categories','publisher_hint','eol_date','notes','tenant_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('software_classifier_rules', 'covered', 'platform or operator decision or state', ARRAY['id','rule_type','pattern','is_regex','enabled','note','created_at']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('software_decisions', 'covered', 'platform or operator decision or state', ARRAY['id','canonical_name','decision','reason','decided_at','client_id','decided_by_id','tenant_id','device_id','publisher']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('software_device_readiness', 'exempt', 'decided 2026-10-16: duplicates finding state', '{}'::text[], '{}'::text[], ARRAY['tenant_id','device_id','finding_type_id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('software_full_reclassification_state', 'exempt', 'reclassification progress', '{}'::text[], '{}'::text[], ARRAY['tenant_id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('software_installation_history', 'history_store', 'stores history or run records', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('software_installations_current', 'own_history', 'software_installation_history (source evidence)', '{}'::text[], '{}'::text[], ARRAY['tenant_id','client_id','device_id','canonical_name']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('software_inventory_devices', 'exempt', 'derived', '{}'::text[], '{}'::text[], ARRAY['tenant_id','device_id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('software_reclassification_targets', 'exempt', 'reclassification work list', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('software_suggestion_rules', 'covered', 'platform or operator decision or state', ARRAY['id','priority','signal','adverse','suggestion','enabled','note','requires']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('source_action_requests', 'history_store', 'stores history or run records', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('source_bindings', 'covered', 'platform or operator decision or state', ARRAY['id','schedule','enabled','collector_instance_id','tenant_id','source_instance_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('source_events', 'own_history', 'immutable source events', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('source_field_mappings', 'covered', 'platform or operator decision or state', ARRAY['id','external_namespace','native_record_type','document_kind','source_field','mapping_version','enabled','attribute_definition_id','source_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('source_instances', 'covered', 'platform or operator decision or state', ARRAY['id','enabled','client_id','source_id','tenant_id']::text[], ARRAY['config']::text[], ARRAY['id']::text[], NULL, NULL, NULL, 'client_id', FALSE, 'trigger'),
    ('source_record_lifecycle_mappings', 'covered', 'platform or operator decision or state', ARRAY['id','external_namespace','entity_type','canonical_field','match_value','lifecycle','counts_as_current_computer_evidence','priority','enabled','source_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('source_record_seen_daily', 'history_store', 'stores history or run records', '{}'::text[], '{}'::text[], ARRAY['tenant_id','source_record_id','rollup_day']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('source_refresh_outputs', 'exempt', 'run output bookkeeping', '{}'::text[], '{}'::text[], ARRAY['run_id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('source_run_queue', 'exempt', 'work queue', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('sources', 'covered', 'platform or operator decision or state', ARRAY['id','name','kind','capabilities','entity_type']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('suppression_rules', 'covered', 'platform or operator decision or state', ARRAY['id','subject_match','reason','expires_at','created_at','created_by_id','finding_type_id','tenant_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('tenants', 'covered', 'platform or operator decision or state', ARRAY['id','slug','display_name','brand_config','created_at']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('title_intel_cache', 'exempt', 'cache', '{}'::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('unmatched_source_groups', 'covered', 'platform or operator decision or state', ARRAY['id','tenant_id','source_id','external_id','external_name','status','first_seen_at','resolved_at','resolved_by']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('user_groups', 'covered', 'platform or operator decision or state', ARRAY['id','group_id','tenant_id','user_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('user_permissions', 'covered', 'platform or operator decision or state', ARRAY['id','permission_id','tenant_id','user_id']::text[], '{}'::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('users', 'covered', 'platform or operator decision or state', ARRAY['id','is_superuser','username','first_name','last_name','email','is_staff','is_active','date_joined','timezone','tenant_id']::text[], ARRAY['password']::text[], ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger');

SELECT operations.enable_change_history(table_name)
  FROM operations.change_history_registry
 WHERE classification = 'covered'
   AND to_regclass('operations.' || quote_ident(table_name)) IS NOT NULL
 ORDER BY table_name;
"""

FINDING_TYPE = {
    "name": "change_history_unclassified",
    "display_name": "Table not classified for change history",
    "description": (
        "A table in the operations schema is not in the change history registry, so changes "
        "to it are not recorded or knowingly exempted. Classify it in a migration."
    ),
    "issue_category": "Data collection",
    "issue_group": "Collection and processing",
    "sort_order": 575,
}


def build_policy(active: dict) -> dict:
    policy = json.loads(json.dumps(active))
    policy["version"] = POLICY_VERSION
    names = {item.get("name") for item in policy["definitions"]}
    if FINDING_TYPE["name"] not in names:
        policy["definitions"].append(
            {"name": FINDING_TYPE["name"], "rules": ["parent_open"], "lifecycle": "active"}
        )
    return policy


def digest(policy: dict) -> str:
    return hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()


def register_finding_type(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO operations.finding_types (
                name, default_severity, finding_class, source_module, subject_scope,
                creates_device_exposure, auto_resolvable, suppressed_by_approval,
                concern_signal, default_decision_scope, drilldown_evidence_key, runbook_path,
                description, display_name, issue_category, issue_group, sort_order
            ) VALUES (%s, 'medium', 'admin', 'evaluator', 'global', FALSE, TRUE, FALSE, FALSE,
                      'global', '', '', %s, %s, %s, %s, %s)
            ON CONFLICT (name) DO NOTHING
            """,
            (
                FINDING_TYPE["name"],
                FINDING_TYPE["description"],
                FINDING_TYPE["display_name"],
                FINDING_TYPE["issue_category"],
                FINDING_TYPE["issue_group"],
                FINDING_TYPE["sort_order"],
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
        ("operations", "0305_remove_lifecycle_transition_noise"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FOUNDATION_SQL, migrations.RunSQL.noop),
        migrations.RunPython(register_finding_type, migrations.RunPython.noop),
    ]
