"""Agent-compliance ingest pipeline."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from psycopg.types.json import Json

from ingest import db
from ingest.agent_compliance import alerts
from ingest.agent_compliance.clients import logmein, ninja, screenconnect, sentinelone
from ingest.agent_compliance.config_loader import (
    SourceConfig,
    get_requirement,
    load_aliases,
    load_clients,
    load_requirements,
    load_sources,
    resolve_client_id,
    sync_clients_from_observations,
)
from ingest.runlog import run_log

log = logging.getLogger(__name__)

_FETCHERS = {
    "Ninja": ninja.fetch,
    "SentinelOne": sentinelone.fetch,
    "LogMeIn": logmein.fetch,
    "ScreenConnect": screenconnect.fetch,
}


def run() -> tuple[int, int]:
    observed_at = datetime.now(timezone.utc)
    with run_log("agent_compliance") as stats:
        run_id = stats["run_id"]
        _clear_stuck_source_runs()
        sources = load_sources()
        requirements = load_requirements()
        source_status: dict[int, str] = {}
        all_observations: list[dict[str, Any]] = []
        fetched_sources: list[tuple[int, SourceConfig, list[dict[str, Any]]]] = []

        for source in sources:
            source_run_id = _start_source_run(run_id, source, observed_at)
            try:
                rows = _FETCHERS[source.platform](source, observed_at)
                fetched_sources.append((source_run_id, source, rows))
                source_status[source.source_id] = "ok"
                log.info(
                    "Agent compliance source %s returned %d observations",
                    source.source_name, len(rows),
                )
            except Exception as exc:
                log.exception("Agent compliance source failed: %s", source.source_name)
                _finish_source_run(source_run_id, "failed", 0, str(exc))
                source_status[source.source_id] = "failed"

        sync_clients_from_observations([
            obs
            for _, _, rows in fetched_sources
            for obs in rows
        ], run_id=run_id, observed_at=observed_at)
        clients = load_clients()
        aliases = load_aliases()
        for source_run_id, source, rows in fetched_sources:
            resolved = _resolve_observations(rows, source, clients, aliases)
            _insert_observations(source_run_id, resolved)
            _finish_source_run(source_run_id, "ok", len(resolved), None)
            all_observations.extend(resolved)
        alignment_by_client = _load_alignment_by_client()

        matrix_rows, finding_rows = _build_matrix_and_findings(
            run_id=run_id,
            observed_at=observed_at,
            observations=all_observations,
            clients=clients,
            requirements=requirements,
            sources=sources,
            source_status=source_status,
            alignment_by_client=alignment_by_client,
        )
        _write_matrix(run_id, matrix_rows)
        _write_findings(finding_rows)
        alerts_sent = alerts.process_alerts(run_id, observed_at)

        stats["rows_inserted"] = len(all_observations) + len(matrix_rows) + len(finding_rows)
        stats["rows_upserted"] = len(matrix_rows)
        stats["alerts_sent"] = alerts_sent
        return len(matrix_rows), len(finding_rows)


def _clear_stuck_source_runs() -> None:
    """Reap source_runs left in 'running' from a prior crash.

    Without this, container restarts mid-cycle leave perpetual 'running'
    rows that confuse v_source_health_current ("DISTINCT ON latest run
    per source ORDER BY started_at DESC") and break the Source Failures
    KPI. We use a 1h floor so a healthy in-flight run is not clobbered.
    """
    with db.transaction() as cur:
        cur.execute(
            """
            UPDATE ninja_agent_compliance.source_runs
            SET status = 'failed',
                finished_at = COALESCE(finished_at, now()),
                error_text = COALESCE(
                    error_text,
                    'Stuck in running state — cleaned up at next run start'
                )
            WHERE status = 'running'
              AND started_at < now() - INTERVAL '1 hour'
            """
        )


def _start_source_run(run_id: int, source: SourceConfig, started_at: datetime) -> int:
    with db.transaction() as cur:
        cur.execute(
            """
            INSERT INTO ninja_agent_compliance.source_runs
                (run_id, source_id, started_at, status)
            VALUES (%s, %s, %s, 'running')
            RETURNING source_run_id
            """,
            (run_id, source.source_id, started_at),
        )
        return cur.fetchone()[0]


def _finish_source_run(
    source_run_id: int,
    status: str,
    rows_observed: int,
    error_text: str | None,
) -> None:
    with db.transaction() as cur:
        cur.execute(
            """
            UPDATE ninja_agent_compliance.source_runs
            SET finished_at = now(),
                status = %s,
                rows_observed = %s,
                error_text = %s
            WHERE source_run_id = %s
            """,
            (status, rows_observed, error_text[:5000] if error_text else None, source_run_id),
        )


def _resolve_observations(
    observations: list[dict[str, Any]],
    source: SourceConfig,
    clients: dict[int, Any],
    aliases: dict[tuple[str, str, str], int],
) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for obs in observations:
        if source.platform == "ScreenConnect" and source.client_id:
            client_id = source.client_id
            method = "source"
        else:
            client_id, method = resolve_client_id(
                aliases,
                source.platform,
                obs.get("platform_group_name"),
                obs.get("platform_group_id"),
            )
        client = clients.get(client_id) if client_id else None
        obs["resolved_client_id"] = client_id
        obs["resolved_client_name"] = client.client_name if client else None
        obs["resolution_method"] = method
        obs["confidence"] = 100 if client_id else 0
        resolved.append(obs)
    return resolved


def _insert_observations(source_run_id: int, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    insert_rows = []
    for row in rows:
        r = dict(row)
        r["source_run_id"] = source_run_id
        insert_rows.append(r)
    with db.transaction() as cur:
        columns = list(insert_rows[0].keys())
        placeholders = ", ".join(f"%({c})s" for c in columns)
        cur.executemany(
            f"""
            INSERT INTO ninja_agent_compliance.platform_observations
                ({", ".join(columns)})
            VALUES ({placeholders})
            """,
            insert_rows,
        )


def _build_matrix_and_findings(
    run_id: int,
    observed_at: datetime,
    observations: list[dict[str, Any]],
    clients: dict[int, Any],
    requirements: list[Any],
    sources: list[SourceConfig],
    source_status: dict[int, str],
    alignment_by_client: dict[int, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    observations = _apply_prefix_matches(observations)
    by_client_norm: dict[tuple[int, str], list[dict[str, Any]]] = {}
    clients_by_norm: dict[str, set[int]] = {}
    for obs in observations:
        client_id = obs.get("resolved_client_id")
        if not client_id:
            continue
        key = (client_id, obs["norm_name"])
        by_client_norm.setdefault(key, []).append(obs)
        clients_by_norm.setdefault(obs["norm_name"], set()).add(client_id)

    source_failures = _source_failure_platforms(sources, source_status)
    matrix_rows: list[dict[str, Any]] = []
    finding_rows: list[dict[str, Any]] = []

    for (client_id, norm), obs_rows in by_client_norm.items():
        client = clients[client_id]
        primary = _primary_observation(obs_rows)
        device_scope = primary["device_type"]
        req = get_requirement(requirements, client_id, device_scope)
        max_age_days = req.max_age_days or client.default_max_age_days
        latest_by_platform = _latest_by_platform(obs_rows)
        no_av_exempt = _has_no_av_exemption(latest_by_platform.get("Ninja"))
        required = tuple(
            platform for platform in req.required_platforms
            if not (platform == "SentinelOne" and no_av_exempt)
        )
        observed_platforms = tuple(sorted(latest_by_platform))
        source_failed = tuple(
            platform for platform in required
            if _required_source_failed(platform, client_id, sources, source_status)
        )
        unknown = source_failed
        missing = tuple(
            platform for platform in required
            if platform not in latest_by_platform and platform not in unknown
        )
        stale = tuple(
            platform for platform, row in latest_by_platform.items()
            if platform in required and _is_stale(row.get("last_seen_at"), observed_at, max_age_days)
        )
        present_required = tuple(platform for platform in required if platform in latest_by_platform)
        active_required = tuple(
            platform for platform in present_required
            if _platform_active(latest_by_platform[platform], observed_at, max_age_days)
        )
        active_any = any(
            _platform_active(row, observed_at, max_age_days)
            for row in latest_by_platform.values()
        )
        present_any = bool(latest_by_platform)
        ps_is_stale = present_any and not active_any
        cross_client = len(clients_by_norm.get(norm, set())) > 1
        is_degraded = (
            not ps_is_stale
            and not missing
            and not unknown
            and len(present_required) > 0
            and len(active_required) < len(present_required)
        )
        # PowerShell parity: $isCompliant = $missing.Count -eq 0 (Multi_org_agent_compliance.ps1:1539).
        # IsStale and CrossOrgConflict are informational, not gates. We add `not unknown`
        # only because PS is one-shot and crashes on source failure; in our continuous
        # model an unreachable source must not silently flip a device non-compliant.
        is_compliant = not missing and not unknown
        alignment = alignment_by_client.get(client_id, {})
        signature = _hash("|".join([
            client.client_name,
            norm,
            ",".join(required),
            ",".join(missing),
            ",".join(stale),
            ",".join(unknown),
            str(cross_client),
            str(no_av_exempt),
            str(is_degraded),
        ]))
        ninja_info = _platform_info(latest_by_platform.get("Ninja"))
        sc_info = _platform_info(latest_by_platform.get("ScreenConnect"))
        s1_info = _platform_info(latest_by_platform.get("SentinelOne"))
        lmi_info = _platform_info(latest_by_platform.get("LogMeIn"))
        matrix = {
            "client_id": client_id,
            "client_name": client.client_name,
            "org_align_status": alignment.get("overall_status"),
            "ninja_status": alignment.get("ninja_status"),
            "sc_status": alignment.get("sc_status"),
            "s1_status": alignment.get("s1_status"),
            "lmi_status": alignment.get("lmi_status"),
            "ninja_platform_name": alignment.get("ninja_platform_name"),
            "s1_platform_name": alignment.get("s1_platform_name"),
            "lmi_platform_name": alignment.get("lmi_platform_name"),
            "norm_name": norm,
            "hostname": primary["hostname"],
            "device_type": device_scope,
            "os_name": primary.get("os_name"),
            "domain_name": primary.get("domain_name"),
            "required_platforms": list(required),
            "observed_platforms": list(observed_platforms),
            "missing_required_platforms": list(missing),
            "stale_required_platforms": list(stale),
            "unknown_required_platforms": list(unknown),
            "source_failed_platforms": list(source_failed),
            "is_compliant": is_compliant,
            "is_stale": ps_is_stale,
            "is_degraded": is_degraded,
            "is_unknown": bool(unknown),
            "cross_client_conflict": cross_client,
            "s1_exempt": no_av_exempt,
            "in_ninja": ninja_info["present"],
            "ninja_online": ninja_info["online"],
            "ninja_last_seen": ninja_info["last_seen"],
            "ninja_device_id": ninja_info["device_id"],
            "in_screenconnect": sc_info["present"],
            "screenconnect_online": sc_info["online"],
            "screenconnect_last_seen": sc_info["last_seen"],
            "screenconnect_device_id": sc_info["device_id"],
            "screenconnect_dup": _screenconnect_dup(latest_by_platform.get("ScreenConnect")),
            "in_sentinelone": s1_info["present"],
            "sentinelone_online": s1_info["online"],
            "sentinelone_last_seen": s1_info["last_seen"],
            "sentinelone_device_id": s1_info["device_id"],
            "in_logmein": lmi_info["present"],
            "logmein_online": lmi_info["online"],
            "logmein_last_seen": lmi_info["last_seen"],
            "logmein_device_id": lmi_info["device_id"],
            "finding_signature": signature,
            "evaluated_at": observed_at,
        }
        matrix_rows.append(matrix)
        finding_rows.extend(_findings_for_matrix(run_id, matrix, observed_at))

    finding_rows.extend(_source_failure_findings(run_id, sources, source_status, observed_at))
    return matrix_rows, finding_rows


def _source_failure_platforms(
    sources: list[SourceConfig],
    source_status: dict[int, str],
) -> dict[int, str]:
    return {
        source.source_id: source.platform
        for source in sources
        if source_status.get(source.source_id) == "failed"
    }


def _load_alignment_by_client() -> dict[int, dict[str, Any]]:
    with db.transaction() as cur:
        cur.execute(
            """
            SELECT
                client_id, overall_status, ninja_status, sc_status,
                s1_status, lmi_status, ninja_platform_name,
                s1_platform_name, lmi_platform_name
            FROM ninja_agent_compliance.org_alignment_current
            """
        )
        rows = cur.fetchall()
    return {
        row[0]: {
            "overall_status": row[1],
            "ninja_status": row[2],
            "sc_status": row[3],
            "s1_status": row[4],
            "lmi_status": row[5],
            "ninja_platform_name": row[6],
            "s1_platform_name": row[7],
            "lmi_platform_name": row[8],
        }
        for row in rows
    }


def _apply_prefix_matches(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge unique truncated hostname matches within the same resolved client."""
    norms_by_client: dict[int, set[str]] = {}
    for obs in observations:
        client_id = obs.get("resolved_client_id")
        norm = obs.get("norm_name")
        if client_id and norm:
            norms_by_client.setdefault(client_id, set()).add(norm)

    canonical_by_client_norm: dict[tuple[int, str], str] = {}
    for client_id, norms in norms_by_client.items():
        for norm in norms:
            candidates = [
                other for other in norms
                if other != norm
                and min(len(other), len(norm)) >= 10
                and (other.startswith(norm) or norm.startswith(other))
            ]
            if len(candidates) == 1:
                candidate = candidates[0]
                canonical_by_client_norm[(client_id, norm)] = (
                    candidate if len(candidate) > len(norm) else norm
                )

    if not canonical_by_client_norm:
        return observations

    merged: list[dict[str, Any]] = []
    for obs in observations:
        client_id = obs.get("resolved_client_id")
        norm = obs.get("norm_name")
        canonical = canonical_by_client_norm.get((client_id, norm))
        if canonical and canonical != norm:
            obs = dict(obs)
            obs["match_name"] = canonical
            obs["norm_name"] = canonical
        merged.append(obs)
    return merged


def _required_source_failed(
    platform: str,
    client_id: int,
    sources: list[SourceConfig],
    source_status: dict[int, str],
) -> bool:
    matching = [
        source for source in sources
        if source.platform == platform
        and (source.is_shared or source.client_id == client_id)
    ]
    return not matching or all(
        source_status.get(source.source_id) == "failed" for source in matching
    )


def _primary_observation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    order = {"Ninja": 0, "SentinelOne": 1, "ScreenConnect": 2, "LogMeIn": 3}
    return sorted(rows, key=lambda row: order.get(row["platform"], 99))[0]


def _latest_by_platform(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        current = latest.get(row["platform"])
        if current is None:
            latest[row["platform"]] = row
            continue
        if (row.get("last_seen_at") or row["observed_at"]) > (
            current.get("last_seen_at") or current["observed_at"]
        ):
            latest[row["platform"]] = row
    return latest


def _has_no_av_exemption(ninja_row: dict[str, Any] | None) -> bool:
    if not ninja_row:
        return False
    raw = _raw_json_obj(ninja_row.get("raw_data"))
    marker = raw.get("_agent_compliance", {}) if isinstance(raw, dict) else {}
    return bool(marker.get("no_av_exempt"))


def _raw_json_obj(value: Any) -> Any:
    if hasattr(value, "obj"):
        return value.obj
    return value


def _is_stale(value: datetime | None, now: datetime, max_age_days: int) -> bool:
    if value is None:
        return True
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return (now - value).days > max_age_days


def _platform_active(row: dict[str, Any], now: datetime, max_age_days: int) -> bool:
    if row.get("is_online") is True:
        return True
    last_seen = row.get("last_seen_at")
    return not _is_stale(last_seen, now, max_age_days)


def _platform_info(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {
            "present": False,
            "online": None,
            "last_seen": None,
            "device_id": "",
        }
    return {
        "present": True,
        "online": row.get("is_online"),
        "last_seen": row.get("last_seen_at"),
        "device_id": row.get("platform_device_id") or "",
    }


def _screenconnect_dup(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    raw = _raw_json_obj(row.get("raw_data"))
    return bool(raw.get("IsDup")) if isinstance(raw, dict) else False


def _findings_for_matrix(
    run_id: int,
    matrix: dict[str, Any],
    now: datetime,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for platform in matrix["missing_required_platforms"]:
        findings.append(_finding(
            run_id, matrix, now, "missing_required_platform", platform,
            _severity("missing_required_platform", platform),
            f"{matrix['hostname']} is missing required {platform}",
            {"missing_platform": platform},
        ))
    for platform in matrix["stale_required_platforms"]:
        findings.append(_finding(
            run_id, matrix, now, "stale_required_platform", platform,
            _severity("stale_required_platform", platform),
            f"{matrix['hostname']} has stale {platform} check-in data",
            {"stale_platform": platform},
        ))
    if matrix["cross_client_conflict"]:
        findings.append(_finding(
            run_id, matrix, now, "cross_client_conflict", None, "high",
            f"{matrix['hostname']} appears under multiple clients",
            {"norm_name": matrix["norm_name"]},
        ))
    return findings


def _source_failure_findings(
    run_id: int,
    sources: list[SourceConfig],
    source_status: dict[int, str],
    now: datetime,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in sources:
        if source_status.get(source.source_id) != "failed":
            continue
        signature = _hash(f"source_failure|{source.source_id}|{source.platform}")
        rows.append({
            "run_id": run_id,
            "finding_signature": signature,
            "finding_type": "source_failure",
            "affected_platform": source.platform,
            "source_id": source.source_id,
            "client_id": source.client_id,
            "client_name": source.client_name,
            "norm_name": None,
            "hostname": source.source_name,
            "device_type": None,
            "severity": "high" if source.platform != "Ninja" else "critical",
            "summary": f"{source.source_name} collector failed",
            "details": Json({
                "source_key": source.source_key,
                "platform": source.platform,
                "client_name": source.client_name,
            }),
            "status": "active",
            "first_seen_at": now,
            "last_seen_at": now,
        })
    return rows


def _finding(
    run_id: int,
    matrix: dict[str, Any],
    now: datetime,
    finding_type: str,
    affected_platform: str | None,
    severity: str,
    summary: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    signature = _hash("|".join([
        finding_type,
        matrix["client_name"],
        matrix["norm_name"],
        affected_platform or "multiple",
    ]))
    details.update({
        "required_platforms": matrix["required_platforms"],
        "observed_platforms": matrix["observed_platforms"],
    })
    return {
        "run_id": run_id,
        "finding_signature": signature,
        "finding_type": finding_type,
        "affected_platform": affected_platform,
        "source_id": None,
        "client_id": matrix["client_id"],
        "client_name": matrix["client_name"],
        "norm_name": matrix["norm_name"],
        "hostname": matrix["hostname"],
        "device_type": matrix["device_type"],
        "severity": severity,
        "summary": summary,
        "details": Json(details),
        "status": "active",
        "first_seen_at": now,
        "last_seen_at": now,
    }


def _severity(finding_type: str, platform: str | None) -> str:
    if finding_type == "missing_required_platform" and platform in {"Ninja", "SentinelOne"}:
        return "critical"
    if finding_type == "missing_required_platform":
        return "high"
    return "medium"


def _write_matrix(run_id: int, rows: list[dict[str, Any]]) -> None:
    with db.transaction() as cur:
        cur.execute("DELETE FROM ninja_agent_compliance.compliance_matrix_current")
        if rows:
            matrix_cols = list(rows[0].keys())
            placeholders = ", ".join(f"%({c})s" for c in matrix_cols)
            cur.executemany(
                f"""
                INSERT INTO ninja_agent_compliance.compliance_matrix_current
                    ({", ".join(matrix_cols)})
                VALUES ({placeholders})
                """,
                rows,
            )
            history_rows = [dict(row, run_id=run_id) for row in rows]
            history_cols = list(history_rows[0].keys())
            history_placeholders = ", ".join(f"%({c})s" for c in history_cols)
            cur.executemany(
                f"""
                INSERT INTO ninja_agent_compliance.compliance_matrix_history
                    ({", ".join(history_cols)})
                VALUES ({history_placeholders})
                """,
                history_rows,
            )


def _write_findings(rows: list[dict[str, Any]]) -> None:
    with db.transaction() as cur:
        if not rows:
            return
        columns = list(rows[0].keys())
        placeholders = ", ".join(f"%({c})s" for c in columns)
        cur.executemany(
            f"""
            INSERT INTO ninja_agent_compliance.compliance_findings
                ({", ".join(columns)})
            VALUES ({placeholders})
            """,
            rows,
        )


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
