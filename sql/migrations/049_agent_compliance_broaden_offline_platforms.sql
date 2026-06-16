-- Broaden action_offline_platforms semantics.
--
-- Previously: stale_required_platforms (only platforms past the
-- max_age_days threshold). A device with required Ninja+LogMeIn
-- present but not currently checking in, last seen 14 days ago under
-- a 30-day threshold, ended up with both `Online in` and `Offline`
-- columns empty — operator could not see that the platforms exist
-- but aren't reporting.
--
-- Now: required + present + not currently online (regardless of the
-- staleness threshold). Same s1_exempt and source_failed exclusions.
--
-- Alert findings still come from Python `stale_required_platforms`
-- (over-threshold), so this change is display-only at the alert
-- layer. State classification will flip a small number of devices
-- from Compliant to Offline (those with a required platform present
-- but not actively checking in). That's the intended semantic.
--
-- Column shape on v_device_state_current is unchanged, so downstream
-- views (v_device_work_queue, v_all_devices_human,
-- v_device_platform_detail_current) keep working without rebuild.

CREATE OR REPLACE VIEW ninja_agent_compliance.v_device_state_current AS
WITH base AS (
    SELECT
        m.*,
        ARRAY(
            SELECT p
            FROM unnest(m.missing_required_platforms) AS p
            WHERE NOT (p = 'SentinelOne' AND m.s1_exempt)
              AND p <> ALL(m.source_failed_platforms)
        )::text[] AS action_missing_platforms,
        ARRAY(
            SELECT p
            FROM unnest(m.required_platforms) AS p
            WHERE NOT (p = 'SentinelOne' AND m.s1_exempt)
              AND p <> ALL(m.source_failed_platforms)
              AND CASE p
                    WHEN 'Ninja' THEN m.in_ninja AND NOT COALESCE(m.ninja_online, false)
                    WHEN 'ScreenConnect' THEN m.in_screenconnect AND NOT COALESCE(m.screenconnect_online, false)
                    WHEN 'SentinelOne' THEN m.in_sentinelone AND NOT COALESCE(m.sentinelone_online, false)
                    WHEN 'LogMeIn' THEN m.in_logmein AND NOT COALESCE(m.logmein_online, false)
                    ELSE false
                  END
        )::text[] AS action_offline_platforms,
        ARRAY_REMOVE(ARRAY[
            CASE WHEN m.ninja_online THEN 'Ninja' END,
            CASE WHEN m.screenconnect_online THEN 'ScreenConnect' END,
            CASE WHEN m.sentinelone_online THEN 'SentinelOne' END,
            CASE WHEN m.logmein_online THEN 'LogMeIn' END
        ], NULL)::text[] AS active_platforms,
        ARRAY_REMOVE(ARRAY[
            CASE WHEN m.in_ninja THEN 'Ninja' END,
            CASE WHEN m.in_screenconnect THEN 'ScreenConnect' END,
            CASE WHEN m.in_sentinelone THEN 'SentinelOne' END,
            CASE WHEN m.in_logmein THEN 'LogMeIn' END
        ], NULL)::text[] AS present_platforms,
        GREATEST(
            m.ninja_last_seen,
            m.screenconnect_last_seen,
            m.sentinelone_last_seen,
            m.logmein_last_seen
        ) AS last_seen_anywhere,
        CASE
            WHEN m.os_name IS NULL THEN 'Unknown'
            WHEN m.os_name ILIKE '%Windows Server 2025%' THEN 'Windows Server 2025'
            WHEN m.os_name ILIKE '%Windows Server 2022%' THEN 'Windows Server 2022'
            WHEN m.os_name ILIKE '%Windows Server 2019%' THEN 'Windows Server 2019'
            WHEN m.os_name ILIKE '%Windows Server 2016%' THEN 'Windows Server 2016'
            WHEN m.os_name ILIKE '%Windows Server 2012 R2%' THEN 'Windows Server 2012 R2'
            WHEN m.os_name ILIKE '%Windows Server 2012%' THEN 'Windows Server 2012'
            WHEN m.os_name ILIKE '%Windows Server 2008 R2%' THEN 'Windows Server 2008 R2'
            WHEN m.os_name ILIKE '%Windows Server 2008%' THEN 'Windows Server 2008'
            WHEN m.os_name ILIKE '%Windows Server%' THEN 'Windows Server (other)'
            WHEN m.os_name ILIKE '%Windows 11%' THEN 'Windows 11'
            WHEN m.os_name ILIKE '%Windows 10%' THEN 'Windows 10'
            WHEN m.os_name ILIKE '%Windows 8.1%' THEN 'Windows 8.1'
            WHEN m.os_name ILIKE '%Windows 8%' THEN 'Windows 8'
            WHEN m.os_name ILIKE '%Windows 7%' THEN 'Windows 7'
            WHEN m.os_name ILIKE '%Windows%' THEN 'Windows (other)'
            ELSE 'Other'
        END AS os_family,
        EXISTS (
            SELECT 1
            FROM ninja_agent_compliance.alert_suppressions s
            WHERE s.enabled
              AND (s.client_id IS NULL OR s.client_id = m.client_id)
              AND (s.norm_name IS NULL OR s.norm_name = m.norm_name)
              AND (s.expires_at IS NULL OR s.expires_at > now())
        ) AS ignored
    FROM ninja_agent_compliance.compliance_matrix_current m
    WHERE NOT EXISTS (
        SELECT 1
        FROM ninja_agent_compliance.org_excludes e
        WHERE e.enabled
          AND e.pattern = lower(trim(m.client_name))
    )
),
cross_customer AS (
    SELECT
        b.client_id,
        b.norm_name,
        jsonb_agg(
            jsonb_build_object(
                'platform', p.platform,
                'customer', other.client_name,
                'hostname', other.hostname
            )
            ORDER BY p.platform, other.client_name, other.hostname
        ) AS cross_customer_matches,
        ARRAY_AGG(DISTINCT p.platform ORDER BY p.platform)::text[] AS cross_customer_platforms
    FROM base b
    CROSS JOIN LATERAL unnest(b.action_missing_platforms) AS p(platform)
    JOIN ninja_agent_compliance.compliance_matrix_current other
      ON other.norm_name = b.norm_name
     AND other.client_id <> b.client_id
     AND p.platform = ANY(other.observed_platforms)
    WHERE NOT EXISTS (
        SELECT 1
        FROM ninja_agent_compliance.v_human_decisions_current d
        WHERE d.decision_type IN ('confirm_missing', 'not_same_device')
          AND d.client_id = b.client_id
          AND d.norm_name = b.norm_name
          AND d.platform = p.platform
    )
    GROUP BY b.client_id, b.norm_name
),
prepared AS (
    SELECT
        b.*,
        COALESCE(c.cross_customer_matches, '[]'::jsonb) AS cross_customer_matches,
        COALESCE(c.cross_customer_platforms, ARRAY[]::text[]) AS cross_customer_platforms,
        (
            cardinality(b.active_platforms) > 0
            OR (NOT b.is_stale AND b.last_seen_anywhere IS NOT NULL)
        ) AS active_or_recent
    FROM base b
    LEFT JOIN cross_customer c
      ON c.client_id = b.client_id
     AND c.norm_name = b.norm_name
),
classified AS (
    SELECT
        p.*,
        (cardinality(p.cross_customer_platforms) > 0) AS needs_review,
        CASE
            WHEN cardinality(p.cross_customer_platforms) > 0
                THEN 'Found under another customer'
            WHEN p.is_degraded
                THEN 'Agent data looks degraded'
            WHEN p.is_unknown
                THEN 'Unknown device state'
            ELSE NULL
        END AS review_reason,
        CASE
            WHEN p.ignored THEN 'Ignored'
            WHEN p.is_stale AND cardinality(p.active_platforms) = 0 THEN 'Stale'
            WHEN cardinality(p.action_missing_platforms) > 0 AND p.active_or_recent THEN 'Missing'
            WHEN cardinality(p.action_offline_platforms) > 0 AND p.active_or_recent THEN 'Offline'
            WHEN p.is_degraded THEN 'Review'
            WHEN p.is_unknown THEN 'Review'
            WHEN p.is_compliant THEN 'Compliant'
            ELSE 'Review'
        END AS device_state
    FROM prepared p
)
SELECT
    client_id,
    client_name,
    norm_name,
    hostname,
    device_type,
    os_name,
    os_family,
    domain_name,
    required_platforms,
    present_platforms,
    active_platforms,
    action_missing_platforms AS missing_platforms,
    action_offline_platforms AS offline_platforms,
    source_failed_platforms,
    last_seen_anywhere,
    device_state,
    needs_review,
    review_reason,
    CASE
        WHEN device_state = 'Ignored' THEN 'Ignored by operator'
        WHEN device_state = 'Stale' THEN
            CASE
                WHEN last_seen_anywhere IS NULL THEN 'Not seen in any platform'
                ELSE 'Not seen in any platform for '
                     || GREATEST(0, FLOOR(EXTRACT(EPOCH FROM (now() - last_seen_anywhere)) / 86400))::int
                     || ' day(s)'
            END
        WHEN device_state = 'Missing' AND needs_review THEN
            'Missing ' || array_to_string(action_missing_platforms, ', ')
            || '; possible match under another customer'
        WHEN device_state = 'Missing' THEN
            'Missing ' || array_to_string(action_missing_platforms, ', ')
            || CASE
                WHEN cardinality(active_platforms) > 0
                    THEN '; active in ' || array_to_string(active_platforms, ', ')
                ELSE ''
            END
            || CASE
                WHEN cardinality(action_offline_platforms) > 0
                    THEN '; offline in ' || array_to_string(action_offline_platforms, ', ')
                ELSE ''
            END
        WHEN device_state = 'Offline' THEN
            'Offline in ' || array_to_string(action_offline_platforms, ', ')
            || CASE
                WHEN last_seen_anywhere IS NULL THEN ''
                ELSE '; last seen anywhere '
                     || GREATEST(0, FLOOR(EXTRACT(EPOCH FROM (now() - last_seen_anywhere)) / 86400))::int
                     || ' day(s) ago'
            END
        WHEN device_state = 'Review' AND review_reason IS NOT NULL THEN review_reason
        WHEN cardinality(source_failed_platforms) > 0 THEN
            'Data unavailable from ' || array_to_string(source_failed_platforms, ', ')
        ELSE 'No current issue'
    END AS state_reason,
    CASE
        WHEN device_state = 'Missing' AND needs_review THEN 'Confirm whether the other-customer match is the same device'
        WHEN device_state = 'Missing' THEN 'Install or reconnect the missing agent'
        WHEN device_state = 'Offline' THEN 'Bring the offline agent back online'
        WHEN device_state = 'Stale' THEN 'Confirm whether the device is retired or should be ignored'
        WHEN device_state = 'Review' THEN 'Review the evidence before remediation'
        ELSE ''
    END AS recommended_action,
    cross_customer_matches,
    s1_exempt,
    ignored,
    is_degraded,
    is_stale,
    is_unknown,
    finding_signature,
    evaluated_at
FROM classified
ORDER BY
    CASE device_state
        WHEN 'Missing' THEN 0
        WHEN 'Offline' THEN 1
        WHEN 'Review' THEN 2
        WHEN 'Stale' THEN 3
        WHEN 'Compliant' THEN 4
        WHEN 'Ignored' THEN 5
        ELSE 9
    END,
    client_name,
    hostname;
