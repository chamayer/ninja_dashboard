"""Add audited operator decisions for existing client/source relationships."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = """
CREATE TABLE operations.client_source_mapping_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id BIGINT NOT NULL REFERENCES operations.tenants(id) CHECK (tenant_id = 1),
    source_link_id UUID NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('explicit', 'automatic', 'ignored', 'review')),
    provenance TEXT NOT NULL CHECK (provenance IN ('operator', 'legacy_alias', 'resolver')),
    reason TEXT NOT NULL CHECK (length(reason) BETWEEN 1 AND 500),
    decided_by_id BIGINT REFERENCES operations.users(id),
    decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    superseded_at TIMESTAMPTZ,
    superseded_by_id UUID REFERENCES operations.client_source_mapping_decisions(id),
    CHECK ((superseded_at IS NULL) = (superseded_by_id IS NULL)),
    UNIQUE (tenant_id, id)
);
CREATE UNIQUE INDEX client_source_mapping_decisions_current
    ON operations.client_source_mapping_decisions (tenant_id, source_link_id)
    WHERE superseded_at IS NULL;

ALTER TABLE operations.client_source_mapping_decisions OWNER TO operations_migrate;
REVOKE ALL ON operations.client_source_mapping_decisions
    FROM PUBLIC, operations_app, operations_readonly, metabase_ro, ninja_ingest;
GRANT SELECT ON operations.client_source_mapping_decisions
    TO operations_app, operations_readonly, ninja_ingest;
ALTER TABLE operations.client_source_mapping_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.client_source_mapping_decisions FORCE ROW LEVEL SECURITY;
CREATE POLICY client_source_mapping_decisions_tenant ON operations.client_source_mapping_decisions
    USING (current_user = 'operations_migrate' OR tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint)
    WITH CHECK (current_user = 'operations_migrate' OR tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint);

CREATE FUNCTION operations.decide_client_source_mapping_v1(
    p_tenant_id BIGINT,
    p_source_link_id UUID,
    p_state TEXT,
    p_reason TEXT,
    p_actor_id BIGINT
) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $$
DECLARE
    v_new_id UUID;
BEGIN
    IF p_tenant_id <> 1
       OR p_state NOT IN ('explicit', 'automatic', 'ignored', 'review')
       OR length(btrim(coalesce(p_reason, ''))) NOT BETWEEN 1 AND 500
       OR NOT EXISTS (
           SELECT 1 FROM operations.v_client_source_link
            WHERE tenant_id = p_tenant_id AND id = p_source_link_id
       ) THEN
        RAISE EXCEPTION 'Invalid client source mapping decision';
    END IF;

    v_new_id := gen_random_uuid();
    UPDATE operations.client_source_mapping_decisions
       SET superseded_at = now(), superseded_by_id = v_new_id
     WHERE tenant_id = p_tenant_id
       AND source_link_id = p_source_link_id
       AND superseded_at IS NULL
       AND id <> v_new_id;

    INSERT INTO operations.client_source_mapping_decisions
        (id, tenant_id, source_link_id, state, provenance, reason, decided_by_id)
    VALUES
        (v_new_id, p_tenant_id, p_source_link_id, p_state, 'operator', btrim(p_reason), p_actor_id);
END;
$$;
ALTER FUNCTION operations.decide_client_source_mapping_v1(BIGINT, UUID, TEXT, TEXT, BIGINT)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.decide_client_source_mapping_v1(BIGINT, UUID, TEXT, TEXT, BIGINT)
    FROM PUBLIC, operations_app, operations_readonly, metabase_ro, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.decide_client_source_mapping_v1(BIGINT, UUID, TEXT, TEXT, BIGINT)
    TO operations_app;

CREATE VIEW operations.v_client_source_mapping_effective
WITH (security_barrier = true) AS
SELECT link.id AS source_link_id,
       link.tenant_id,
       link.client_id,
       link.source_id,
       link.external_id,
       link.external_namespace,
       link.first_seen_at,
       link.last_seen_at,
       link.missing_since,
       observation.observed_name,
       observation.observed_at,
       COALESCE(decision.state, 'review') AS mapping_state,
       decision.provenance,
       decision.reason AS decision_reason,
       decision.decided_at
  FROM operations.v_client_source_link link
  LEFT JOIN operations.client_source_mapping_decisions decision
    ON decision.tenant_id = link.tenant_id
   AND decision.source_link_id = link.id
   AND decision.superseded_at IS NULL
  LEFT JOIN LATERAL (
       SELECT COALESCE(NULLIF(observation.canonical_data ->> 'name', ''),
                       NULLIF(observation.canonical_data ->> 'display_name', '')) AS observed_name,
              observation.observed_at
         FROM operations.entity_observation_current observation
         JOIN operations.source_instances instance
           ON instance.id = observation.source_instance_id
        WHERE observation.tenant_id = link.tenant_id
          AND instance.source_id = link.source_id
          AND observation.entity_type = 'org'
          AND observation.external_namespace = link.external_namespace
          AND observation.external_id = link.external_id
          AND observation.active
        ORDER BY observation.observed_at DESC
        LIMIT 1
  ) observation ON TRUE;
ALTER VIEW operations.v_client_source_mapping_effective OWNER TO operations_view_owner;
REVOKE ALL ON operations.v_client_source_mapping_effective
    FROM PUBLIC, operations_app, operations_readonly, metabase_ro, ninja_ingest;
GRANT SELECT ON operations.v_client_source_mapping_effective
    TO operations_app, operations_readonly, ninja_ingest;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.v_client_source_mapping_effective
    FROM operations_app, operations_readonly, metabase_ro, ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [("operations", "0200_seed_findings_navigation_taxonomy")]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
