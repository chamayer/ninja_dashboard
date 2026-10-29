-- PLAN-003 R2 rehearsal fixture: one synthetic admin finding per production
-- subject shape (see results-2026-10-29.md), with resolvable and unresolvable
-- references. Run on a scratch database before migration 0364. No real data:
-- referenced IDs are taken from existing scratch rows or generated.
BEGIN;
CREATE TEMP TABLE m2_fixture_expect (id uuid PRIMARY KEY, expect_subject text NOT NULL);

DO $$
DECLARE
    v_device uuid := (SELECT id FROM operations.devices WHERE tenant_id = 1 LIMIT 1);
    v_client uuid := (SELECT id FROM operations.clients WHERE tenant_id = 1 LIMIT 1);
    v_binding uuid := (SELECT id FROM operations.source_bindings WHERE tenant_id = 1 LIMIT 1);
    v_missing uuid := gen_random_uuid();
    v_signal uuid := gen_random_uuid();
    r record;
BEGIN
    FOR r IN SELECT * FROM (VALUES
        ('client_name_conflict', jsonb_build_object('client_display_name', 'X', 'client_id', v_client,
            'client_link_id', 1, 'external_id', 'e1', 'observed_name', 'x', 'source_id', 3),
            '{}'::jsonb, 'client'),
        ('client_name_conflict', jsonb_build_object('client_display_name', 'X', 'client_id', v_missing,
            'client_link_id', 1, 'external_id', 'e1', 'observed_name', 'x', 'source_id', 3,
            'external_name_stored', 'y'), '{}'::jsonb, 'legacy_context'),
        ('client_source_group_merge', jsonb_build_object('external_id', 'g1', 'source_id', 3),
            jsonb_build_object('external_ids', jsonb_build_array('g1', 'g2')), 'source_group_set'),
        ('client_source_group_merge', jsonb_build_object('external_id', 'g1', 'source_id', 3),
            '{}'::jsonb, 'legacy_context'),
        ('client_unattached_group', jsonb_build_object('external_id', 'g3', 'external_name', 'G',
            'platform', 'ninja', 'source_binding_id', v_binding), '{}'::jsonb, 'source_group'),
        ('client_unattached_group', jsonb_build_object('external_id', 'g3', 'external_name', 'G',
            'platform', 'ninja', 'source_binding_id', v_missing), '{}'::jsonb, 'legacy_context'),
        ('duplicate_platform_record', jsonb_build_object('client_id', v_client, 'device_id', v_device,
            'entity_type', 'computer', 'hostname', 'h', 'platform', 'ninja'), '{}'::jsonb, 'device'),
        ('duplicate_platform_record', jsonb_build_object('client_id', v_client, 'entity_type', 'computer',
            'hostname', 'h', 'platform', 'ninja', 'observed_at', NULL), '{}'::jsonb, 'client'),
        ('jobs_timeout', jsonb_build_object('signal_id', v_signal, 'signal_kind', 'jobs'),
            '{}'::jsonb, 'platform_signal'),
        ('software_inventory_held', jsonb_build_object('device_id', v_device, 'signal_id', gen_random_uuid(),
            'signal_kind', 'software_inventory'), '{}'::jsonb, 'platform_signal'),
        ('source_failure', jsonb_build_object('client_id', v_client, 'platform', 'ninja',
            'source_binding_id', v_binding), '{}'::jsonb, 'source_binding'),
        ('source_failure', jsonb_build_object('platform', 'ninja'), '{}'::jsonb, 'legacy_context'),
        ('source_failure', jsonb_build_object('signal_id', gen_random_uuid(), 'signal_kind', 'domain'),
            '{}'::jsonb, 'platform_signal')
    ) AS s(type_name, ref, details, expect) LOOP
        WITH ins AS (
            INSERT INTO operations.admin_findings (version, id, condition_key, severity, status,
                subject_ref, details, first_detected_at, last_detected_at, resolved_at,
                finding_type_id, tenant_id)
            SELECT 0, gen_random_uuid(), 'm2-fixture-' || gen_random_uuid(), 'medium', 'open',
                   r.ref, r.details, now(), now(), NULL, t.id, 1
              FROM operations.finding_types t WHERE t.name = r.type_name
            RETURNING id)
        INSERT INTO m2_fixture_expect SELECT id, r.expect FROM ins;
    END LOOP;
END
$$;

CREATE TABLE public.m2_fixture_expect AS SELECT * FROM m2_fixture_expect;
SELECT count(*) AS fixture_rows FROM public.m2_fixture_expect;
COMMIT;
