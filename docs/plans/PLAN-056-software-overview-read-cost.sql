-- SET ASIDE: no external measurement is requested or authorized by the current task.
-- PLAN-056 / ADR-0058: retained unapproved representative read-cost draft.
-- REVIEW/AUTHORIZATION REQUIRED BEFORE EXTERNAL EXECUTION.
-- Produces EXPLAIN JSON, not application rows/customer data. No refresh, DDL,
-- queue request, classifier, rebuild, cache reset or repeated timing run.
-- This estimates overview calculation cost; it does not certify refresh-write
-- overhead, Jobs queue delay, trigger load or full-HTML acceptance.
BEGIN READ ONLY;
SET LOCAL operations.tenant_id = '1';
SET LOCAL statement_timeout = '30s';
SET LOCAL lock_timeout = '2s';

EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
WITH ctx AS MATERIALIZED (SELECT statement_timestamp() AS at),
qualifying AS MATERIALIZED (
    SELECT i.tenant_id, i.canonical_name, i.publisher, i.device_id,
           i.client_id, i.software_version_id, i.first_observed_at,
           i.last_observed_at
      FROM operations.software_installations_current i
      JOIN operations.devices d ON d.tenant_id=i.tenant_id AND d.id=i.device_id
     WHERE i.tenant_id=1 AND i.deleted_at IS NULL AND i.stale_since IS NULL
       AND d.deleted_at IS NULL AND d.lifecycle_status <> 'retired'
),
titles AS MATERIALIZED (
    SELECT tenant_id, canonical_name,
           mode() WITHIN GROUP (ORDER BY publisher) AS publisher,
           count(*)::bigint AS installations,
           count(DISTINCT device_id) FILTER (
               WHERE first_observed_at >= (SELECT at FROM ctx) - interval '7 days'
           )::bigint AS weekly_devices
      FROM qualifying GROUP BY tenant_id,canonical_name
),
title_flags AS (
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
status_counts AS MATERIALIZED (
    SELECT (CASE WHEN title_flags.rejected THEN 'reject'
       WHEN title_flags.awaiting THEN 'pending'
       WHEN investigate_titles.title_key IS NOT NULL
            OR investigate_publishers.publisher_key IS NOT NULL THEN 'investigate'
       ELSE 'approve' END) AS status, count(*)::bigint AS n
      FROM titles sic LEFT JOIN title_flags ON title_flags.title_key = lower(sic.canonical_name)
  LEFT JOIN investigate_titles ON investigate_titles.title_key = lower(sic.canonical_name)
  LEFT JOIN investigate_publishers
    ON investigate_publishers.publisher_key = lower(COALESCE(sic.publisher, ''))
     GROUP BY 1
),
capability_titles AS MATERIALIZED (
    SELECT DISTINCT q.canonical_name FROM qualifying q
      JOIN catalog.software_versions sv ON sv.id=q.software_version_id
      JOIN catalog.products p ON p.id=sv.product_id
      JOIN catalog.v_product_capability_effective c ON c.product_uuid=p.product_uuid
),
safety AS MATERIALIZED (
    SELECT s.canonical_name,s.safety_band,t.weekly_devices
      FROM operations.v_software_safety s
      JOIN titles t ON t.tenant_id=s.tenant_id AND t.canonical_name=s.canonical_name
     WHERE s.tenant_id=1
),
top_new AS MATERIALIZED (
    SELECT canonical_name,weekly_devices FROM titles WHERE weekly_devices > 0
     ORDER BY weekly_devices DESC,canonical_name LIMIT 1
),
prompt_values AS MATERIALIZED (
    SELECT DISTINCT f.finding_details->'canonical_name' AS canonical_value
      FROM operations.findings f
      JOIN operations.finding_types ft ON ft.id=f.finding_type_id
     WHERE f.tenant_id=1 AND f.status IN ('open','acknowledged','investigating')
       AND ft.name IN ('whitelist_suggestion','rare_recent')
),
label AS MATERIALIZED (
    SELECT i.display_name FROM operations.software_installations_current i
     WHERE i.tenant_id=1
       AND lower(i.canonical_name)=(SELECT lower(canonical_name) FROM top_new)
       AND i.display_name <> ''
     ORDER BY i.last_observed_at DESC,i.display_name,i.device_id LIMIT 1
)
SELECT
    coalesce((SELECT sum(installations) FROM titles),0)::bigint AS installations,
    (SELECT count(*) FROM titles) AS products,
    (SELECT count(*) FROM capability_titles) AS categorized,
    (SELECT jsonb_object_agg(status,n) FROM status_counts) AS title_status,
    (SELECT jsonb_object_agg(safety_band,n) FROM
        (SELECT safety_band,count(*) AS n FROM safety GROUP BY safety_band) b) AS risk,
    (SELECT count(*) FROM operations.findings f
       JOIN operations.finding_types ft ON ft.id=f.finding_type_id
      WHERE f.tenant_id=1 AND f.status IN ('open','acknowledged','investigating')
        AND ft.issue_category='Software & security'
        AND ft.name <> 'whitelist_suggestion') AS software_issues,
    (SELECT count(*) FROM prompt_values) AS prompt_titles,
    (SELECT count(DISTINCT lower(f.finding_details->>'publisher'))
       FROM operations.findings f
       JOIN operations.finding_types ft ON ft.id=f.finding_type_id
      WHERE f.tenant_id=1 AND f.status IN ('open','acknowledged')
        AND ft.name IN ('whitelist_suggestion','rare_recent')
        AND coalesce(f.finding_details->>'publisher','') <> '') AS awaiting_publishers,
    (SELECT count(DISTINCT e.device_id) FROM operations.v_device_software_exposure e
      WHERE e.tenant_id=1 AND e.status IN ('open','acknowledged')
        AND e.finding_type <> 'whitelist_suggestion') AS cleanup_devices,
    (SELECT count(*) FROM titles WHERE weekly_devices > 0) AS weekly_products,
    (SELECT count(*) FROM safety WHERE safety_band='high' AND weekly_devices > 0) AS weekly_high_risk,
    (SELECT canonical_name FROM top_new) AS top_new_name,
    (SELECT weekly_devices FROM top_new) AS top_new_devices,
    (SELECT display_name FROM label) AS top_new_label,
    (SELECT min(first_observed_at + interval '7 days') FROM qualifying
      WHERE first_observed_at + interval '7 days' >= (SELECT at FROM ctx)) AS next_weekly_expiry;

ROLLBACK;
