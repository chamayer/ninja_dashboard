"""Compact overview reader prepared for the separately approved cutover."""

import json
import logging

from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, connection, transaction
from django.utils.dateparse import parse_datetime

log = logging.getLogger(__name__)

_MESSAGES = {
    "restricted_scope": "A tenant-wide Software summary is unavailable in client context.",
    "missing": "The Software summary has not been published yet.",
    "uncertified": "The Software summary is awaiting verification.",
    "unverifiable": "The Software summary cannot be verified.",
    "publication_failed": "The latest Software summary refresh did not complete successfully.",
    "publication_pending": "The Software summary refresh is still completing.",
    "input_changed": "Software inputs changed. Summary values are pending refresh.",
    "expired": "The retained Software summary has expired. Values are awaiting refresh.",
    "input_failed": "A required Software input refresh did not complete successfully.",
    "read_failed": "The Software summary is temporarily unavailable.",
    "completed": "The completed Software summary is shown below.",
}


def _context(payload: dict) -> dict:
    state = payload["state"]
    reason = payload["reason"]
    if state not in {"current", "pending", "stale", "unavailable"} or reason not in _MESSAGES:
        raise ValueError("Unrecognized Software publication state")
    publication = {"state": state, "reason": reason, "message": _MESSAGES[reason]}
    for key in (
        "computed_at",
        "published_at",
        "inventory_observed_at",
        "oldest_input_completed_at",
    ):
        value = payload.get(key)
        publication[key] = parse_datetime(value) if value else None
    context = {"overview_publication": publication}
    if state != "current":
        return context
    data = payload["data"]
    for key in (
        "installations",
        "unique_titles",
        "categorized_titles",
        "uncategorized_titles",
        "approved_titles",
        "rejected_titles",
        "investigate_titles",
        "pending_decisions",
        "software_issues",
        "whitelist_suggestions",
    ):
        context[key] = data[key]
    context["risk_distribution"] = {
        band: data[f"risk_{band}"] for band in ("high", "medium", "low", "clean", "unknown")
    }
    context["high_risk_titles"] = data["risk_high"]
    context["workflow_state"] = {
        "publishers_undecided": data["publishers_undecided"],
        "tech_checklist_devices": data["tech_checklist_devices"],
    }
    context["this_week"] = {
        "new_products": data["new_products"],
        "new_high_risk": data["new_high_risk"],
        "top_new_product": {
            "name": data["top_new_name"],
            "display_name": data["top_new_display_name"],
            "devices": data["top_new_devices"],
        }
        if data["top_new_name"] is not None
        else None,
    }
    return context


def read_overview(request) -> dict:
    """Read one protected result; never rebuild or fall back to live aggregates."""
    user = request.user
    if (
        not user.is_authenticated
        or not user.is_active
        or getattr(request, "tenant_id", None) != 1
        or user.tenant_id != 1
        or not user.has_perm("operations.view_software")
    ):
        raise PermissionDenied
    if getattr(request, "org_mode", None) == "client" or getattr(request, "current_client", None):
        return _context({"state": "unavailable", "reason": "restricted_scope"})
    try:
        # A savepoint keeps a missing function/read failure from aborting the
        # outer tenant request transaction before the unavailable page renders.
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SELECT operations.read_software_overview(%s, NULL)", [1])
            payload = cur.fetchone()[0]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return _context(payload)
    except (DatabaseError, KeyError, TypeError, ValueError):
        log.exception("Software overview protected read failed")
        return _context({"state": "unavailable", "reason": "read_failed"})
