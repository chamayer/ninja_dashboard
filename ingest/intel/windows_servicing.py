"""Project Windows build evidence onto endoflife.date servicing cycles.

Build candidates come entirely from ``intel.eol_releases.latest_version``.
The small rule table only describes stable product and edition semantics; it
contains no build numbers or dates and requires no operator maintenance.
Ambiguity is retained as an explicit unknown state, and ESU availability never
implies that a device is entitled to ESU coverage.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ingest import db

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Release:
    product_name: str
    cycle: str
    label: str
    latest_version: str
    eoas_from: date | None
    is_eoas: bool | None
    eol_from: date | None
    is_eol: bool
    eoes_from: date | None
    is_eoes: bool | None
    is_maintained: bool
    is_lts: bool


@dataclass(frozen=True)
class Rule:
    key: str
    kind: str
    priority: int
    product_name: str
    os_name_pattern: str
    cycle_pattern: str | None


@dataclass(frozen=True)
class Classification:
    support_state: str
    build_number: int | None
    release: Release | None
    reason: str
    extended_security_available: bool = False


def _extract_build(value: object) -> int | None:
    """Return the Windows base-build component from common source/API forms."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value)
    dotted = re.match(r"^\s*\d+\.\d+\.(\d{4,6})(?:\.|$)", text)
    if dotted:
        return int(dotted.group(1))
    candidates = [int(part) for part in re.findall(r"\d{4,6}", text)]
    return max(candidates) if candidates else None


def _score_release(release: Release, os_name: str, release_id: str) -> int:
    cycle = release.cycle.casefold()
    label = release.label.casefold()
    score = 0
    normalized_release = re.sub(r"[^a-z0-9]", "", release_id.casefold())
    if normalized_release:
        normalized_cycle = re.sub(r"[^a-z0-9]", "", cycle)
        normalized_label = re.sub(r"[^a-z0-9]", "", label)
        if normalized_release in normalized_cycle or normalized_release in normalized_label:
            score += 10
    for year in re.findall(r"\b20\d{2}\b", os_name):
        if year in cycle or year in label:
            score += 20
    return score


def _support_state(
    release: Release,
    *,
    today: date,
    warning_days: int,
) -> tuple[str, bool]:
    base_eol = release.eol_from is not None and release.eol_from <= today
    if base_eol or (release.eol_from is None and release.is_eol):
        esu_available = bool(release.eoes_from and release.eoes_from > today)
        return ("eol_esu_available" if esu_available else "eol", esu_available)
    if release.eol_from and release.eol_from <= today + timedelta(days=warning_days):
        return "approaching_eol", False
    if (release.eoas_from and release.eoas_from <= today) or (
        release.eoas_from is None and release.is_eoas
    ):
        return "security_support", False
    return "supported", False


