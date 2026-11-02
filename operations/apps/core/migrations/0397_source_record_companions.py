"""Ninja device health is part of the Ninja device record, not a record of its own (PLAN-038).

The Ninja health collection stores each device's health snapshot as its own
observation (namespace ``device-health``). Since 0370 every observation was
admitted as a source record, so each Ninja device had a second record, typed
like the device and linked to a Computer by itself.

A *companion stream* (admin-managed: ``source_record_companion_streams``) is a
data set that has no life of its own:

* it is never admitted as a source record and gets no link of its own;
* ``attach_source_record_companions`` attaches each of its observations to the
  owner record whose ``owner_key_field`` equals its external id;
* an active companion needs a present owner (deferred ``check_companion_owner``),
  and withdrawing the owner withdraws its companions in the same transaction;
* the attribute projector attributes companion claims to the owner's link, and a
  field the owner itself reports is not claimed again by the companion.

One-time cleanup: attach the existing health observations, end their own links
through ``set_source_association``, and remove their source records (none has a
case, disposition, Issue or lookup key; checked read-only 2026-11-02).
"""

from __future__ import annotations

import importlib
from typing import ClassVar

from django.db import migrations


def _projector_sql() -> str:
    """0103's claim projector (identical to production) with companion claims."""
    sql = importlib.import_module(
        "apps.core.migrations.0103_attribute_claim_projection"
    ).PROJECTOR_SQL
    start = sql.index(
        "CREATE OR REPLACE FUNCTION operations.sync_entity_attribute_claims_from_observations("
    )
    end = sql.index("$function$;", start) + len("$function$;")
    function = sql[start:end]
    edits = [
        (
            "               link.id AS entity_source_link_id, link.entity_id,\n",
            "               link.id AS entity_source_link_id, link.entity_id,\n"
            "               owner_observation.canonical_data AS owner_canonical_data,\n",
        ),
        (
            "                   || '|entity:' || COALESCE(link.entity_id::text, '')\n",
            "                   || '|entity:' || COALESCE(link.entity_id::text, '')\n"
            "                   || CASE WHEN owner.id IS NULL THEN '' ELSE\n"
            "                      '|owner:' || owner.id::text || ':'\n"
            "                      || COALESCE(encode(owner_observation.material_hash, 'hex'), '')\n"
            "                      END\n",
        ),
        (
            "        LEFT JOIN entity_source_links link\n"
            "          ON link.tenant_id = o.tenant_id\n"
            "         AND link.source_instance_id = o.source_instance_id\n"
            "         AND link.external_namespace = o.external_namespace\n"
            "         AND link.parent_external_namespace = o.parent_external_namespace\n"
            "         AND link.parent_external_id = o.parent_external_id\n"
            "         AND link.external_id = o.external_id\n",
            "        LEFT JOIN source_record_companions companion\n"
            "          ON companion.tenant_id = o.tenant_id\n"
            "         AND companion.observation_id = o.observation_id\n"
            "        LEFT JOIN source_record_subjects owner\n"
            "          ON owner.tenant_id = companion.tenant_id\n"
            "         AND owner.id = companion.owner_subject_id\n"
            "        LEFT JOIN entity_observation_current owner_observation\n"
            "          ON owner_observation.tenant_id = owner.tenant_id\n"
            "         AND owner_observation.observation_id = owner.observation_id\n"
            "        LEFT JOIN entity_source_links link\n"
            "          ON link.tenant_id = o.tenant_id\n"
            "         AND link.source_instance_id = o.source_instance_id\n"
            "         AND link.external_namespace\n"
            "             = COALESCE(owner.external_namespace, o.external_namespace)\n"
            "         AND link.parent_external_namespace\n"
            "             = COALESCE(owner.parent_external_namespace, o.parent_external_namespace)\n"
            "         AND link.parent_external_id\n"
            "             = COALESCE(owner.parent_external_id, o.parent_external_id)\n"
            "         AND link.external_id = COALESCE(owner.external_id, o.external_id)\n",
        ),
        (
            "    WHERE CASE mapping.document_kind\n"
            "          WHEN 'raw' THEN batch.raw_data ? mapping.source_field\n",
            "    WHERE NOT COALESCE(mapping.document_kind <> 'raw'\n"
            "               AND batch.owner_canonical_data ? mapping.source_field\n"
            "               AND batch.owner_canonical_data -> mapping.source_field <> 'null'::jsonb,\n"
            "               FALSE)\n"
            "      AND CASE mapping.document_kind\n"
            "          WHEN 'raw' THEN batch.raw_data ? mapping.source_field\n",
        ),
    ]
    for old, new in edits:
        if function.count(old) != 1:
            raise RuntimeError(f"0103 projector text changed; cannot place: {old.strip()[:60]}")
        function = function.replace(old, new)
    return function + "\n"


