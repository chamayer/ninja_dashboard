"""One name, one category and one group for every finding type.

All of it lives on ``finding_types`` (the registry). This module is the only
reader: the Issues taxonomy, the display name used on every screen, and the
parents that cover a finding are built from that one table.
"""

from __future__ import annotations

import re
import time
from typing import Any

# The five categories. Their labels are data (``finding_types.issue_category``);
# these names exist so code that needs "all patching findings" says so once.
INVENTORY = "Inventory"
AGENTS = "Agents & reporting"
SOFTWARE = "Software & security"
PATCHING = "Patching & support"
COLLECTION = "Data collection"

_NAME_CACHE_SECONDS = 60
_names: dict[str, str] = {}
_loaded_at = 0.0


def slug(label: str) -> str:
    """URL key for a category or group label: 'Agents & reporting' -> 'agents_reporting'."""
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def invalidate() -> None:
    """Forget cached names; call after the registry changes."""
    global _loaded_at
    _loaded_at = 0.0


def _load_names() -> dict[str, str]:
    global _names, _loaded_at
    from .models import FindingType

    if time.monotonic() - _loaded_at > _NAME_CACHE_SECONDS or not _names:
        _names = dict(FindingType.objects.values_list("name", "display_name"))
        _loaded_at = time.monotonic()
    return _names


def finding_type_name(type_name: str) -> str:
    """The one display name for a finding type; the code name only for an unknown type."""
    return _load_names().get(type_name, type_name)


def build_taxonomy() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Categories and groups for the Issues page, in the shape the page reads.

    Order follows ``sort_order``: a category or group appears where its first type does.
    """
    from .models import FindingType

    rows = list(
        FindingType.objects.order_by("sort_order", "name").values(
            "name", "display_name", "issue_category", "issue_group"
        )
    )
    categories: dict[str, dict[str, Any]] = {}
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        category_key = slug(row["issue_category"])
        category = categories.setdefault(
            category_key,
            {
                "key": category_key,
                "label": row["issue_category"],
                "categories": {category_key, row["issue_category"]},
                "types": set(),
            },
        )
        category["types"].add(row["name"])
        group_key = slug(row["issue_group"])
        group = groups.setdefault(
            group_key,
            {
                "value": group_key,
                "label": row["issue_group"],
                "types": set(),
                "issues": [],
                "legacy_types": set(),
                "category": category_key,
            },
        )
        group["types"].add(row["name"])
        group["issues"].append({"value": row["name"], "label": row["display_name"]})
    for group in groups.values():
        group["issues"] = tuple(group["issues"])
    return list(categories.values()), groups


def registry_problems(rows: list[dict[str, Any]]) -> list[str]:
    """Everything wrong with a set of registry rows (empty when it is sound).

    Used by the Finding types page before it saves and by the tests.
    """
    problems: list[str] = []
    names = {row["name"] for row in rows}
    display: dict[str, str] = {}
    group_category: dict[str, str] = {}
    for row in rows:
        name = row["name"]
        if not row["display_name"].strip():
            problems.append(f"{name} has no display name.")
        elif row["display_name"] in display:
            problems.append(f"{name} and {display[row['display_name']]} share the name {row['display_name']!r}.")
        display[row["display_name"]] = name
        if not row["issue_category"].strip() or not row["issue_group"].strip():
            problems.append(f"{name} needs a category and a group.")
        owner = group_category.setdefault(row["issue_group"], row["issue_category"])
        if owner != row["issue_category"]:
            problems.append(f"Group {row['issue_group']!r} is in two categories.")
        for parent in row["covered_by"]:
            if parent not in names:
                problems.append(f"{name} is covered by unknown type {parent}.")
            if parent == name:
                problems.append(f"{name} cannot cover itself.")
    parents = {row["name"]: list(row["covered_by"]) for row in rows}

    def reaches(start: str, target: str) -> bool:
        stack, seen = [start], set()
        while stack:
            node = stack.pop()
            if node == target:
                return True
            if node in seen:
                continue
            seen.add(node)
            stack.extend(parents.get(node, []))
        return False

    for row in rows:
        for parent in row["covered_by"]:
            if parent in parents and reaches(parent, row["name"]):
                problems.append(f"{row['name']} and {parent} would cover each other.")
    return problems