def classify_windows(
    os_name: str,
    os_build_number: object,
    os_release_id: object,
    releases: list[Release],
    rules: list[Rule],
    *,
    today: date | None = None,
    warning_days: int = 180,
) -> Classification | None:
    """Classify one Windows device, returning ``None`` for non-Windows OSes."""
    os_name = (os_name or "").strip()
    if "windows" not in os_name.casefold() and not re.search(
        r"(?i)\bhyper-v\s+server\b", os_name
    ):
        return None

    build = _extract_build(os_build_number)
    if build is None:
        return Classification("unknown", None, None, "missing Windows build number")

    product_rule = next(
        (
            rule
            for rule in sorted(rules, key=lambda item: (item.priority, item.key))
            if rule.kind == "product" and re.search(rule.os_name_pattern, os_name)
        ),
        None,
    )
    if product_rule is None:
        return Classification("unknown", build, None, "no Windows product rule matched")

    candidates = [
        release
        for release in releases
        if release.product_name == product_rule.product_name
        and _extract_build(release.latest_version) == build
    ]
    if not candidates:
        return Classification(
            "unknown",
            build,
            None,
            f"build {build} is absent from endoflife.date:{product_rule.product_name}",
        )

    selected_rule: Rule | None = None
    for rule in sorted(rules, key=lambda item: (item.priority, item.key)):
        if rule.kind != "edition" or rule.product_name != product_rule.product_name:
            continue
        if not re.search(rule.os_name_pattern, os_name):
            continue
        narrowed = [r for r in candidates if re.search(rule.cycle_pattern or "", r.cycle)]
        if narrowed:
            candidates = narrowed
            selected_rule = rule
            break

    if len(candidates) > 1:
        release_id = str(os_release_id or "")
        ranked = sorted(
            ((_score_release(r, os_name, release_id), r) for r in candidates),
            key=lambda item: (-item[0], item[1].cycle),
        )
        if ranked[0][0] <= 0 or (
            len(ranked) > 1 and ranked[0][0] == ranked[1][0]
        ):
            cycles = ", ".join(sorted(r.cycle for r in candidates))
            return Classification(
                "unknown", build, None, f"build {build} matches multiple cycles: {cycles}"
            )
        release = ranked[0][1]
        reason = f"build {build} plus release/title token selected {release.cycle}"
    else:
        release = candidates[0]
        reason = f"build {build} selected {release.product_name}#{release.cycle}"
    if selected_rule:
        reason += f" via {selected_rule.key}"

    state, esu_available = _support_state(
        release, today=today or date.today(), warning_days=warning_days
    )
    return Classification(state, build, release, reason, esu_available)


def _load_rules(cur: Any) -> list[Rule]:
    cur.execute(
        """
        SELECT rule_key, rule_kind, priority, product_name,
               os_name_pattern, cycle_pattern
        FROM intel.windows_servicing_rules
        ORDER BY rule_kind, priority, rule_key
        """
    )
    return [Rule(*row) for row in cur.fetchall()]


def _load_releases(cur: Any) -> list[Release]:
    cur.execute(
        """
        SELECT product_name, cycle, label, latest_version,
               eoas_from, is_eoas, eol_from, is_eol,
               eoes_from, is_eoes, is_maintained, is_lts
        FROM intel.eol_releases
        WHERE product_name IN ('windows', 'windows-server')
        """
    )
    return [Release(*row) for row in cur.fetchall()]


def _load_devices(cur: Any, tenant_id: int, device_id: uuid.UUID | None) -> list[tuple]:
    cur.execute(
        """
        SELECT d.id, d.client_id,
               COALESCE(attr.os_name, d.os_name, ninja.os_name, ''),
               COALESCE(attr.os_build_number, ninja.os_build_number, ''),
               COALESCE(attr.os_release_id, ninja.os_release_id, ''),
               CASE
                 WHEN attr.os_build_number IS NOT NULL THEN 'effective attributes'
                 WHEN ninja.os_build_number IS NOT NULL THEN 'Ninja normalized evidence'
                 ELSE 'effective attributes'
               END
        FROM operations.devices d
        LEFT JOIN LATERAL (
            SELECT MAX(e.value_text) FILTER (WHERE definition.key = 'os_name')
                       AS os_name,
                   MAX(e.value_text) FILTER (
                       WHERE definition.key = 'os_build_number'
                   ) AS os_build_number,
                   MAX(e.value_text) FILTER (
                       WHERE definition.key = 'os_release_id'
                   ) AS os_release_id
            FROM operations.entity_attribute_effective_current e
            JOIN operations.attribute_definitions definition
              ON definition.id = e.attribute_definition_id
            WHERE e.tenant_id = d.tenant_id
              AND e.entity_id = d.entity_id
              AND e.status = 'selected'
              AND definition.key IN ('os_name', 'os_build_number', 'os_release_id')
        ) attr ON TRUE
        LEFT JOIN LATERAL (
            SELECT nd.os_name, nd.os_build_number, nd.os_release_id
            FROM operations.v_device_source_link link
            JOIN operations.sources source
              ON source.id = link.source_id AND source.name = 'Ninja'
            JOIN ninja_core.devices nd
              ON link.external_id ~ '^[0-9]+$'
             AND nd.id = link.external_id::bigint
            WHERE link.tenant_id = d.tenant_id
              AND link.device_id = d.id
            ORDER BY nd.is_current DESC, nd.last_seen_at DESC NULLS LAST
            LIMIT 1
        ) ninja ON TRUE
        WHERE d.tenant_id = %s
          AND d.deleted_at IS NULL
          AND (%s::uuid IS NULL OR d.id = %s)
        """,
        (tenant_id, device_id, device_id),
    )
    return cur.fetchall()


