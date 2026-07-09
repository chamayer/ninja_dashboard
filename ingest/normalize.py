"""Normalization helpers for cross-platform device matching."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

_TRAILING_PARENS_RE = re.compile(r"\s*\(.*?\)\s*$")
_HOST_STRIP_CHARS_RE = re.compile(r"[\s'`\u2018\u2019]")
_HOST_LOOSE_CHARS_RE = re.compile(r"[^a-z0-9]")
_ORG_STRIP_CHARS_RE = re.compile(r"[\s\-_.]")
_PLACEHOLDER_ORG_NAMES = {
    "defaultsite",
    "default",
    "unknown",
    "various",
}

PLATFORM_ALIASES = {
    "ninja": "Ninja",
    "sentinelone": "SentinelOne",
    "s1": "SentinelOne",
    "logmein": "LogMeIn",
    "lmi": "LogMeIn",
    "screenconnect": "ScreenConnect",
    "sc": "ScreenConnect",
}


def canonical_platform(value: str) -> str:
    key = value.strip().replace(" ", "").lower()
    return PLATFORM_ALIASES.get(key, value.strip())


def normalize_hostname(name: str | None) -> str:
    if not name:
        return ""
    clean = _TRAILING_PARENS_RE.sub("", name)
    short = clean.split(".", 1)[0].lower().strip()
    return _HOST_STRIP_CHARS_RE.sub("", short)


def normalize_loose_hostname(name: str | None) -> str:
    if not name:
        return ""
    clean = _TRAILING_PARENS_RE.sub("", name)
    short = clean.split(".", 1)[0].lower().strip()
    return _HOST_LOOSE_CHARS_RE.sub("", short)


def is_macos_name(os_name: str | None) -> bool:
    if not os_name:
        return False
    value = os_name.lower()
    return "macos" in value or "os x" in value or "darwin" in value


def normalize_org_name(name: str | None) -> str:
    if not name:
        return ""
    return _ORG_STRIP_CHARS_RE.sub("", name).lower().strip()


def is_placeholder_org_name(name: str | None) -> bool:
    if not name:
        return False
    return normalize_org_name(name) in _PLACEHOLDER_ORG_NAMES


def parse_dt(value: Any) -> datetime | None:
    if value in (None, "", 0):
        return None
    if isinstance(value, datetime):
        return value
    try:
        text = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def infer_device_type(os_name: str | None, ninja_node_class: str | None = None) -> str:
    node = (ninja_node_class or "").upper()
    if "SERVER" in node:
        return "server"
    if "WORKSTATION" in node:
        return "workstation"
    if os_name and "server" in os_name.lower():
        return "server"
    return "workstation"
