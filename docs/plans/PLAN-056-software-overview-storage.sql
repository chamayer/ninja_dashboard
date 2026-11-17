-- SET ASIDE: speculative design, not the implementation plan. DO NOT EXECUTE.
-- Separate change-log/receipt storage and broad triggers have not been justified.
-- PLAN-056 / ADR-0058: retained unapproved storage/publication draft.
-- Documentation artifact only. Not a migration; not executed or DB-validated.
-- Hook bindings and owner receipt integration are specified in the companion design.
-- Current platform supports tenant 1; do not imply multi-tenant certification.

CREATE TABLE operations.software_overview_dirty (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id bigint NOT NULL REFERENCES operations.tenants(id) CHECK (tenant_id = 1),
    dependency text NOT NULL CHECK (dependency IN
        ('inventory','population','catalog','intelligence','findings','decisions','eligibility')),
    relation_name text NOT NULL,
    changed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX software_overview_dirty_lookup
    ON operations.software_overview_dirty (tenant_id, dependency, changed_at, id);

CREATE TABLE operations.software_overview_input_publications (
    tenant_id bigint NOT NULL REFERENCES operations.tenants(id) CHECK (tenant_id = 1),
    component text NOT NULL CHECK (component IN
        ('titles','catalog','safety','classification','exposure')),
    generation uuid NOT NULL,
    run_id uuid NOT NULL,
    computed_at timestamptz NOT NULL,
    published_at timestamptz NOT NULL,
    covered_event_ids uuid[] NOT NULL,
    upstream_generations jsonb NOT NULL CHECK (jsonb_typeof(upstream_generations) = 'object'),
    source_as_of jsonb NOT NULL CHECK (jsonb_typeof(source_as_of) = 'object'),
    expires_at timestamptz,
    failed boolean NOT NULL DEFAULT false,
    failure_run_id uuid,
    PRIMARY KEY (tenant_id, component),
    FOREIGN KEY (tenant_id, run_id)
        REFERENCES operations.operator_job_runs (tenant_id, id),
    FOREIGN KEY (tenant_id, failure_run_id)
        REFERENCES operations.operator_job_runs (tenant_id, id),
    CHECK (published_at >= computed_at),
    CHECK (array_position(covered_event_ids, NULL) IS NULL)
);

CREATE TABLE operations.software_overview_current (
    tenant_id bigint PRIMARY KEY REFERENCES operations.tenants(id) CHECK (tenant_id = 1),
    generation uuid NOT NULL,
    run_id uuid NOT NULL,
    computed_at timestamptz NOT NULL,
    published_at timestamptz NOT NULL,
    input_watermarks jsonb NOT NULL CHECK (jsonb_typeof(input_watermarks) = 'object'),
    source_as_of jsonb NOT NULL CHECK (jsonb_typeof(source_as_of) = 'object'),
    window_expires_at timestamptz,
    safety_expires_at timestamptz,
    exposure_expires_at timestamptz,
    installations bigint NOT NULL CHECK (installations >= 0),
    products bigint NOT NULL CHECK (products >= 0),
    categorized bigint NOT NULL CHECK (categorized >= 0),
    uncategorized bigint NOT NULL CHECK (uncategorized >= 0),
    title_no_issue bigint NOT NULL CHECK (title_no_issue >= 0),
    title_reject bigint NOT NULL CHECK (title_reject >= 0),
    title_investigate bigint NOT NULL CHECK (title_investigate >= 0),
    title_pending bigint NOT NULL CHECK (title_pending >= 0),
    risk_high bigint NOT NULL CHECK (risk_high >= 0),
    risk_medium bigint NOT NULL CHECK (risk_medium >= 0),
    risk_low bigint NOT NULL CHECK (risk_low >= 0),
    risk_clean bigint NOT NULL CHECK (risk_clean >= 0),
    risk_unknown bigint NOT NULL CHECK (risk_unknown >= 0),
    software_issues bigint NOT NULL CHECK (software_issues >= 0),
    prompt_titles bigint NOT NULL CHECK (prompt_titles >= 0),
    awaiting_publishers bigint NOT NULL CHECK (awaiting_publishers >= 0),
    cleanup_devices bigint NOT NULL CHECK (cleanup_devices >= 0),
    weekly_products bigint NOT NULL CHECK (weekly_products >= 0),
    weekly_high_risk bigint NOT NULL CHECK (weekly_high_risk >= 0),
    top_new_name text,
    top_new_display_name text,
    top_new_devices bigint CHECK (top_new_devices > 0),
    FOREIGN KEY (tenant_id, run_id)
        REFERENCES operations.operator_job_runs (tenant_id, id),
    CHECK (published_at >= computed_at),
    CHECK (categorized <= products AND uncategorized = products - categorized),
    CHECK (title_no_issue + title_reject + title_investigate + title_pending = products),
    CHECK (risk_high + risk_medium + risk_low + risk_clean + risk_unknown <= products),
    CHECK (weekly_products <= products AND weekly_high_risk <= weekly_products),
    CHECK ((top_new_name IS NULL AND top_new_display_name IS NULL AND top_new_devices IS NULL)
        OR (top_new_name IS NOT NULL AND top_new_name <> ''
            AND top_new_display_name IS NOT NULL AND top_new_devices IS NOT NULL))
);

ALTER TABLE operations.software_overview_dirty OWNER TO operations_migrate;
ALTER TABLE operations.software_overview_dirty ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.software_overview_dirty FORCE ROW LEVEL SECURITY;
CREATE POLICY software_overview_dirty_tenant ON operations.software_overview_dirty
    USING (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint)
    WITH CHECK (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint);
REVOKE ALL ON operations.software_overview_dirty
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT SELECT ON operations.software_overview_dirty TO operations_view_owner;

ALTER TABLE operations.software_overview_input_publications OWNER TO operations_migrate;
ALTER TABLE operations.software_overview_input_publications ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.software_overview_input_publications FORCE ROW LEVEL SECURITY;
CREATE POLICY software_overview_input_publications_tenant ON operations.software_overview_input_publications
    USING (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint)
    WITH CHECK (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint);
REVOKE ALL ON operations.software_overview_input_publications
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT SELECT ON operations.software_overview_input_publications TO operations_view_owner;

ALTER TABLE operations.software_overview_current OWNER TO operations_migrate;
ALTER TABLE operations.software_overview_current ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.software_overview_current FORCE ROW LEVEL SECURITY;
CREATE POLICY software_overview_current_tenant ON operations.software_overview_current
    USING (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint)
    WITH CHECK (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint);
REVOKE ALL ON operations.software_overview_current
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT SELECT ON operations.software_overview_current TO operations_view_owner;

-- No new retired-role grant. Migration ACL review must also inspect inherited
-- memberships/default ACLs, rather than assuming these direct revokes suffice.

-- Sole visible-summary writer. The candidate is prepared by the trusted owner
-- in a separate read-only REPEATABLE READ transaction. No candidate construction
-- or upstream matview refresh occurs while this function holds locks.
CREATE FUNCTION operations.publish_software_overview(
    p_tenant bigint, p_run uuid, p_claim uuid, p_base_generation uuid,
    p_events uuid[], p_candidate jsonb
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_base uuid;
    v_generation uuid := gen_random_uuid();
    v_run operations.operator_job_runs%ROWTYPE;
    v_next operations.software_overview_current%ROWTYPE;
BEGIN
    IF p_tenant IS DISTINCT FROM
           nullif(current_setting('operations.tenant_id', true), '')::bigint
       OR p_tenant IS DISTINCT FROM 1
       OR p_run IS NULL OR p_claim IS NULL OR p_events IS NULL
       OR array_position(p_events, NULL) IS NOT NULL
       OR p_candidate IS NULL OR jsonb_typeof(p_candidate) <> 'object' THEN
        RAISE EXCEPTION 'Software publication context is invalid';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended('operations.software.overview:' || p_tenant::text, 0));
    SELECT * INTO v_run FROM operations.operator_job_runs
     WHERE tenant_id = p_tenant AND id = p_run FOR UPDATE;
    IF NOT FOUND OR v_run.contract_version <> 1
       OR v_run.job_key <> 'software-overview'
       OR v_run.scope_identity IS DISTINCT FROM ('tenant:' || p_tenant::text)
       OR v_run.status <> 'running' OR v_run.claim_token IS DISTINCT FROM p_claim
       OR v_run.cancellation_requested_at IS NOT NULL
       OR v_run.deadline_at IS NULL OR v_run.deadline_at <= clock_timestamp()
       OR NOT EXISTS (
           SELECT 1 FROM operations.job_resource_claims c
            WHERE c.tenant_id = p_tenant AND c.run_id = p_run
              AND c.claim_token = p_claim
              AND c.claim_generation = v_run.claim_generation
              AND c.state = 'held'
              AND c.resource_identity = ('tenant:' || p_tenant::text || ':software-overview')
       ) THEN
        RAISE EXCEPTION 'Software publication claim is unavailable or fenced';
    END IF;

    SELECT generation INTO v_base FROM operations.software_overview_current
     WHERE tenant_id = p_tenant;
    IF v_base IS DISTINCT FROM p_base_generation THEN
        RAISE EXCEPTION 'Software publication base changed; rebuild candidate';
    END IF;
    IF EXISTS (
        SELECT 1 FROM operations.software_overview_dirty
         WHERE id = ANY(p_events) AND tenant_id <> p_tenant
    ) THEN
        RAISE EXCEPTION 'Software publication input scope is invalid';
    END IF;

    SELECT * INTO v_next FROM jsonb_populate_record(
        NULL::operations.software_overview_current,
        p_candidate || jsonb_build_object(
            'tenant_id', p_tenant, 'generation', v_generation,
            'run_id', p_run, 'published_at', clock_timestamp()));
    IF v_next.computed_at IS NULL OR v_next.computed_at > clock_timestamp()
       OR v_next.window_expires_at IS NOT NULL
          AND v_next.window_expires_at < clock_timestamp()
       OR v_next.safety_expires_at IS NOT NULL
          AND v_next.safety_expires_at < clock_timestamp()
       OR v_next.exposure_expires_at IS NOT NULL
          AND v_next.exposure_expires_at < clock_timestamp() THEN
        RAISE EXCEPTION 'Software publication candidate needs recomputation';
    END IF;

    -- Compare captured successful owner generations atomically with replacement.
    -- Receipt writers use the same tenant publication advisory lock only for
    -- their short receipt-commit section, never for upstream calculation.
    IF (SELECT count(*) FROM operations.software_overview_input_publications
         WHERE tenant_id = p_tenant AND NOT failed) <> 5
       OR EXISTS (
           SELECT 1 FROM operations.software_overview_input_publications r
            WHERE r.tenant_id = p_tenant
              AND (r.failed OR
                   v_next.input_watermarks->>r.component IS DISTINCT FROM r.generation::text)
       ) THEN
        RAISE EXCEPTION 'Software input publication changed or is incomplete';
    END IF;

    DELETE FROM operations.software_overview_current WHERE tenant_id = p_tenant;
    INSERT INTO operations.software_overview_current SELECT v_next.*;
    -- UUID acknowledgments cannot remove a newer invalidation for the same
    -- dependency. No broad timestamp, max(sequence) or dependency-key deletion.
    DELETE FROM operations.software_overview_dirty
     WHERE tenant_id = p_tenant AND id = ANY(p_events);
    RETURN v_generation;
END
$fn$;
ALTER FUNCTION operations.publish_software_overview(bigint,uuid,uuid,uuid,uuid[],jsonb)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.publish_software_overview(bigint,uuid,uuid,uuid,uuid[],jsonb)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.publish_software_overview(bigint,uuid,uuid,uuid,uuid[],jsonb)
    TO ninja_ingest;

-- Protected read: affected metric groups are masked when next-read decision/
-- eligibility guards or freshness checks cannot certify their values. Raw
-- metadata stays private; unrelated available groups remain readable.
CREATE VIEW operations.v_software_overview WITH (security_barrier=true) AS
WITH readiness AS (
    SELECT h.*,
           r.receipt_count = 5
           AND NOT (d.lagged && ARRAY['inventory','population']::text[])
           AND NOT (d.pending && ARRAY[]::text[])
           AND NOT (r.failed && ARRAY[]::text[]) AS inventory_ready,
           r.receipt_count = 5
           AND NOT (d.lagged && ARRAY['inventory','population','findings']::text[])
           AND NOT (d.pending && ARRAY['decisions']::text[])
           AND NOT (r.failed && ARRAY['classification']::text[]) AS status_ready,
           r.receipt_count = 5
           AND NOT (d.lagged && ARRAY['inventory','population','catalog']::text[])
           AND NOT (d.pending && ARRAY[]::text[])
           AND NOT (r.failed && ARRAY['catalog']::text[]) AS capability_ready,
           r.receipt_count = 5
           AND NOT (d.lagged && ARRAY['inventory','population','intelligence','catalog']::text[])
           AND NOT (d.pending && ARRAY['decisions']::text[])
           AND NOT (r.failed && ARRAY['titles','safety']::text[])
           AND (h.safety_expires_at IS NULL OR statement_timestamp() <= h.safety_expires_at + interval '60 seconds') AS risk_ready,
           r.receipt_count = 5
           AND NOT (d.lagged && ARRAY['findings']::text[])
           AND NOT (d.pending && ARRAY[]::text[])
           AND NOT (r.failed && ARRAY['classification']::text[]) AS findings_ready,
           r.receipt_count = 5
           AND NOT (d.lagged && ARRAY['inventory','catalog']::text[])
           AND NOT (d.pending && ARRAY['decisions','eligibility','population','findings']::text[])
           AND NOT (r.failed && ARRAY['exposure','classification']::text[])
           AND (h.exposure_expires_at IS NULL OR statement_timestamp() <= h.exposure_expires_at) AS exposure_ready,
           r.receipt_count = 5
           AND NOT (d.lagged && ARRAY['inventory','population','intelligence','catalog']::text[])
           AND NOT (d.pending && ARRAY['decisions']::text[])
           AND NOT (r.failed && ARRAY['safety','titles']::text[])
           AND (h.window_expires_at IS NULL OR statement_timestamp() <= h.window_expires_at + interval '60 seconds') AND (h.safety_expires_at IS NULL OR statement_timestamp() <= h.safety_expires_at + interval '60 seconds') AS weekly_ready
      FROM operations.software_overview_current h
      CROSS JOIN LATERAL (
          SELECT ARRAY(SELECT k FROM unnest(ARRAY['inventory','population','catalog',
                     'intelligence','findings','decisions','eligibility']) AS keys(k)
                    WHERE EXISTS (SELECT 1 FROM operations.software_overview_dirty e
                        WHERE e.tenant_id = h.tenant_id AND e.dependency = k)) AS pending,
                 ARRAY(SELECT k FROM unnest(ARRAY['inventory','population','catalog',
                     'intelligence','findings','decisions','eligibility']) AS keys(k)
                    WHERE EXISTS (SELECT 1 FROM operations.software_overview_dirty e
                        WHERE e.tenant_id = h.tenant_id AND e.dependency = k
                          AND e.changed_at <= statement_timestamp() - interval '60 seconds')) AS lagged
      ) d
      CROSS JOIN LATERAL (
          SELECT count(*) AS receipt_count,
                 coalesce(array_agg(r.component) FILTER (WHERE r.failed), '{}'::text[]) AS failed
            FROM operations.software_overview_input_publications r
           WHERE r.tenant_id = h.tenant_id
      ) r
     WHERE h.tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint
)
SELECT tenant_id, generation, computed_at, published_at, source_as_of,
       input_watermarks, window_expires_at, safety_expires_at, exposure_expires_at,
       inventory_ready, status_ready, capability_ready, risk_ready,
       findings_ready, exposure_ready, weekly_ready,
       inventory_ready AND status_ready AND capability_ready AND risk_ready
           AND findings_ready AND exposure_ready AND weekly_ready AS available,
       CASE WHEN inventory_ready THEN installations END AS installations,
       CASE WHEN inventory_ready THEN products END AS products,
       CASE WHEN capability_ready THEN categorized END AS categorized,
       CASE WHEN capability_ready THEN uncategorized END AS uncategorized,
       CASE WHEN status_ready THEN title_no_issue END AS title_no_issue,
       CASE WHEN status_ready THEN title_reject END AS title_reject,
       CASE WHEN status_ready THEN title_investigate END AS title_investigate,
       CASE WHEN status_ready THEN title_pending END AS title_pending,
       CASE WHEN risk_ready THEN risk_high END AS risk_high,
       CASE WHEN risk_ready THEN risk_medium END AS risk_medium,
       CASE WHEN risk_ready THEN risk_low END AS risk_low,
       CASE WHEN risk_ready THEN risk_clean END AS risk_clean,
       CASE WHEN risk_ready THEN risk_unknown END AS risk_unknown,
       CASE WHEN findings_ready THEN software_issues END AS software_issues,
       CASE WHEN findings_ready THEN prompt_titles END AS prompt_titles,
       CASE WHEN status_ready THEN awaiting_publishers END AS awaiting_publishers,
       CASE WHEN exposure_ready THEN cleanup_devices END AS cleanup_devices,
       CASE WHEN weekly_ready THEN weekly_products END AS weekly_products,
       CASE WHEN weekly_ready THEN weekly_high_risk END AS weekly_high_risk,
       CASE WHEN weekly_ready THEN top_new_name END AS top_new_name,
       CASE WHEN weekly_ready THEN top_new_display_name END AS top_new_display_name,
       CASE WHEN weekly_ready THEN top_new_devices END AS top_new_devices
  FROM readiness;
ALTER VIEW operations.v_software_overview OWNER TO operations_view_owner;
REVOKE ALL ON operations.v_software_overview
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.v_software_overview
    FROM operations_app, operations_readonly, ninja_ingest;
GRANT SELECT ON operations.v_software_overview TO operations_app, operations_readonly;

-- This proposal is not an executable migration release. Startup preflight,
-- actual owner integration and reversal packaging must accompany implementation.

-- Transactional, append-only input invalidation. Statement transition tables
-- avoid one persisted event per installation and avoid a shared counter lock.
-- TG_ARGV: dependency, scope ("tenant" or "global"), watched column CSV or "*".
CREATE FUNCTION operations.software_overview_invalidate_statement()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_dependency text := TG_ARGV[0];
    v_scope text := TG_ARGV[1];
    v_watch text := TG_ARGV[2];
    v_tenant_expr text;
    v_state text;
    v_columns text;
    v_new text;
    v_old text;
    v_query text;
    v_tenant bigint;
    v_prior text := current_setting('operations.tenant_id', true);
BEGIN
    IF v_dependency NOT IN
        ('inventory','population','catalog','intelligence','findings','decisions','eligibility')
       OR v_scope NOT IN ('tenant','global') THEN
        RAISE EXCEPTION 'Invalid Software invalidation binding';
    END IF;
    v_tenant_expr := CASE WHEN v_scope = 'global' THEN '1::bigint' ELSE 'r.tenant_id' END;
    IF v_watch = '*' THEN
        v_state := 'to_jsonb(r)';
    ELSE
        SELECT string_agg(format('r.%I', c), ',') INTO v_columns
          FROM unnest(string_to_array(v_watch, ',')) AS cols(c);
        IF v_columns IS NULL THEN RAISE EXCEPTION 'Empty Software watch list'; END IF;
        v_state := 'jsonb_build_array(' || v_columns || ')';
    END IF;
    v_new := format('SELECT %s AS tenant_id, %s AS watched FROM new_rows r',
                    v_tenant_expr, v_state);
    v_old := format('SELECT %s AS tenant_id, %s AS watched FROM old_rows r',
                    v_tenant_expr, v_state);
    IF TG_OP = 'INSERT' THEN
        v_query := format('SELECT DISTINCT %s FROM new_rows r', v_tenant_expr);
    ELSIF TG_OP = 'DELETE' THEN
        v_query := format('SELECT DISTINCT %s FROM old_rows r', v_tenant_expr);
    ELSIF TG_OP = 'UPDATE' THEN
        v_query := format(
            'SELECT DISTINCT tenant_id FROM ((%s EXCEPT ALL %s) UNION ALL (%s EXCEPT ALL %s)) d',
            v_new, v_old, v_old, v_new);
    ELSE
        -- Authorized rebuild/TRUNCATE must still invalidate an empty result.
        v_query := 'SELECT 1::bigint';
    END IF;
    FOR v_tenant IN EXECUTE v_query LOOP
        IF v_tenant IS DISTINCT FROM 1 THEN
            RAISE EXCEPTION 'Unsupported Software invalidation tenant';
        END IF;
        PERFORM set_config('operations.tenant_id', v_tenant::text, true);
        INSERT INTO operations.software_overview_dirty (tenant_id, dependency, relation_name)
        VALUES (v_tenant, v_dependency, TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME);
    END LOOP;
    PERFORM set_config('operations.tenant_id', coalesce(v_prior, ''), true);
    RETURN NULL;
END
$fn$;
ALTER FUNCTION operations.software_overview_invalidate_statement()
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.software_overview_invalidate_statement()
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;

-- Static persisted-writer inventory. "*" is conservative full-row comparison
-- on smaller/configuration surfaces; representative overhead remains unmeasured.
-- All listed targets must exist; absence fails atomically rather than silently
-- omitting hooks. Deploy installation after both migration tracks are ready.
DO $hooks$
DECLARE
    b record;
    v_table regclass;
    v_prefix text;
    c text;
BEGIN
    FOR b IN SELECT * FROM (VALUES
        ('operations.software_installations_current','inventory','tenant',
         'tenant_id,client_id,device_id,canonical_name,publisher,version,software_version_id,display_name,first_observed_at,last_observed_at,deleted_at,stale_since'),
        ('operations.devices','population','tenant',
         'tenant_id,id,client_id,lifecycle_status,deleted_at'),
        ('operations.source_record_subjects','population','tenant',
         'tenant_id,id,association_version,observation_id,presence'),
        ('operations.computer_client_ownership','population','tenant','*'),
        ('catalog.products','catalog','global','id,product_uuid,publisher_id,canonical_name'),
        ('catalog.software_versions','catalog','global','id,version_uuid,product_id,version,eol_date,eol_source'),
        ('catalog.capability','catalog','global','*'),
        ('catalog.capability_source','catalog','global','*'),
        ('catalog.capability_assertion_machine','catalog','global','*'),
        ('catalog.capability_assertion_operator','catalog','global','*'),
        ('catalog.capability_rule','catalog','global','*'),
        ('catalog.category_assertion_machine','catalog','global','*'),
        ('catalog.category_assertion_operator','catalog','global','*'),
        ('catalog.category_tag_rule','catalog','global','*'),
        ('operations.cve_match','intelligence','tenant',
         'id,tenant_id,canonical_name,cve_id,match_kind,version_range,confidence'),
        ('intel.cves','intelligence','global',
         'cve_id,cvss_v3,epss_score,kev_flag,last_modified_at'),
        ('operations.safety_signal','intelligence','tenant',
         'id,tenant_id,canonical_name,publisher,source,signal_type,severity,details,observed_at'),
        ('operations.publisher_aliases','intelligence','global','*'),
        ('operations.findings','findings','tenant',
         'id,tenant_id,subject_type,subject_id,finding_type_id,status,finding_details'),
        ('operations.finding_types','findings','global','*'),
        ('operations.evaluator_config','eligibility','tenant','*'),
        ('operations.software_classifier_rules','eligibility','global','*'),
        ('operations.software_suggestion_rules','eligibility','global','*'),
        ('operations.software_decisions','decisions','tenant',
         'id,tenant_id,canonical_name,publisher,client_id,device_id,decision,decided_at'),
        ('operations.software_device_readiness','eligibility','tenant','*'),
        ('operations.condition_assessments','eligibility','tenant','*'),
        ('operations.condition_participants','eligibility','tenant','*'),
        ('operations.condition_policy_versions','eligibility','global','*'),
        ('operations.condition_policies','eligibility','global','*'),
        ('operations.software_installation_history','eligibility','tenant',
         'id,tenant_id,source_binding_id,client_id,device_id,canonical_name,last_seen_at,active,effective_to'),
        ('operations.entity_observation_current','eligibility','tenant',
         'observation_id,tenant_id,device_id,source_instance_id,external_namespace,entity_type,active,canonical_data'),
        ('operations.source_bindings','eligibility','tenant','*'),
        ('operations.source_instances','eligibility','tenant','*'),
        ('operations.source_record_lifecycle_mappings','eligibility','global','*')
    ) AS x(relation_name,dependency,scope,watched) LOOP
        v_table := to_regclass(b.relation_name);
        IF v_table IS NULL THEN
            RAISE EXCEPTION 'Software hook target is missing: %', b.relation_name;
        END IF;
        IF b.watched <> '*' THEN
            FOREACH c IN ARRAY string_to_array(b.watched, ',') LOOP
                IF NOT EXISTS (SELECT 1 FROM pg_attribute
                    WHERE attrelid = v_table AND attname = c
                      AND attnum > 0 AND NOT attisdropped) THEN
                    RAISE EXCEPTION 'Software hook column is missing: %.%', b.relation_name, c;
                END IF;
            END LOOP;
        END IF;
        v_prefix := 'software_overview_' || split_part(b.relation_name, '.', 2);
        EXECUTE format(
            'CREATE TRIGGER %I AFTER INSERT ON %s REFERENCING NEW TABLE AS new_rows '
            'FOR EACH STATEMENT EXECUTE FUNCTION operations.software_overview_invalidate_statement(%L,%L,%L)',
            v_prefix || '_insert', v_table, b.dependency, b.scope, b.watched);
        EXECUTE format(
            'CREATE TRIGGER %I AFTER UPDATE ON %s REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows '
            'FOR EACH STATEMENT EXECUTE FUNCTION operations.software_overview_invalidate_statement(%L,%L,%L)',
            v_prefix || '_update', v_table, b.dependency, b.scope, b.watched);
        EXECUTE format(
            'CREATE TRIGGER %I AFTER DELETE ON %s REFERENCING OLD TABLE AS old_rows '
            'FOR EACH STATEMENT EXECUTE FUNCTION operations.software_overview_invalidate_statement(%L,%L,%L)',
            v_prefix || '_delete', v_table, b.dependency, b.scope, b.watched);
        EXECUTE format(
            'CREATE TRIGGER %I BEFORE TRUNCATE ON %s '
            'FOR EACH STATEMENT EXECUTE FUNCTION operations.software_overview_invalidate_statement(%L,%L,%L)',
            v_prefix || '_truncate', v_table, b.dependency, b.scope, b.watched);
    END LOOP;
END
$hooks$;

-- Input publication receipt: call in the SAME transaction as successful input
-- publication, with events captured from that publication's actual input
-- snapshot. Never read a newer event list after refresh and label it covered.
CREATE FUNCTION operations.record_software_overview_input(
    p_tenant bigint, p_component text, p_run uuid, p_claim uuid,
    p_base_generation uuid, p_computed_at timestamptz,
    p_events uuid[], p_upstream jsonb, p_source_as_of jsonb,
    p_expires_at timestamptz DEFAULT NULL
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_run operations.operator_job_runs%ROWTYPE;
    v_base uuid;
    v_generation uuid := gen_random_uuid();
    v_allowed text[];
BEGIN
    IF p_tenant IS DISTINCT FROM
           nullif(current_setting('operations.tenant_id', true), '')::bigint
       OR p_tenant IS DISTINCT FROM 1 OR p_run IS NULL OR p_claim IS NULL
       OR p_computed_at IS NULL OR p_computed_at > clock_timestamp()
       OR p_events IS NULL OR array_position(p_events, NULL) IS NOT NULL
       OR p_upstream IS NULL OR jsonb_typeof(p_upstream) <> 'object'
       OR p_source_as_of IS NULL OR jsonb_typeof(p_source_as_of) <> 'object' THEN
        RAISE EXCEPTION 'Software input receipt context is invalid';
    END IF;
    v_allowed := CASE p_component
        WHEN 'titles' THEN ARRAY['software-queue-drain','software-enqueue-orgs','software-overview']
        WHEN 'catalog' THEN ARRAY['software-queue-drain','software-enqueue-orgs','software-overview']
        WHEN 'safety' THEN ARRAY['software-queue-drain','software-enqueue-orgs','intel-matcher',
             'software-classify','software-classify-only','software-classify-full','software-overview']
        WHEN 'classification' THEN ARRAY['software-classify','software-classify-only','software-classify-full']
        WHEN 'exposure' THEN ARRAY['software-classify','software-classify-only',
             'software-classify-full','software-overview']
        ELSE NULL END;
    IF v_allowed IS NULL THEN RAISE EXCEPTION 'Unknown Software input owner'; END IF;
    PERFORM pg_advisory_xact_lock(
        hashtextextended('operations.software.overview:' || p_tenant::text, 0));
    SELECT * INTO v_run FROM operations.operator_job_runs
     WHERE tenant_id = p_tenant AND id = p_run FOR UPDATE;
    IF NOT FOUND OR v_run.contract_version <> 1 OR v_run.status <> 'running'
       OR NOT (v_run.job_key = ANY(v_allowed))
       OR v_run.claim_token IS DISTINCT FROM p_claim
       OR v_run.cancellation_requested_at IS NOT NULL
       OR v_run.deadline_at IS NULL OR v_run.deadline_at <= clock_timestamp()
       OR NOT EXISTS (
           SELECT 1 FROM operations.job_resource_claims c
            WHERE c.tenant_id = p_tenant AND c.run_id = p_run
              AND c.claim_token = p_claim AND c.claim_generation = v_run.claim_generation
              AND c.state = 'held'
       ) THEN
        RAISE EXCEPTION 'Software input receipt claim is unavailable or fenced';
    END IF;
    SELECT generation INTO v_base FROM operations.software_overview_input_publications
     WHERE tenant_id = p_tenant AND component = p_component;
    IF v_base IS DISTINCT FROM p_base_generation THEN
        RAISE EXCEPTION 'Software input receipt base changed';
    END IF;
    INSERT INTO operations.software_overview_input_publications (
        tenant_id,component,generation,run_id,computed_at,published_at,
        covered_event_ids,upstream_generations,source_as_of,expires_at)
    VALUES (p_tenant,p_component,v_generation,p_run,p_computed_at,clock_timestamp(),
            p_events,p_upstream,p_source_as_of,p_expires_at)
    ON CONFLICT (tenant_id,component) DO UPDATE SET
        generation = EXCLUDED.generation, run_id = EXCLUDED.run_id,
        computed_at = EXCLUDED.computed_at, published_at = EXCLUDED.published_at,
        covered_event_ids = EXCLUDED.covered_event_ids,
        upstream_generations = EXCLUDED.upstream_generations,
        source_as_of = EXCLUDED.source_as_of, expires_at = EXCLUDED.expires_at,
        failed = false, failure_run_id = NULL;
    RETURN v_generation;
END
$fn$;
ALTER FUNCTION operations.record_software_overview_input(
    bigint,text,uuid,uuid,uuid,timestamptz,uuid[],jsonb,jsonb,timestamptz) OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.record_software_overview_input(
    bigint,text,uuid,uuid,uuid,timestamptz,uuid[],jsonb,jsonb,timestamptz)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.record_software_overview_input(
    bigint,text,uuid,uuid,uuid,timestamptz,uuid[],jsonb,jsonb,timestamptz) TO ninja_ingest;

-- Preserve successful receipt timestamps and data when an owner fails.
-- A newer success makes an older failure's base comparison fail harmlessly.
CREATE FUNCTION operations.fail_software_overview_input(
    p_tenant bigint, p_component text, p_run uuid, p_claim uuid, p_base_generation uuid
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_run operations.operator_job_runs%ROWTYPE;
    v_allowed text[];
    v_changed integer;
BEGIN
    IF p_tenant IS DISTINCT FROM
           nullif(current_setting('operations.tenant_id', true), '')::bigint
       OR p_tenant IS DISTINCT FROM 1 OR p_run IS NULL OR p_claim IS NULL THEN
        RAISE EXCEPTION 'Software failure context is invalid';
    END IF;
    v_allowed := CASE p_component
        WHEN 'titles' THEN ARRAY['software-queue-drain','software-enqueue-orgs','software-overview']
        WHEN 'catalog' THEN ARRAY['software-queue-drain','software-enqueue-orgs','software-overview']
        WHEN 'safety' THEN ARRAY['software-queue-drain','software-enqueue-orgs','intel-matcher',
             'software-classify','software-classify-only','software-classify-full','software-overview']
        WHEN 'classification' THEN ARRAY['software-classify','software-classify-only','software-classify-full']
        WHEN 'exposure' THEN ARRAY['software-classify','software-classify-only',
             'software-classify-full','software-overview']
        ELSE NULL END;
    IF v_allowed IS NULL THEN RAISE EXCEPTION 'Unknown Software input owner'; END IF;
    PERFORM pg_advisory_xact_lock(
        hashtextextended('operations.software.overview:' || p_tenant::text, 0));
    SELECT * INTO v_run FROM operations.operator_job_runs
     WHERE tenant_id = p_tenant AND id = p_run FOR UPDATE;
    IF NOT FOUND OR v_run.contract_version <> 1
       OR v_run.claim_token IS DISTINCT FROM p_claim
       OR NOT (v_run.job_key = ANY(v_allowed))
       OR v_run.status NOT IN ('running','failed') THEN
        RAISE EXCEPTION 'Software failure claim is unavailable or fenced';
    END IF;
    UPDATE operations.software_overview_input_publications
       SET failed = true, failure_run_id = p_run
     WHERE tenant_id = p_tenant AND component = p_component
       AND generation = p_base_generation;
    GET DIAGNOSTICS v_changed = ROW_COUNT;
    RETURN v_changed = 1;
END
$fn$;
ALTER FUNCTION operations.fail_software_overview_input(bigint,text,uuid,uuid,uuid)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.fail_software_overview_input(bigint,text,uuid,uuid,uuid)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.fail_software_overview_input(bigint,text,uuid,uuid,uuid)
    TO ninja_ingest;
