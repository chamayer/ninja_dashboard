"""R-U-ON agent collector (read-only).

R-U-ON has no public API, so this signs in to the web console and reads the
agent overview table, the same method as the UTA cleanup script. Only GET/POST
login and the overview page are used; nothing is deleted or modified.

Limits that are deliberate rather than overlooked:

* The overview carries no group id, so the normalized group name is the stable
  container id. Renaming a group in R-U-ON therefore reads as a new group.
* Displayed times carry no timezone, so `last_seen_at` is left null and the
  displayed text is kept in `raw_data["last_contact_text"]` — a time is never
  guessed. Parsing needs a decision on where the console's timezone comes from.
* Only `ServerOn` agents (machine monitoring) become observations. A
  `ProcessOn` agent (process monitoring) is never a machine: when exactly one
  `ServerOn` agent has the same group, name and private IP, the monitor is
  listed on that machine's record (`process_monitors`); otherwise it is only
  counted in the log. Other types are counted and logged each run.
* `is_online` is set only when the State column is `ON` or `OFF`
  (the values the console returns). Any other value is preserved raw with `is_online` null.
"""

from __future__ import annotations

import collections
import html
import logging
import re
from datetime import datetime

import httpx
from psycopg.types.json import Json

from ingest.normalize import normalize_hostname
from ingest.sources import SourceConfig


log = logging.getLogger(__name__)

PLATFORM = "R-U-ON"
# Agent type that is a machine. Other types (e.g. ProcessOn, a process monitor)
# are not devices and must never be created as one.
MACHINE_TYPE = "ServerOn"
# Agent type that monitors a process on a machine; listed on that machine.
MONITOR_TYPE = "ProcessOn"
EXTERNAL_NAMESPACE = "agent"
CONTAINER_EXTERNAL_NAMESPACE = "group"
DEFAULT_BASE_URL = "https://www.r-u-on.com"

_ROW_RE = re.compile(r"(?is)<tr\b[^>]*>(.*?)</tr>")
_CELL_RE = re.compile(r"(?is)<td\b(?P<attrs>[^>]*)>(?P<value>.*?)</td>")
_SPAN_RE = re.compile(r"(?is)<span\b[^>]*>(.*?)</span>")
_LINK_RE = re.compile(
    r'(?is)<a\b[^>]*href="/ctrl\?action=agentdetail(?:&|&amp;)agent=(?P<id>[0-9]+)"[^>]*>(?P<name>.*?)</a>'
)
_STATE_HEADER_RE = re.compile(r"(?is)<th\b[^>]*>\s*State\s*</th>")
_LAST_CONTACT_RE = re.compile(r'title="Last contact at ([^"]+)"')
_TAG_RE = re.compile(r"<[^>]*>")
_LOGIN_OK_RE = re.compile(r"url=/ctrl\?action=overview|action=logout")


def _plain(fragment: str) -> str:
    return html.unescape(_TAG_RE.sub("", fragment)).strip()


def group_id_for(name: str | None) -> str:
    """Stable container id for a group (name-derived; see module docstring)."""
    return re.sub(r"\s+", " ", (name or "").strip()).lower()


_STATES = {"on": True, "off": False}


def parse_state(state: str) -> bool | None:
    return _STATES.get(state.strip().lower())


def parse_overview(page: str) -> list[dict]:
    """Parse the overview HTML into agent dicts.

    Raises on an unauthenticated page or an unrecognized layout rather than
    returning an empty list: silence would read as "every agent disappeared".
    """
    if "action=logout" not in page:
        raise RuntimeError("R-U-ON did not return an authenticated page")
    if not _STATE_HEADER_RE.search(page):
        raise RuntimeError("R-U-ON returned an unrecognized agent list")

    agents: list[dict] = []
    group: str | None = None
    for row in _ROW_RE.finditer(page):
        cells = list(_CELL_RE.finditer(row.group(1)))
        if not cells:
            continue
        if 'class="group"' in cells[0].group("attrs"):
            span = _SPAN_RE.search(cells[0].group(0))
            group = _plain(span.group(1)) if span else _plain(cells[0].group("value"))
            continue
        link = _LINK_RE.search(cells[0].group(0))
        if not link:
            continue
        if len(cells) != 5:
            raise RuntimeError("R-U-ON returned an unrecognized agent row")
        last_contact = _LAST_CONTACT_RE.search(cells[4].group(0))
        agents.append(
            {
                "agent_id": link.group("id"),
                "name": _plain(link.group("name")),
                "group": group,
                "type": _plain(cells[1].group("value")),
                "private_ip": _plain(cells[2].group("value")),
                "public_ip": _plain(cells[3].group("value")),
                "state": _plain(cells[4].group("value")),
                "last_contact_text": html.unescape(last_contact.group(1))
                if last_contact
                else "",
            }
        )
    return agents


def _pairing_key(agent: dict) -> tuple[str, str, str] | None:
    """Group, name and private IP; None when the name or IP is missing."""
    name = agent["name"].strip().casefold()
    ip = agent["private_ip"].strip()
    if not name or not ip:
        return None
    return (group_id_for(agent["group"]), name, ip)


