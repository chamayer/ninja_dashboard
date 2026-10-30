"""One-key source-record cases and audited duplicate dispositions (PLAN-004 R4 Stage C).

A case is one qualified question about one shared key: several present records
of one source instance report the same serial, VM UUID or MAC (design §6.1).
It is a native mechanism subject, not a Computer and not proof of shared
physical identity. Joining through one key adopts no other key; a record can be
a member of several cases. There is no combine, split, redirect or repointing.

* ``source_record_cases``: one open (or validly reserved duplicate) case per
  scope, enforced by a partial unique index. A valid duplicate disposition keeps
  its scope reserved so the evaluator does not recreate the case.
* ``source_record_case_members``: active and released memberships with
  provenance; each member qualifies directly under the case's key.
* ``mark_source_record_case_duplicate``: the one operator decision. Exclusive
  tenant guard required; rejects self, cyclic and cross-tenant references;
  records reason, actor and the member fingerprint it was made against; resolves
  the case finding as a duplicate disposition (never a verified correction);
  advances the tenant generation and requeues both keys.

The case-key queue rows from 0370 are queued again; Stage A acknowledged them
without effect.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE TABLE operations.source_record_cases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id bigint NOT NULL REFERENCES operations.tenants (id),
    scope_key uuid NOT NULL,
    family text NOT NULL DEFAULT 'duplicate_review' CHECK (family IN ('duplicate_review')),
    correction_dimension text NOT NULL DEFAULT 'duplicate_entry',
    compatible_role text NOT NULL DEFAULT 'computer',
    source_instance_id uuid NOT NULL,
    key_family text NOT NULL CHECK (key_family IN ('serial', 'vm_uuid', 'mac')),
    key_value text NOT NULL CHECK (key_value > ''),
    normalization_version smallint NOT NULL DEFAULT 1,
    state text NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'duplicate', 'closed')),
    version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
    member_count integer NOT NULL DEFAULT 0,
    member_fingerprint text NOT NULL DEFAULT '',
    duplicate_of_id uuid,
    disposition_valid boolean NOT NULL DEFAULT false,
    disposition_fingerprint text NOT NULL DEFAULT '',
    decision_reason text NOT NULL DEFAULT '',
    decided_by_id bigint,
    decided_at timestamptz,
    opened_at timestamptz NOT NULL DEFAULT now(),
    closed_at timestamptz,
    closure_reason text NOT NULL DEFAULT '',
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, source_instance_id)
        REFERENCES operations.source_instances (tenant_id, id),
    FOREIGN KEY (tenant_id, duplicate_of_id)
        REFERENCES operations.source_record_cases (tenant_id, id),
    CHECK (duplicate_of_id IS NULL OR duplicate_of_id <> id),
    CHECK (state <> 'duplicate' OR (duplicate_of_id IS NOT NULL AND decision_reason > ''))
);
CREATE UNIQUE INDEX uq_source_record_cases_one_open_per_scope
    ON operations.source_record_cases (tenant_id, scope_key)
    WHERE state = 'open' OR (state = 'duplicate' AND disposition_valid);
CREATE INDEX idx_source_record_cases_state
    ON operations.source_record_cases (tenant_id, state, key_family);

CREATE TABLE operations.source_record_case_members (
    tenant_id bigint NOT NULL,
    case_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    evidence_role text NOT NULL DEFAULT 'shares_key',
    joined_at timestamptz NOT NULL DEFAULT now(),
    released_at timestamptz,
    release_reason text NOT NULL DEFAULT '',
    FOREIGN KEY (tenant_id, case_id)
        REFERENCES operations.source_record_cases (tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, subject_id)
        REFERENCES operations.source_record_subjects (tenant_id, id)
);
CREATE UNIQUE INDEX uq_source_record_case_members_active
    ON operations.source_record_case_members (tenant_id, case_id, subject_id)
    WHERE released_at IS NULL;
CREATE INDEX idx_source_record_case_members_subject
    ON operations.source_record_case_members (tenant_id, subject_id)
    WHERE released_at IS NULL;

DO $rls$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['source_record_cases', 'source_record_case_members'] LOOP
        EXECUTE format('ALTER TABLE operations.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE operations.%I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON operations.%I
               USING (tenant_id = nullif(current_setting(''operations.tenant_id'', true), '''')::bigint)
               WITH CHECK (tenant_id = nullif(current_setting(''operations.tenant_id'', true), '''')::bigint)',
            t);
        EXECUTE format('REVOKE ALL ON operations.%I FROM PUBLIC', t);
        EXECUTE format(
            'REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.%I
               FROM operations_app, ninja_ingest, operations_readonly', t);
        EXECUTE format(
            'GRANT SELECT ON operations.%I TO operations_app, operations_readonly, ninja_ingest', t);
        -- Case publication is graph work: exclusive guard and findings contract.
        EXECUTE format(
            'CREATE TRIGGER assert_findings_writer BEFORE INSERT OR UPDATE OR DELETE
               ON operations.%I FOR EACH STATEMENT
               EXECUTE FUNCTION operations.assert_findings_writer()', t);
        EXECUTE format(
            'CREATE TRIGGER assert_findings_row_tenant BEFORE INSERT OR UPDATE OR DELETE
               ON operations.%I FOR EACH ROW
               EXECUTE FUNCTION operations.assert_findings_row_tenant()', t);
    END LOOP;
END
$rls$;

INSERT INTO operations.change_history_registry (
    table_name, classification, reason, recorded_columns, secret_columns, key_columns,
    computer_column, computer_condition_column, computer_condition_value, client_column,
    is_global, capture
) VALUES
    ('source_record_cases', 'covered', 'platform or operator decision or state',
     ARRAY['id', 'state', 'version', 'member_count', 'duplicate_of_id', 'disposition_valid',
           'decision_reason', 'decided_by_id', 'closure_reason']::text[], '{}'::text[],
     ARRAY['id']::text[], NULL, NULL, NULL, NULL, FALSE, 'trigger'),
    ('source_record_case_members', 'exempt',
     'derived membership with joined/released provenance kept in the row',
     '{}'::text[], '{}'::text[], '{}'::text[], NULL, NULL, NULL, NULL, FALSE, NULL)
ON CONFLICT (table_name) DO NOTHING;
SELECT operations.enable_change_history('source_record_cases');

-- The operator duplicate disposition (design §6.1).
CREATE FUNCTION operations.mark_source_record_case_duplicate(
    p_case uuid, p_duplicate_of uuid, p_reason text, p_actor bigint, p_expected_version bigint
) RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_tenant bigint := nullif(current_setting('operations.tenant_id', true), '')::bigint;
    v_case operations.source_record_cases%ROWTYPE;
    v_target operations.source_record_cases%ROWTYPE;
    v_cursor uuid;
    v_steps integer := 0;
    v_type smallint;
BEGIN
    PERFORM operations.assert_tenant_guard(v_tenant, 'exclusive');
    IF p_reason IS NULL OR btrim(p_reason) = '' THEN
        RAISE EXCEPTION 'a duplicate disposition needs a reason';
    END IF;
    IF p_case = p_duplicate_of THEN
        RAISE EXCEPTION 'a case cannot be a duplicate of itself';
    END IF;
    SELECT * INTO v_case FROM operations.source_record_cases
     WHERE tenant_id = v_tenant AND id = p_case FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'case % not found for this tenant', p_case;
    END IF;
    IF v_case.version <> p_expected_version THEN
        RAISE EXCEPTION 'the case changed since it was shown (version % now %); review it again',
                        p_expected_version, v_case.version;
    END IF;
    IF v_case.state <> 'open' THEN
        RAISE EXCEPTION 'only an open case can be marked a duplicate (state %)', v_case.state;
    END IF;
    SELECT * INTO v_target FROM operations.source_record_cases
     WHERE tenant_id = v_tenant AND id = p_duplicate_of FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'target case % not found for this tenant', p_duplicate_of;
    END IF;
    IF v_target.state = 'closed' THEN
        RAISE EXCEPTION 'the target case is closed';
    END IF;
    v_cursor := v_target.duplicate_of_id;
    WHILE v_cursor IS NOT NULL LOOP
        IF v_cursor = p_case THEN
            RAISE EXCEPTION 'the disposition would form a cycle';
        END IF;
        v_steps := v_steps + 1;
        IF v_steps > 100 THEN
            RAISE EXCEPTION 'duplicate chain too long';
        END IF;
        SELECT duplicate_of_id INTO v_cursor FROM operations.source_record_cases
         WHERE tenant_id = v_tenant AND id = v_cursor;
    END LOOP;

    UPDATE operations.source_record_cases
       SET state = 'duplicate', duplicate_of_id = p_duplicate_of, disposition_valid = true,
           disposition_fingerprint = member_fingerprint, decision_reason = btrim(p_reason),
           decided_by_id = p_actor, decided_at = now(), version = version + 1
     WHERE tenant_id = v_tenant AND id = p_case;

    SELECT id INTO v_type FROM operations.finding_types WHERE name = 'source_record_duplicate_review';
    UPDATE operations.findings
       SET status = 'resolved', closed_at = now(), last_seen_at = now(),
           finding_details = finding_details || jsonb_build_object(
               'disposition', 'duplicate_of', 'duplicate_of_case', p_duplicate_of,
               'disposition_reason', btrim(p_reason), 'decided_by_id', p_actor,
               'decided_at', now())
     WHERE tenant_id = v_tenant AND finding_type_id = v_type
       AND subject_type = 'source_record_case' AND subject_id = p_case
       AND status IN ('open', 'acknowledged', 'investigating', 'suppressed');

    INSERT INTO operations.source_record_tenant_state AS t (tenant_id, input_generation)
    VALUES (v_tenant, 1)
    ON CONFLICT (tenant_id) DO UPDATE SET input_generation = t.input_generation + 1,
                                          updated_at = now();
    PERFORM operations.source_record_enqueue(v_tenant, 'case_key', v_case.scope_key,
        jsonb_build_object('source_instance_id', v_case.source_instance_id,
                           'key_family', v_case.key_family, 'normalized_value', v_case.key_value));
    PERFORM operations.source_record_enqueue(v_tenant, 'case_key', v_target.scope_key,
        jsonb_build_object('source_instance_id', v_target.source_instance_id,
                           'key_family', v_target.key_family, 'normalized_value', v_target.key_value));
    RETURN v_case.version + 1;
END
$fn$;
REVOKE ALL ON FUNCTION operations.mark_source_record_case_duplicate(uuid, uuid, text, bigint, bigint)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.mark_source_record_case_duplicate(uuid, uuid, text, bigint, bigint)
    TO operations_app;

UPDATE operations.source_record_assessment_queue
   SET dirty_revision = dirty_revision + 1, status = 'pending', queued_at = now()
 WHERE target_kind = 'case_key';
INSERT INTO operations.source_record_assessment_queue (tenant_id, target_kind, target_id, target_key)
SELECT k.tenant_id, 'case_key',
       operations.source_record_case_key_id(k.tenant_id, k.source_instance_id, k.key_family, k.normalized_value),
       jsonb_build_object('source_instance_id', k.source_instance_id,
                          'key_family', k.key_family, 'normalized_value', k.normalized_value)
  FROM operations.source_record_lookup_keys k
 WHERE k.key_family <> 'name'
 GROUP BY k.tenant_id, k.source_instance_id, k.key_family, k.normalized_value
HAVING count(*) > 1
ON CONFLICT DO NOTHING;
"""

REVERSE_SQL = r"""
DROP FUNCTION IF EXISTS operations.mark_source_record_case_duplicate(uuid, uuid, text, bigint, bigint);
DROP TABLE IF EXISTS operations.source_record_cases_change_history;
DELETE FROM operations.change_history_registry
 WHERE table_name IN ('source_record_cases', 'source_record_case_members');
DROP TABLE IF EXISTS operations.source_record_case_members;
DROP TABLE IF EXISTS operations.source_record_cases;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0372_source_record_assessment_resource_limit"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