def _write_current(
    cur: Any,
    tenant_id: int,
    device_id: uuid.UUID | None,
    rows: list[dict[str, Any]],
) -> None:
    if rows:
        cur.executemany(
            """
            INSERT INTO operations.device_windows_servicing_current (
                tenant_id, device_id, client_id, os_name, os_build_number,
                os_release_id, build_number, product_name, cycle, release_label,
                support_state, active_support_ends_on, security_support_ends_on,
                extended_security_ends_on, is_lts,
                extended_security_available, classification_reason,
                evidence_source, evaluated_at
            ) VALUES (
                %(tenant_id)s, %(device_id)s, %(client_id)s, %(os_name)s,
                %(os_build_number)s, %(os_release_id)s, %(build_number)s,
                %(product_name)s, %(cycle)s, %(release_label)s,
                %(support_state)s, %(eoas_from)s, %(eol_from)s, %(eoes_from)s,
                %(is_lts)s, %(esu_available)s, %(reason)s, %(evidence_source)s,
                %(evaluated_at)s
            )
            ON CONFLICT (tenant_id, device_id) DO UPDATE SET
                client_id = EXCLUDED.client_id,
                os_name = EXCLUDED.os_name,
                os_build_number = EXCLUDED.os_build_number,
                os_release_id = EXCLUDED.os_release_id,
                build_number = EXCLUDED.build_number,
                product_name = EXCLUDED.product_name,
                cycle = EXCLUDED.cycle,
                release_label = EXCLUDED.release_label,
                support_state = EXCLUDED.support_state,
                active_support_ends_on = EXCLUDED.active_support_ends_on,
                security_support_ends_on = EXCLUDED.security_support_ends_on,
                extended_security_ends_on = EXCLUDED.extended_security_ends_on,
                is_lts = EXCLUDED.is_lts,
                extended_security_available = EXCLUDED.extended_security_available,
                classification_reason = EXCLUDED.classification_reason,
                evidence_source = EXCLUDED.evidence_source,
                evaluated_at = EXCLUDED.evaluated_at
            """,
            rows,
        )
    current_ids = [row["device_id"] for row in rows]
    if device_id is not None:
        if not current_ids:
            cur.execute(
                "DELETE FROM operations.device_windows_servicing_current "
                "WHERE tenant_id = %s AND device_id = %s",
                (tenant_id, device_id),
            )
    elif current_ids:
        cur.execute(
            """
            DELETE FROM operations.device_windows_servicing_current
            WHERE tenant_id = %s AND NOT (device_id = ANY(%s::uuid[]))
            """,
            (tenant_id, current_ids),
        )
    else:
        cur.execute(
            "DELETE FROM operations.device_windows_servicing_current WHERE tenant_id = %s",
            (tenant_id,),
        )


def _finding_condition(tenant_id: int, device_id: uuid.UUID, name: str) -> str:
    return hashlib.sha256(f"{tenant_id}:{device_id}:{name}".encode()).hexdigest()[:64]