def pair_monitors(agents: list[dict]) -> dict[str, str]:
    """Map each process monitor's agent id to its machine agent's id.

    A monitor pairs only when exactly one machine agent has the same group,
    name and private IP. Anything less certain stays unpaired rather than
    being attached to a guess.
    """
    machines: dict[tuple[str, str, str], list[str]] = {}
    for agent in agents:
        key = _pairing_key(agent) if agent["type"] == MACHINE_TYPE else None
        if key:
            machines.setdefault(key, []).append(agent["agent_id"])
    pairs: dict[str, str] = {}
    for agent in agents:
        key = _pairing_key(agent) if agent["type"] == MONITOR_TYPE else None
        matches = machines.get(key, []) if key else []
        if len(matches) == 1:
            pairs[agent["agent_id"]] = matches[0]
    return pairs


def _login(client: httpx.Client, base_url: str, username: str, password: str) -> None:
    client.get(f"{base_url}/").raise_for_status()
    resp = client.post(
        f"{base_url}/ctrl?action=login",
        data={"USERNAME": username, "PASSWORD": password},
    )
    resp.raise_for_status()
    if not _LOGIN_OK_RE.search(resp.text):
        raise RuntimeError("R-U-ON login was not confirmed; check the credentials")
    if not any(c.name == "JSESSIONID" for c in client.cookies.jar):
        raise RuntimeError("R-U-ON did not provide a session cookie")


def fetch(source: SourceConfig, observed_at: datetime) -> list[dict]:
    if not source.client_id_value or not source.client_secret:
        raise RuntimeError(
            "R-U-ON source requires client_id_ref (username) and client_secret_ref (password)"
        )
    base_url = (source.base_url or DEFAULT_BASE_URL).rstrip("/")

    with httpx.Client(timeout=60, follow_redirects=True) as client:
        _login(client, base_url, source.client_id_value, source.client_secret)
        resp = client.get(f"{base_url}/ctrl", params={"action": "overview"})
        resp.raise_for_status()
        agents = parse_overview(resp.text)

    observations: list[dict] = []
    groups: dict[str, str] = {}
    skipped: collections.Counter[str] = collections.Counter()
    pairs = pair_monitors(agents)
    monitors_by_machine: dict[str, list[dict]] = {}
    for agent in agents:
        if agent["agent_id"] in pairs:
            monitors_by_machine.setdefault(pairs[agent["agent_id"]], []).append(agent)
    unpaired = 0
    for agent in agents:
        if agent["type"] == MONITOR_TYPE:
            unpaired += agent["agent_id"] not in pairs
            continue
        if agent["type"] != MACHINE_TYPE:
            skipped[agent["type"] or "(blank)"] += 1
            continue
        hostname = agent["name"]
        norm = normalize_hostname(hostname)
        if not hostname or not norm:
            continue
        group_name = agent["group"]
        group_id = group_id_for(group_name)
        if group_id:
            groups.setdefault(group_id, group_name or "")
        raw_data = dict(agent)
        canonical_extra: dict[str, list[dict]] = {}
        monitors = monitors_by_machine.get(agent["agent_id"])
        if monitors:
            # Only machines that have monitors gain the key, so every other
            # record's content (and history) is unchanged.
            raw_data["process_monitors"] = monitors
            canonical_extra["process_monitors"] = [
                {
                    "agent_id": monitor["agent_id"],
                    "name": monitor["name"],
                    "is_online": parse_state(monitor["state"]),
                }
                for monitor in monitors
            ]
        observations.append(
            {
                "observed_at": observed_at,
                "platform": PLATFORM,
                "external_namespace": EXTERNAL_NAMESPACE,
                "container_external_namespace": CONTAINER_EXTERNAL_NAMESPACE,
                "source_id": source.source_id,
                "source_name": source.source_name,
                "source_client_name": None,
                "platform_group_name": group_name,
                "platform_group_id": group_id,
                "platform_device_id": agent["agent_id"],
                "hostname": hostname,
                "norm_name": norm,
                "match_name": norm,
                # R-U-ON states no OS or server/workstation role; asserting none.
                "device_type": None,
                "os_name": None,
                "domain_name": None,
                "is_online": parse_state(agent["state"]),
                "last_seen_at": None,
                "raw_data": Json(raw_data),
                "canonical_extra": canonical_extra,
            }
        )
    if skipped:
        log.warning("R-U-ON: skipped unsupported agent types: %s", dict(skipped))
    if unpaired:
        log.warning(
            "R-U-ON: %d process monitors matched no single machine agent", unpaired
        )
    # Container-only rows keep a group with no agents visible, as for LMI.
    for group_id, group_name in groups.items():
        observations.append(
            {
                "_org_only": True,
                "platform": PLATFORM,
                "container_external_namespace": CONTAINER_EXTERNAL_NAMESPACE,
                "platform_group_id": group_id,
                "platform_group_name": group_name,
            }
        )
    return observations
