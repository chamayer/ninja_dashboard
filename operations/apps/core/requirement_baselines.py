"""Requirement baselines as editable service rows (Requirements page).

A baseline is either the global requirements (client-less
``coverage_requirements``, used by clients with no profile) or one profile's
items. The evaluator uses a role-scoped baseline list *instead of* the
all-devices list. The view therefore makes an operator choose whether the
first rule for a role copies the all-devices list or intentionally replaces it.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

ALL_SCOPE = "all"
ROLE_SCOPES = ("server", "workstation")
VALID_SCOPES = (ALL_SCOPE, *ROLE_SCOPES)

# Columns copied when a new profile starts from an existing baseline.
COPIED_FIELDS = (
    "agent_id",
    "entity_type",
    "platform",
    "device_scope",
    "applicable_os_groups",
    "severity",
    "gap_after_hours",
    "confidence_probable",
    "confidence_confirmed",
)


def matches_agent(row: Any, agent: Any) -> bool:
    """True when a requirement row is for this service.

    Rows written before agents existed carry only the entity type and
    platform name, so those identify the service instead.
    """
    if row.agent_id is not None:
        return row.agent_id == agent.id
    return row.entity_type == agent.entity_type and row.platform == agent.name


def new_item_values(agent: Any) -> dict:
    """Values for a new all-devices requirement, using the service's defaults."""
    return {
        "agent_id": agent.id,
        "entity_type": agent.entity_type,
        "platform": agent.name,
        "device_scope": ALL_SCOPE,
        "severity": agent.default_severity,
        "gap_after_hours": agent.default_gap_after_hours,
        "confidence_probable": agent.default_confidence_probable,
        "confidence_confirmed": agent.default_confidence_confirmed,
    }


def baseline_rows(agents: Iterable[Any], required: Iterable[Any]) -> list[dict]:
    """One row per service for all devices, plus every existing scoped item.

    ``required`` holds the baseline's active rows: a profile's items, or the
    enabled global requirements.
    """
    agents = list(agents)
    rows: dict[tuple, dict] = {
        (agent.id, ALL_SCOPE): {
            "agent": agent,
            "name": agent.name,
            "entity_type": agent.entity_type,
            "scope": ALL_SCOPE,
            "item": None,
        }
        for agent in agents
    }
    for item in required:
        agent = next((a for a in agents if matches_agent(item, a)), None)
        identity = agent.id if agent else ("legacy", item.entity_type, item.platform)
        rows[(identity, item.device_scope)] = {
            "agent": agent,
            "name": agent.name if agent else (item.platform or item.entity_type),
            "entity_type": agent.entity_type if agent else item.entity_type,
            "scope": item.device_scope,
            "item": item,
        }
    result = [{**row, "required": row["item"] is not None} for row in rows.values()]
    return sorted(
        result,
        key=lambda row: (row["name"].lower(), row["scope"] != ALL_SCOPE, row["scope"]),
    )
