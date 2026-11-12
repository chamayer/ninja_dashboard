"""Prepare the Software overview aggregate without enabling runtime cutover.

PLAN-056 implementation step 2 / ADR-0058. The current-Computer population and
metric SQL are frozen from the compatibility reader. Existing title/safety/
exposure publications and consumers are unchanged. No rows are built at startup.

Later steps must supply complete input maintenance, actual completion watermarks,
Jobs publication fences and live-decision/freshness guards before certifying a row.
The producer always writes contract_ready=false; runtime cannot read it yet.
"""

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
-- The definer owns the Operations inputs, but ownership of the catalog and
-- protected exposure view belongs to other roles. Grant only required reads.
GRANT USAGE ON SCHEMA catalog TO operations_migrate;
GRANT SELECT ON catalog.products, catalog.software_versions,
    catalog.v_product_capability_effective,
    operations.device_software_exposure_current,
    operations.v_device_software_exposure TO operations_migrate;

CREATE TABLE operations.software_overview_current (
    tenant_id bigint PRIMARY KEY REFERENCES operations.tenants(id) CHECK (tenant_id = 1),
    generation uuid NOT NULL,
    computed_at timestamptz NOT NULL,
    published_at timestamptz NOT NULL,
    inventory_observed_at timestamptz,
    window_expires_at timestamptz,
    exposure_expires_at timestamptz,
    input_watermarks jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(input_watermarks) = 'object'),
    contract_ready boolean NOT NULL DEFAULT false,
    installations bigint NOT NULL CHECK (installations >= 0),
    unique_titles bigint NOT NULL CHECK (unique_titles >= 0),
    categorized_titles bigint NOT NULL CHECK (categorized_titles >= 0),
    uncategorized_titles bigint NOT NULL CHECK (uncategorized_titles >= 0),
    approved_titles bigint NOT NULL CHECK (approved_titles >= 0),
    rejected_titles bigint NOT NULL CHECK (rejected_titles >= 0),
    investigate_titles bigint NOT NULL CHECK (investigate_titles >= 0),
    pending_decisions bigint NOT NULL CHECK (pending_decisions >= 0),
    risk_high bigint NOT NULL CHECK (risk_high >= 0),
    risk_medium bigint NOT NULL CHECK (risk_medium >= 0),
    risk_low bigint NOT NULL CHECK (risk_low >= 0),
    risk_clean bigint NOT NULL CHECK (risk_clean >= 0),
    risk_unknown bigint NOT NULL CHECK (risk_unknown >= 0),
    software_issues bigint NOT NULL CHECK (software_issues >= 0),
    whitelist_suggestions bigint NOT NULL CHECK (whitelist_suggestions >= 0),
    publishers_undecided bigint NOT NULL CHECK (publishers_undecided >= 0),
    tech_checklist_devices bigint NOT NULL CHECK (tech_checklist_devices >= 0),
    new_products bigint NOT NULL CHECK (new_products >= 0),
    new_high_risk bigint NOT NULL CHECK (new_high_risk >= 0),
    top_new_name text,
    top_new_display_name text,
    top_new_devices bigint CHECK (top_new_devices > 0),
    CHECK (published_at >= computed_at),
    CHECK (categorized_titles <= unique_titles),
    CHECK (uncategorized_titles = unique_titles - categorized_titles),
    CHECK (approved_titles + rejected_titles + investigate_titles + pending_decisions = unique_titles),
    CHECK (risk_high + risk_medium + risk_low + risk_clean + risk_unknown <= unique_titles),
    CHECK (new_products <= unique_titles AND new_high_risk <= new_products),
    CHECK ((top_new_name IS NULL AND top_new_display_name IS NULL AND top_new_devices IS NULL)
        OR (top_new_name IS NOT NULL AND top_new_display_name IS NOT NULL
            AND top_new_devices IS NOT NULL))
);
ALTER TABLE operations.software_overview_current OWNER TO operations_migrate;
ALTER TABLE operations.software_overview_current ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.software_overview_current FORCE ROW LEVEL SECURITY;
CREATE POLICY software_overview_tenant ON operations.software_overview_current
    USING (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint)
    WITH CHECK (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint);
REVOKE ALL ON operations.software_overview_current
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest, operations_view_owner;
GRANT SELECT ON operations.software_overview_current TO operations_view_owner;

