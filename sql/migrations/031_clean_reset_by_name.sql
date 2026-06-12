-- Follow-up to migration 030. The original reset filtered on
-- `source NOT IN ('seed', 'manual')`, but pre-v0.16.4 dynamic
-- discovery never set the source column explicitly, so those rows
-- inherited the table DEFAULT ('seed') and survived the reset. The
-- only durable way to distinguish PS-seeded clients from
-- ghost-seeded discovery rows is the explicit name list from
-- migration 019.
--
-- Same preservation rules as 030: keep PS-seeded canonicals and
-- operator-manual rows. Wipe everything else, including any rows
-- mis-tagged as 'seed' that aren't actually in the migration 019
-- name list.
--
-- Discovery will re-surface every non-PS Ninja org on the next
-- run; LMI/S1/SC observations route via the PS alias map; the
-- review queue absorbs the rest.

-- 1. FK cleanup: alert_suppressions, platform_sources tied to
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

-- 2. Drop ghost-seeded clients + their aliases + their requirements.
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
