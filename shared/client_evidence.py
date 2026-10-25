"""Which existing client a new source group's computers point to (ADR-0041).

One rule for the candidate page and the resolver's automatic promotion. The
evidence is computer names: a record in the group that is not yet matched to a
Computer still reports a name, and a name counts only when exactly one client
owns a current Computer with it. Names many clients use (default names,
images) say nothing about ownership.

A source keeps two clients separate when it reports each as its own group;
shared computers then point to a misfiled group, not to the same client
(e.g. NYCD Management and City Painting in Hudu, Ninja and SentinelOne).

Every function takes a cursor whose transaction has ``operations.tenant_id``
set.
"""

from __future__ import annotations

from typing import Any

_NAME_OWNERS_SQL = """
WITH live_groups AS (
    SELECT * FROM unnest(%s::int[], %s::int[], %s::text[])
        AS g(row_index, source_id, external_id)
), unlinked AS (
    SELECT DISTINCT g.row_index, si.source_id, observation.entity_key,
           lower(observation.reported_name) AS name
      FROM operations.v_entity_observation_admin_metadata observation
      JOIN operations.source_instances si ON si.id = observation.source_instance_id
      JOIN live_groups g
        ON g.source_id = si.source_id AND g.external_id = observation.platform_group_id
     WHERE observation.entity_type <> 'org' AND observation.active
       AND observation.device_id IS NULL
       AND COALESCE(observation.reported_name, '') <> ''
), single_owner AS (
    SELECT lower(device.canonical_hostname) AS name, min(device.client_id::text) AS client_id
      FROM operations.devices device
     WHERE device.tenant_id = 1 AND device.deleted_at IS NULL
       AND device.lifecycle_status <> 'retired' AND device.client_id IS NOT NULL
       AND COALESCE(device.canonical_hostname, '') <> ''
     GROUP BY 1
    HAVING count(DISTINCT device.client_id) = 1
), named AS (
    SELECT row_index, count(*)::int AS named FROM unlinked GROUP BY 1
)
SELECT named.row_index, named.named, client.id::text, client.display_name,
       count(unlinked.entity_key)::int AS records
  FROM named
  LEFT JOIN unlinked ON unlinked.row_index = named.row_index
  LEFT JOIN single_owner ON single_owner.name = unlinked.name
  LEFT JOIN operations.clients client
    ON client.id::text = single_owner.client_id AND client.deleted_at IS NULL
 GROUP BY 1, 2, 3, 4
 ORDER BY 1, 5 DESC, 4
"""


def name_owners(cur: Any, live_by_row: dict[int, list[tuple[int, str]]]) -> dict[int, tuple]:
    """Per row: the clients owning its groups' unlinked computer names, largest first.

    ``live_by_row`` maps a row to its live ``(source_id, external_id)`` groups.
    Returns ``(matches, named)`` per row, where each match is
    ``{"client_id", "display_name", "record_count"}`` and ``named`` is how many
    unlinked records report a name.
    """
    groups = [(row, key[0], key[1]) for row, keys in live_by_row.items() for key in keys]
    result: dict[int, tuple] = {row: ([], 0) for row in live_by_row}
    if not groups:
        return result
    cur.execute(
        _NAME_OWNERS_SQL,
        (
            [group[0] for group in groups],
            [group[1] for group in groups],
            [group[2] for group in groups],
        ),
    )
    for row_index, named, client_id, name, records in cur.fetchall():
        matches, _ = result[row_index]
        if client_id:
            matches.append({"client_id": client_id, "display_name": name, "record_count": records})
        result[row_index] = (matches, named)
    return result


def client_source_ids(cur: Any, client_ids: set[str]) -> dict[str, set[int]]:
    """Sources in which each client already has its own attached group."""
    if not client_ids:
        return {}
    cur.execute(
        """
        SELECT DISTINCT client_id::text, source_id
          FROM operations.v_client_source_mapping_effective
         WHERE tenant_id = 1 AND client_id::text = ANY(%s)
           AND mapping_state <> 'ignored'
        """,
        [sorted(client_ids)],
    )
    result: dict[str, set[int]] = {}
    for client_id, source_id in cur.fetchall():
        result.setdefault(client_id, set()).add(source_id)
    return result


def kept_separate(client_id: str, live, separate: dict[str, set[int]]) -> bool:
    """Whether a source of the new group already has its own group for this client."""
    return bool(separate.get(client_id, set()) & {key[0] for key in live})


def first_unseparated(options: list[dict], live, separate: dict[str, set[int]]):
    """The strongest suggested client no source of the new group keeps separate."""
    return next(
        (option for option in options if not kept_separate(option["client_id"], live, separate)),
        None,
    )
