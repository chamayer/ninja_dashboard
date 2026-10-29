"""Copy admin findings into the common findings ledger (PLAN-003 M2).

Part of the coordinated M2-M4 artifact: it runs only in the drained maintenance
window, together with the protected writers (M3) and the reader cutover (M4), and
no process is served between them.

* Aborts unless the preflight invariants still hold: no UUID in both ledgers, no
  active condition key in both ledgers for a tenant, no tenant mismatch on the R1
  composite FKs.
* Deletes the admin-labelled assessments and participants whose finding is not
  an admin finding (4 + 4 in production on 2026-10-29, all belonging to entity
  findings). Assessments are derived; evaluation re-assesses real conditions.
* ``subject_id`` may be NULL only for structured subjects: a source group, a
  source group set or retained legacy context, each with a non-empty
  ``subject_ref``.
* Every admin row is copied with its UUID, version, key, severity and status,
  ``condition_namespace = 'admin'`` and the field map of technical design §3.
  Its subject is normalized from the admin ``subject_ref``; the original value is
  kept byte-for-byte under ``subject_ref -> 'legacy_ref'`` and a legacy reference
  row records the admin origin. References that do not resolve in the tenant
  (deleted Computer, client or binding) become ``legacy_context`` rather than a
  guessed target.
* Active-key uniqueness becomes (tenant, namespace, key) with the same four
  active statuses, since equal keys in the two old ledgers are not the same
  condition.
* Assessments and participants get composite (tenant_id, finding_id) FKs to
  findings; the R1 FKs are validated.

``condition_identity`` stays NULL: identity is still derived from tenant,
namespace (the legacy ``row_kind``), type name and key exactly as today. A later
semantic conversion that changes one of those inputs stores the old identity.
The copy is recorded in change history as one storage-migration action.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
DO $$
DECLARE
    v_count bigint;
BEGIN
    SELECT count(*) INTO v_count
      FROM operations.findings f JOIN operations.admin_findings a ON a.id = f.id;
    IF v_count > 0 THEN
        RAISE EXCEPTION 'M2 preflight: % finding UUIDs exist in both ledgers', v_count;
    END IF;
    SELECT count(*) INTO v_count
      FROM operations.findings f
      JOIN operations.admin_findings a
        ON a.tenant_id = f.tenant_id AND a.condition_key = f.condition_key
     WHERE f.condition_key > ''
       AND f.status IN ('open', 'acknowledged', 'investigating', 'suppressed')
       AND a.status IN ('open', 'acknowledged', 'investigating', 'suppressed');
    IF v_count > 0 THEN
        RAISE EXCEPTION 'M2 preflight: % active condition keys exist in both ledgers', v_count;
    END IF;
    SELECT count(*) INTO v_count
      FROM operations.finding_state s JOIN operations.findings f ON f.id = s.finding_id
     WHERE s.tenant_id <> f.tenant_id;
    v_count := v_count + (
        SELECT count(*)
          FROM operations.source_action_requests r JOIN operations.findings f ON f.id = r.finding_id
         WHERE r.tenant_id <> f.tenant_id);
    IF v_count > 0 THEN
        RAISE EXCEPTION 'M2 preflight: % related rows disagree with their finding tenant', v_count;
    END IF;
END
$$;

SELECT operations.begin_change(
    'plan003.m2_admin_findings_conversion',
    'Storage migration: admin findings copied into the common findings ledger',
    '{}'::jsonb, 'migration', NULL, 'operations.0364', '0364', NULL, true);

DELETE FROM operations.condition_participants x
 WHERE x.row_kind = 'admin'
   AND NOT EXISTS (SELECT 1 FROM operations.admin_findings a WHERE a.id = x.finding_id);
DELETE FROM operations.condition_assessments x
 WHERE x.row_kind = 'admin'
   AND NOT EXISTS (SELECT 1 FROM operations.admin_findings a WHERE a.id = x.finding_id);

DROP INDEX operations.uq_findings_active_condition_key_scope;
CREATE UNIQUE INDEX uq_findings_active_condition_key_scope
    ON operations.findings (tenant_id, condition_namespace, condition_key)
    WHERE condition_key > ''
      AND status IN ('open', 'acknowledged', 'investigating', 'suppressed');
ALTER TABLE operations.findings ALTER COLUMN subject_id DROP NOT NULL;
ALTER TABLE operations.findings ADD CONSTRAINT findings_structured_subject CHECK (
    subject_id IS NOT NULL
    OR (subject_type IN ('source_group', 'source_group_set', 'legacy_context')
        AND subject_ref <> '{}'::jsonb));

-- Normalized subject for each admin row. A reference is used only when it
-- resolves to a row of the same tenant; otherwise the row keeps legacy context.
CREATE TEMP TABLE m2_admin_subjects ON COMMIT DROP AS
WITH parsed AS (
    SELECT a.*,
           t.name AS type_name,
           CASE WHEN a.subject_ref->>'device_id' ~* '^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$'
                THEN (a.subject_ref->>'device_id')::uuid END AS ref_device,
           CASE WHEN a.subject_ref->>'client_id' ~* '^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$'
                THEN (a.subject_ref->>'client_id')::uuid END AS ref_client,
           CASE WHEN a.subject_ref->>'source_binding_id' ~* '^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$'
                THEN (a.subject_ref->>'source_binding_id')::uuid END AS ref_binding,
           CASE WHEN a.subject_ref->>'signal_id' ~* '^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$'
                THEN (a.subject_ref->>'signal_id')::uuid END AS ref_signal
      FROM operations.admin_findings a
      JOIN operations.finding_types t ON t.id = a.finding_type_id
), resolved AS (
    SELECT p.*,
           EXISTS (SELECT 1 FROM operations.devices d
                    WHERE d.id = p.ref_device AND d.tenant_id = p.tenant_id) AS device_ok,
           EXISTS (SELECT 1 FROM operations.clients c
                    WHERE c.id = p.ref_client AND c.tenant_id = p.tenant_id) AS client_ok,
           EXISTS (SELECT 1 FROM operations.source_bindings b
                    WHERE b.id = p.ref_binding AND b.tenant_id = p.tenant_id) AS binding_ok
      FROM parsed p
)
SELECT r.id,
       CASE
           WHEN r.ref_signal IS NOT NULL THEN 'platform_signal'
           WHEN r.ref_binding IS NOT NULL AND r.binding_ok AND r.subject_ref ? 'external_id'
               THEN 'source_group'
           WHEN r.ref_binding IS NOT NULL AND r.binding_ok THEN 'source_binding'
           WHEN r.ref_device IS NOT NULL AND r.device_ok THEN 'device'
           WHEN r.ref_client IS NOT NULL AND r.client_ok THEN 'client'
           WHEN r.subject_ref ? 'source_id' AND r.finding_details_external_ids IS NOT NULL
               THEN 'source_group_set'
           ELSE 'legacy_context'
       END AS subject_type,
       r.ref_signal, r.ref_binding, r.ref_device, r.ref_client,
       r.binding_ok, r.device_ok, r.client_ok, r.finding_details_external_ids
  FROM (SELECT resolved.*,
               CASE WHEN jsonb_typeof(resolved.details->'external_ids') = 'array'
                    THEN resolved.details->'external_ids' END AS finding_details_external_ids
          FROM resolved) r;

INSERT INTO operations.findings (
    version, id, subject_type, subject_id, finding_details, severity, status,
    sla_due_at, first_seen_at, last_seen_at, last_reviewed_at, finding_type_id,
    owner_id, tenant_id, client_id, condition_key, confidence, last_detected_at,
    snoozed_until, acknowledged_at, closed_at, subject_layer, subject_layer_entity_id,
    subject_ref, condition_namespace)
SELECT a.version, a.id, s.subject_type,
       CASE s.subject_type
           WHEN 'platform_signal' THEN s.ref_signal
           WHEN 'source_binding' THEN s.ref_binding
           WHEN 'device' THEN s.ref_device
           WHEN 'client' THEN s.ref_client
       END,
       a.details, a.severity, a.status,
       NULL, a.first_detected_at, a.last_detected_at, NULL, a.finding_type_id,
       NULL, a.tenant_id, CASE WHEN s.client_ok THEN s.ref_client END,
       a.condition_key, '', a.last_detected_at,
       NULL, NULL, a.resolved_at, '', NULL,
       jsonb_strip_nulls(jsonb_build_object(
           'kind', s.subject_type,
           'source_binding_id', CASE WHEN s.binding_ok THEN s.ref_binding::text END,
           'source_id', a.subject_ref->'source_id',
           'external_id', a.subject_ref->'external_id',
           'external_ids', CASE WHEN s.subject_type = 'source_group_set'
                                THEN s.finding_details_external_ids END,
           'signal_kind', a.subject_ref->'signal_kind'))
       || jsonb_build_object('legacy_ref', a.subject_ref),
       'admin'
  FROM operations.admin_findings a
  JOIN m2_admin_subjects s ON s.id = a.id;

INSERT INTO operations.finding_legacy_refs (tenant_id, legacy_kind, legacy_id, finding_id)
SELECT a.tenant_id, 'admin_finding', a.id::text, a.id FROM operations.admin_findings a;
-- Flush the findings FKs (deferred) before altering related tables.
SET CONSTRAINTS ALL IMMEDIATE;


ALTER TABLE operations.condition_assessments
    ADD CONSTRAINT condition_assessments_tenant_finding_fkey
    FOREIGN KEY (tenant_id, finding_id) REFERENCES operations.findings (tenant_id, id)
    NOT VALID;
ALTER TABLE operations.condition_participants
    ADD CONSTRAINT condition_participants_tenant_finding_fkey
    FOREIGN KEY (tenant_id, finding_id) REFERENCES operations.findings (tenant_id, id)
    NOT VALID;
ALTER TABLE operations.condition_assessments
    VALIDATE CONSTRAINT condition_assessments_tenant_finding_fkey;
ALTER TABLE operations.condition_participants
    VALIDATE CONSTRAINT condition_participants_tenant_finding_fkey;
ALTER TABLE operations.finding_state VALIDATE CONSTRAINT finding_state_tenant_finding_fkey;
ALTER TABLE operations.source_action_requests
    VALIDATE CONSTRAINT source_action_requests_tenant_finding_fkey;

DO $$
DECLARE
    v_admin bigint;
    v_copied bigint;
BEGIN
    SELECT count(*) INTO v_admin FROM operations.admin_findings;
    SELECT count(*) INTO v_copied
      FROM operations.findings f JOIN operations.admin_findings a USING (id)
     WHERE f.condition_namespace = 'admin'
       AND f.tenant_id = a.tenant_id AND f.version = a.version
       AND f.condition_key = a.condition_key AND f.status = a.status
       AND f.severity = a.severity AND f.finding_type_id = a.finding_type_id
       AND f.finding_details = a.details
       AND f.subject_ref->'legacy_ref' = a.subject_ref
       AND f.first_seen_at = a.first_detected_at
       AND f.last_detected_at = a.last_detected_at
       AND f.closed_at IS NOT DISTINCT FROM a.resolved_at;
    IF v_copied <> v_admin THEN
        RAISE EXCEPTION 'M2 conservation: % of % admin findings copied exactly', v_copied, v_admin;
    END IF;
END
$$;
"""

REVERSE_SQL = r"""
ALTER TABLE operations.condition_participants
    DROP CONSTRAINT IF EXISTS condition_participants_tenant_finding_fkey;
ALTER TABLE operations.condition_assessments
    DROP CONSTRAINT IF EXISTS condition_assessments_tenant_finding_fkey;
DROP INDEX operations.uq_findings_active_condition_key_scope;
DELETE FROM operations.finding_legacy_refs WHERE legacy_kind = 'admin_finding';
DELETE FROM operations.finding_state s
 USING operations.findings f
 WHERE f.id = s.finding_id AND f.condition_namespace = 'admin';
DELETE FROM operations.findings WHERE condition_namespace = 'admin';
CREATE UNIQUE INDEX uq_findings_active_condition_key_scope
    ON operations.findings (tenant_id, condition_key)
    WHERE condition_key > ''
      AND status IN ('open', 'acknowledged', 'investigating', 'suppressed');
ALTER TABLE operations.findings DROP CONSTRAINT IF EXISTS findings_structured_subject;
ALTER TABLE operations.findings ALTER COLUMN subject_id SET NOT NULL;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0363_common_findings_expansion"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
