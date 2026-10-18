"""Roaming agent records are not hardware evidence (ADR-0032).

Found 2026-10-18: SentinelOne agents baked into Citrix MCS golden images
(CitrixAppMCS, UTAW-CTX-Golden, CTXMCSGOLD) keep one agent identity while it
moves from clone to clone, reporting each clone's name and VMware serial in
turn (5 to 11 serials per record). The automatic merge matched such a record
on the serial it held at that moment and merged citrixappmcs into
citrixapp27 although neither machine was proven the other.

``operations.identity_roaming_records`` lists agent records that have
reported three or more usable serials under three or more names. Matching,
the automatic merge, ``shared_serial`` and the two-machines check ignore
their serial and VM UUID; the records still attach by name and are still
shown. A genuine rename or hardware change shows two (measured: 62 records
with two serials, none of the real machines with three).

``operations.refresh_identity_roaming_records`` recomputes the list from the
observation history (about 6 s in production); the resolver calls it when it
is older than an hour.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE TABLE operations.identity_roaming_records (
    tenant_id bigint NOT NULL,
    source_instance_id uuid NOT NULL,
    external_id text NOT NULL,
    platform varchar(80) NOT NULL,
    serial_count integer NOT NULL,
    name_count integer NOT NULL,
    computed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, source_instance_id, external_id)
);
ALTER TABLE operations.identity_roaming_records ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_read ON operations.identity_roaming_records FOR SELECT
    USING (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint);
REVOKE ALL ON operations.identity_roaming_records FROM PUBLIC;
GRANT SELECT ON operations.identity_roaming_records TO operations_app, operations_readonly, ninja_ingest;

INSERT INTO operations.change_history_registry (
    table_name, classification, reason, recorded_columns, secret_columns, key_columns,
    computer_column, computer_condition_column, computer_condition_value, client_column,
    is_global, capture
) VALUES (
    'identity_roaming_records', 'exempt',
    'derived from observation history each hour; rebuildable',
    '{}'::text[], '{}'::text[], '{}'::text[], NULL, NULL, NULL, NULL, FALSE, NULL
) ON CONFLICT (table_name) DO NOTHING;

CREATE FUNCTION operations.refresh_identity_roaming_records(p_tenant bigint)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_count integer;
BEGIN
    DELETE FROM operations.identity_roaming_records WHERE tenant_id = p_tenant;
    INSERT INTO operations.identity_roaming_records
        (tenant_id, source_instance_id, external_id, platform, serial_count, name_count)
    SELECT p_tenant, h.source_instance_id, h.external_id, min(h.platform),
           count(DISTINCT lower(btrim(h.material_data ->> 'serial_number'))) FILTER (
               WHERE length(btrim(coalesce(h.material_data ->> 'serial_number', ''))) >= 4
                 AND lower(h.material_data ->> 'serial_number') <> 'none'),
           count(DISTINCT lower(h.material_data ->> 'hostname'))
      FROM operations.entity_observation_history h
     WHERE h.tenant_id = p_tenant AND h.entity_type LIKE 'agent.%'
       AND h.entity_key NOT LIKE 'device-health:%'
     GROUP BY h.source_instance_id, h.external_id
    HAVING count(DISTINCT lower(btrim(h.material_data ->> 'serial_number'))) FILTER (
               WHERE length(btrim(coalesce(h.material_data ->> 'serial_number', ''))) >= 4
                 AND lower(h.material_data ->> 'serial_number') <> 'none') >= 3
       AND count(DISTINCT lower(h.material_data ->> 'hostname')) >= 3;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END
$fn$;
REVOKE ALL ON FUNCTION operations.refresh_identity_roaming_records(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.refresh_identity_roaming_records(bigint) TO ninja_ingest;

SELECT operations.refresh_identity_roaming_records(t.id) FROM operations.tenants t;

-- Merges proven only by roaming records are undone: every record the merge
-- moved is roaming, so no machine evidence joined the two (2026-10-18: the
-- citrixapp27 / citrixappmcs merge). The split is recorded with its reason;
-- the resolver treats a split pair as kept apart.
SELECT operations.split_computer_merge(
           m.id,
           'Proven only by an agent that moves between clones of one image (migration 0318).',
           'migration', NULL, 'operations.migrations')
  FROM operations.computer_merges m
 WHERE m.split_at IS NULL
   AND cardinality(m.moved_observation_ids) > 0
   AND NOT EXISTS (
       SELECT 1 FROM operations.entity_observation_current eo
        WHERE eo.observation_id = ANY(m.moved_observation_ids)
          AND eo.entity_type LIKE 'agent.%'
          AND eo.entity_key NOT LIKE 'device-health:%'
          AND NOT EXISTS (SELECT 1 FROM operations.identity_roaming_records rr
                           WHERE rr.tenant_id = eo.tenant_id
                             AND rr.source_instance_id = eo.source_instance_id
                             AND rr.external_id = eo.external_id))
   AND EXISTS (
       SELECT 1 FROM operations.entity_observation_current eo
         JOIN operations.identity_roaming_records rr
           ON rr.tenant_id = eo.tenant_id AND rr.source_instance_id = eo.source_instance_id
          AND rr.external_id = eo.external_id
        WHERE eo.observation_id = ANY(m.moved_observation_ids));
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0317_close_moved_link_history"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
