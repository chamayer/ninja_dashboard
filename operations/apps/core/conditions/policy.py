"""Validated, data-driven shadow profile. No arbitrary policy expressions."""

from __future__ import annotations

import hashlib
import json
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


def load_profile(path: Path | None = None) -> Profile:
    source = path or Path(__file__).with_name("profile.json")
    return parse_profile(json.loads(source.read_text(encoding="utf-8")))


def parse_profile(data: dict) -> Profile:
    if data.get("schema_version") != 1 or not data.get("version"):
        raise ValueError("Unsupported or unversioned shadow profile")
    rules = data["rules"]
    allowed_effects = {"gate", "suppress_attention"}
    for name, rule in rules.items():
        if rule.get("effect") not in allowed_effects or not rule.get("explanation"):
            raise ValueError(f"Invalid rule: {name}")
        if set(rule.get("requires", [])) - rules.keys():
            raise ValueError(f"Unknown prerequisite rule: {name}")
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
        if type(data[key]) is not int or data[key] <= 0:
            raise ValueError(f"{key} must be a positive integer")
    consumers = tuple(data["consumers"])
    if not consumers or len(consumers) != len(set(consumers)):
        raise ValueError("Consumer names must be nonempty and unique")
    if data["identity_group_type"] not in definitions or not data["identity_member_field"]:
        raise ValueError("Invalid identity evidence mapping")
    digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return Profile(
        data["version"],
        digest,
        definitions,
        rules,
        consumers,
        data["offline_days"],
        data["freshness_hours"],
        data["identity_member_field"],
        data["identity_group_type"],
    )


def _definitions(data, rules):
    definitions = {}
    for definition in data["definitions"]:
        name = definition["name"]
        if not name or name in definitions:
            raise ValueError("Duplicate or empty condition definition")
        if set(definition["rules"]) - rules.keys():
            raise ValueError(f"Unknown dependency for {name}")
        if definition["lifecycle"] not in {"active", "historical", "unverified", "disabled"}:
            raise ValueError(f"Invalid definition lifecycle: {name}")
        if not definition["category"] or not definition["label"]:
            raise ValueError(f"Missing operator classification: {name}")
        definitions[name] = definition
    return definitions