SCHEMA_SQL = r"""
CREATE TABLE operations.source_record_companion_streams (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id smallint NOT NULL REFERENCES operations.sources (id),
    external_namespace text NOT NULL CHECK (external_namespace > ''),
    owner_key_field text NOT NULL CHECK (owner_key_field > ''),
    description text NOT NULL CHECK (description > ''),
    enabled boolean NOT NULL DEFAULT true,
    UNIQUE (source_id, external_namespace)
);
REVOKE ALL ON operations.source_record_companion_streams FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.source_record_companion_streams
    FROM operations_app, ninja_ingest, operations_readonly;
GRANT SELECT ON operations.source_record_companion_streams
    TO operations_app, operations_readonly, ninja_ingest;
INSERT INTO operations.change_history_registry (
    table_name, classification, reason, recorded_columns, secret_columns, key_columns,
    computer_column, computer_condition_column, computer_condition_value, client_column,
    is_global, capture
) VALUES ('source_record_companion_streams', 'covered', 'admin-managed source configuration',
          ARRAY['id', 'source_id', 'external_namespace', 'owner_key_field', 'description',
                'enabled']::text[], '{}'::text[], ARRAY['id']::text[],
          NULL, NULL, NULL, NULL, TRUE, 'trigger')
ON CONFLICT (table_name) DO NOTHING;
SELECT operations.enable_change_history('source_record_companion_streams');

INSERT INTO operations.source_record_companion_streams (
    source_id, external_namespace, owner_key_field, description)
SELECT id, 'device-health', 'ninja_node_id',
       'Ninja device health (/v2/queries/device-health) is detail of the Ninja device record'
  FROM operations.sources WHERE name = 'Ninja';

CREATE TABLE operations.source_record_companions (
    tenant_id bigint NOT NULL REFERENCES operations.tenants (id),
    observation_id uuid NOT NULL,
    stream_id bigint NOT NULL REFERENCES operations.source_record_companion_streams (id),
    owner_subject_id uuid NOT NULL,
    attached_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, observation_id),
    FOREIGN KEY (tenant_id, observation_id)
        REFERENCES operations.entity_observation_current (tenant_id, observation_id)
        ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, owner_subject_id)
        REFERENCES operations.source_record_subjects (tenant_id, id) ON DELETE CASCADE
);
CREATE INDEX idx_source_record_companions_owner
    ON operations.source_record_companions (tenant_id, owner_subject_id);
ALTER TABLE operations.source_record_companions ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.source_record_companions FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.source_record_companions
    USING (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint)
    WITH CHECK (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint);
REVOKE ALL ON operations.source_record_companions FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.source_record_companions
    FROM operations_app, ninja_ingest, operations_readonly;
GRANT SELECT ON operations.source_record_companions
    TO operations_app, operations_readonly, ninja_ingest;
INSERT INTO operations.change_history_registry (
    table_name, classification, reason, recorded_columns, secret_columns, key_columns,
    computer_column, computer_condition_column, computer_condition_value, client_column,
    is_global, capture
) VALUES ('source_record_companions', 'exempt',
          'derived from observations by attach_source_record_companions',
          '{}'::text[], '{}'::text[], '{}'::text[], NULL, NULL, NULL, NULL, FALSE, NULL)
ON CONFLICT (table_name) DO NOTHING;

CREATE FUNCTION operations.is_companion_stream(
    p_tenant bigint, p_source_instance uuid, p_external_namespace text
) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
    SELECT EXISTS (
        SELECT 1 FROM operations.source_record_companion_streams cs
          JOIN operations.source_instances si ON si.source_id = cs.source_id
         WHERE si.tenant_id = p_tenant AND si.id = p_source_instance
           AND cs.external_namespace = p_external_namespace AND cs.enabled)
$fn$;

-- (Re)attaches every companion observation of one source instance to its owner
-- record. Owner: the record of the same instance, outside the stream, whose
-- owner_key_field equals the companion's external id; a present owner first.
CREATE FUNCTION operations.attach_source_record_companions(
    p_tenant bigint, p_source_instance uuid
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_count integer;
BEGIN
    PERFORM set_config('operations.tenant_id', p_tenant::text, true);
    WITH streams AS (
        SELECT cs.id, cs.external_namespace, cs.owner_key_field
          FROM operations.source_record_companion_streams cs
          JOIN operations.source_instances si ON si.source_id = cs.source_id
         WHERE si.tenant_id = p_tenant AND si.id = p_source_instance AND cs.enabled
    ), owners AS (
        SELECT DISTINCT ON (st.id, o.canonical_data ->> st.owner_key_field)
               st.id AS stream_id, o.canonical_data ->> st.owner_key_field AS owner_key,
               s.id AS subject_id
          FROM streams st
          JOIN operations.entity_observation_current o
            ON o.tenant_id = p_tenant AND o.source_instance_id = p_source_instance
           AND o.external_namespace <> st.external_namespace
           AND o.canonical_data ? st.owner_key_field
          JOIN operations.source_record_subjects s
            ON s.tenant_id = o.tenant_id AND s.observation_id = o.observation_id
           AND s.subject_kind = 'record'
         ORDER BY st.id, o.canonical_data ->> st.owner_key_field,
                  o.active DESC, o.last_seen_at DESC, s.id
    ), attached AS (
        INSERT INTO operations.source_record_companions AS c (
            tenant_id, observation_id, stream_id, owner_subject_id)
        SELECT p_tenant, companion.observation_id, st.id, owner.subject_id
          FROM streams st
          JOIN operations.entity_observation_current companion
            ON companion.tenant_id = p_tenant
           AND companion.source_instance_id = p_source_instance
           AND companion.external_namespace = st.external_namespace
          JOIN owners owner
            ON owner.stream_id = st.id AND owner.owner_key = companion.external_id
        ON CONFLICT (tenant_id, observation_id) DO UPDATE
           SET owner_subject_id = EXCLUDED.owner_subject_id,
               stream_id = EXCLUDED.stream_id, attached_at = now()
         WHERE c.owner_subject_id IS DISTINCT FROM EXCLUDED.owner_subject_id
            OR c.stream_id IS DISTINCT FROM EXCLUDED.stream_id
        RETURNING 1
    )
    SELECT count(*) INTO v_count FROM attached;
    RETURN v_count;
END
$fn$;
REVOKE ALL ON FUNCTION operations.is_companion_stream(bigint, uuid, text),
                       operations.attach_source_record_companions(bigint, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.is_companion_stream(bigint, uuid, text)
    TO operations_app, ninja_ingest, operations_readonly;
GRANT EXECUTE ON FUNCTION operations.attach_source_record_companions(bigint, uuid)
    TO ninja_ingest;

-- A companion stream is never admitted as a source record.
CREATE OR REPLACE FUNCTION operations.source_record_admit_observation() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_role text := operations.source_record_role(NEW.entity_type);
    v_subject uuid;
    v_old_f text[];
    v_old_v text[];
    v_new_f text[];
    v_new_v text[];
BEGIN
    IF operations.is_companion_stream(NEW.tenant_id, NEW.source_instance_id,
                                      NEW.external_namespace) THEN
        RETURN NULL;
    END IF;
    INSERT INTO operations.source_record_subjects AS s (
        tenant_id, source_instance_id, external_namespace, parent_external_namespace,
        parent_external_id, external_id, observation_id, platform, entity_type,
        record_role, presence)
    VALUES (NEW.tenant_id, NEW.source_instance_id, NEW.external_namespace,
            NEW.parent_external_namespace, NEW.parent_external_id, NEW.external_id,
            NEW.observation_id, NEW.platform, NEW.entity_type, v_role,
            CASE WHEN NEW.active THEN 'present' ELSE 'withdrawn' END)
    ON CONFLICT (tenant_id, source_instance_id, external_namespace,
                 parent_external_namespace, parent_external_id, external_id)
        WHERE subject_kind = 'record'
    DO UPDATE SET observation_id = EXCLUDED.observation_id,
                  platform = EXCLUDED.platform,
                  entity_type = EXCLUDED.entity_type,
                  record_role = EXCLUDED.record_role,
                  presence = EXCLUDED.presence,
                  input_version = s.input_version + 1,
                  updated_at = now()
    RETURNING id INTO v_subject;

    SELECT coalesce(array_agg(key_family), '{}'), coalesce(array_agg(normalized_value), '{}')
      INTO v_old_f, v_old_v
      FROM operations.source_record_lookup_keys
     WHERE tenant_id = NEW.tenant_id AND subject_id = v_subject;
    DELETE FROM operations.source_record_lookup_keys
     WHERE tenant_id = NEW.tenant_id AND subject_id = v_subject;
    INSERT INTO operations.source_record_lookup_keys (
        tenant_id, subject_id, source_instance_id, record_role, key_family, normalized_value)
    SELECT NEW.tenant_id, v_subject, NEW.source_instance_id, v_role, k.key_family, k.normalized_value
      FROM operations.source_record_keys(NEW.tenant_id, NEW.source_instance_id,
                                         NEW.external_id, v_role, NEW.canonical_data) k;
    SELECT coalesce(array_agg(key_family), '{}'), coalesce(array_agg(normalized_value), '{}')
      INTO v_new_f, v_new_v
      FROM operations.source_record_lookup_keys
     WHERE tenant_id = NEW.tenant_id AND subject_id = v_subject;

    PERFORM operations.source_record_enqueue(NEW.tenant_id, 'source_record', v_subject);
    PERFORM operations.source_record_enqueue_neighbors(
        NEW.tenant_id, v_subject, NEW.source_instance_id,
        v_old_f || v_new_f, v_old_v || v_new_v);
    RETURN NULL;
END
$fn$;

-- An active companion needs a present owner when the transaction commits.
CREATE FUNCTION operations.check_companion_owner() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
BEGIN
    IF NOT operations.is_companion_stream(NEW.tenant_id, NEW.source_instance_id,
                                          NEW.external_namespace) THEN
        RETURN NULL;
    END IF;
    IF EXISTS (SELECT 1 FROM operations.entity_observation_current o
                WHERE o.tenant_id = NEW.tenant_id AND o.observation_id = NEW.observation_id
                  AND o.active)
       AND NOT EXISTS (
           SELECT 1 FROM operations.source_record_companions c
             JOIN operations.source_record_subjects s
               ON s.tenant_id = c.tenant_id AND s.id = c.owner_subject_id
            WHERE c.tenant_id = NEW.tenant_id AND c.observation_id = NEW.observation_id
              AND s.presence = 'present') THEN
        RAISE EXCEPTION 'companion observation % (%) has no present owner record',
                        NEW.observation_id, NEW.external_namespace;
    END IF;
    RETURN NULL;
END
$fn$;
CREATE CONSTRAINT TRIGGER check_companion_owner
    AFTER INSERT OR UPDATE ON operations.entity_observation_current
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.active)
    EXECUTE FUNCTION operations.check_companion_owner();

-- Withdrawing an owner record withdraws its companions and closes their history.
CREATE FUNCTION operations.withdraw_companions_with_owner() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_at timestamptz := coalesce(NEW.withdrawn_at, clock_timestamp());
BEGIN
    WITH companions AS (
        SELECT c.observation_id
          FROM operations.source_record_subjects s
          JOIN operations.source_record_companions c
            ON c.tenant_id = s.tenant_id AND c.owner_subject_id = s.id
         WHERE s.tenant_id = NEW.tenant_id AND s.observation_id = NEW.observation_id
    ), withdrawn AS (
        UPDATE operations.entity_observation_current o
           SET active = FALSE, withdrawn_at = v_at
          FROM companions c
         WHERE o.tenant_id = NEW.tenant_id AND o.observation_id = c.observation_id
           AND o.active
        RETURNING o.tenant_id, o.source_instance_id, o.external_namespace,
                  o.parent_external_namespace, o.parent_external_id, o.external_id,
                  o.last_seen_at
    )
    UPDATE operations.entity_observation_history h
       SET effective_to = GREATEST(v_at, h.effective_from), last_seen_at = w.last_seen_at
      FROM withdrawn w
     WHERE h.tenant_id = w.tenant_id AND h.source_instance_id = w.source_instance_id
       AND h.external_namespace = w.external_namespace
       AND h.parent_external_namespace = w.parent_external_namespace
       AND h.parent_external_id = w.parent_external_id
       AND h.external_id = w.external_id AND h.effective_to IS NULL;
    RETURN NULL;
END
$fn$;
CREATE TRIGGER withdraw_companions_with_owner
    AFTER UPDATE OF active ON operations.entity_observation_current
    FOR EACH ROW WHEN (OLD.active AND NOT NEW.active)
    EXECUTE FUNCTION operations.withdraw_companions_with_owner();
REVOKE ALL ON FUNCTION operations.check_companion_owner(),
                       operations.withdraw_companions_with_owner() FROM PUBLIC;

-- Record counts per source instance and type, companions excluded (Sources page).
CREATE VIEW operations.v_source_instance_record_counts
WITH (security_barrier = true) AS
SELECT observation.tenant_id, observation.source_instance_id,
       observation.entity_type,
       entity_type.entity_class_id AS entity_class,
       COUNT(*)::bigint AS current_count,
       COUNT(*) FILTER (WHERE observation.active)::bigint AS active_count,
       COUNT(*) FILTER (WHERE NOT observation.active)::bigint AS withdrawn_count,
       MAX(observation.last_seen_at) AS last_seen_at
  FROM operations.entity_observation_current observation
  JOIN operations.entity_types entity_type
    ON entity_type.name = observation.entity_type
 WHERE observation.tenant_id = operations.current_tenant_id()
   AND NOT operations.is_companion_stream(observation.tenant_id,
                                          observation.source_instance_id,
                                          observation.external_namespace)
 GROUP BY observation.tenant_id, observation.source_instance_id,
          observation.entity_type, entity_type.entity_class_id;
REVOKE ALL ON operations.v_source_instance_record_counts FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.v_source_instance_record_counts
    FROM operations_app, ninja_ingest, operations_readonly;
GRANT SELECT ON operations.v_source_instance_record_counts
    TO operations_app, operations_readonly;

-- A record's companion data sets, for the source-record page.
CREATE VIEW operations.v_source_record_companion_detail
WITH (security_barrier = true) AS
SELECT c.tenant_id, c.owner_subject_id, cs.external_namespace, cs.description,
       o.active, o.observed_at, o.last_seen_at, o.withdrawn_at, o.canonical_data
  FROM operations.source_record_companions c
  JOIN operations.source_record_companion_streams cs ON cs.id = c.stream_id
  JOIN operations.entity_observation_current o
    ON o.tenant_id = c.tenant_id AND o.observation_id = c.observation_id
 WHERE c.tenant_id = operations.current_tenant_id();
REVOKE ALL ON operations.v_source_record_companion_detail FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.v_source_record_companion_detail
    FROM operations_app, ninja_ingest, operations_readonly;
GRANT SELECT ON operations.v_source_record_companion_detail
    TO operations_app, operations_readonly;
"""