CREATE VIEW operations.v_software_overview WITH (security_barrier = true) AS
SELECT * FROM operations.software_overview_current
 WHERE tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint
   AND contract_ready;
ALTER VIEW operations.v_software_overview OWNER TO operations_view_owner;
REVOKE ALL ON operations.v_software_overview
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.v_software_overview
    FROM operations_app, operations_readonly, ninja_ingest;
GRANT SELECT ON operations.v_software_overview TO operations_app, operations_readonly;

-- Step 2 builds the aggregate only. Later steps supply dependency watermarks,
-- Jobs fencing, live-decision guards and readiness certification before cutover.
CREATE FUNCTION operations.refresh_software_overview(p_tenant bigint)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_at timestamptz;
    v_generation uuid := gen_random_uuid();
BEGIN
    IF p_tenant IS DISTINCT FROM 1 OR p_tenant IS DISTINCT FROM
        nullif(current_setting('operations.tenant_id', true), '')::bigint THEN
        RAISE EXCEPTION 'Software overview tenant context is invalid';
    END IF;
    PERFORM pg_advisory_xact_lock(
        hashtextextended('operations.software.overview:' || p_tenant::text, 0));
    v_at := clock_timestamp();

    WITH qualifying AS MATERIALIZED (
        SELECT i.tenant_id, i.canonical_name, i.publisher, i.device_id,
               i.software_version_id, i.first_observed_at, i.last_observed_at
          FROM operations.software_installations_current i
          JOIN operations.devices d ON d.tenant_id = i.tenant_id AND d.id = i.device_id
         WHERE i.tenant_id = p_tenant AND i.deleted_at IS NULL AND i.stale_since IS NULL
           AND d.deleted_at IS NULL AND d.lifecycle_status <> 'retired'
    ), current_titles AS MATERIALIZED (
        SELECT tenant_id, canonical_name,
               mode() WITHIN GROUP (ORDER BY publisher) AS publisher,
               count(*)::bigint AS installations,
               count(DISTINCT device_id) FILTER (
                   WHERE first_observed_at >= v_at - interval '7 days'
               )::bigint AS weekly_devices
          FROM qualifying GROUP BY tenant_id, canonical_name
    ), title_flags AS (
    SELECT lower(finding.finding_details->>'canonical_name') AS title_key,
           bool_or(finding_type.name = 'rejected_software_installed') AS rejected,
           bool_or(finding_type.name IN ('whitelist_suggestion', 'rare_recent')) AS awaiting
      FROM operations.findings finding
      JOIN operations.finding_types finding_type ON finding_type.id = finding.finding_type_id
     WHERE finding.tenant_id = 1 AND finding.status IN ('open', 'acknowledged')
       AND finding_type.name IN ('rejected_software_installed', 'whitelist_suggestion', 'rare_recent')
     GROUP BY 1
),
investigate_titles AS (
    SELECT DISTINCT lower(canonical_name) AS title_key
      FROM operations.software_decisions
     WHERE tenant_id = 1 AND decision = 'investigate' AND canonical_name <> ''
       AND client_id IS NULL AND device_id IS NULL
),
investigate_publishers AS (
    SELECT DISTINCT lower(publisher) AS publisher_key
      FROM operations.software_decisions
     WHERE tenant_id = 1 AND decision = 'investigate' AND canonical_name = ''
       AND publisher <> '' AND client_id IS NULL AND device_id IS NULL
),
    statuses AS (
        SELECT (CASE WHEN title_flags.rejected THEN 'reject'
       WHEN title_flags.awaiting THEN 'pending'
       WHEN investigate_titles.title_key IS NOT NULL
            OR investigate_publishers.publisher_key IS NOT NULL THEN 'investigate'
       ELSE 'approve' END) AS status
          FROM current_titles sic
          LEFT JOIN title_flags ON title_flags.title_key = lower(sic.canonical_name)
  LEFT JOIN investigate_titles ON investigate_titles.title_key = lower(sic.canonical_name)
  LEFT JOIN investigate_publishers
    ON investigate_publishers.publisher_key = lower(COALESCE(sic.publisher, ''))
    ), status_counts AS (
        SELECT count(*) FILTER (WHERE status = 'approve') AS approved_titles,
               count(*) FILTER (WHERE status = 'reject') AS rejected_titles,
               count(*) FILTER (WHERE status = 'investigate') AS investigate_titles,
               count(*) FILTER (WHERE status = 'pending') AS pending_decisions
          FROM statuses
    ), title_totals AS (
        SELECT coalesce(sum(installations), 0)::bigint AS installations,
               count(*) AS unique_titles,
               count(*) FILTER (WHERE weekly_devices > 0) AS new_products
          FROM current_titles
    ), category_totals AS (
        SELECT count(DISTINCT q.canonical_name) AS categorized_titles
          FROM qualifying q
          JOIN catalog.software_versions sv ON sv.id = q.software_version_id
          JOIN catalog.products p ON p.id = sv.product_id
          JOIN catalog.v_product_capability_effective c ON c.product_uuid = p.product_uuid
    ), safety AS MATERIALIZED (
        SELECT s.safety_band, t.weekly_devices
          FROM operations.v_software_safety s
          JOIN current_titles t
            ON t.tenant_id = s.tenant_id AND t.canonical_name = s.canonical_name
         WHERE s.tenant_id = p_tenant
    ), risk_totals AS (
        SELECT count(*) FILTER (WHERE safety_band = 'high') AS risk_high,
               count(*) FILTER (WHERE safety_band = 'medium') AS risk_medium,
               count(*) FILTER (WHERE safety_band = 'low') AS risk_low,
               count(*) FILTER (WHERE safety_band = 'clean') AS risk_clean,
               count(*) FILTER (WHERE safety_band = 'unknown') AS risk_unknown,
               count(*) FILTER (WHERE safety_band = 'high' AND weekly_devices > 0) AS new_high_risk
          FROM safety
    ), finding_rows AS MATERIALIZED (
        SELECT f.status, f.finding_details, ft.name, ft.issue_category
          FROM operations.findings f
          JOIN operations.finding_types ft ON ft.id = f.finding_type_id
         WHERE f.tenant_id = p_tenant
           AND f.status IN ('open', 'acknowledged', 'investigating')
    ), finding_totals AS (
        SELECT count(*) FILTER (
                   WHERE issue_category = 'Software & security' AND name <> 'whitelist_suggestion'
               ) AS software_issues,
               count(DISTINCT lower(finding_details->>'publisher')) FILTER (
                   WHERE status IN ('open', 'acknowledged')
                     AND name IN ('whitelist_suggestion', 'rare_recent')
                     AND coalesce(finding_details->>'publisher', '') <> ''
               ) AS publishers_undecided
          FROM finding_rows
    ), prompt_totals AS (
        -- COUNT of distinct rows preserves one SQL-NULL group, JSON null, case
        -- and JSON values exactly as the compatibility ORM distinct().count().
        SELECT count(*) AS whitelist_suggestions FROM (
            SELECT DISTINCT finding_details->'canonical_name' AS value
              FROM finding_rows WHERE name IN ('whitelist_suggestion', 'rare_recent')
        ) prompts
    ), cleanup AS MATERIALIZED (
        SELECT e.* FROM operations.v_device_software_exposure e
         WHERE e.tenant_id = p_tenant AND e.status IN ('open', 'acknowledged')
           AND e.finding_type <> 'whitelist_suggestion'
    ), cleanup_totals AS (
        SELECT count(DISTINCT device_id) AS tech_checklist_devices FROM cleanup
    ), exposure_deadline AS (
        SELECT min(least(b.evidence_fresh_until, b.condition_fresh_until)) AS expires_at
          FROM cleanup e
          JOIN operations.device_software_exposure_current b
            ON b.tenant_id = e.tenant_id AND b.finding_id = e.finding_id
           AND b.device_id = e.device_id AND b.canonical_name = e.canonical_name
    ), window_state AS (
        SELECT min(last_observed_at) AS inventory_observed_at,
               min(first_observed_at + interval '7 days') FILTER (
                   WHERE first_observed_at + interval '7 days' >= v_at
               ) AS expires_at
          FROM qualifying
    ), top_new AS (
        SELECT canonical_name, weekly_devices FROM current_titles WHERE weekly_devices > 0
         ORDER BY weekly_devices DESC, canonical_name LIMIT 1
    ), top_label AS (
        SELECT top.canonical_name, top.weekly_devices,
               coalesce(label.display_name, top.canonical_name) AS display_name
          FROM top_new top
          LEFT JOIN LATERAL (
              SELECT i.display_name FROM operations.software_installations_current i
               WHERE i.tenant_id = p_tenant AND i.display_name <> ''
                 AND lower(i.canonical_name) = lower(btrim(top.canonical_name))
                 AND lower(top.canonical_name) = lower(btrim(top.canonical_name))
               ORDER BY i.last_observed_at DESC, i.display_name, i.device_id
               LIMIT 1
          ) label ON true
    )
    INSERT INTO operations.software_overview_current (
        tenant_id, generation, computed_at, published_at, inventory_observed_at,
        window_expires_at, exposure_expires_at, input_watermarks, contract_ready,
        installations, unique_titles, categorized_titles, uncategorized_titles, approved_titles, rejected_titles, investigate_titles, pending_decisions, risk_high, risk_medium, risk_low, risk_clean, risk_unknown, software_issues, whitelist_suggestions, publishers_undecided, tech_checklist_devices, new_products, new_high_risk,
        top_new_name, top_new_display_name, top_new_devices
    )
    SELECT p_tenant, v_generation, v_at, clock_timestamp(), w.inventory_observed_at,
           w.expires_at, ed.expires_at, '{}'::jsonb, false,
           t.installations, t.unique_titles, c.categorized_titles,
           greatest(t.unique_titles - c.categorized_titles, 0),
           s.approved_titles, s.rejected_titles, s.investigate_titles, s.pending_decisions,
           r.risk_high, r.risk_medium, r.risk_low, r.risk_clean, r.risk_unknown,
           f.software_issues, p.whitelist_suggestions, f.publishers_undecided,
           e.tech_checklist_devices, t.new_products, r.new_high_risk,
           top.canonical_name, top.display_name, top.weekly_devices
      FROM title_totals t CROSS JOIN category_totals c CROSS JOIN status_counts s
      CROSS JOIN risk_totals r CROSS JOIN finding_totals f CROSS JOIN prompt_totals p
      CROSS JOIN cleanup_totals e CROSS JOIN exposure_deadline ed CROSS JOIN window_state w
      LEFT JOIN top_label top ON true
    ON CONFLICT (tenant_id) DO UPDATE SET
        generation = EXCLUDED.generation,
        computed_at = EXCLUDED.computed_at, published_at = EXCLUDED.published_at,
        inventory_observed_at = EXCLUDED.inventory_observed_at,
        window_expires_at = EXCLUDED.window_expires_at,
        exposure_expires_at = EXCLUDED.exposure_expires_at,
        input_watermarks = EXCLUDED.input_watermarks, contract_ready = false,
        installations = EXCLUDED.installations,
        unique_titles = EXCLUDED.unique_titles,
        categorized_titles = EXCLUDED.categorized_titles,
        uncategorized_titles = EXCLUDED.uncategorized_titles,
        approved_titles = EXCLUDED.approved_titles,
        rejected_titles = EXCLUDED.rejected_titles,
        investigate_titles = EXCLUDED.investigate_titles,
        pending_decisions = EXCLUDED.pending_decisions,
        risk_high = EXCLUDED.risk_high,
        risk_medium = EXCLUDED.risk_medium,
        risk_low = EXCLUDED.risk_low,
        risk_clean = EXCLUDED.risk_clean,
        risk_unknown = EXCLUDED.risk_unknown,
        software_issues = EXCLUDED.software_issues,
        whitelist_suggestions = EXCLUDED.whitelist_suggestions,
        publishers_undecided = EXCLUDED.publishers_undecided,
        tech_checklist_devices = EXCLUDED.tech_checklist_devices,
        new_products = EXCLUDED.new_products,
        new_high_risk = EXCLUDED.new_high_risk,
        top_new_name = EXCLUDED.top_new_name,
        top_new_display_name = EXCLUDED.top_new_display_name,
        top_new_devices = EXCLUDED.top_new_devices;
    RETURN v_generation;
END
$fn$;
ALTER FUNCTION operations.refresh_software_overview(bigint) OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.refresh_software_overview(bigint)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.refresh_software_overview(bigint) TO ninja_ingest;
"""

REVERSE_SQL = """
-- Keep migration-owner source reads: reversing cannot safely revoke a grant
-- that may already have existed or now be used by another migration.
DROP VIEW operations.v_software_overview;
DROP FUNCTION operations.refresh_software_overview(bigint);
DROP TABLE operations.software_overview_current;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0406_batch_source_client_evidence"),
    ]

    operations: ClassVar = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
