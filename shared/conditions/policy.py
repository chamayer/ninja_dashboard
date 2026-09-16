"""Validated, data-driven shadow profile. No arbitrary policy expressions."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Profile:
    version: str
    digest: str
    definitions: dict[str, dict[str, Any]]
    rules: dict[str, dict[str, Any]]
    consumers: tuple[str, ...]
    offline_days: int
    freshness_hours: int
    identity_member_field: str
    identity_group_type: str
    issue_categories: tuple[dict[str, Any], ...]
    issue_type_aliases: tuple[dict[str, Any], ...]


def load_profile(path: Path | None = None) -> Profile:
    """Load the packaged shadow/bootstrap profile.

    Live callers must use ``parse_profile`` on the selected database policy.
    """
    source = path or Path(__file__).with_name("profile.json")
    return parse_profile(json.loads(source.read_text(encoding="utf-8")))


def parse_profile(data: dict) -> Profile:
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Unsupported or unversioned shadow profile")
    version = data.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("Unsupported or unversioned shadow profile")
    rules = data.get("rules")
    if not isinstance(rules, dict) or not rules:
        raise ValueError("A policy must define at least one rule")
    allowed_effects = {"gate", "suppress_attention"}
    for name, rule in rules.items():
        if not isinstance(name, str) or not _KEY_RE.fullmatch(name) or not isinstance(rule, dict):
            raise ValueError(f"Invalid rule: {name}")
        if rule.get("effect") not in allowed_effects or not rule.get("explanation"):
            raise ValueError(f"Invalid rule: {name}")
        requires = rule.get("requires", [])
        if not isinstance(requires, list) or any(not isinstance(parent, str) for parent in requires):
            raise ValueError(f"Invalid prerequisite list: {name}")
        if len(requires) != len(set(requires)) or set(requires) - rules.keys() or any(
            not _KEY_RE.fullmatch(parent) for parent in requires
        ):
            raise ValueError(f"Unknown prerequisite rule: {name}")
        participant_kind = rule.get("participant_kind")
        if participant_kind is not None and (
            not isinstance(participant_kind, str) or not _KEY_RE.fullmatch(participant_kind)
        ):
            raise ValueError(f"Invalid participant kind: {name}")
    visiting, visited = set(), set()

    def visit(name):
        if name in visiting:
            raise ValueError("Cyclic dependency policy")
        if name in visited:
            return
        visiting.add(name)
        for parent in rules[name].get("requires", []):
            visit(parent)
        visiting.remove(name)
        visited.add(name)

    for name in rules:
        visit(name)
    definitions = _definitions(data, rules)
    for key in ("offline_days", "freshness_hours"):
        if type(data.get(key)) is not int or data[key] <= 0:
            raise ValueError(f"{key} must be a positive integer")
    consumers_value = data.get("consumers")
    if not isinstance(consumers_value, list):
        raise ValueError("Consumers must be a list")
    consumers = tuple(consumers_value)
    if not consumers or len(consumers) != len(set(consumers)) or any(
        not isinstance(name, str) or not _KEY_RE.fullmatch(name) for name in consumers
    ):
        raise ValueError("Consumer names must be nonempty and unique")
    if (
        not isinstance(data.get("identity_group_type"), str)
        or data["identity_group_type"] not in definitions
        or not isinstance(data.get("identity_member_field"), str)
        or not _KEY_RE.fullmatch(data["identity_member_field"])
    ):
        raise ValueError("Invalid identity evidence mapping")
    issue_categories = _issue_categories(data.get("issue_categories"))
    issue_type_aliases = _issue_type_aliases(data.get("issue_type_aliases"))
    # Keep this representation identical to the migration/admin digest
    # contract. JSONB returns canonical key ordering, while the separators
    # remain the standard JSON separators used when policies are created.
    digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return Profile(
        version,
        digest,
        definitions,
        rules,
        consumers,
        data["offline_days"],
        data["freshness_hours"],
        data["identity_member_field"],
        data["identity_group_type"],
        issue_categories,
        issue_type_aliases,
    )


def _definitions(data, rules):
    definitions = {}
    definitions_value = data.get("definitions")
    if not isinstance(definitions_value, list) or not definitions_value:
        raise ValueError("A policy must define at least one condition")
    for definition in definitions_value:
        if not isinstance(definition, dict):
            raise ValueError("Invalid condition definition")
        name = definition.get("name")
        if not isinstance(name, str) or not _KEY_RE.fullmatch(name) or name in definitions:
            raise ValueError("Duplicate or empty condition definition")
        required_keys = ("category", "type", "label", "lifecycle", "rules")
        if any(not isinstance(definition.get(key), str) for key in required_keys[:3]):
            raise ValueError(f"Missing operator classification: {name}")
        definition_rules = definition.get("rules")
        if not isinstance(definition_rules, list) or any(
            not isinstance(rule, str) for rule in definition_rules
        ):
            raise ValueError(f"Invalid rule list: {name}")
        if len(definition_rules) != len(set(definition_rules)) or set(definition_rules) - rules.keys() or any(
            not _KEY_RE.fullmatch(rule) for rule in definition_rules
        ):
            raise ValueError(f"Unknown dependency for {name}")
        if definition["lifecycle"] not in {"active", "historical", "unverified", "disabled"}:
            raise ValueError(f"Invalid definition lifecycle: {name}")
        if not definition["category"].strip() or not definition["type"].strip() or not definition["label"].strip():
            raise ValueError(f"Missing operator classification: {name}")
        definitions[name] = definition
    aliases = data.get("issue_type_aliases")
    if isinstance(aliases, list):
        for alias in aliases:
            if isinstance(alias, dict) and isinstance(alias.get("types"), list):
                if set(alias["types"]) - definitions.keys():
                    raise ValueError("Issue type alias references an unknown condition")
    return definitions


_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _issue_categories(value) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("Issue categories must be a nonempty list")
    result = []
    keys = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Invalid issue category")
        key, label, categories = item.get("key"), item.get("label"), item.get("categories")
        if not isinstance(key, str) or not key or key in keys:
            raise ValueError("Duplicate or empty issue category key")
        if not isinstance(label, str) or not label:
            raise ValueError("Missing issue category label")
        if not isinstance(categories, list) or not categories or any(
            not isinstance(category, str) or not category for category in categories
        ):
            raise ValueError("Invalid issue category members")
        keys.add(key)
        result.append({"key": key, "label": label, "categories": tuple(categories)})
    return tuple(result)


def _issue_type_aliases(value) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        raise ValueError("Issue type aliases must be a list")
    result = []
    keys = set()
    members = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Invalid issue type alias")
        key, label, types = item.get("key"), item.get("label"), item.get("types")
        if not isinstance(key, str) or not key or key in keys:
            raise ValueError("Duplicate or empty issue type alias key")
        if not isinstance(label, str) or not label:
            raise ValueError("Missing issue type alias label")
        if not isinstance(types, list) or not types or any(
            not isinstance(type_name, str) or not type_name for type_name in types
        ):
            raise ValueError("Invalid issue type alias members")
        if members.intersection(types):
            raise ValueError("Issue type cannot belong to multiple aliases")
        keys.add(key)
        members.update(types)
        result.append({"key": key, "label": label, "types": tuple(types)})
    return tuple(result)
