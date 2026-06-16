-- Human-first device state model for agent compliance.
--
-- This creates a clean reporting contract on top of the existing
-- compliance_matrix_current table. It does not rewrite ingest storage.

CREATE TABLE IF NOT EXISTS ninja_agent_compliance.human_decisions (
    decision_id      bigserial PRIMARY KEY,
    decision_type    text NOT NULL CHECK (
        decision_type IN (
            'ignore_device',
            'ignore_finding',
            'confirm_missing',
            'same_device',
            'not_same_device',
            'accept_customer_name',
            'alias_customer_name',
            'ignore_customer_name',
            'platform_required_on',
            'platform_required_off'
        )
    ),
    client_id        bigint REFERENCES ninja_agent_compliance.clients(client_id),
    norm_name        text,
    hostname         text,
    platform         text CHECK (
        platform IS NULL OR platform IN ('Ninja', 'SentinelOne', 'LogMeIn', 'ScreenConnect')
    ),
    other_client_id  bigint REFERENCES ninja_agent_compliance.clients(client_id),
    candidate_name   text,
    target_client_id bigint REFERENCES ninja_agent_compliance.clients(client_id),
    notes            text,
    expires_at       timestamptz,
    enabled          boolean NOT NULL DEFAULT true,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    updated_by       text NOT NULL DEFAULT 'system'
);

CREATE INDEX IF NOT EXISTS human_decisions_lookup_idx
    ON ninja_agent_compliance.human_decisions
    (decision_type, client_id, norm_name, platform, enabled);

CREATE OR REPLACE VIEW ninja_agent_compliance.v_human_decisions_current AS
SELECT *
FROM ninja_agent_compliance.human_decisions
WHERE enabled
  AND (expires_at IS NULL OR expires_at > now());

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
            FROM unnest(m.stale_required_platforms) AS p
            WHERE p <> ALL(m.source_failed_platforms)
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

CREATE OR REPLACE VIEW ninja_agent_compliance.v_device_work_queue AS
SELECT
    client_id,
    client_name,
    norm_name,
    hostname,
    device_type,
    os_name,
    domain_name,
    required_platforms,
    present_platforms AS found_platforms,
    missing_platforms,
    offline_platforms AS stale_platforms,
    source_failed_platforms,
    active_platforms AS online_platforms,
    last_seen_anywhere,
    state_reason AS issue,
    CASE
        WHEN device_state IN ('Missing', 'Offline', 'Review', 'Stale') THEN device_state
        ELSE device_state
    END AS work_state,
    s1_exempt,
    is_degraded,
    is_stale,
    false AS cross_client_conflict,
    finding_signature,
    evaluated_at,
    COALESCE(
        ARRAY(
            SELECT DISTINCT match.value->>'platform'
            FROM jsonb_array_elements(cross_customer_matches) AS match(value)
        ),
        ARRAY[]::text[]
    ) AS cross_customer_actionable_platforms,
    os_family
FROM ninja_agent_compliance.v_device_state_current
WHERE NOT ignored
  AND device_state IN ('Missing', 'Offline', 'Review', 'Stale')
ORDER BY
    CASE device_state
        WHEN 'Missing' THEN 0
        WHEN 'Offline' THEN 1
        WHEN 'Review' THEN 2
        WHEN 'Stale' THEN 3
        ELSE 9
    END,
    client_name,
    hostname;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_all_devices_human AS
SELECT
    client_id,
    client_name,
    norm_name,
    hostname,
    device_type,
    os_name,
    domain_name,
    required_platforms,
    present_platforms AS found_platforms,
    missing_platforms,
    offline_platforms AS stale_platforms,
    source_failed_platforms,
    active_platforms AS online_platforms,
    last_seen_anywhere,
    device_state AS state,
    state_reason AS issue,
    s1_exempt,
    ignored,
    evaluated_at,
    COALESCE(
        ARRAY(
            SELECT DISTINCT match.value->>'platform'
            FROM jsonb_array_elements(cross_customer_matches) AS match(value)
        ),
        ARRAY[]::text[]
    ) AS cross_customer_actionable_platforms,
    os_family
