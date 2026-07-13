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


# BIOS/SMBIOS placeholder serials seen in live fleet data. These are shared
# by unrelated machines, so serial matching on them merges distinct devices
# into one blob (observed: 100 UTA servers collapsed onto one device via
# serial 'None').
_JUNK_SERIALS = {
    "",
    "none",
    "null",
    "default string",
    "to be filled by o.e.m.",
    "to be filled by o.e.m",
    "system serial number",
    "chassis serial number",
    "123-1234-123",
    "invalid",
    "not specified",
    "not applicable",
    "n/a",
    "na",
    "unknown",
    "0",
    "00000000",
    "0123456789",
}


def is_usable_serial(serial: str | None) -> bool:
    """True when a serial is specific enough to identify one machine."""
    if not serial:
        return False
    value = serial.strip().lower()
    if value in _JUNK_SERIALS or len(value) < 4:
        return False
    # All one repeated character (e.g. '0000000', 'FFFFFFFF') is filler.
    return len(set(value)) > 1


_MAC_RE = re.compile(r"^[0-9a-f]{2}([:-][0-9a-f]{2}){5}$")
# All-zero/all-FF are filler; VirtualBox default NAT MAC shows on many VMs.
_JUNK_MACS = {"00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff", "02:00:4c:4f:4f:50"}


def normalize_mac(value: str | None) -> str:
    if not value:
        return ""
    mac = value.strip().lower().replace("-", ":")
    if len(mac) == 12 and ":" not in mac:
        mac = ":".join(mac[i:i + 2] for i in range(0, 12, 2))
    if not _MAC_RE.match(mac) or mac in _JUNK_MACS:
        return ""
    return mac


def extract_macs(raw: dict) -> list[str]:
    """Collect usable MAC addresses from a raw platform payload."""
    found: set[str] = set()
    candidates: list[Any] = []
    for ni in raw.get("networkInterfaces") or []:  # SentinelOne
        if isinstance(ni, dict):
            candidates.append(ni.get("physical"))
    for key in ("macAddress", "MacAddress", "macAddresses"):
        candidates.append(raw.get(key))
    guest = raw.get("GuestInfo")  # ScreenConnect
    if isinstance(guest, dict):
        candidates.append(guest.get("HardwareNetworkAddress"))
    flat: list[Any] = []
    for c in candidates:
        if isinstance(c, list):
            flat.extend(c)
        else:
            flat.append(c)
    for c in flat:
        if isinstance(c, str):
            mac = normalize_mac(c)
            if mac:
                found.add(mac)
    return sorted(found)


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


# Ninja is an aggregation agent carrying multiple observation streams;
# node_class tells us which stream a record belongs to. A vm.guest
# record proves the VM exists — NOT that an agent is on it.
_AGENT_NODE_CLASSES = {
    "WINDOWS_WORKSTATION",
    "WINDOWS_SERVER",
    "LINUX_WORKSTATION",
    "LINUX_SERVER",
    "MAC",
    "MAC_SERVER",
}


def entity_type_for_node_class(node_class: str | None) -> str:
    """Map a Ninja node_class to the observation stream it belongs to.

    Returns 'unknown' for unmapped classes — callers must surface those
    (admin finding / warning), never silently drop them.
    """
    nc = (node_class or "").upper()
    if nc in _AGENT_NODE_CLASSES:
        return "agent.rmm"
    if nc.endswith("_VMM_GUEST") or nc.endswith("_VM_GUEST"):
        return "vm.guest"
    if nc.endswith("_VMM_HOST") or nc.endswith("_VM_HOST"):
        return "vm.host"
    if nc.startswith("NMS_"):
        return "network.device"
    if nc == "CLOUD_MONITOR_TARGET":
        return "monitor.target"
    return "unknown"


def infer_device_type(os_name: str | None, ninja_node_class: str | None = None) -> str:
    node = (ninja_node_class or "").upper()
    if "SERVER" in node:
        return "server"
    if "WORKSTATION" in node:
        return "workstation"
    if os_name and "server" in os_name.lower():
        return "server"
    return "workstation"


def infer_device_role(
    os_name: str | None,
    node_class: str | None = None,
    machine_type: str | None = None,
) -> str | None:
    """Server/workstation role from explicit signals only — never guessed.

    Signals, in priority order: Ninja node_class, SentinelOne machineType,
    then the OS name itself. Returns None when no signal identifies the
    role (e.g. bare 'Linux'); callers must treat None as unknown, not
    default it.
    """
    node = (node_class or "").upper()
    if "SERVER" in node:
        return "server"
    if "WORKSTATION" in node or node == "MAC":
        return "workstation"
    machine = (machine_type or "").lower()
    if machine == "server":
        return "server"
    if machine in ("desktop", "laptop"):
        return "workstation"
    os_lower = (os_name or "").lower()
    if "server" in os_lower:
        return "server"
    if "windows" in os_lower or is_macos_name(os_name):
        return "workstation"
    return None


# Ordered: first match wins. Ported from legacy matview taxonomy
# (sql/migrations/051_agent_compliance_unresolved_and_macos.sql).
_OS_FAMILY_PATTERNS: tuple[tuple[str, str], ...] = (
    ("windows server 2025", "Windows Server 2025"),
    ("windows server 2022", "Windows Server 2022"),
    ("windows server 2019", "Windows Server 2019"),
    ("windows server 2016", "Windows Server 2016"),
    ("windows server 2012 r2", "Windows Server 2012 R2"),
    ("windows server 2012", "Windows Server 2012"),
    ("windows server 2008 r2", "Windows Server 2008 R2"),
    ("windows server 2008", "Windows Server 2008"),
    ("windows server", "Windows Server (other)"),
    ("windows 11", "Windows 11"),
    ("windows 10", "Windows 10"),
    ("windows 8.1", "Windows 8.1"),
    ("windows 8", "Windows 8"),
    ("windows 7", "Windows 7"),
    ("windows", "Windows (other)"),
    ("macos 26", "macOS 26"),
    ("macos 15", "macOS 15"),
    ("macos 14", "macOS 14"),
    ("macos 13", "macOS 13"),
    ("macos 12", "macOS 12"),
    ("macos 11", "macOS 11"),
    ("macos 10", "macOS 10"),
    ("macos", "macOS (other)"),
    ("os x", "macOS (other)"),
    ("darwin", "macOS (other)"),
    ("linux", "Linux"),
    ("ubuntu", "Linux"),
    ("centos", "Linux"),
    ("debian", "Linux"),
    ("red hat", "Linux"),
)


def os_family(os_name: str | None) -> str:
    if not os_name:
        return "Unknown"
    value = os_name.lower()
    for needle, family in _OS_FAMILY_PATTERNS:
        if needle in value:
            return family
    return "Other"
