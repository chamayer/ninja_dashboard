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
    issue_taxonomy: tuple[dict[str, Any], ...]
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
    taxonomy_value = data.get("issue_taxonomy")
    if taxonomy_value is None and isinstance(data.get("issue_categories"), list):
        # Read old immutable policies while the reviewed taxonomy version is
        # awaiting activation. The Issues projection supplies the packaged
        # taxonomy during this compatibility window.
        issue_taxonomy = ()
    else:
        issue_taxonomy = _issue_taxonomy(taxonomy_value, definitions)
    issue_type_aliases = _issue_type_aliases(data.get("issue_type_aliases", []), definitions)
    issue_categories = tuple(
        {
            "key": category["key"],
            "label": category["label"],
            "categories": (category["key"],),
            "types": frozenset(
                condition
                for item in category["types"]
                for condition in item["conditions"]
            ),
        }
        for category in issue_taxonomy
    )
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
        issue_taxonomy,
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
    return definitions


_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _issue_taxonomy(value, definitions) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("Issue taxonomy must be a nonempty list")
    categories, category_keys, category_labels, type_keys, type_labels, members = [], set(), set(), set(), set(), set()
    for category in value:
        if not isinstance(category, dict):
            raise ValueError("Invalid issue taxonomy category")
        key, label, types = category.get("key"), category.get("label"), category.get("types")
        if not isinstance(key, str) or not _KEY_RE.fullmatch(key) or key in category_keys:
            raise ValueError("Duplicate or invalid issue taxonomy category key")
        if not isinstance(label, str) or not label.strip() or not isinstance(types, list) or not types:
            raise ValueError("Invalid issue taxonomy category")
        if label in category_labels:
            raise ValueError("Duplicate issue taxonomy category label")
        category_keys.add(key)
        category_labels.add(label)
        parsed_types = []
        for type_item in types:
            if not isinstance(type_item, dict):
                raise ValueError("Invalid issue taxonomy type")
            type_key, type_label, conditions = (
                type_item.get("key"), type_item.get("label"), type_item.get("conditions")
            )
            if not isinstance(type_key, str) or not _KEY_RE.fullmatch(type_key) or type_key in type_keys:
                raise ValueError("Duplicate or invalid issue taxonomy type key")
            if not isinstance(type_label, str) or not type_label.strip() or not isinstance(conditions, list) or not conditions:
                raise ValueError("Invalid issue taxonomy type")
            if any(not isinstance(name, str) or name not in definitions for name in conditions):
                raise ValueError("Issue taxonomy references an unknown condition")
            if members.intersection(conditions):
                raise ValueError("Issue condition belongs to multiple taxonomy types")
            if type_label in type_labels:
                raise ValueError("Duplicate issue taxonomy type label")
            type_keys.add(type_key)
            type_labels.add(type_label)
            members.update(conditions)
            parsed_types.append({"key": type_key, "label": type_label, "conditions": tuple(conditions)})
        categories.append({"key": key, "label": label, "types": tuple(parsed_types)})
    if members != set(definitions):
        raise ValueError("Issue taxonomy must map every condition exactly once")
    return tuple(categories)


def _issue_type_aliases(value, definitions) -> tuple[dict[str, Any], ...]:
    """Validate legacy URL aliases without using them as taxonomy authority."""
    if not isinstance(value, list):
        raise ValueError("Issue type aliases must be a list")
    result = []
    keys = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Invalid issue type alias")
        key, label, types = item.get("key"), item.get("label"), item.get("types")
        if not isinstance(key, str) or not key or key in keys:
            raise ValueError("Duplicate or empty issue type alias key")
        if not isinstance(label, str) or not label:
            raise ValueError("Missing issue type alias label")
        if not isinstance(types, list) or not types or any(
            not isinstance(type_name, str) or type_name not in definitions for type_name in types
        ):
            raise ValueError("Invalid issue type alias members")
        keys.add(key)
        result.append({"key": key, "label": label, "types": tuple(types)})
    return tuple(result)
