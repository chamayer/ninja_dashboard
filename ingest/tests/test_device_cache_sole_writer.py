"""ADR-0012: only the projector writes the five device cache columns.

`operations.devices.os_name / os_family / os_group / device_role / device_type`
are derived from source evidence. An evidence producer -- connector, resolver,
evaluator, UI action -- must not write them; `ingest.device_cache_projector`
reads the effective attribute contract and owns them.

This is the enforcement mechanism for that rule. A privilege was considered and
rejected: the projector runs on the shared `ingest.db` pool as the ingest role,
so revoking UPDATE from that role would disable the projector along with the
producers. A revoke would only add protection against ad-hoc `psql` writes,
which self-heal on the next projection -- these are rebuildable cache columns
and the blast radius of a violation is one cycle.

The inventory this replaced was wrong three times, each time because it was
derived by reading rather than by searching. This test searches.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

CACHE_COLUMNS = ("os_name", "os_family", "os_group", "device_role", "device_type")

# The only module permitted to write them.
_PROJECTOR = "ingest/device_cache_projector.py"

# `lifecycle_status` is ADR-0011's audited lifecycle contract and `deleted_at`
# is a tombstone; neither is a source-derived cache column.
_ALLOWED_OTHER_COLUMNS = ("lifecycle_status", "deleted_at", "stale_reason")

_SEARCH_ROOTS = ("ingest", "operations/apps")

# Raw SQL touching operations.devices, and Django ORM writes to the Device
# model. Both paths have hidden a writer before, so both are searched.
_SQL_WRITE_RE = re.compile(
    r"(?:UPDATE|INSERT\s+INTO)\s+operations\.devices\b", re.IGNORECASE
)
_ORM_WRITE_RE = re.compile(r"\bdevice\.save\s*\(|\bDevice\.objects\.[a-z_]*update\b")


def _python_files() -> list[Path]:
    out: list[Path] = []
    for root in _SEARCH_ROOTS:
        for path in (_REPO_ROOT / root).rglob("*.py"):
            parts = path.parts
            if "tests" in parts or "migrations" in parts or "__pycache__" in parts:
                continue
            out.append(path)
    return sorted(out)


def _statement_writes_cache_column(text: str, start: int) -> list[str]:
    """Return cache columns assigned within the statement beginning at `start`.

    Bounded to the enclosing triple-quoted SQL block or 40 lines, whichever is
    shorter, so an unrelated later statement is not attributed to this one.
    """
    window = text[start : start + 4000]
    end = window.find('"""', 3)
    if end != -1:
        window = window[:end]
    window = "\n".join(window.split("\n")[:40])

    if re.match(r"\s*INSERT", window, re.IGNORECASE):
        return _insert_writes_cache_column(window)

    return [col for col in CACHE_COLUMNS if re.search(rf"\b{col}\s*=", window)]


def _split_top_level(text: str) -> list[str]:
    """Split on commas that are not nested inside parentheses."""
    parts, depth, current = [], 0, []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    parts.append("".join(current).strip())
    return parts


def _insert_writes_cache_column(window: str) -> list[str]:
    """Flag an INSERT only where a cache column receives a bound parameter.

    The five columns are NOT NULL, so promotion has to name them. Naming is not
    a producer write; supplying a source-derived value is. A neutral literal
    ('' / 'unknown') is the anchor being created without pretending to know,
    which is what ADR-0012 requires -- the projector fills them afterwards.
    """
    cols_match = re.search(
        r"INSERT\s+INTO\s+operations\.devices\s*\((.*?)\)", window, re.IGNORECASE | re.S
    )
    vals_match = re.search(r"VALUES\s*\((.*?)\)\s*$", window, re.IGNORECASE | re.S)
    if not cols_match or not vals_match:
        # Unrecognized shape -- fail loud rather than silently allow.
        return [c for c in CACHE_COLUMNS if re.search(rf"\b{c}\b", window)]

    columns = [c.strip() for c in _split_top_level(cols_match.group(1))]
    values = _split_top_level(vals_match.group(1))
    if len(columns) != len(values):
        return [c for c in CACHE_COLUMNS if re.search(rf"\b{c}\b", window)]

    return [
        col
        for col, val in zip(columns, values, strict=True)
        if col in CACHE_COLUMNS and "%s" in val
    ]


def test_only_projector_writes_device_cache_columns() -> None:
    violations: list[str] = []

    for path in _python_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if rel == _PROJECTOR:
            continue
        text = path.read_text(encoding="utf-8")

        for match in _SQL_WRITE_RE.finditer(text):
            cols = _statement_writes_cache_column(text, match.start())
            if cols:
                line = text[: match.start()].count("\n") + 1
                violations.append(f"{rel}:{line} writes {', '.join(sorted(set(cols)))}")

        for match in _ORM_WRITE_RE.finditer(text):
            window = text[match.start() : match.start() + 600]
            cols = [c for c in CACHE_COLUMNS if re.search(rf"[\"']{c}[\"']", window)]
            if cols:
                line = text[: match.start()].count("\n") + 1
                violations.append(
                    f"{rel}:{line} ORM-writes {', '.join(sorted(set(cols)))}"
                )

    assert not violations, (
        "ADR-0012: only ingest/device_cache_projector.py may write the device "
        "cache columns. Found:\n  " + "\n  ".join(violations)
    )


@pytest.mark.parametrize("column", CACHE_COLUMNS)
def test_projector_writes_every_cache_column(column: str) -> None:
    """The converse: the projector must actually own all five.

    Without this, deleting a producer and forgetting to add the column to the
    projector would leave it silently frozen and this suite still green.
    """
    text = (_REPO_ROOT / _PROJECTOR).read_text(encoding="utf-8")
    update_block = text[text.find("UPDATE operations.devices") :]
    assert re.search(rf"\b{column}\s*=", update_block), (
        f"{_PROJECTOR} does not write {column}; a producer was removed without "
        "the projector taking ownership."
    )