CLEANUP_SQL = r"""
DO $cleanup$
DECLARE
    r record;
    v_orphans integer;
    v_links integer := 0;
BEGIN
    FOR r IN
        SELECT DISTINCT si.tenant_id, si.id
          FROM operations.source_record_companion_streams cs
          JOIN operations.source_instances si ON si.source_id = cs.source_id
         WHERE cs.enabled
    LOOP
        PERFORM operations.attach_source_record_companions(r.tenant_id, r.id);
    END LOOP;

    -- Defense in depth: an active companion without a present owner is withdrawn
    -- (none on 2026-11-02), so the deferred owner check holds at commit.
    WITH orphans AS (
        UPDATE operations.entity_observation_current o
           SET active = FALSE, withdrawn_at = clock_timestamp()
         WHERE o.active
           AND operations.is_companion_stream(o.tenant_id, o.source_instance_id,
                                              o.external_namespace)
           AND NOT EXISTS (
               SELECT 1 FROM operations.source_record_companions c
                 JOIN operations.source_record_subjects s
                   ON s.tenant_id = c.tenant_id AND s.id = c.owner_subject_id
                WHERE c.tenant_id = o.tenant_id AND c.observation_id = o.observation_id
                  AND s.presence = 'present')
        RETURNING o.*
    ), closed AS (
        UPDATE operations.entity_observation_history h
           SET effective_to = GREATEST(w.withdrawn_at, h.effective_from)
          FROM orphans w
         WHERE h.tenant_id = w.tenant_id AND h.source_instance_id = w.source_instance_id
           AND h.external_namespace = w.external_namespace
           AND h.parent_external_namespace = w.parent_external_namespace
           AND h.parent_external_id = w.parent_external_id
           AND h.external_id = w.external_id AND h.effective_to IS NULL
        RETURNING 1
    )
    SELECT count(*) INTO v_orphans FROM orphans;
    RAISE NOTICE 'PLAN-038: % active companion(s) without an owner withdrawn', v_orphans;

    -- End the companions' own links through the one association writer.
    FOR r IN
        SELECT s.tenant_id, s.id, l.entity_class_id
          FROM operations.source_record_subjects s
          JOIN operations.entity_source_links l
            ON l.tenant_id = s.tenant_id AND l.source_subject_id = s.id
         WHERE operations.is_companion_stream(s.tenant_id, s.source_instance_id,
                                              s.external_namespace)
         ORDER BY s.tenant_id, s.id
    LOOP
        PERFORM set_config('operations.tenant_id', r.tenant_id::text, true);
        PERFORM operations.set_source_association(
            r.id, NULL, r.entity_class_id, 'companion', 1,
            'Health data is part of the Ninja device record (PLAN-038)', NULL,
            'system', NULL, 'migration.0397', '{}'::jsonb);
        v_links := v_links + 1;
    END LOOP;
    RAISE NOTICE 'PLAN-038: % companion link(s) ended', v_links;

    UPDATE operations.entity_observation_current o
       SET device_id = NULL
     WHERE o.device_id IS NOT NULL
       AND operations.is_companion_stream(o.tenant_id, o.source_instance_id,
                                          o.external_namespace);

    -- Remove the companions' source records and their derived rows.
    CREATE TEMP TABLE plan038_companion_subjects ON COMMIT DROP AS
    SELECT s.tenant_id, s.id
      FROM operations.source_record_subjects s
     WHERE operations.is_companion_stream(s.tenant_id, s.source_instance_id,
                                          s.external_namespace);
    IF EXISTS (SELECT 1 FROM operations.entity_source_links l
                 JOIN plan038_companion_subjects x
                   ON x.tenant_id = l.tenant_id AND x.id = l.source_subject_id) THEN
        RAISE EXCEPTION 'PLAN-038: companion records still have links';
    END IF;
    IF EXISTS (SELECT 1 FROM operations.findings f
                 JOIN plan038_companion_subjects x
                   ON x.tenant_id = f.tenant_id AND x.id = f.subject_id) THEN
        RAISE EXCEPTION 'PLAN-038: companion records have Issues';
    END IF;
    DELETE FROM operations.source_record_assessment_current a
     USING plan038_companion_subjects x
     WHERE a.tenant_id = x.tenant_id AND a.target_kind = 'source_record' AND a.target_id = x.id;
    DELETE FROM operations.source_record_assessment_queue q
     USING plan038_companion_subjects x
     WHERE q.tenant_id = x.tenant_id AND q.target_kind = 'source_record' AND q.target_id = x.id;
    DELETE FROM operations.source_record_subjects s
     USING plan038_companion_subjects x
     WHERE s.tenant_id = x.tenant_id AND s.id = x.id;
    RAISE NOTICE 'PLAN-038: % companion source record(s) removed',
                 (SELECT count(*) FROM plan038_companion_subjects);
END
$cleanup$;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0396_close_legacy_step_source_failures"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(SCHEMA_SQL, migrations.RunSQL.noop),
        migrations.RunSQL(_projector_sql(), migrations.RunSQL.noop),
        migrations.RunSQL(CLEANUP_SQL, migrations.RunSQL.noop),
    ]
