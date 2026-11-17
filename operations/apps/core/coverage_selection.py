"""Coverage selector candidate; maintained serving path remains disabled.

Reads maintained/protected facts and returns compact counts and ordered IDs.
Complete filter/export parity and persistent maintenance are release gates.
"""

import json

from django.db import connection, transaction

DEFAULT_SELECTION_SQL = """
WITH computers AS MATERIALIZED (
    SELECT d.id, d.client_id, c.slug, c.display_name,
           coalesce(d.canonical_hostname, '') AS hostname, d.canonical_hostname AS sort_hostname,
           coalesce(d.os_family, '') AS os_family, d.device_type, d.device_role,
           d.lifecycle_status, coalesce(session.is_online_any, false) AS online,
           session.last_contact_at,
           coalesce(decision.value, '{}'::jsonb) ? 'agent.edr' AS s1_exempt,
           coalesce(nullif(c.offline_after_days, 0), %s) AS offline_days
    FROM operations.devices d
    JOIN operations.computer_client_ownership owner
      ON owner.tenant_id = d.tenant_id AND owner.device_id = d.id
     AND owner.effective_client_id = d.client_id
     AND owner.state IN ('resolved', 'decision_protected')
    JOIN operations.clients c ON c.id = d.client_id
    LEFT JOIN operations.device_session_current session
      ON session.tenant_id = d.tenant_id AND session.device_id = d.id
    LEFT JOIN operations.device_operator_decisions decision
      ON decision.tenant_id = d.tenant_id AND decision.device_id = d.id
     AND decision.dimension = 'exemptions'
    WHERE d.tenant_id = %s AND d.deleted_at IS NULL
      AND d.lifecycle_status <> 'retired'
), presence AS MATERIALIZED (
    SELECT presence.device_id, presence.platform,
           bool_or(presence.reported_online) AS online,
           max(coalesce(presence.last_contact_at, presence.last_observed_at)) AS contact
    FROM operations.device_agent_presence_current presence
    WHERE presence.tenant_id = %s
      AND (presence.entity_type LIKE 'agent.%%' OR presence.entity_type = 'vm.guest')
      AND EXISTS (SELECT 1 FROM operations.devices current_device
                  WHERE current_device.tenant_id = presence.tenant_id
                    AND current_device.id = presence.device_id
                    AND current_device.deleted_at IS NULL
                    AND current_device.lifecycle_status <> 'retired')
    GROUP BY presence.device_id, presence.platform
), observations AS MATERIALIZED (
    SELECT observation.device_id, observation.source_name AS platform,
           bool_or(observation.observation_active) AS current
    FROM operations.v_device_observation_current observation
    WHERE observation.tenant_id = %s
      AND (observation.entity_type LIKE 'agent.%%' OR observation.entity_type = 'vm.guest')
      AND EXISTS (SELECT 1 FROM operations.devices current_device
                  WHERE current_device.tenant_id = observation.tenant_id
                    AND current_device.id = observation.device_id
                    AND current_device.deleted_at IS NULL
                    AND current_device.lifecycle_status <> 'retired')
    GROUP BY observation.device_id, observation.source_name
), hudu AS MATERIALIZED (
    SELECT record.device_id,
           count(*) FILTER (WHERE lifecycle.record_lifecycle = 'archived') AS archived,
           count(*) FILTER (WHERE lifecycle.record_lifecycle IS DISTINCT FROM 'archived') AS current,
           bool_or(record.has_relayed_cards) FILTER (
               WHERE lifecycle.record_lifecycle IS DISTINCT FROM 'archived') AS current_links,
           bool_or(record.has_relayed_cards) FILTER (
               WHERE lifecycle.record_lifecycle = 'archived') AS archived_links
    FROM operations.v_hudu_computer_inventory_observation_current record
    JOIN computers computer ON computer.id = record.device_id
                           AND computer.client_id = record.client_id
    LEFT JOIN LATERAL (
        SELECT state.record_lifecycle
        FROM operations.v_device_source_record_lifecycle_current state
        WHERE state.tenant_id = record.tenant_id
          AND state.observation_id = record.observation_id
        OFFSET 0
    ) lifecycle ON true
    WHERE record.tenant_id = %s
    GROUP BY record.device_id
), requirement_presence AS MATERIALIZED (
    SELECT device_id, entity_type,
           CASE WHEN grouping(platform) = 1 THEN 'any' ELSE platform END AS platform,
           bool_or(reported_online) AS online
    FROM operations.device_agent_presence_current WHERE tenant_id = %s
    GROUP BY GROUPING SETS ((device_id, entity_type, platform), (device_id, entity_type))
), requirement_rows AS MATERIALIZED (
    SELECT state.device_id, state.platform,
           CASE state.verdict WHEN 'missing' THEN 'Missing' WHEN 'stale' THEN 'Stale'
               WHEN 'satisfied' THEN CASE WHEN coalesce(presence.online, false)
                                         THEN 'Online' ELSE 'Offline' END
               WHEN 'os_unknown' THEN 'N/A — OS unknown'
               WHEN 'pending_cleanup' THEN 'N/A — Cleanup' ELSE 'No agents' END AS status,
           CASE state.verdict WHEN 'missing' THEN 0 WHEN 'stale' THEN 1
                WHEN 'satisfied' THEN CASE WHEN coalesce(presence.online, false)
                                          THEN 4 ELSE 3 END ELSE 2 END AS priority
    FROM operations.device_requirement_state state
    JOIN computers computer ON computer.id = state.device_id
    LEFT JOIN requirement_presence presence ON presence.device_id = state.device_id
      AND presence.entity_type = state.entity_type AND presence.platform = state.platform
    WHERE state.tenant_id = %s AND state.verdict <> 'exempt'
), requirement_keys AS MATERIALIZED (
    SELECT DISTINCT ON (device_id, platform) device_id, platform, status, priority
    FROM requirement_rows ORDER BY device_id, platform, priority
), platforms AS MATERIALIZED (
    SELECT platform FROM (
        SELECT platform FROM presence UNION ALL SELECT platform FROM observations
        UNION ALL SELECT platform FROM requirement_keys
        UNION ALL SELECT 'Hudu' WHERE EXISTS (SELECT 1 FROM hudu)
    ) names
    GROUP BY platform
), record_statuses AS MATERIALIZED (
    SELECT computer.id AS device_id, platform.platform, presence.contact AS source_contact_at,
           requirement.status AS requirement_status,
           CASE WHEN presence.online THEN 'Online' WHEN presence.online = false THEN 'Offline'
                WHEN presence.device_id IS NOT NULL THEN 'Current' END AS source_status,
           CASE WHEN platform.platform = 'SentinelOne' AND computer.s1_exempt THEN 'Exempt'
                WHEN requirement.priority IN (0, 1, 2) THEN requirement.status
                WHEN requirement.priority IS NOT NULL THEN 'Required' ELSE 'N/A' END AS rule_status,
           CASE WHEN platform.platform = 'Hudu' THEN
                    CASE WHEN hudu.current > 0 THEN 'No status'
                         WHEN hudu.archived > 0 THEN 'Withdrawn' ELSE 'No record' END
                WHEN presence.online THEN 'Online'
                WHEN presence.online = false THEN
                    CASE WHEN presence.contact >= %s - make_interval(days => computer.offline_days)
                         THEN 'Offline' ELSE 'Stale' END
                WHEN presence.device_id IS NOT NULL OR observations.current THEN 'No status'
                WHEN observations.current = false THEN 'Withdrawn' ELSE 'No record' END AS status
    FROM computers computer CROSS JOIN platforms platform
    LEFT JOIN presence ON presence.device_id = computer.id AND presence.platform = platform.platform
    LEFT JOIN observations ON observations.device_id = computer.id AND observations.platform = platform.platform
    LEFT JOIN hudu ON hudu.device_id = computer.id
    LEFT JOIN requirement_keys requirement
      ON requirement.device_id = computer.id AND requirement.platform = platform.platform
), record_counts AS (
    SELECT platform, status, count(*) AS total FROM record_statuses GROUP BY platform, status
), hudu_options AS (
    SELECT %s::jsonb AS value
), source_text AS MATERIALIZED (
    SELECT device_id, lower(string_agg(concat_ws(' ', platform, status,
        CASE WHEN status IN ('Offline','Stale') AND source_contact_at IS NOT NULL THEN
          CASE WHEN greatest(0,extract(epoch FROM ((value->>'now')::timestamptz-source_contact_at))) < 3600
               THEN greatest(1,floor(greatest(0,extract(epoch FROM ((value->>'now')::timestamptz-source_contact_at)))/60))::text || 'm'
               WHEN greatest(0,extract(epoch FROM ((value->>'now')::timestamptz-source_contact_at))) < 86400
               THEN floor(greatest(0,extract(epoch FROM ((value->>'now')::timestamptz-source_contact_at)))/3600)::text || 'h'
               ELSE floor(greatest(0,extract(epoch FROM ((value->>'now')::timestamptz-source_contact_at)))/86400)::text || 'd' END END,
        CASE WHEN rule_status IN ('Missing','Stale') THEN 'Required · ' || rule_status ELSE rule_status END),
        ' ' ORDER BY coalesce(array_position(ARRAY['Ninja','SentinelOne','LogMeIn','R-U-ON','ScreenConnect','Hudu'],platform),99),lower(platform))) AS value
    FROM record_statuses CROSS JOIN hudu_options
    WHERE value->>'agents' <> '' GROUP BY device_id
), computer_facts AS MATERIALIZED (
    SELECT cell.device_id,
           coalesce(bool_or(cell.source_status IS NOT NULL), false) AS has_presence,
           coalesce(bool_or(cell.source_status IS NOT NULL OR cell.requirement_status IS NOT NULL)
               FILTER (WHERE value->'any_states' = '[]'::jsonb
                       OR value->'any_states' ? cell.source_status
                       OR value->'any_states' ? cell.requirement_status), false) AS matches_any,
           coalesce(bool_or(cell.requirement_status IS NOT NULL)
               FILTER (WHERE (value->'platforms' = '[]'::jsonb OR value->'platforms' ? cell.platform)
                         AND (value->'states' = '[]'::jsonb
                              OR value->'states' ? cell.requirement_status)), false) AS matches_requirement,
           coalesce(bool_or(cell.status IN ('Online', 'Offline', 'Stale', 'No status'))
               FILTER (WHERE cell.platform IN (
                   SELECT name FROM operations.agents WHERE entity_type LIKE 'agent.%%'
               )), false) AS has_product,
           coalesce(bool_or(cell.status = 'Online') FILTER (WHERE cell.platform IN (
               SELECT name FROM operations.agents WHERE entity_type LIKE 'agent.%%'
           )), false) AS product_online,
           coalesce(bool_or(cell.status = 'Offline') FILTER (WHERE cell.platform IN (
               SELECT name FROM operations.agents WHERE entity_type LIKE 'agent.%%'
           )), false) AS product_offline,
           coalesce(bool_or(cell.status IN ('Online', 'Offline', 'Stale', 'No status')), false) AS has_current,
           coalesce(bool_or(cell.requirement_status = 'Missing'), false) AS missing,
           coalesce(bool_or(cell.requirement_status = 'Stale'), false) AS stale
    FROM record_statuses cell CROSS JOIN hudu_options
    GROUP BY cell.device_id
), requirement_counts AS (
    SELECT cell.platform,
           bool_or(cell.rule_status IN ('Required', 'Missing', 'Stale', 'Exempt')) AS has_requirements,
           count(*) FILTER (WHERE cell.rule_status = 'Missing' AND computer.online) AS online,
           count(*) FILTER (WHERE cell.rule_status = 'Missing' AND NOT computer.online
               AND computer.last_contact_at >= %s - make_interval(days => computer.offline_days)) AS offline,
           count(*) FILTER (WHERE cell.rule_status = 'Missing' AND NOT computer.online
               AND (computer.last_contact_at IS NULL
                    OR computer.last_contact_at < %s - make_interval(days => computer.offline_days))) AS stale
    FROM record_statuses cell JOIN computers computer ON computer.id = cell.device_id
    GROUP BY cell.platform
), agent_matches AS MATERIALIZED (
    SELECT cell.device_id
    FROM record_statuses cell CROSS JOIN hudu_options
    JOIN LATERAL jsonb_array_elements(value->'conditions') WITH ORDINALITY
        AS demand(condition, sequence) ON cell.platform = condition->>'agent'
    WHERE (condition->'states' = '[]'::jsonb OR condition->'states' ? cell.status)
      AND (condition->'requirements' = '[]'::jsonb
           OR condition->'requirements' ? cell.rule_status
           OR (condition->'requirements' ? 'Required'
               AND cell.rule_status IN ('Required', 'Missing', 'Stale')))
    GROUP BY cell.device_id, value
    HAVING count(DISTINCT sequence) = jsonb_array_length(value->'conditions')
), coverage_matches AS MATERIALIZED (
    SELECT cell.device_id
    FROM record_statuses cell CROSS JOIN hudu_options
    JOIN LATERAL jsonb_array_elements(value->'coverage') WITH ORDINALITY
        AS demand(condition, sequence) ON cell.platform = condition->>'agent'
    WHERE coalesce(cell.requirement_status, cell.source_status) IS NOT NULL
      AND (condition->'states' = '[]'::jsonb
           OR condition->'states' ? coalesce(cell.requirement_status, cell.source_status))
    GROUP BY cell.device_id, value
    HAVING count(DISTINCT sequence) = jsonb_array_length(value->'coverage')
), hudu_flags AS MATERIALIZED (
    SELECT computer.id, coalesce(hudu.current, 0) AS current,
           coalesce(hudu.archived, 0) AS archived,
           CASE value->>'record_filter'
               WHEN 'has_current' THEN coalesce(hudu.current, 0) > 0
               WHEN 'has_archived' THEN coalesce(hudu.archived, 0) > 0
               WHEN 'current_only' THEN coalesce(hudu.current, 0) > 0
                                        AND coalesce(hudu.archived, 0) = 0
               WHEN 'archived_only' THEN coalesce(hudu.archived, 0) > 0
                                         AND coalesce(hudu.current, 0) = 0
               WHEN 'both' THEN coalesce(hudu.current, 0) > 0 AND coalesce(hudu.archived, 0) > 0
               ELSE coalesce(hudu.current, 0) + coalesce(hudu.archived, 0) > 0
           END AS matches_record,
           CASE WHEN NOT (value->'scope' ? 'in_hudu')
                     OR value->>'record_filter' IN ('any', 'both')
                THEN coalesce(hudu.current_links, false) OR coalesce(hudu.archived_links, false)
                WHEN value->>'record_filter' IN ('has_current', 'current_only')
                THEN coalesce(hudu.current_links, false)
                ELSE coalesce(hudu.archived_links, false)
           END AS matching_links
    FROM computers computer LEFT JOIN hudu ON hudu.device_id = computer.id
    CROSS JOIN hudu_options
), filtered AS MATERIALIZED (
    SELECT computer.*,
           coalesce(hudu.current, 0) AS hudu_current,
           coalesce(hudu.archived, 0) AS hudu_archived
    FROM computers computer JOIN hudu_flags hudu ON hudu.id = computer.id
    LEFT JOIN computer_facts facts ON facts.device_id = computer.id
    LEFT JOIN source_text AS source_search(device_id, search_text)
      ON source_search.device_id = computer.id
    CROSS JOIN hudu_options
    WHERE (%s::text[] = '{}' OR computer.slug = ANY(%s::text[]))
      AND (%s = '' OR position(%s in lower(computer.hostname)) > 0)
      AND (%s::text[] = '{}' OR computer.os_family = ANY(%s::text[]))
      AND (%s::text[] = '{}' OR computer.device_type = ANY(%s::text[]))
      AND (%s::text[] = '{}' OR computer.device_role = ANY(%s::text[]))
      AND (value->>'agents' = '' OR position(value->>'agents' in source_search.search_text)>0)
      AND (NOT (value->>'no_platform')::boolean OR NOT coalesce(facts.has_presence, false))
      AND (NOT (value->>'any_platform')::boolean OR coalesce(facts.matches_any, false))
      AND ((value->'platforms' = '[]'::jsonb AND value->'states' = '[]'::jsonb)
           OR coalesce(facts.matches_requirement, false))
      AND (value->'computer_scope' = '[]'::jsonb OR value->'computer_scope' ?| ARRAY[
           CASE WHEN coalesce(facts.has_product, false) THEN 'has_product_record'
                ELSE 'no_product_records' END,
           CASE WHEN facts.product_online THEN 'any_online' END,
           CASE WHEN facts.product_offline THEN 'any_offline' END,
           CASE WHEN NOT coalesce(facts.has_current, false) AND hudu.current = 0
                THEN 'no_current_records' END,
           CASE WHEN facts.missing THEN 'missing_required' END,
           CASE WHEN facts.stale THEN 'stale_required' END,
           CASE WHEN computer.online THEN 'online_anywhere'
                WHEN computer.last_contact_at >= %s - make_interval(days => computer.offline_days)
                THEN 'offline_recent' ELSE 'not_reporting' END])
      AND (value->'scope' = '[]'::jsonb OR value->'scope' ?
           CASE WHEN hudu.current + hudu.archived > 0 THEN 'in_hudu' ELSE 'not_in_hudu' END)
      AND (NOT (value->'scope' ? 'in_hudu') OR hudu.matches_record)
      AND (value->'links' = '[]'::jsonb OR (hudu.matches_record AND value->'links' ?
           CASE WHEN hudu.matching_links THEN 'has_links' ELSE 'no_links' END))
      AND (value->'exemptions' = '[]'::jsonb OR value->'exemptions' ?
           CASE WHEN computer.s1_exempt THEN 'exempt' ELSE 'not_exempt' END)
      AND (jsonb_array_length(value->'conditions') = 0
           OR computer.id IN (SELECT device_id FROM agent_matches))
      AND (jsonb_array_length(value->'coverage') = 0
           OR computer.id IN (SELECT device_id FROM coverage_matches))
), pagination AS (
    SELECT CASE WHEN %s::bigint < 1 THEN greatest(1, (count(*) + 99) / 100)
                ELSE least(%s::bigint, greatest(1, (count(*) + 99) / 100)) END AS page
    FROM filtered
)
SELECT (SELECT count(*) FROM computers) AS computer_total,
       count(*) AS filtered_total,
       count(DISTINCT client_id) AS filtered_clients,
       count(*) FILTER (WHERE hudu_current + hudu_archived > 0) AS filtered_in_hudu,
       (SELECT count(*) FROM computers
        WHERE online OR last_contact_at >= %s - make_interval(days => offline_days)) AS recent,
       ARRAY(SELECT id FROM filtered ORDER BY display_name, sort_hostname, id
             LIMIT 100 OFFSET (SELECT (page - 1) * 100 FROM pagination)) AS page_ids,
       (SELECT jsonb_agg(jsonb_build_array(platform, status, total)) FROM record_counts)
           AS platform_record_counts,
       (SELECT jsonb_build_object(
           'Current only', count(*) FILTER (WHERE current > 0 AND archived = 0),
           'Current + archived', count(*) FILTER (WHERE current > 0 AND archived > 0),
           'Archived only', count(*) FILTER (WHERE current = 0 AND archived > 0),
           'No record', count(*) FILTER (WHERE current + archived = 0))
        FROM hudu_flags) AS hudu_categories,
       (SELECT jsonb_agg(jsonb_build_array(platform, has_requirements, online, offline, stale))
        FROM requirement_counts) AS platform_requirement_counts,
       (SELECT page FROM pagination) AS page,
       (SELECT jsonb_build_object(
           'online_anywhere', count(*) FILTER (WHERE online),
           'offline_recent', count(*) FILTER (WHERE NOT online AND last_contact_at >= %s - make_interval(days => offline_days)),
           'not_reporting', count(*) FILTER (WHERE NOT online AND (last_contact_at IS NULL OR last_contact_at < %s - make_interval(days => offline_days))))
        FROM computers) AS reporting_counts
FROM filtered
"""


