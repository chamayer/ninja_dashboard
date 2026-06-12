-- Retry of the corrected 031 cleanup for hosts where 031 is already
-- recorded in schema_migrations. This is intentionally idempotent.
--
-- Preserve:
--   * operator manual clients/config (source = 'manual')
--   * the explicit PowerShell-derived seed client list from migration 019
--
-- Remove:
--   * ghost-seeded discovery clients that inherited source='seed'
--   * config rows tied to those ghost clients
--   * runtime state that may FK to those ghost clients/sources

CREATE TEMP TABLE ps_seed_clients (
    client_name text PRIMARY KEY
) ON COMMIT DROP;

INSERT INTO ps_seed_clients (client_name)
VALUES
    ('UTA'),
    ('A.M. Rose'),
    ('All Data Health'),
    ('BH Management'),
    ('C2P'),
    ('Chartwell Pharma'),
    ('CPS'),
    ('DJ Direct'),
    ('Freunds Fish'),
    ('GF Supplies'),
    ('GGI International'),
    ('Kerekes'),
    ('KIT'),
    ('MD Door'),
    ('Park Bookeeping'),
    ('Ruby Staffing'),
    ('SMS Supplies'),
    ('Spencer Myrtle / Express Builders'),
    ('Deco/Trimworx'),
    ('United Supply'),
    ('Platinum Care'),
    ('PCHC - Parent Care Health Care'),
    ('Nutty Naturals'),
    ('Lion HVAC'),
    ('Expressive Lighting'),
    ('County\CNY'),
    ('Abco - Omni Dental');

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

CREATE TEMP TABLE ghost_clients (
    client_id bigint PRIMARY KEY
) ON COMMIT DROP;

INSERT INTO ghost_clients (client_id)
SELECT c.client_id
FROM ninja_agent_compliance.clients c
LEFT JOIN ps_seed_clients ps ON ps.client_name = c.client_name
WHERE COALESCE(c.source, '') <> 'manual'
  AND ps.client_name IS NULL;

CREATE TEMP TABLE ghost_sources (
    source_id bigint PRIMARY KEY
) ON COMMIT DROP;

INSERT INTO ghost_sources (source_id)
SELECT ps.source_id
FROM ninja_agent_compliance.platform_sources ps
JOIN ghost_clients gc ON gc.client_id = ps.client_id;

DELETE FROM ninja_agent_compliance.alert_suppressions s
USING ghost_clients gc
WHERE s.client_id = gc.client_id;

DELETE FROM ninja_agent_compliance.alert_rules r
USING ghost_clients gc
WHERE r.client_id = gc.client_id;

DELETE FROM ninja_agent_compliance.client_aliases a
WHERE a.client_id IN (SELECT client_id FROM ghost_clients)
   OR a.source_id IN (SELECT source_id FROM ghost_sources);

DELETE FROM ninja_agent_compliance.platform_requirements r
USING ghost_clients gc
WHERE r.client_id = gc.client_id;

DELETE FROM ninja_agent_compliance.platform_sources ps
USING ghost_sources gs
WHERE ps.source_id = gs.source_id;

DELETE FROM ninja_agent_compliance.clients c
USING ghost_clients gc
WHERE c.client_id = gc.client_id;
