-- Keep the review queue focused on names that still need a decision.
-- Ninja-authoritative discovery can promote a customer while older
-- candidate rows remain open from a previous run. Close those rows
-- and make the current view defensive.

UPDATE ninja_agent_compliance.org_candidates oc
SET status = 'promoted',
    enabled = false,
    updated_at = now(),
    updated_by = 'agent_compliance'
WHERE oc.enabled
  AND oc.status = 'open'
  AND (
      EXISTS (
          SELECT 1
          FROM ninja_agent_compliance.clients c
          WHERE c.enabled
            AND c.source <> 'alignment'
            AND lower(regexp_replace(c.client_name, '[[:space:]_.-]', '', 'g')) = oc.norm_name
      )
      OR EXISTS (
          SELECT 1
          FROM ninja_agent_compliance.client_aliases a
          JOIN ninja_agent_compliance.clients c
            ON c.client_id = a.client_id
          WHERE a.enabled
            AND c.enabled
            AND c.source <> 'alignment'
            AND lower(regexp_replace(a.alias_value, '[[:space:]_.-]', '', 'g')) = oc.norm_name
      )
  );

CREATE OR REPLACE VIEW ninja_agent_compliance.v_org_candidates_current AS
SELECT
    oc.candidate_id,
    oc.norm_name,
    oc.candidate_name,
    oc.platform,
    oc.source_name,
    oc.observed_count,
    oc.status,
    oc.suggested_target,
    oc.notes,
    oc.first_seen_at,
    oc.last_seen_at,
    oc.updated_at,
    oc.updated_by
FROM ninja_agent_compliance.org_candidates oc
WHERE oc.enabled
  AND oc.status = 'open'
  AND NOT EXISTS (
      SELECT 1
      FROM ninja_agent_compliance.clients c
      WHERE c.enabled
        AND c.source <> 'alignment'
        AND lower(regexp_replace(c.client_name, '[[:space:]_.-]', '', 'g')) = oc.norm_name
  )
  AND NOT EXISTS (
      SELECT 1
      FROM ninja_agent_compliance.client_aliases a
      JOIN ninja_agent_compliance.clients c
        ON c.client_id = a.client_id
      WHERE a.enabled
        AND c.enabled
        AND c.source <> 'alignment'
        AND lower(regexp_replace(a.alias_value, '[[:space:]_.-]', '', 'g')) = oc.norm_name
  );
