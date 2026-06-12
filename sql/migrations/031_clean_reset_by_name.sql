-- Follow-up to migration 030. The original reset filtered on
-- `source NOT IN ('seed', 'manual')`, but pre-v0.16.4 dynamic
-- discovery never set the source column explicitly, so those rows
-- inherited the table DEFAULT ('seed') and survived the reset. The
-- only durable way to distinguish PS-seeded clients from
-- ghost-seeded discovery rows is the explicit name list from
-- migration 019.
--
-- The previous attempt at this migration failed because a scheduled
-- discovery cycle re-populated org_alignment_current between the
-- 030 deploy and this one, leaving FKs to ghost-seeded clients.
-- This version TRUNCATEs the same state tables 030 cleared, then
-- does the name-based DELETE — idempotent and safe to re-run.
--
-- Discovery will re-surface every non-PS Ninja org on the next
-- run; LMI/S1/SC observations route via the PS alias map; the
-- review queue absorbs the rest.

-- 1. Re-truncate compliance state — discovery may have re-populated
--    these between migration 030 applying and this one starting.
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

-- 2. FK cleanup: alert_suppressions, platform_sources tied to
--    soon-to-be-deleted clients.
DELETE FROM ninja_agent_compliance.alert_suppressions
 WHERE client_id IN (
     SELECT client_id FROM ninja_agent_compliance.clients
      WHERE source <> 'manual'
        AND client_name NOT IN (
            'UTA',
            'A.M. Rose',
            'All Data Health',
            'BH Management',
            'C2P',
            'Chartwell Pharma',
            'CPS',
            'DJ Direct',
            'Freunds Fish',
            'GF Supplies',
            'GGI International',
            'Kerekes',
            'KIT',
            'MD Door',
            'Park Bookeeping',
            'Ruby Staffing',
            'SMS Supplies',
            'Spencer Myrtle / Express Builders',
            'Deco/Trimworx',
            'United Supply',
            'Platinum Care',
            'PCHC - Parent Care Health Care',
            'Nutty Naturals',
            'Lion HVAC',
            'Expressive Lighting',
            'County\CNY',
            'Abco - Omni Dental'
        )
 );

DELETE FROM ninja_agent_compliance.platform_sources
 WHERE client_id IN (
     SELECT client_id FROM ninja_agent_compliance.clients
      WHERE source <> 'manual'
        AND client_name NOT IN (
            'UTA',
            'A.M. Rose',
            'All Data Health',
            'BH Management',
            'C2P',
            'Chartwell Pharma',
            'CPS',
            'DJ Direct',
            'Freunds Fish',
            'GF Supplies',
            'GGI International',
            'Kerekes',
            'KIT',
            'MD Door',
            'Park Bookeeping',
            'Ruby Staffing',
            'SMS Supplies',
            'Spencer Myrtle / Express Builders',
            'Deco/Trimworx',
            'United Supply',
            'Platinum Care',
            'PCHC - Parent Care Health Care',
            'Nutty Naturals',
            'Lion HVAC',
            'Expressive Lighting',
            'County\CNY',
            'Abco - Omni Dental'
        )
 );

-- 3. Drop ghost-seeded clients + their aliases + their requirements.
DELETE FROM ninja_agent_compliance.client_aliases
 WHERE client_id IN (
     SELECT client_id FROM ninja_agent_compliance.clients
      WHERE source <> 'manual'
        AND client_name NOT IN (
            'UTA',
            'A.M. Rose',
            'All Data Health',
            'BH Management',
            'C2P',
            'Chartwell Pharma',
            'CPS',
            'DJ Direct',
            'Freunds Fish',
            'GF Supplies',
            'GGI International',
            'Kerekes',
            'KIT',
            'MD Door',
            'Park Bookeeping',
            'Ruby Staffing',
            'SMS Supplies',
            'Spencer Myrtle / Express Builders',
            'Deco/Trimworx',
            'United Supply',
            'Platinum Care',
            'PCHC - Parent Care Health Care',
            'Nutty Naturals',
            'Lion HVAC',
            'Expressive Lighting',
            'County\CNY',
            'Abco - Omni Dental'
        )
 );

DELETE FROM ninja_agent_compliance.platform_requirements
 WHERE client_id IN (
     SELECT client_id FROM ninja_agent_compliance.clients
      WHERE source <> 'manual'
        AND client_name NOT IN (
            'UTA',
            'A.M. Rose',
            'All Data Health',
            'BH Management',
            'C2P',
            'Chartwell Pharma',
            'CPS',
            'DJ Direct',
            'Freunds Fish',
            'GF Supplies',
            'GGI International',
            'Kerekes',
            'KIT',
            'MD Door',
            'Park Bookeeping',
            'Ruby Staffing',
            'SMS Supplies',
            'Spencer Myrtle / Express Builders',
            'Deco/Trimworx',
            'United Supply',
            'Platinum Care',
            'PCHC - Parent Care Health Care',
            'Nutty Naturals',
            'Lion HVAC',
            'Expressive Lighting',
            'County\CNY',
            'Abco - Omni Dental'
        )
 );

DELETE FROM ninja_agent_compliance.clients
 WHERE source <> 'manual'
   AND client_name NOT IN (
       'UTA',
       'A.M. Rose',
       'All Data Health',
       'BH Management',
       'C2P',
       'Chartwell Pharma',
       'CPS',
       'DJ Direct',
       'Freunds Fish',
       'GF Supplies',
       'GGI International',
       'Kerekes',
       'KIT',
       'MD Door',
       'Park Bookeeping',
       'Ruby Staffing',
       'SMS Supplies',
       'Spencer Myrtle / Express Builders',
       'Deco/Trimworx',
       'United Supply',
       'Platinum Care',
       'PCHC - Parent Care Health Care',
       'Nutty Naturals',
       'Lion HVAC',
       'Expressive Lighting',
       'County\CNY',
       'Abco - Omni Dental'
   );