def default_selection(
    *,
    tenant_id,
    active_device_days,
    now,
    client=(),
    device="",
    os_family=(),
    device_type=(),
    device_role=(),
    page=1,
    hudu=(),
    hudu_record_filter="any",
    hudu_links=(),
    agent_conditions=(),
    coverage_conditions=(),
    s1_exemption=(),
    platform=(),
    state=(),
    any_platform=False,
    any_platform_status=(),
    no_platform=False,
    computer_scope=(),
    agents="",
    _maintained=False,
    _all_ids=False,
):
    """Isolated selector; condition inputs must use the legacy view's normalization.

    Full parity and persistent maintenance validation remain incomplete.
    The serving view must not enable this reader yet.
    """
    params = [
        active_device_days,
        tenant_id,
        tenant_id,
        tenant_id,
        tenant_id,
        tenant_id,
        tenant_id,
        now,
    ]
    if hudu_record_filter not in {
        "any",
        "has_current",
        "has_archived",
        "current_only",
        "archived_only",
        "both",
    }:
        hudu_record_filter = "any"
    params.append(
        json.dumps(
            {
                "scope": [v for v in hudu if v in {"in_hudu", "not_in_hudu"}],
                "record_filter": hudu_record_filter,
                "links": [v for v in hudu_links if v in {"has_links", "no_links"}],
                "conditions": list(agent_conditions),
                "coverage": list(coverage_conditions),
                "exemptions": [v for v in s1_exemption if v in {"exempt", "not_exempt"}],
                "platforms": list(platform),
                "states": list(state),
                "any_platform": bool(any_platform or any_platform_status),
                "any_states": list(any_platform_status),
                "no_platform": bool(no_platform),
                "computer_scope": list(computer_scope),
                "agents": agents.strip().lower(),
                "now": now.isoformat(),
            }
        )
    )
    params.extend((now, now))
    for values in (list(client),):
        params.extend((values, values))
    params.extend((device.strip().lower(), device.strip().lower()))
    for values in (list(os_family), list(device_type), list(device_role)):
        params.extend((values, values))
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 1
    # Bound arbitrary request integers to PostgreSQL bigint; both bounds retain
    # Django's first/last-page behavior without overflowing the adapter.
    page = min(max(page, -(2**63)), 2**63 - 1)
    params.extend((now, page, page, now, now, now))
    with connection.cursor() as cursor:
        sql = DEFAULT_SELECTION_SQL
        if _all_ids:
            sql = sql.replace("LIMIT 100 OFFSET (SELECT (page - 1) * 100 FROM pagination)", "")
        if _maintained:
            sql = (
                MAINTAINED_INPUT_SQL
                + ", record_counts AS ("
                + sql.split(", record_counts AS (", 1)[1]
            )
            sql = sql.removesuffix("FROM filtered\n") + (
                ", (SELECT availability FROM publication_state) AS availability\nFROM filtered\n"
            )
            params = [active_device_days, tenant_id, *params[8:]]
        cursor.execute(sql, params)
        row = list(cursor.fetchone())
        for index in (6, 7, 8, 10):
            if isinstance(row[index], str):
                row[index] = json.loads(row[index])
        return tuple(row)


