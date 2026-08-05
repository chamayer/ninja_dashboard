"""Normalization helpers for cross-platform device matching."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

_log = logging.getLogger(__name__)

_TRAILING_PARENS_RE = re.compile(r"\s*\(.*?\)\s*$")
_HOST_STRIP_CHARS_RE = re.compile(r"[\s'`\u2018\u2019]")
_HOST_LOOSE_CHARS_RE = re.compile(r"[^a-z0-9]")
_ORG_STRIP_CHARS_RE = re.compile(r"[\s\-_.]")

# Aliases live in operations.platform_aliases, alongside client_name_aliases
# and publisher_aliases. This dict is the bootstrap fallback, used only before
# the table has been loaded (or if loading fails) so a container starting
# against a pre-0092 database behaves exactly as before.
#
# canonical_platform() keeps its no-argument signature deliberately: it has 15
# call sites in the legacy agent-compliance loader, and threading a cursor
# through all of them would mean editing retirement-path code for no benefit.
# Instead load_platform_aliases() primes a process-level cache once per run.
_BUILTIN_ALIASES = {
    "ninja": "Ninja",
    "sentinelone": "SentinelOne",
    "s1": "SentinelOne",
    "logmein": "LogMeIn",
    "lmi": "LogMeIn",
    "screenconnect": "ScreenConnect",
    "sc": "ScreenConnect",
    "hudu": "Hudu",
}

_alias_cache: dict[str, str] | None = None


def _load_mapping_rows(cur, sql: str, label: str) -> list | None:
    """Run a mapping-table query that is allowed to fail, without poisoning
    the caller's transaction.

    A bare try/except is not enough. In PostgreSQL a failed statement aborts
    the whole transaction, so every later statement raises
    `InFailedSqlTransaction` even though the exception here was swallowed.
    That is not hypothetical: 0119 shipped without this and the ingest
    container, which starts in parallel with the Operations migrate step,
    queried `node_class_mappings` before the table existed. The loader
    "degraded gracefully" and then took two collector threads down with it.

    A SAVEPOINT scopes the rollback to this statement, so a missing table
    genuinely degrades to the built-in patterns.
    """
    cur.execute(f"SAVEPOINT {label}")
    try:
        cur.execute(sql)
        rows = cur.fetchall()
    except Exception:
        cur.execute(f"ROLLBACK TO SAVEPOINT {label}")
        _log.exception("%s load failed — using built-in patterns", label)
        return None
    cur.execute(f"RELEASE SAVEPOINT {label}")
    return rows


def load_platform_aliases(cur) -> None:
    """Prime the alias cache from operations.platform_aliases.

    Called once per collection run by ingest.sources.load_sources. On failure
    the built-in map stays in effect, so a missing table degrades to previous
    behaviour rather than breaking canonicalisation.
    """
    global _alias_cache
    rows = _load_mapping_rows(
        cur,
        "SELECT lower(alias), canonical FROM operations.platform_aliases",
        "platform_aliases",
    )
    if rows:
        _alias_cache = dict(rows)


def canonical_platform(value: str) -> str:
    key = value.strip().replace(" ", "").lower()
    table = _alias_cache if _alias_cache is not None else _BUILTIN_ALIASES
    return table.get(key, value.strip())


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
#
# Authoritative source is operations.node_class_mappings (migration 0119).
# This is the bootstrap fallback only, used before the first
# load_node_class_mappings() call and if that query fails. Do not add patterns
# here; add rows to the table.
#
# form_factor is empty for the agent classes on purpose: agent presence is not
# evidence of form factor (ADR-0005).
_BUILTIN_NODE_CLASS_PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("WINDOWS_WORKSTATION", "agent.rmm", ""),
    ("WINDOWS_SERVER", "agent.rmm", ""),
    ("LINUX_WORKSTATION", "agent.rmm", ""),
    ("LINUX_SERVER", "agent.rmm", ""),
    ("MAC", "agent.rmm", ""),
    ("MAC_SERVER", "agent.rmm", ""),
    ("%\\_VMM\\_GUEST", "vm.guest", "vm"),
    ("%\\_VM\\_GUEST", "vm.guest", "vm"),
    ("%\\_VMM\\_HOST", "vm.host", "hypervisor-host"),
    ("%\\_VM\\_HOST", "vm.host", "hypervisor-host"),
    ("NMS\\_%", "network.device", "network-device"),
    ("CLOUD_MONITOR_TARGET", "monitor.target", ""),
)

# [(compiled pattern, entity_type, form_factor)] in priority order.
_node_class_cache: list[tuple[re.Pattern[str], str, str]] | None = None


def _compiled_node_class_rules() -> list[tuple[re.Pattern[str], str, str]]:
    if _node_class_cache is not None:
        return _node_class_cache
    return [
        (_like_to_regex(pattern), entity_type, form_factor)
        for pattern, entity_type, form_factor in _BUILTIN_NODE_CLASS_PATTERNS
    ]


def load_node_class_mappings(cur) -> None:
    """Load operations.node_class_mappings into the process cache.

    Same contract as load_platform_aliases and load_os_family_mappings: called
    once per collection run, and on failure the built-in patterns stay in
    effect rather than the taxonomy going empty.
    """
    global _node_class_cache
    rows = _load_mapping_rows(
        cur,
        "SELECT pattern, entity_type, COALESCE(form_factor, '') "
        "FROM operations.node_class_mappings ORDER BY priority, id",
        "node_class_mappings",
    )
    if rows is None:
        return
    if not rows:
        _log.warning("node_class_mappings is empty — using built-in patterns")
        return
    _node_class_cache = [
        (_like_to_regex(pattern), entity_type, form_factor or "")
        for pattern, entity_type, form_factor in rows
    ]


def entity_type_for_node_class(node_class: str | None) -> str:
    """Map a Ninja node_class to the observation stream it belongs to.

    Returns 'unknown' for unmapped classes — callers must surface those
    (admin finding / warning), never silently drop them.
    """
    nc = (node_class or "").upper()
    if not nc:
        return "unknown"
    for rx, entity_type, _form_factor in _compiled_node_class_rules():
        if rx.match(nc):
            return entity_type
    return "unknown"


def form_factor_for_node_class(node_class: str | None) -> str | None:
    """Form factor implied by a node_class, or None when it implies nothing.

    None is the honest answer for every `agent.*` class — see ADR-0005. Callers
    must not substitute 'physical'.
    """
    nc = (node_class or "").upper()
    if not nc:
        return None
    for rx, _entity_type, form_factor in _compiled_node_class_rules():
        if rx.match(nc):
            return form_factor or None
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


# Authoritative source is operations.os_family_mappings (migration 0118).
# This is the bootstrap fallback only, used before load_os_family_mappings()
# has primed the cache or if that load fails — exactly the contract
# _BUILTIN_ALIASES has above. Do not add patterns here; add rows to the table.
_BUILTIN_OS_FAMILY_PATTERNS: tuple[tuple[str, str], ...] = (
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

# Populated by load_os_family_mappings(); list of (compiled pattern, family)
# in priority order. None means "table not loaded — use the fallback above".
_os_family_cache: list[tuple[re.Pattern[str], str]] | None = None


def _like_to_regex(pattern: str) -> re.Pattern[str]:
    """Compile a SQL LIKE pattern to an equivalent case-insensitive regex.

    Kept faithful to LIKE rather than assuming `%foo%`, so an operator adding
    a prefix or suffix pattern to the table gets SQL semantics in Python too.

    LIKE matches the *whole* string, so the result is anchored. That makes
    `.search()` and `.match()` both behave as a full match, which is why the
    existing `os_family` call site needs no change: its patterns are all
    `%...%`, which anchor out to the same substring test.

    Backslash escapes are honoured — `\\_` is a literal underscore, not the
    single-character wildcard. `node_class` patterns such as `NMS\\_%` depend on
    this; without it the underscore would match any character.
    """
    out = []
    escaped = False
    for ch in pattern:
        if escaped:
            out.append(re.escape(ch))
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == "%":
            out.append(".*")
        elif ch == "_":
            out.append(".")
        else:
            out.append(re.escape(ch))
    if escaped:  # trailing lone backslash — treat as a literal
        out.append(re.escape("\\"))
    return re.compile(r"\A" + "".join(out) + r"\Z", re.IGNORECASE)


def load_os_family_mappings(cur) -> None:
    """Prime the os_family cache from operations.os_family_mappings.

    Same contract as load_platform_aliases: called once per collection run,
    and on failure the built-in patterns stay in effect so a container
    starting against a pre-0118 database behaves exactly as before.
    """
    global _os_family_cache
    rows = _load_mapping_rows(
        cur,
        "SELECT pattern, os_family FROM operations.os_family_mappings "
        "ORDER BY priority, id",
        "os_family_mappings",
    )
    if rows:
        _os_family_cache = [(_like_to_regex(p), f) for p, f in rows]


def os_family(os_name: str | None) -> str | None:
    """Map an OS name to its family.

    Returns None — not "Unknown" — when there is no OS name. "Unknown" was a
    fallback presented as a value; once it reached the claim layer it won
    authority for 488 devices whose family was actually known. A caller with
    no OS name must record no family. See ADR-0012.
    """
    if not os_name or not os_name.strip():
        return None
    if _os_family_cache is not None:
        for rx, family in _os_family_cache:
            if rx.search(os_name):
                return family
        return "Other"
    value = os_name.lower()
    for needle, family in _BUILTIN_OS_FAMILY_PATTERNS:
        if needle in value:
            return family
    return "Other"