def _sync_findings(
    cur: Any,
    tenant_id: int,
    device_id: uuid.UUID | None,
    rows: list[dict[str, Any]],
    now: datetime,
) -> int:
    cur.execute(
        """
        SELECT id, name, default_severity
        FROM operations.finding_types
        WHERE name IN (
            'windows_servicing_eol',
            'windows_servicing_approaching_eol',
            'windows_servicing_unknown'
        )
        """
    )
    types = {name: (finding_id, severity) for finding_id, name, severity in cur.fetchall()}
    if not types:
        return 0

    offenders: dict[str, list[uuid.UUID]] = {name: [] for name in types}
    affected = 0
    for row in rows:
        state = row["support_state"]
        if state in ("eol", "eol_esu_available"):
            name = "windows_servicing_eol"
        elif state == "approaching_eol":
            name = "windows_servicing_approaching_eol"
        elif state == "unknown":
            name = "windows_servicing_unknown"
        else:
            continue
        if name not in types:
            continue
        offenders[name].append(row["device_id"])
        finding_type_id, severity = types[name]
        details = {
            "os_name": row["os_name"],
            "os_build_number": row["os_build_number"],
            "os_release_id": row["os_release_id"],
            "build_number": row["build_number"],
            "product": row["product_name"],
            "cycle": row["cycle"],
            "support_state": state,
            "active_support_ends_on": _iso(row["eoas_from"]),
            "security_support_ends_on": _iso(row["eol_from"]),
            "extended_security_ends_on": _iso(row["eoes_from"]),
            "extended_security_available": row["esu_available"],
            "extended_security_entitlement": "unknown",
            "reason": row["reason"],
            "source": "endoflife.date",
        }
        cur.execute(
            """
            INSERT INTO operations.findings (
                id, version, tenant_id, finding_type_id, client_id,
                subject_type, subject_id, subject_layer, finding_details,
                condition_key, severity, confidence, status,
                first_seen_at, last_seen_at, last_detected_at
            ) VALUES (
                gen_random_uuid(), 1, %s, %s, %s,
                'device', %s, '', %s::jsonb,
                %s, %s, 'confirmed', 'open', %s, %s, %s
            )
            ON CONFLICT (tenant_id, condition_key)
                WHERE condition_key > '' AND status IN ('open', 'acknowledged')
            DO UPDATE SET
                finding_details = EXCLUDED.finding_details,
                severity = EXCLUDED.severity,
                confidence = EXCLUDED.confidence,
                last_seen_at = EXCLUDED.last_seen_at,
                last_detected_at = EXCLUDED.last_detected_at
            """,
            (
                tenant_id,
                finding_type_id,
                row["client_id"],
                row["device_id"],
                json.dumps(details),
                _finding_condition(tenant_id, row["device_id"], name),
                severity,
                now,
                now,
                now,
            ),
        )
        affected += cur.rowcount or 0

    for name, (finding_type_id, _severity) in types.items():
        cur.execute(
            """
            UPDATE operations.findings
            SET status = 'resolved', last_seen_at = %s, closed_at = COALESCE(closed_at, %s)
            WHERE tenant_id = %s
              AND finding_type_id = %s
              AND status IN ('open', 'acknowledged')
              AND (%s::uuid IS NULL OR subject_id = %s)
              AND NOT (subject_id = ANY(%s::uuid[]))
            """,
            (now, now, tenant_id, finding_type_id, device_id, device_id, offenders[name]),
        )
        affected += cur.rowcount or 0
    return affected


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def sync(
    cur: Any,
    tenant_id: int,
    device_id: uuid.UUID | None = None,
    *,
    now: datetime | None = None,
) -> int:
    """Project current Windows servicing state and synchronize its findings."""
    cur.execute(
        """
        SELECT to_regclass('operations.device_windows_servicing_current') IS NOT NULL
           AND to_regclass('intel.windows_servicing_rules') IS NOT NULL
        """
    )
    if not cur.fetchone()[0]:
        return 0

    evaluated_at = now or datetime.now(timezone.utc)
    rules = _load_rules(cur)
    releases = _load_releases(cur)
    projected: list[dict[str, Any]] = []
    for (
        current_device_id,
        client_id,
        os_name,
        os_build_number,
        os_release_id,
        evidence_source,
    ) in _load_devices(cur, tenant_id, device_id):
        result = classify_windows(
            os_name,
            os_build_number,
            os_release_id,
            releases,
            rules,
            today=evaluated_at.date(),
        )
        if result is None:
            continue
        release = result.release
        projected.append(
            {
                "tenant_id": tenant_id,
                "device_id": current_device_id,
                "client_id": client_id,
                "os_name": os_name,
                "os_build_number": str(os_build_number or ""),
                "os_release_id": str(os_release_id or ""),
                "build_number": result.build_number,
                "product_name": release.product_name if release else None,
                "cycle": release.cycle if release else None,
                "release_label": release.label if release else "",
                "support_state": result.support_state,
                "eoas_from": release.eoas_from if release else None,
                "eol_from": release.eol_from if release else None,
                "eoes_from": release.eoes_from if release else None,
                "is_lts": release.is_lts if release else False,
                "esu_available": result.extended_security_available,
                "reason": result.reason,
                "evidence_source": evidence_source,
                "evaluated_at": evaluated_at,
            }
        )

    _write_current(cur, tenant_id, device_id, projected)
    return _sync_findings(cur, tenant_id, device_id, projected, evaluated_at)