FROM ninja_agent_compliance.v_device_state_current
ORDER BY client_name, hostname;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_device_platform_detail_current AS
WITH latest_obs AS (
    SELECT DISTINCT ON (resolved_client_id, norm_name, platform)
        resolved_client_id AS client_id,
        norm_name,
        platform,
        platform_group_name,
        hostname AS platform_hostname,
        platform_device_id,
        is_online,
        last_seen_at,
        observed_at
    FROM ninja_agent_compliance.platform_observations
    WHERE resolved_client_id IS NOT NULL
    ORDER BY resolved_client_id, norm_name, platform, observed_at DESC
),
expanded AS (
    SELECT
        d.client_id,
        d.client_name,
        d.norm_name,
        d.hostname,
        s.device_state,
        s.needs_review,
        s.review_reason,
        s.state_reason,
        s.recommended_action,
        p.platform,
        p.platform = ANY(s.required_platforms) AS required,
        p.platform = ANY(s.present_platforms) AS found,
        p.platform = ANY(s.active_platforms) AS active,
        p.platform = ANY(s.missing_platforms) AS missing,
        p.platform = ANY(s.offline_platforms) AS offline,
        p.platform = ANY(s.source_failed_platforms) AS source_failed,
        p.platform = ANY(
            COALESCE(
                ARRAY(
                    SELECT DISTINCT match.value->>'platform'
                    FROM jsonb_array_elements(s.cross_customer_matches) AS match(value)
                ),
                ARRAY[]::text[]
            )
        ) AS found_under_other_customer,
        CASE p.platform
            WHEN 'Ninja' THEN d.ninja_last_seen
            WHEN 'ScreenConnect' THEN d.screenconnect_last_seen
            WHEN 'SentinelOne' THEN d.sentinelone_last_seen
            WHEN 'LogMeIn' THEN d.logmein_last_seen
            ELSE NULL
        END AS last_seen_at,
        CASE p.platform
            WHEN 'Ninja' THEN d.ninja_device_id
            WHEN 'ScreenConnect' THEN d.screenconnect_device_id
            WHEN 'SentinelOne' THEN d.sentinelone_device_id
            WHEN 'LogMeIn' THEN d.logmein_device_id
            ELSE NULL
        END AS platform_device_id
    FROM ninja_agent_compliance.compliance_matrix_current d
    JOIN ninja_agent_compliance.v_device_state_current s
      ON s.client_id = d.client_id
     AND s.norm_name = d.norm_name
    CROSS JOIN (VALUES
        ('Ninja'),
        ('ScreenConnect'),
        ('SentinelOne'),
        ('LogMeIn')
    ) AS p(platform)
)
SELECT
    e.client_id,
    e.client_name,
    e.norm_name,
    e.hostname,
    e.device_state,
    e.needs_review,
    e.review_reason,
    e.state_reason,
    e.recommended_action,
    e.platform,
    e.required,
    e.found,
    e.active,
    e.missing,
    e.offline,
    e.source_failed,
    e.found_under_other_customer,
    CASE
        WHEN e.source_failed THEN 'Source unavailable'
        WHEN NOT e.required THEN 'Not required'
        WHEN e.missing THEN 'Missing'
        WHEN e.offline THEN 'Offline'
        WHEN e.active THEN 'Active'
        WHEN e.found THEN 'Found'
        ELSE 'Not found'
    END AS platform_status,
    e.last_seen_at,
    CASE
        WHEN e.last_seen_at IS NULL THEN 'Never'
        ELSE GREATEST(0, FLOOR(EXTRACT(EPOCH FROM (now() - e.last_seen_at)) / 86400))::int || ' day(s) ago'
    END AS age_text,
    lo.platform_group_name AS platform_customer,
    COALESCE(lo.platform_hostname, e.hostname) AS platform_hostname,
    COALESCE(lo.platform_device_id, e.platform_device_id) AS platform_device_id,
    CASE
        WHEN e.found_under_other_customer THEN 'Possible match under another customer'
        WHEN e.source_failed THEN 'Collector failed; do not blame device'
        WHEN e.missing THEN 'Required platform is absent'
        WHEN e.offline THEN 'Required platform is not checking in'
        WHEN NOT e.required THEN 'Platform is not required for this device'
        ELSE ''
    END AS notes
FROM expanded e
LEFT JOIN latest_obs lo
  ON lo.client_id = e.client_id
 AND lo.norm_name = e.norm_name
 AND lo.platform = e.platform
ORDER BY e.client_name, e.hostname,
    CASE e.platform
        WHEN 'Ninja' THEN 1
        WHEN 'SentinelOne' THEN 2
        WHEN 'LogMeIn' THEN 3
        WHEN 'ScreenConnect' THEN 4
        ELSE 9
    END;
