"""Client domains: learned from computers, edited by operators (ADR-0042).

A domain is *learned* for a client when at least ``min_computers`` of its live
Computers have a current record reporting it, ignoring the values in
``ignored`` (both from ``evaluator_config`` row ``client_domains``). Learned
domains are computed when read; nothing stores them. An operator adds a
domain or removes a learned one as an attribute decision on
``client.domains``; a removal keeps a learned domain out until restored.
"""

from __future__ import annotations

import re
from collections import defaultdict

from django.db import connection, transaction

from .attribute_decisions import (
    DecisionMemberInput,
    deactivate_attribute_decision,
    set_attribute_decision,
)
from .models import (
    AttributeDefinition,
    Client,
    EntityAttributeDecisionCurrent,
    EntityAttributeDecisionMemberCurrent,
    EvaluatorConfig,
)

DEFAULTS = {"min_computers": 2, "ignored": ["", "workgroup", "local", "localdomain"]}
_DOMAIN = re.compile(
    r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$"
)

_LEARNED_SQL = """
SELECT d.client_id::text, lower(trim(trailing '.' FROM btrim(eo.canonical_data ->> 'domain'))),
       count(DISTINCT d.id)::int
  FROM operations.entity_observation_current eo
  JOIN operations.devices d ON d.id = eo.device_id AND d.deleted_at IS NULL
   AND d.lifecycle_status <> 'retired'
 WHERE eo.tenant_id = 1 AND eo.active
   AND COALESCE(btrim(eo.canonical_data ->> 'domain'), '') <> ''
   AND d.client_id::text = ANY(%s)
 GROUP BY 1, 2
"""


def normalize(value: str) -> str:
    return (value or "").strip().strip(".").lower()


def is_valid(value: str) -> bool:
    return bool(_DOMAIN.match(normalize(value)))


def settings() -> dict:
    row = EvaluatorConfig.objects.filter(tenant_id=1, evaluator_name="client_domains").first()
    merged = {**DEFAULTS, **((row.config or {}) if row else {})}
    merged["ignored"] = {normalize(value) for value in merged.get("ignored") or []}
    return merged


def definition() -> AttributeDefinition | None:
    return AttributeDefinition.objects.filter(
        entity_class_id="client", key="domains", enabled=True
    ).first()


def learned(client_ids: list[str]) -> dict[str, dict[str, int]]:
    """Per client: each learned domain and how many live Computers report it."""
    if not client_ids:
        return {}
    config = settings()
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(_LEARNED_SQL, [list(client_ids)])
        rows = cur.fetchall()
    result: dict[str, dict[str, int]] = defaultdict(dict)
    for client_id, domain, computers in rows:
        if domain in config["ignored"] or computers < int(config["min_computers"]):
            continue
        result[client_id][domain] = computers
    return result


def _decided(clients: list[Client], definition_row) -> dict[str, dict[str, str]]:
    """Per client: each domain an operator added or removed."""
    if definition_row is None:
        return {}
    members = EntityAttributeDecisionMemberCurrent.objects.filter(
        decision__tenant_id=1,
        decision__attribute_definition=definition_row,
        decision__active=True,
        decision__entity_id__in=[client.entity_id for client in clients],
    ).values_list("decision__entity_id", "action", "value_text")
    entity_to_client = {client.entity_id: str(client.id) for client in clients}
    result: dict[str, dict[str, str]] = defaultdict(dict)
    for entity_id, action, value in members:
        result[entity_to_client[entity_id]][normalize(value)] = action
    return result


def domains_for(clients: list[Client]) -> dict[str, list[dict]]:
    """Per client: its domains, each learned (with a count) and/or added, or removed."""
    learned_by_client = learned([str(client.id) for client in clients])
    decided_by_client = _decided(clients, definition())
    result = {}
    for client in clients:
        key = str(client.id)
        found = learned_by_client.get(key, {})
        decided = decided_by_client.get(key, {})
        rows = []
        for domain in sorted(set(found) | set(decided)):
            action = decided.get(domain)
            rows.append(
                {
                    "domain": domain,
                    "computers": found.get(domain, 0),
                    "added": action == EntityAttributeDecisionMemberCurrent.Action.ADD,
                    "removed": action == EntityAttributeDecisionMemberCurrent.Action.REMOVE,
                }
            )
        result[key] = rows
    return result


def edit(*, actor, client: Client, domain: str, action: str, reason: str) -> None:
    """Add a domain, remove one, or restore (drop the operator's edit).

    A decision replaces the client's current one, so it carries every edit.
    """
    domain = normalize(domain)
    if not is_valid(domain):
        raise ValueError("Enter a domain such as example.local.")
    definition_row = definition()
    if definition_row is None:
        raise ValueError("Client domains are not available yet.")
    edits = dict(_decided([client], definition_row).get(str(client.id), {}))
    if action == "restore":
        edits.pop(domain, None)
    elif action in ("add", "remove"):
        edits[domain] = action
    else:
        raise ValueError("Unknown domain action.")
    if not edits:
        if EntityAttributeDecisionCurrent.objects.filter(
            tenant_id=1,
            entity_id=client.entity_id,
            attribute_definition=definition_row,
            active=True,
        ).exists():
            deactivate_attribute_decision(
                actor=actor,
                entity=client.entity,
                attribute_definition=definition_row,
                reason=reason,
            )
        return
    set_attribute_decision(
        actor=actor,
        entity=client.entity,
        attribute_definition=definition_row,
        operation=EntityAttributeDecisionCurrent.Operation.MODIFY,
        reason=reason,
        members=tuple(DecisionMemberInput(action=a, value=d) for d, a in sorted(edits.items())),
    )