def project_and_evaluate(
    tenant_id: int,
    device_id: uuid.UUID | None = None,
) -> int:
    """Transactional entry point for corpus-refresh orchestration."""
    with db.transaction() as cur:
        cur.execute(f"SET LOCAL operations.tenant_id = {int(tenant_id)}")
        return sync(cur, tenant_id, device_id)


def rollout_summary(tenant_id: int) -> dict[str, Any]:
    """Return a read-only post-deployment validation summary.

    This deliberately makes no assertion about a historic device count: fleet
    state changes. It verifies the contract that every actionable state has a
    resolved corpus cycle/date and every unknown state explains why it is
    unknown, then returns the live state distribution for rollout comparison.
    """
    with db.transaction() as cur:
        cur.execute(f"SET LOCAL operations.tenant_id = {int(tenant_id)}")
        cur.execute(
            "SELECT to_regclass('operations.device_windows_servicing_current') IS NOT NULL"
        )
        if not cur.fetchone()[0]:
            return {
                "states": {},
                "missing_cycle": 0,
                "missing_security_end": 0,
                "unexplained_unknown": 0,
                "invalid_rows": 0,
                "status": "migration_pending",
            }
        cur.execute(
            """
            SELECT support_state, COUNT(*)
            FROM operations.device_windows_servicing_current
            WHERE tenant_id = %s
            GROUP BY support_state
            ORDER BY support_state
            """,
            (tenant_id,),
        )
        states = {state: count for state, count in cur.fetchall()}
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE support_state IN (
                        'supported', 'security_support', 'approaching_eol',
                        'eol_esu_available', 'eol'
                    )
                      AND (product_name IS NULL OR cycle IS NULL)
                ) AS missing_cycle,
                COUNT(*) FILTER (
                    WHERE support_state IN ('approaching_eol', 'eol_esu_available', 'eol')
                      AND security_support_ends_on IS NULL
                ) AS missing_security_end,
                COUNT(*) FILTER (
                    WHERE support_state = 'unknown'
                      AND classification_reason = ''
                ) AS unexplained_unknown
            FROM operations.device_windows_servicing_current
            WHERE tenant_id = %s
            """,
            (tenant_id,),
        )
        missing_cycle, missing_security_end, unexplained_unknown = cur.fetchone()
    invalid_rows = int(missing_cycle or 0) + int(missing_security_end or 0) + int(
        unexplained_unknown or 0
    )
    return {
        "states": states,
        "missing_cycle": int(missing_cycle or 0),
        "missing_security_end": int(missing_security_end or 0),
        "unexplained_unknown": int(unexplained_unknown or 0),
        "invalid_rows": invalid_rows,
    }
