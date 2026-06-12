-- Clean reset of agent-compliance runtime state and dynamic-discovery
-- cruft.
--
-- Preserves:
--   * The PowerShell-derived seed in clients / client_aliases /
--     platform_requirements / org_excludes (source='seed', from
--     migrations 019, 021, 029).
--   * Any operator-promoted customers (source='manual').
--   * The shared notification_routes + alert_rules + shared
--     platform_sources (Ninja / SentinelOne / LogMeIn config).
--
-- Wipes:
--   * All compliance state. Rebuilt by the next /run/agent-compliance.
--   * All dynamic-discovery clients (source='alignment'), demoted
--     clients (source='demoted' from migration 029), and any per-client
--     SC platform_sources / aliases / requirements that reference them.
--
-- Why this is safe re: aliases: PS-seeded client_aliases have
-- source_id IS NULL (they were inserted by the migration 019/029
-- seed VALUES blocks, not by the discovery flow), so deleting
-- dynamic-discovery platform_sources never breaks a PS alias FK.
--
-- After this migration applies, the next ingest cycle:
--   1. Sees Ninja observations and routes each to its PS-seeded
--      canonical via the existing alias map.
--   2. Sees Ninja orgs not in the PS seed (AOS, Avalon, etc.) and
--      creates them as new source='alignment' clients.
--   3. Sees LMI/S1/SC names that don't match a PS alias and surfaces
--      them in 'Customer names to review' for operator triage.
--
-- Previously demoted clients (Bobov45, Glas, D Miller Books, Silk Edge,
-- Silvercup, Ready, TSK) come back via discovery if their observations
-- are still present, landing in the review queue for explicit operator
-- decision.

-- 1. Compliance state — fully rebuilt on the next run.
TRUNCATE
    ninja_agent_compliance.alert_events,
    ninja_agent_compliance.alert_state,
    ninja_agent_compliance.compliance_findings,
    ninja_agent_compliance.compliance_matrix_current,
    ninja_agent_compliance.compliance_matrix_history,
    ninja_agent_compliance.org_alignment_current,
    ninja_agent_compliance.org_alignment_history,
    ninja_agent_compliance.platform_observations,
    ninja_agent_compliance.source_runs,
    ninja_agent_compliance.org_candidates
    RESTART IDENTITY;

-- 2. FK cleanup: alert_suppressions that point at non-PS clients.
--    Operator ignores on PS-seeded clients are preserved.
DELETE FROM ninja_agent_compliance.alert_suppressions
 WHERE client_id IN (
     SELECT client_id FROM ninja_agent_compliance.clients
      WHERE source NOT IN ('seed', 'manual')
 );

-- 3. FK cleanup: per-client platform_sources (e.g. dynamically
--    discovered SC sources) whose parent client is being deleted.
--    Shared sources (client_id IS NULL — Ninja / S1 / LMI mains) stay.
DELETE FROM ninja_agent_compliance.platform_sources
 WHERE client_id IN (
     SELECT client_id FROM ninja_agent_compliance.clients
      WHERE source NOT IN ('seed', 'manual')
 );

-- 4. Drop dynamic-discovery cruft from the config tables. PS seed
--    and operator-manual rows stay.
DELETE FROM ninja_agent_compliance.client_aliases
 WHERE source NOT IN ('seed', 'manual');

DELETE FROM ninja_agent_compliance.platform_requirements
 WHERE source NOT IN ('seed', 'manual');

DELETE FROM ninja_agent_compliance.clients
 WHERE source NOT IN ('seed', 'manual');