MAINTAINED_INPUT_SQL = """
WITH publication_state AS MATERIALIZED (
 SELECT CASE WHEN p.tenant_id IS NULL THEN 'missing'
             WHEN p.revision <> r.revision THEN 'input_changed'
             WHEN p.expires_at <= statement_timestamp() THEN 'expired'
             WHEN p.active_device_days <> %s THEN 'policy_changed'
             ELSE 'ready' END AS availability
 FROM operations.coverage_read_revision r
 LEFT JOIN operations.coverage_read_publication p USING (tenant_id)
 WHERE r.tenant_id = %s
), stored AS MATERIALIZED (
 SELECT current.* FROM operations.coverage_computer_read_current current
 WHERE current.tenant_id = operations.current_tenant_id()
 AND (SELECT availability FROM publication_state) = 'ready'
), computers AS MATERIALIZED (
 SELECT decoded.* FROM stored CROSS JOIN LATERAL jsonb_to_record(computer) AS decoded(
 id uuid, client_id uuid, slug text, display_name text, hostname text,
 sort_hostname text, os_family text, device_type text, device_role text,
 lifecycle_status text, online boolean, last_contact_at timestamptz,
 s1_exempt boolean, offline_days integer)
), hudu AS MATERIALIZED (
 SELECT decoded.* FROM stored CROSS JOIN LATERAL jsonb_to_record(hudu) AS decoded(
 device_id uuid, archived bigint, current bigint, current_links boolean, archived_links boolean)
 WHERE decoded.device_id IS NOT NULL
), record_statuses AS MATERIALIZED (
 SELECT cell.device_id, cell.platform, cell.source_contact_at, cell.requirement_status, cell.source_status,
        cell.rule_status, cell.status
 FROM operations.coverage_cell_read_current cell
 JOIN stored ON stored.device_id = cell.device_id AND stored.tenant_id = cell.tenant_id
)
""".strip()


def maintained_selection(**options):
    """Candidate read path; unavailable publication never becomes successful zeros."""
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('operations.tenant_id', %s, true)", [str(options["tenant_id"])]
        )
        # The maintained reader's materialized/JSON stages inflate row estimates;
        # measured JIT compilation consumed 6.64 of 7.20 seconds. This bounded
        # interactive read is cheaper to execute directly. Scope the setting to
        # this read and restore it for other work in the caller's transaction.
        # An exception rolls back this atomic block (including its settings).
        cursor.execute("SHOW jit")
        previous_jit = cursor.fetchone()[0]
        cursor.execute("SET LOCAL jit = off")
        result = default_selection(**options, _maintained=True)
        cursor.execute("SELECT set_config('jit', %s, true)", [previous_jit])
    availability = result[-1] or "missing"
    return {
        "availability": availability,
        "selection": result[:-1] if availability == "ready" else None,
    }
