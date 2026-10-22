"""Which software installations a decision covers (ADR-0039).

A decision covers an installation when that installation's own effective
decision approves it: title before publisher, device before client before
global (migration 113, ``v_software_decision_keys``). A publisher decision
matches the installation's own publisher string, so an installation with a
blank or different publisher never inherits a publisher approval; the string
is set by the installer.

An undecided-software prompt describes only the installations no decision
covers. Its details carry those counts (``uncovered_*``) beside the title's
whole-fleet counts, and every reader shows the uncovered ones.
"""

from __future__ import annotations

from typing import Any

APPROVED = ("approve", "approve_publisher")

# Effective decision per installation; ``i`` is the installation alias.
EFFECTIVE_DECISION_JOINS = """
  LEFT JOIN operations.v_software_decision_keys title_device
    ON title_device.tenant_id = i.tenant_id AND title_device.match_kind = 'title'
   AND title_device.scope = 'device' AND title_device.device_id = i.device_id
   AND title_device.match_key = lower(i.canonical_name)
  LEFT JOIN operations.v_software_decision_keys title_client
    ON title_client.tenant_id = i.tenant_id AND title_client.match_kind = 'title'
   AND title_client.scope = 'client' AND title_client.client_id = i.client_id
   AND title_client.match_key = lower(i.canonical_name)
  LEFT JOIN operations.v_software_decision_keys title_global
    ON title_global.tenant_id = i.tenant_id AND title_global.match_kind = 'title'
   AND title_global.scope = 'global' AND title_global.match_key = lower(i.canonical_name)
  LEFT JOIN operations.v_software_decision_keys publisher_device
    ON publisher_device.tenant_id = i.tenant_id AND publisher_device.match_kind = 'publisher'
   AND publisher_device.scope = 'device' AND publisher_device.device_id = i.device_id
   AND publisher_device.match_key = lower(i.publisher)
  LEFT JOIN operations.v_software_decision_keys publisher_client
    ON publisher_client.tenant_id = i.tenant_id AND publisher_client.match_kind = 'publisher'
   AND publisher_client.scope = 'client' AND publisher_client.client_id = i.client_id
   AND publisher_client.match_key = lower(i.publisher)
  LEFT JOIN operations.v_software_decision_keys publisher_global
    ON publisher_global.tenant_id = i.tenant_id AND publisher_global.match_kind = 'publisher'
   AND publisher_global.scope = 'global' AND publisher_global.match_key = lower(i.publisher)
"""
TITLE_DECISION = (
    "COALESCE(title_device.decision, title_client.decision, title_global.decision)"
)
PUBLISHER_DECISION = "COALESCE(publisher_device.decision, publisher_client.decision, publisher_global.decision)"

# No decision of any kind reaches the installation.
UNDECIDED = f"({TITLE_DECISION} IS NULL AND {PUBLISHER_DECISION} IS NULL)"
# No title decision; at most a publisher approval. A publisher approval does not
# answer a rare title that carries another concern (design D9).
TITLE_OPEN = f"({TITLE_DECISION} IS NULL AND ({PUBLISHER_DECISION} IS NULL OR {PUBLISHER_DECISION} IN {APPROVED}))"

# Which installations an open prompt is about, recorded on the prompt.
SCOPE_UNDECIDED = "undecided"
SCOPE_TITLE_OPEN = "title_open"

# Prompt details written before ADR-0039 carry only fleet counts.
PROMPT_DEVICES_SQL = "COALESCE(finding_details->>'uncovered_device_count', finding_details->>'fleet_device_count')"
PROMPT_CLIENTS_SQL = "COALESCE(finding_details->>'uncovered_client_count', finding_details->>'client_count')"


def prompt_devices(details: dict[str, Any]) -> int | None:
    """Computers a prompt is about: the uncovered ones."""
    value = details.get("uncovered_device_count", details.get("fleet_device_count"))
    return None if value is None else int(value)


def prompt_clients(details: dict[str, Any]) -> int:
    value = details.get("uncovered_client_count", details.get("client_count"))
    return int(value or 0)


def prompt_scope_filter(scope: str) -> str:
    """SQL predicate selecting the installations a prompt of ``scope`` is about."""
    return TITLE_OPEN if scope == SCOPE_TITLE_OPEN else UNDECIDED
