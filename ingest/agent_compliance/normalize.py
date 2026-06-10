"""Normalization helpers for cross-platform device matching."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

_TRAILING_PARENS_RE = re.compile(r"\s*\(.*?\)\s*$")
_HOST_STRIP_CHARS_RE = re.compile(r"[\s'`\u2018\u2019]")
_ORG_STRIP_CHARS_RE = re.compile(r"[\s\-_.]")

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


def normalize_org_name(name: str | None) -> str:
    if not name:
        return ""
    return _ORG_STRIP_CHARS_RE.sub("", name).lower().strip()


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
