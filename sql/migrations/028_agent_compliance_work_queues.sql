-- Keep the human queues current: closed name candidates should not stay
-- in the primary review list, and source/config problems get their own
-- current-state work queue.

UPDATE ninja_agent_compliance.org_candidates oc
SET status = 'ignored',
    enabled = false,
    updated_at = now(),
    updated_by = 'migration_028'
WHERE oc.enabled
  AND EXISTS (
      SELECT 1
      FROM ninja_agent_compliance.org_excludes e
      WHERE e.enabled
        AND e.pattern = lower(trim(oc.candidate_name))
  );

UPDATE ninja_agent_compliance.org_candidates oc
SET status = 'promoted',
    enabled = false,
    updated_at = now(),
    updated_by = 'migration_028'
WHERE oc.enabled
  AND EXISTS (
      SELECT 1
      FROM ninja_agent_compliance.client_aliases a
      WHERE a.enabled
        AND a.platform = oc.platform
        AND lower(trim(a.alias_value)) = lower(trim(oc.candidate_name))
  );

CREATE OR REPLACE VIEW ninja_agent_compliance.v_org_candidates_current AS
SELECT *
FROM ninja_agent_compliance.org_candidates
WHERE enabled
  AND status = 'open'
ORDER BY last_seen_at DESC, candidate_name;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_source_work_current AS
WITH clients AS (
    SELECT client_id, client_name
    FROM ninja_agent_compliance.clients
    WHERE enabled
      AND source <> 'alignment'
),
scopes(scope_name) AS (
    VALUES ('server'), ('workstation'), ('all')
),
effective_requirements AS (
    SELECT DISTINCT
        c.client_id,
        c.client_name,
        platform
    FROM clients c
    CROSS JOIN scopes s
    JOIN LATERAL (
        SELECT pr.required_platforms
        FROM ninja_agent_compliance.platform_requirements pr
        WHERE pr.enabled
          AND (pr.client_id = c.client_id OR pr.client_id IS NULL)
          AND pr.device_scope IN (s.scope_name, 'all')
        ORDER BY
          CASE WHEN pr.client_id = c.client_id THEN 0 ELSE 1 END,
          CASE WHEN pr.device_scope = s.scope_name THEN 0 ELSE 1 END
        LIMIT 1
    ) req ON true
    CROSS JOIN LATERAL unnest(req.required_platforms) AS platform
),
missing_sources AS (
    SELECT
        'Missing source'::text AS work_type,
        90::integer AS severity,
        er.platform,
        'Not configured'::text AS source_name,
        er.client_name,
        0::integer AS rows_observed,
        ('No enabled ' || er.platform || ' source covers this org')::text AS issue
    FROM effective_requirements er
    WHERE NOT EXISTS (
        SELECT 1
        FROM ninja_agent_compliance.platform_sources ps
        WHERE ps.enabled
          AND ps.platform = er.platform
          AND (ps.is_shared OR ps.client_id = er.client_id)
    )
),
failed_sources AS (
    SELECT
        'Source failed'::text AS work_type,
        100::integer AS severity,
        h.platform,
        h.source_name,
        COALESCE(NULLIF(h.client_name, ''), 'Shared') AS client_name,
        h.rows_observed,
        COALESCE(NULLIF(h.error_text, ''), 'Collector failed') AS issue
    FROM ninja_agent_compliance.v_source_health_current h
    WHERE h.enabled
      AND h.status = 'failed'
)
SELECT *
FROM failed_sources
UNION ALL
SELECT *
FROM missing_sources
ORDER BY severity DESC, platform, source_name, client_name;
