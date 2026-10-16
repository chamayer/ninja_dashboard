"""Operator decision ``in_use_confirmed`` (ADR-0032 "Retirement").

An operator who confirms that a Computer nothing reports for is still in use
puts it back in the coverage check: each missing required agent then raises
``missing_required_platform``, and the Computer is not retired automatically.
The decision is cleared, with its reason recorded, once the machine reports
again (``ingest.evaluator``).
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
SELECT operations.begin_change(
    'decision_dimension.register',
    'ADR-0032: confirming a Computer in use returns it to the coverage check.',
    '{"migration": "0311_confirmed_in_use"}'::jsonb,
    'migration', NULL, 'operations.migrations', '0311', NULL, true);

INSERT INTO operations.operator_decision_dimensions
    (name, entity_type, value_type, allowed_values, description, enabled)
VALUES
    ('in_use_confirmed', 'device', 'boolean', NULL,
     'An operator confirmed this Computer is still in use although nothing reports for it. '
     || 'It stays in the coverage check and is not retired automatically; cleared when it '
     || 'reports again.', TRUE)
ON CONFLICT (name) DO NOTHING;

CREATE FUNCTION operations.confirm_computers_in_use(
    p_device_ids uuid[],
    p_reason text,
    p_actor_id bigint DEFAULT NULL
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_tenant bigint;
    v_count integer;
BEGIN
    IF p_reason IS NULL OR p_reason = '' THEN
        RAISE EXCEPTION 'confirm_computers_in_use: a reason is required';
    END IF;
    SELECT min(tenant_id) INTO v_tenant
      FROM operations.devices WHERE id = ANY(p_device_ids) AND deleted_at IS NULL;
    IF v_tenant IS NULL THEN
        RAISE EXCEPTION 'confirm_computers_in_use: no current Computer';
    END IF;
    PERFORM set_config('operations.tenant_id', v_tenant::text, true);
    PERFORM operations.begin_change(
        'computer.confirm_in_use', p_reason,
        jsonb_build_object('device_ids', to_jsonb(p_device_ids)),
        'operator', p_actor_id, 'operations.ui', '', v_tenant, true);
    INSERT INTO operations.device_operator_decisions
        (id, version, tenant_id, device_id, dimension, value, reason, set_by, set_at)
    SELECT gen_random_uuid(), 1, d.tenant_id, d.id, 'in_use_confirmed', 'true'::jsonb,
           p_reason, coalesce('user:' || p_actor_id::text, 'operator'), now()
      FROM operations.devices d
     WHERE d.id = ANY(p_device_ids) AND d.deleted_at IS NULL AND d.tenant_id = v_tenant
    ON CONFLICT (tenant_id, device_id, dimension) DO UPDATE
       SET value = EXCLUDED.value, reason = EXCLUDED.reason, set_by = EXCLUDED.set_by,
           set_at = EXCLUDED.set_at, version = operations.device_operator_decisions.version + 1;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END
$fn$;

REVOKE ALL ON FUNCTION operations.confirm_computers_in_use(uuid[], text, bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.confirm_computers_in_use(uuid[], text, bigint) TO operations_app;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0310_listing_evidence_and_retirement"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
