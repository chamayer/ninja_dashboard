"""Pure, shared compilation for software classifier pattern rules."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from collections.abc import Callable, Iterable

log = logging.getLogger(__name__)


def compile_rules(
    rows: Iterable[tuple[str, str, bool]],
) -> dict[str, Callable[[str], bool]]:
    """Compile configured literal and regular-expression rules by type."""
    grouped: dict[str, list[tuple[str, bool]]] = defaultdict(list)
    for rule_type, pattern, is_regex in rows:
        grouped[rule_type].append((pattern, bool(is_regex)))

    def predicate(rules: list[tuple[str, bool]]) -> Callable[[str], bool]:
        compiled = []
        literals = []
        for pattern, is_regex in rules:
            if is_regex:
                try:
                    compiled.append(re.compile(pattern, re.IGNORECASE))
                except re.error:
                    log.warning(
                        "software_reconcile: invalid rule pattern skipped: %r", pattern
                    )
            else:
                literals.append(pattern.lower())

        def matches(text: str) -> bool:
            lowered = (text or "").lower()
            return any(rule.search(lowered) for rule in compiled) or any(
                literal in lowered for literal in literals if lowered
            )

        return matches

    return {rule_type: predicate(rules) for rule_type, rules in grouped.items()}


def never(_text: str) -> bool:
    """Default predicate for an absent optional rule."""
    return False
