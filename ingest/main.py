"""Ingest entry point.

Boot sequence:
  1. Load settings, configure logging.
  2. Start HTTP server FIRST in a background thread so /healthz is
     reachable immediately. Docker HEALTHCHECK polls this — if the
     server isn't up within start-period, the container gets killed
     mid-startup (which historically caused migration rollback loops).
     /readyz reports starting/ready state; /healthz is always green
     once the listener binds.
  3. Initialize DB pool.
  4. Apply pending migrations.
  5. Start APScheduler at the configured interval. No jobs wired yet —
     each ingest module adds its job once it lands.
  6. Catch-up: if the last successful core run is older than the
     schedule interval, fire run_once now in a background thread.
     Fresh installs (no run_log rows) wait for the first scheduled tick.
  7. Mark service ready; block forever serving HTTP.
"""

from __future__ import annotations

from html import escape
import http.server
import logging
import socketserver
import threading
import time
from urllib.parse import parse_qs, quote, urlparse
from datetime import datetime, timedelta, timezone

import httpx
from apscheduler.schedulers.background import BackgroundScheduler

from ingest import db, migrations, retention_observations
from ingest.derived import refresh_after_collection
from ingest.config import settings
from ingest.logging_utils import install_log_safety
from ingest.activities import ingest as activities_ingest
from ingest.agent_compliance import ingest as agent_compliance_ingest
from ingest.agent_compliance import review_digest
from ingest.source_observations import (
    SourceObservationFailure,
    is_identity_source,
    run_source_observations,
)
from ingest import operator_job_queue
from ingest.inventory import software as software_ingest
from ingest.inventory import queue as software_queue
from ingest.runlog import run_log
from ingest.sources import load_sources
from ingest.agent_compliance.config_loader import (
    add_device_ignore,
    add_device_merge_decision,
    add_human_decision,
    add_org_exclude,
    approve_customer_name,
    bulk_ignore_devices,
    promote_alignment_aliases,
    remove_org_exclude,
    remove_device_ignore,
    set_customer_max_age,
    set_customer_requirement,
    toggle_customer_required_platform,
)
from ingest.url_utils import redact_url
from ingest.core import (
    custom_fields,
    device_health,
    devices,
    locations,
    organizations,
    policies,
)
from ingest.policy_scope import sync_patching_enabled_policies
from ingest.ninja_client import NinjaClient
from ingest.evaluator import evaluate as platform_evaluate
from ingest.notifications import dispatch as notify_dispatch
from ingest.notifications_digest import send_digest as notify_send_digest
from ingest.patch_findings import classify as patch_classify
from ingest.parity_check import run as parity_check_run
from ingest.software_findings import classify as software_classify
from ingest.identity.client_resolver import drain_client_resolution as _drain_client_resolution
from ingest.identity.resolver import drain_resolution as _drain_resolution
from ingest import scope_selector as _scope_selector
from ingest.patches import ingest as patches_ingest
from ingest.summary_views import refresh_device_troubleshooting_signal
from shared.jobs_registry import definition_keys, validate_registry

log = logging.getLogger("ingest.main")
_AGENT_COMPLIANCE_LOCK = threading.Lock()
_PATCH_CYCLE_LOCK_ID = 6_803_904_731_027_441

def run_once() -> None:
    run_patching_once()


def run_patching_once() -> bool:
    """Execute one full patch/Ninja ingest cycle. Modules run in dependency order
    with per-module exception isolation: a failure in one module is
    logged with status='failed' in run_log and the rest continue.
    Shared `snapshot_at` so all rows from a single run carry the
    same first/last_observed_at."""
    with db.pool.connection() as lock_conn, lock_conn.cursor() as lock_cur:
        lock_cur.execute("SELECT pg_try_advisory_lock(%s)", (_PATCH_CYCLE_LOCK_ID,))
        if not lock_cur.fetchone()[0]:
            log.info("Patch ingest run skipped; another process holds the cycle lock")
            return False
        try:
            with run_log("patch_cycle"):
                log.info("Patch ingest run starting")
                snapshot_at = datetime.now(timezone.utc)
                failures: list[tuple[str, Exception]] = []
                with NinjaClient(
                    base_url=settings.NINJA_BASE_URL,
                    token_url=settings.NINJA_TOKEN_URL,
                    client_id=settings.NINJA_CLIENT_ID,
                    client_secret=settings.NINJA_CLIENT_SECRET.get_secret_value(),
                    scope=settings.NINJA_SCOPE,
                ) as client:
                    for failure in (
                        _safe("organizations", organizations.run, client),
                        _safe("locations", locations.run, client),
                        _safe("policies", policies.run, client),
                        _safe("patching_enabled_policies", sync_patching_enabled_policies),
                        _safe("devices", devices.run, client, snapshot_at),
                        _safe("device_health", device_health.run, client, snapshot_at),
                        _safe("custom_fields", custom_fields.run, client, snapshot_at),
                    ):
                        if failure:
                            failures.append(failure)
                    # Patching-scope matview reads ninja_core.custom_field_values +
                    # ninja_core.policies + ops.devices; must refresh AFTER
                    # custom_fields ingest lands. Track O batch O4.
                    for failure in (
                        _safe("patching_scope_refresh", devices.refresh_patching_scope_current),
                        _safe("patches", patches_ingest.run, client, snapshot_at),
                        _safe("activities", activities_ingest.run, client),
                        _safe("troubleshooting_signal", refresh_device_troubleshooting_signal),
                    ):
                        if failure:
                            failures.append(failure)
                for failure in (
                    _safe("derived_refresh", refresh_after_collection, "Ninja patch collection"),
                    _safe("windows_servicing", run_windows_servicing_once),
                ):
                    if failure:
                        failures.append(failure)
                _raise_step_failures("Patch collection", failures)
                log.info("Patch ingest run complete")
            return True
        finally:
            lock_cur.execute("SELECT pg_advisory_unlock(%s)", (_PATCH_CYCLE_LOCK_ID,))


def run_identity_resolver_once(*, refresh_current: bool = True) -> None:
    """Drain unresolved observations and optionally refresh presence state."""
    failures: list[tuple[str, Exception]] = []
    try:
        attached = _drain_client_resolution()
        log.info("Client resolver complete: attached=%d", attached)
    except Exception as exc:
        log.exception("Client resolver failed")
        failures.append(("client resolver", exc))
    try:
        resolved = _drain_resolution(batch_size=500, refresh_current=refresh_current)
        log.info("Identity resolver complete: resolved=%d", resolved)
    except Exception as exc:
        log.exception("Identity resolver failed")
        failures.append(("identity resolver", exc))
    _raise_step_failures("Identity resolution", failures)


def run_ninja_observations_once() -> None:
    """Sync Ninja orgs + devices into Operations without the full patch cycle.

    Runs org/location/device sync only — populates operations.devices,
    source links, and entity_observations (agent.rmm), then refreshes
    device_agent_presence_current. Skips device-health, patches, activities,
    and custom fields, so it completes in seconds instead of minutes.
    Used by the source run queue demand trigger.
    """
    log.info("Ninja observations run starting")
    snapshot_at = datetime.now(timezone.utc)
    failures: list[tuple[str, Exception]] = []
    with NinjaClient(
        base_url=settings.NINJA_BASE_URL,
        token_url=settings.NINJA_TOKEN_URL,
        client_id=settings.NINJA_CLIENT_ID,
        client_secret=settings.NINJA_CLIENT_SECRET.get_secret_value(),
        scope=settings.NINJA_SCOPE,
    ) as client:
        for failure in (
            _safe("organizations", organizations.run, client),
            _safe("locations", locations.run, client),
            _safe("devices", devices.run, client, snapshot_at),
        ):
            if failure:
                failures.append(failure)
    for failure in (
        _safe("derived_refresh", refresh_after_collection, "Ninja observations collection"),
        _safe("windows_servicing", run_windows_servicing_once),
    ):
        if failure:
            failures.append(failure)
    _raise_step_failures("Ninja observations", failures)
    log.info("Ninja observations run complete")


def run_agent_observations_once() -> None:
    """Fetch S1/SC/LMI and write to entity_observations, then resolve device IDs.

    INTERIM (see `.work/backlog.md` "Honour source_bindings.schedule"): the
    source list is filtered to identity-signal sources so slow documentation
    collectors do not delay live agent telemetry on this cycle. Reverting to
    a single unified cycle means dropping this filter and the companion
    `run_documentation_observations_once` job — or, without a code change,
    setting DOCUMENTATION_SCHEDULE_HOURS equal to
    AGENT_COMPLIANCE_SCHEDULE_HOURS.
    """
    try:
        sources = [s for s in load_sources() if is_identity_source(s)]
        observed_at = datetime.now(timezone.utc)
        collection_failure = None
        try:
            counts = run_source_observations(sources, observed_at)
        except SourceObservationFailure as exc:
            counts = exc.counts
            collection_failure = exc
        total = sum(counts.values())
        refresh_after_collection("agent observations collection")
        if collection_failure:
            raise collection_failure
        log.info("Agent observations run complete: %s total=%d", counts, total)
    except Exception:
        log.exception("Agent observations run failed")
        raise


def run_documentation_observations_once() -> None:
    """Fetch non-identity sources on their own slower cadence.

    Covers every source outside IDENTITY_ENTITY_TYPES, which today means the
    CMDB class (Hudu, entity_type `cmdb.asset`). A second CMDB — or any future
    non-identity source — lands here automatically with no code change.

    Split from the agent cycle because such sources change daily at most,
    while that cycle runs every 4h — Hudu alone is ~122 paginated requests,
    and `load_sources()` orders by name so it would precede and delay every
    agent source. Same writer and run-log semantics as the agent cycle; only
    the schedule differs.

    INTERIM alongside `run_agent_observations_once` — see that docstring and
    the backlog entry for the revert path.

    Startup catch-up is conditional on source freshness, so an ordinary
    deploy does not refetch a current asset set but cannot postpone an overdue
    reconciliation indefinitely.
    """
    try:
        sources = [s for s in load_sources() if not is_identity_source(s)]
        if not sources:
            log.info("Documentation observations: no documentation sources enabled")
            return
        observed_at = datetime.now(timezone.utc)
        collection_failure = None
        try:
            counts = run_source_observations(sources, observed_at)
        except SourceObservationFailure as exc:
            counts = exc.counts
            collection_failure = exc
        total = sum(counts.values())
        refresh_after_collection("documentation observations collection")
        if collection_failure:
            raise collection_failure
        log.info("Documentation observations run complete: %s total=%d", counts, total)
    except Exception:
        log.exception("Documentation observations run failed")
        raise


def documentation_observations_overdue(sources: list, schedule_hours: int) -> bool:
    """Return whether any enabled documentation source lacks a recent success.

    APScheduler starts an interval from process startup. Without this check,
    an otherwise ordinary deployment can keep moving a documentation source's
    next run into the future. Source observations write to ``operations``
    run_log, not the legacy Ninja run log used by ``should_catch_up``.
    """
    documentation_sources = [
        source for source in sources if not is_identity_source(source)
    ]
    if not documentation_sources:
        return False

    source_kinds = [
        f"source.{source.platform}.{source.source_key}".rstrip(".")
        for source in documentation_sources
    ]
    try:
        with db.transaction() as cur:
            cur.execute(
                """
                SELECT kind, MAX(ended_at)
                FROM operations.run_log
                WHERE tenant_id = 1
                  AND ok
                  AND kind = ANY(%s)
                GROUP BY kind
                """,
                (source_kinds,),
            )
            latest_by_kind = dict(cur.fetchall())
    except Exception:
        log.exception("Documentation catch-up status probe failed; scheduling run")
        return True

    cutoff = datetime.now(timezone.utc) - timedelta(hours=schedule_hours)
    for kind in source_kinds:
        last_success = latest_by_kind.get(kind)
        if last_success is None:
            return True
        if last_success.tzinfo is None:
            last_success = last_success.replace(tzinfo=timezone.utc)
        if last_success < cutoff:
            return True
    return False


def run_agent_compliance_once() -> None:
    if not settings.AGENT_COMPLIANCE_ENABLED:
        raise RuntimeError("Agent compliance is disabled")
    if not _AGENT_COMPLIANCE_LOCK.acquire(blocking=False):
        raise RuntimeError("Another agent compliance operation is already running")
    log.info("Agent compliance run starting")
    try:
        agent_compliance_ingest.run()
    finally:
        _AGENT_COMPLIANCE_LOCK.release()
    log.info("Agent compliance run complete")


def run_agent_compliance_evaluate_once() -> None:
    if not settings.AGENT_COMPLIANCE_ENABLED:
        raise RuntimeError("Agent compliance is disabled")
    if not _AGENT_COMPLIANCE_LOCK.acquire(blocking=False):
        raise RuntimeError("Another agent compliance operation is already running")
    log.info("Agent compliance evaluate starting")
    try:
        agent_compliance_ingest.evaluate(send_alerts=True)
    finally:
        _AGENT_COMPLIANCE_LOCK.release()
    log.info("Agent compliance evaluate complete")


def enqueue_all_orgs_once() -> None:
    """Populate Q1 with one entry per Ninja org. Dedup prevents duplicates
    when the previous sweep hasn't fully drained yet."""
    if not settings.SOFTWARE_QUEUE_ENABLED:
        return
    with db.transaction() as cur:
        cur.execute("SELECT id FROM ninja_core.organizations ORDER BY id")
        org_ids = [row[0] for row in cur.fetchall()]
    if not org_ids:
        log.warning("enqueue_all_orgs: no orgs in ninja_core.organizations — skipping")
        return
    enqueued = sum(
        software_queue.enqueue_scheduled(org_id, reason="ninja.ingest.scheduled_sweep")
        for org_id in org_ids
    )
    log.info("Scheduled sweep enqueue: %d / %d orgs added to Q1", enqueued, len(org_ids))


def run_software_queue_once(job_run_id: object) -> int:
    """Drain governed demand, activity, and scheduled software work."""
    if not settings.SOFTWARE_QUEUE_ENABLED:
        return 0
    with NinjaClient(
        base_url=settings.NINJA_BASE_URL,
        token_url=settings.NINJA_TOKEN_URL,
        client_id=settings.NINJA_CLIENT_ID,
        client_secret=settings.NINJA_CLIENT_SECRET.get_secret_value(),
        scope=settings.NINJA_SCOPE,
    ) as client:
        result = software_queue.drain_background(
            client, settings.SOFTWARE_QUEUE_WORKER_BATCH, job_run_id
        )
    demand = result["demand"]
    activity = result["activity"]
    scheduled = result["scheduled"]
    if demand or activity or scheduled:
        software_ingest.refresh_read_models()
    log.info(
        "Software queue drain complete: demand=%d activity=%d scheduled=%d",
        demand, activity, scheduled,
    )
    if result["failed"]:
        raise RuntimeError(
            f"{result['failed']} software queue item(s) failed; retained for review or retry"
        )
    return demand + activity + scheduled


def schedule_agent_compliance_evaluate(reason: str) -> bool:
    if not settings.AGENT_COMPLIANCE_ENABLED or not _READY.is_set():
        return False
    log.info("Scheduling agent compliance evaluate: %s", reason)
    try:
        operator_job_queue.request_system_job(
            "agent-compliance-evaluate", f"agent-compliance-action:{reason}"
        )
        return True
    except Exception:
        log.exception("Could not request agent compliance evaluation")
        return False


def run_platform_evaluate_once() -> None:
    """Run the platform evaluator for tenant 1."""
    try:
        affected = platform_evaluate(tenant_id=1)
        log.info("Platform evaluate complete: findings_affected=%d", affected)
    except Exception:
        log.exception("Platform evaluate failed")


def run_windows_servicing_once() -> None:
    """Refresh Windows servicing state after device or corpus evidence changes."""
    from ingest.intel.windows_servicing import project_and_evaluate, rollout_summary

    affected = project_and_evaluate(tenant_id=1)
    summary = rollout_summary(tenant_id=1)
    if summary["invalid_rows"]:
        raise RuntimeError("Windows servicing lifecycle validation failed")
    log.info(
        "Windows servicing lifecycle complete: findings_affected=%d states=%s",
        affected,
        summary["states"],
    )


def run_intel_nvd_once() -> None:
    try:
        from ingest.intel import nvd
        rows = nvd.run_once()
        log.info("Intel NVD complete: rows=%d", rows)
    except Exception:
        log.exception("Intel NVD failed")


def run_intel_cpe_dict_once() -> None:
    try:
        from ingest.intel import cpe_dict
        rows = cpe_dict.run_once()
        log.info("Intel CPE dict complete: rows=%d", rows)
    except Exception:
        log.exception("Intel CPE dict failed")


def run_intel_kev_once() -> None:
    try:
        from ingest.intel import cisa_kev
        rows = cisa_kev.run_once()
        log.info("Intel CISA KEV complete: rows=%d", rows)
    except Exception:
        log.exception("Intel CISA KEV failed")


def run_intel_epss_once() -> None:
    try:
        from ingest.intel import epss
        rows = epss.run_once()
        log.info("Intel EPSS complete: rows=%d", rows)
    except Exception:
        log.exception("Intel EPSS failed")


def run_intel_matcher_once() -> None:
    try:
        from ingest.intel import matcher
        rows = matcher.run_once()
        log.info("Intel matcher complete: rows=%d", rows)
    except Exception:
        log.exception("Intel matcher failed")


def run_intel_winget_once() -> None:
    try:
        from ingest.intel import winget
        rows = winget.run_once()
        log.info("Intel Winget complete: rows=%d", rows)
    except Exception:
        log.exception("Intel Winget failed")


def run_intel_chocolatey_once() -> None:
    try:
        from ingest.intel import chocolatey
        rows = chocolatey.run_once()
        log.info("Intel Chocolatey complete: rows=%d", rows)
    except Exception:
        log.exception("Intel Chocolatey failed")


def run_intel_otx_once() -> None:
    try:
        from ingest.intel import otx
        rows = otx.run_once()
        log.info("Intel OTX complete: rows=%d", rows)
    except Exception:
        log.exception("Intel OTX failed")


def run_intel_abusech_once() -> None:
    try:
        from ingest.intel import abusech
        rows = abusech.run_once()
        log.info("Intel abuse.ch complete: rows=%d", rows)
    except Exception:
        log.exception("Intel abuse.ch failed")


def run_intel_endoflife_once() -> int:
    from ingest.intel import endoflife, eol_match

    failures: list[tuple[str, Exception]] = []
    changed = 0
    material_changed = False
    try:
        outcome = endoflife.run_once()
        changed += int(outcome or 0)
        material_changed = material_changed or bool(
            getattr(outcome, "material_changed", False)
        )
    except Exception as exc:
        log.exception("end-of-life fetch failed; continuing with retained corpus")
        failures.append(("end-of-life fetch", exc))
    # Projection follows the fetch in the same job: a refreshed corpus that
    # never reaches catalog.software_versions.eol_date changes nothing an
    # operator can see. Runs even if the fetch failed, so a corpus already on
    # disk still projects.
    try:
        outcome = eol_match.run_once()
        changed += int(outcome or 0)
        material_changed = material_changed or bool(
            getattr(outcome, "material_changed", False)
        )
    except Exception as exc:
        log.exception("end-of-life projection failed")
        failures.append(("end-of-life projection", exc))
    # Windows servicing state is another projection of this same corpus.  Run
    # it even after a fetch failure so an already-retained corpus still reaches
    # device findings, matching the software EOL projector above.
    failure = _safe("windows servicing", run_windows_servicing_once)
    if failure:
        failures.append(failure)
    _raise_step_failures("End-of-life intelligence", failures)
    from ingest.intel.material import MaterialCount

    return MaterialCount(changed, material_changed=material_changed)


def run_notifications_dispatch_once() -> None:
    try:
        sent = notify_dispatch(tenant_id=1)
        log.info("Notifications dispatch complete: sent=%d", sent)
    except Exception:
        log.exception("Notifications dispatch failed")


def run_notifications_digest_once() -> None:
    try:
        fired = notify_send_digest(tenant_id=1)
        log.info("Notifications digest complete: routes_fired=%d", fired)
    except Exception:
        log.exception("Notifications digest failed")


def run_software_classify_once(*, with_intel_pre_steps: bool = True) -> None:
    """Classify software findings, optionally enriching intel first.

    `with_intel_pre_steps` is True for the manual `/run/software-classify`
    trigger, where nothing else guarantees the intel tables are fresh. The
    scheduled job passes False: the matcher, Winget and Chocolatey enrichers
    are already registered as their own scheduler jobs, so running them here
    too would duplicate that work on every classifier tick.
    """
    # When intel is enabled, the intel matcher + Winget/Chocolatey
    # enrichers run first so the classifier sees fresh cve_match rows
    # and safety_signal rows for newly ingested products. Each intel
    # step is best-effort and never blocks the classifier itself.
    if with_intel_pre_steps and settings.INTEL_ENABLED:
        for step_name, step_fn in (
            ("intel matcher pre-classify",     run_intel_matcher_once),
            ("intel Winget pre-classify",      run_intel_winget_once),
            ("intel Chocolatey pre-classify",  run_intel_chocolatey_once),
        ):
            try:
                step_fn()
            except Exception:
                log.exception("Best-effort intel step failed: %s", step_name)
    try:
        affected = software_classify(
            tenant_id=1, incremental=not with_intel_pre_steps
        )
        log.info("Software classifier complete: affected=%d", affected)
    except Exception:
        log.exception("Software classifier failed")
    # Refresh the software risk matview so the UI reflects fresh
    # findings + decisions. Best-effort — never blocks the classifier.
    try:
        with db.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("REFRESH MATERIALIZED VIEW operations.v_software_safety")
        log.info("Refreshed operations.v_software_safety matview")
    except Exception:
        log.exception("Failed to refresh v_software_safety matview")


def run_software_classify_scheduled() -> None:
    """Scheduler entry point for the software classifier.

    Named rather than a lambda so the job id, the log line and the traceback
    all identify it. See `run_software_classify_once` for why the intel
    pre-steps are skipped on this path.
    """
    run_software_classify_once(with_intel_pre_steps=False)


def software_classify_overdue(
    schedule_hours: int, now: datetime | None = None, *, mode: str | None = None
) -> bool:
    """True when the selected classifier mode's last run is overdue.

    Deliberately not `should_catch_up()`: that helper reads
    `ninja_core.run_log` on `domain`/`status`/`finished_at`, while the
    classifier records itself in `operations.run_log` on `kind`/`ok`/
    `ended_at`. Passing 'software_classifier' to it would match no row,
    return False, and disable this catch-up silently.

    ``mode=None`` covers every classifier run; ``mode='full'`` checks only
    authoritative rebuilds. Returns True when there is no successful run at
    all. That differs from
    `should_catch_up`, which returns False for a never-run domain to avoid
    kicking a fresh install; here a missing row is the exact condition we
    need to correct, and the classifier reads existing tables rather than
    calling a vendor API.
    """
    now = now or datetime.now(timezone.utc)
    try:
        with db.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT ended_at FROM operations.run_log
                WHERE kind = 'software_classifier' AND ok
                  AND (%s::text IS NULL OR subject_ref->>'mode' = %s::text)
                ORDER BY started_at DESC
                LIMIT 1
                """
                ,
                (mode, mode),
            )
            row = cur.fetchone()
    except Exception:
        # A probe failure must not decide "recent" and skip the run.
        log.exception("Software classifier catch-up probe failed — assuming overdue")
        return True
    if row is None or row[0] is None:
        return True
    ended_at = row[0]
    if ended_at.tzinfo is None:
        ended_at = ended_at.replace(tzinfo=timezone.utc)
    return (now - ended_at) > timedelta(hours=schedule_hours)


def run_intel_capability_once() -> None:
    """Project capability evidence from the rule table.

    Shadow mode: this records assertions and nothing consumes them for
    enforcement. `unauthorized_*` emission is unchanged until the Phase 4
    enablement gate, which needs its own approval.
    """
    try:
        from ingest.intel import capability_match

        rows = capability_match.run_once()
        log.info("Capability projection complete: rows=%d", rows)
    except Exception:
        log.exception("Capability projection failed")


def run_intel_category_once() -> None:
    """Project general-category evidence from Winget/Chocolatey tags.

    A different axis from capability (migration 104): descriptive taxonomy,
    never alertable, never consumed by any finding. Nothing enforces this --
    there is nothing to enforce.
    """
    try:
        from ingest.intel import category_match

        rows = category_match.run_once()
        log.info("Category projection complete: rows=%d", rows)
    except Exception:
        log.exception("Category projection failed")


def run_intel_lolrmm_once() -> None:
    """Refresh the LOLRMM corpus and exact local-product assertions."""
    try:
        from ingest.intel import lolrmm

        rows = lolrmm.run_once()
        log.info("LOLRMM corpus refresh complete: rows=%d", rows)
    except Exception:
        log.exception("LOLRMM corpus refresh failed")


def run_patch_classify_once() -> None:
    try:
        affected = patch_classify(tenant_id=1)
        log.info("Patch classifier complete: affected=%d", affected)
    except Exception:
        log.exception("Patch classifier failed")


def run_parity_check_once() -> None:
    try:
        rows = parity_check_run(tenant_id=1)
        log.info("Parity check complete: rows=%d", rows)
    except Exception:
        log.exception("Parity check failed")


def run_review_digest_once() -> None:
    if not settings.AGENT_COMPLIANCE_ENABLED:
        raise RuntimeError("Agent compliance is disabled")
    if not settings.AGENT_COMPLIANCE_REVIEW_DIGEST_ENABLED:
        raise RuntimeError("Agent compliance review digest is disabled")
    log.info("Review digest starting")
    with run_log("agent_compliance.review_digest") as stats:
        sent = review_digest.send_review_digest(datetime.now(timezone.utc))
        stats["alerts_sent"] = sent
    log.info("Review digest complete")


def run_observation_history_prune_once() -> None:
    """Delete closed history versions older than the configured retention.

    Delegates to `operations.purge_closed_observation_history(cutoff)` via
    `retention_observations.purge_all()`. The security-definer function
    owns the "never delete an open version" guarantee (see migration 0074).
    """
    days = int(getattr(settings, "OBSERVATION_HISTORY_RETENTION_DAYS", 90))
    log.info("Observation history retention starting: keep %d days", days)
    with run_log("retention.observation_history") as stats:
        generic, software = retention_observations.purge_all(days=days)
        claims = retention_observations.purge_claim_history(days=days)
        stats["generic_deleted"] = generic
        stats["software_deleted"] = software
        stats["attribute_claims_deleted"] = claims


def _safe(name: str, func, *args) -> tuple[str, Exception] | None:
    try:
        func(*args)
    except Exception as exc:
        log.exception("%s ingest failed; continuing with next module", name)
        return name, exc
    return None


def _raise_step_failures(context: str, failures: list[tuple[str, Exception]]) -> None:
    if failures:
        names = ", ".join(name for name, _ in failures)
        raise RuntimeError(f"{context} had {len(failures)} failed required step(s): {names}")


# ── Metabase auto-bootstrap ─────────────────────────────────────────

def _wait_for_metabase(url: str, timeout: int = 300) -> bool:
    """Poll /api/health every 5s until reachable or timeout (seconds)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"{url.rstrip('/')}/api/health", timeout=5)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(5)
    return False


def _metabase_setup_complete(url: str) -> bool:
    """True if Metabase's first-run wizard has been completed."""
    try:
        r = httpx.get(f"{url.rstrip('/')}/api/session/properties", timeout=10)
        if r.status_code != 200:
            return False
        return bool(r.json().get("has-user-setup"))
    except Exception:
        return False


def metabase_bootstrap_enabled() -> bool:
    """Whether the configured bootstrap can safely be admitted as a Job."""
    return bool(settings.MB_BOOTSTRAP_USER and settings.MB_BOOTSTRAP_PASS.get_secret_value())


def bootstrap_metabase() -> int:
    """Provision dashboards and return the number of published dashboard URLs.

    This runs only through the governed maintenance Job.  A configured but
    unavailable or incomplete Metabase instance is a factual Job failure,
    rather than a successful row backed only by a log message.
    """
    user = settings.MB_BOOTSTRAP_USER
    password = settings.MB_BOOTSTRAP_PASS.get_secret_value()
    url = settings.MB_BOOTSTRAP_URL

    if not user or not password:
        raise RuntimeError("Metabase bootstrap capability is not configured")

    log.info("Waiting for Metabase at %s", redact_url(url))
    if not _wait_for_metabase(url, timeout=300):
        raise RuntimeError("Metabase was not reachable within the five-minute bootstrap window")

    if not _metabase_setup_complete(url):
        raise RuntimeError(
            "Metabase first-run setup is incomplete; finish setup before retrying the bootstrap Job"
        )
        return

    log.info("Running Metabase dashboard bootstrap")
    from ingest.inventory.metabase_retirement import retire_inventory_metabase
    from ingest.metabase_bootstrap import run_bootstrap
    from ingest.agent_compliance.metabase_bootstrap import (
        run_bootstrap as run_agent_compliance_bootstrap,
    )

    retired = retire_inventory_metabase(url=url, user=user, password=password)
    log.info(
        "Inventory Metabase retirement complete: dashboards=%d cards=%d collections=%d",
        retired["dashboards"], retired["cards"], retired["collections"],
    )
    urls = run_bootstrap(
        url=url, user=user, password=password, db_name=settings.MB_BOOTSTRAP_DB_NAME,
    )
    if settings.AGENT_COMPLIANCE_ENABLED:
        urls.extend(run_agent_compliance_bootstrap(
            url=url, user=user, password=password, db_name=settings.MB_BOOTSTRAP_DB_NAME,
        ))
    for dashboard_url in urls:
        log.info("Dashboard ready: %s", dashboard_url)
    return len(urls)


def last_successful_run_at(domain: str | None = None) -> datetime | None:
    with db.transaction() as cur:
        if domain:
            cur.execute(
                "SELECT MAX(finished_at) FROM ninja_core.run_log "
                "WHERE status = 'ok' AND domain = %s",
                (domain,),
            )
        else:
            cur.execute(
                "SELECT MAX(finished_at) FROM ninja_core.run_log "
                "WHERE status = 'ok'"
            )
        row = cur.fetchone()
        return row[0] if row else None


def should_catch_up(
    domain: str | None = None,
    schedule_hours: int | None = None,
    now: datetime | None = None,
) -> bool:
    now = now or datetime.now(timezone.utc)
    last = last_successful_run_at(domain)
    if last is None:
        return False
    return (now - last) > timedelta(hours=schedule_hours or settings.INGEST_SCHEDULE_HOURS)


# ── HTTP endpoints ──────────────────────────────────────────────────

# Set by main() after migrations + scheduler are up. /healthz is
# liveness (always 200 once HTTP server binds); /readyz is readiness
# (503 with "starting" body until this event is set).
_READY = threading.Event()

_HTTP_JOB_PATHS = {
    "/run": "patches", "/run/patches": "patches",
    "/run/agent-compliance": "agent-compliance",
    "/run/agent-compliance-evaluate": "agent-compliance-evaluate",
    "/run/agent-compliance-review-digest": "agent-compliance-review-digest",
    "/run/resolver": "resolver", "/run/notifications/dispatch": "notifications-dispatch",
    "/run/platform-evaluate": "platform-evaluate",
    "/run/software-classify": "software-classify",
    "/run/software-classify-only": "software-classify-only",
    "/run/intel-capability": "intel-capability", "/run/intel-category": "intel-category",
    "/run/intel-lolrmm": "intel-lolrmm", "/run/patch-classify": "patch-classify",
    "/run/parity-check": "parity-check", "/run/notifications/digest": "notifications-digest",
    "/run/intel-nvd": "intel-nvd", "/run/intel-cpe-dict": "intel-cpe-dict",
    "/run/intel-kev": "intel-kev", "/run/intel-epss": "intel-epss",
    "/run/intel-matcher": "intel-matcher", "/run/intel-winget": "intel-winget",
    "/run/intel-chocolatey": "intel-chocolatey", "/run/intel-otx": "intel-otx",
    "/run/intel-abusech": "intel-abusech", "/run/intel-endoflife": "intel-endoflife",
    "/bootstrap-metabase": "metabase-bootstrap",
}


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        log.info("http %s - %s", self.address_string(), fmt % args)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            # Liveness — server is alive. Always 200 once we bind.
            self._respond(200, b"ok\n")
        elif self.path == "/readyz":
            # Readiness — migrations done, scheduler up.
            if _READY.is_set():
                self._respond(200, b"ready\n")
            else:
                self._respond(503, b"starting\n")
        elif self.path == "/run/software/scoped" or self.path.startswith("/run/software/scoped?"):
            self._handle_software_scoped()
        elif self.path == "/run/software/enqueue" or self.path.startswith("/run/software/enqueue?"):
            self._handle_software_enqueue()
        elif self.path.startswith("/run/software/demand/"):
            self._handle_software_demand_status()
        elif self.path == "/run/software/queue":
            self._handle_software_queue_status()
        elif self.path.startswith("/run/sources"):
            self._respond(410, b"source refreshes are managed in Operations Sources\n")
        elif self.path.startswith("/agent-compliance/action/") or self.path.startswith("/a/"):
            self._handle_agent_compliance_action()
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        governed_job = _HTTP_JOB_PATHS.get(self.path)
        if governed_job is not None:
            if not _READY.is_set():
                self._respond(503, b"still starting - try again shortly\n")
                return
            if governed_job == "metabase-bootstrap" and not metabase_bootstrap_enabled():
                self._respond(409, b"metabase bootstrap is not configured\n")
                return
            try:
                run_id = operator_job_queue.request_system_job(governed_job, self.path)
            except Exception:
                log.exception("governed HTTP Job request failed: %s", governed_job)
                self._respond(503, b"job admission unavailable\n")
                return
            self._respond(202, f"job queued: {run_id}\n".encode())
            return
        if self.path == "/run/software/enqueue" or self.path.startswith("/run/software/enqueue?"):
            self._handle_software_enqueue()
        elif self.path == "/run/software/scoped" or self.path.startswith("/run/software/scoped?"):
            self._handle_software_scoped()
        elif self.path.startswith("/run/sources"):
            self._respond(410, b"source refreshes are managed in Operations Sources\n")
        elif self.path.startswith("/agent-compliance/action/"):
            self._handle_agent_compliance_action()
        else:
            self.send_error(404)

    def _handle_agent_compliance_action(self) -> None:
        if not _READY.is_set():
            self._respond(503, b"still starting - try again shortly\n")
            return
        parsed = urlparse(self.path)
        path = {
            "/a/aa": "/agent-compliance/action/add-alias",
            "/a/ac": "/agent-compliance/action/approve-customer",
            "/a/eo": "/agent-compliance/action/exclude-org",
            "/a/sr": "/agent-compliance/action/set-requirement",
            "/a/ue": "/agent-compliance/action/unexclude-org",
            "/a/ig": "/agent-compliance/action/ignore-device",
            "/a/md": "/agent-compliance/action/merge-device",
            "/a/ui": "/agent-compliance/action/unignore-device",
            "/a/cm": "/agent-compliance/action/confirm-missing",
            "/a/bs": "/agent-compliance/action/bulk-ignore-stale",
            "/a/sd": "/agent-compliance/action/set-max-age",
            "/a/tr": "/agent-compliance/action/toggle-alert-rule",
            "/a/sca": "/agent-compliance/action/set-customer-alert",
            "/a/ma": "/agent-compliance/action/manual-alias",
            "/a/tp": "/agent-compliance/action/toggle-platform-requirement",
            "/a/as": "/agent-compliance/action/add-source",
        }.get(parsed.path, parsed.path)
        params = parse_qs(parsed.query)
        confirm = params.get("confirm", ["0"])[0]

        def _text_param(*names: str, hex_names: tuple[str, ...] = ()) -> str | None:
            for name in names:
                value = params.get(name, [""])[0].strip()
                if value:
                    return value
            for name in hex_names:
                value = params.get(name, [""])[0].strip()
                if not value:
                    continue
                try:
                    return bytes.fromhex(value).decode("utf-8")
                except ValueError:
                    self._respond(400, f"invalid {name}\n".encode("utf-8"))
                    return None
            return None

        if path == "/agent-compliance/action/add-source" and confirm != "1":
            # Load active customer names for the dropdown.
            with db.transaction() as cur:
                cur.execute(
                    """
                    SELECT client_name
                    FROM ninja_agent_compliance.clients
                    WHERE enabled
                      AND source NOT IN ('alignment', 'demoted')
                    ORDER BY client_name
                    """
                )
                customers = [r[0] for r in cur.fetchall() if r[0]]
            options = "\n".join(
                f'<option value="{escape(c)}">{escape(c)}</option>'
                for c in customers
            )
            body = f"""
                <!doctype html>
                <html>
                <head>
                  <meta charset="utf-8">
                  <title>Add ScreenConnect source</title>
                  <style>
                    body {{ font-family: sans-serif; margin: 24px; color: #1f2933; max-width: 720px; }}
                    label {{ display: block; font-weight: 700; margin: 16px 0 6px; }}
                    input, select {{ font-size: 16px; padding: 8px 10px; width: 100%; box-sizing: border-box; }}
                    button {{ margin-top: 18px; padding: 9px 14px; font-weight: 700; }}
                    .hint {{ color: #52606d; font-size: 14px; }}
                    .secret-note {{ background: #fef9c3; padding: 12px; border-radius: 4px; margin-top: 24px; }}
                    pre {{ background: #f3f4f6; padding: 10px; border-radius: 4px; }}
                  </style>
                </head>
                <body>
                  <h2>Add ScreenConnect source</h2>
                  <p class="hint">
                    Adds a per-customer ScreenConnect tenant to
                    <code>platform_sources</code>. The EXT_GUID and
                    SECRET_KEY values stay on the host in
                    <code>.env</code>; this form only references env
                    var names. The next screen tells you exactly which
                    vars to set.
                  </p>
                  <form method="get" action="/a/as">
                    <input type="hidden" name="confirm" value="1">
                    <label for="customer">Customer</label>
                    <select id="customer" name="customer" required>
                      <option value="">— select —</option>
                      {options}
                    </select>
                    <label for="source_slug">Source slug</label>
                    <input id="source_slug" name="source_slug" placeholder="bobov45" required pattern="[a-z0-9_]+" minlength="2" maxlength="40">
                    <p class="hint">Lowercase letters, digits, underscores. Used for the source key and env var names.</p>
                    <label for="source_name">Display name</label>
                    <input id="source_name" name="source_name" placeholder="Bobov45 ScreenConnect" required maxlength="100">
                    <label for="base_url">Base URL</label>
                    <input id="base_url" name="base_url" type="url" placeholder="https://bobov45.screenconnect.com" required>
                    <button type="submit">Add source</button>
                  </form>
                </body>
                </html>
            """.encode("utf-8")
            self._respond_html(200, body)
            return

        if path == "/agent-compliance/action/ignore-device" and confirm != "1":
            client_name = _text_param("client", "client_name", hex_names=("client_hex",)) or ""
            hostname = _text_param("host", "hostname", hex_names=("host_hex",)) or ""
            if not client_name or not hostname:
                self._respond(400, b"missing client or host\n")
                return
            body = f"""
                <!doctype html>
                <html>
                <head>
                  <meta charset="utf-8">
                  <title>Ignore device issue</title>
                  <style>
                    body {{ font-family: sans-serif; margin: 24px; color: #1f2933; }}
                    label {{ display: block; font-weight: 700; margin: 16px 0 6px; }}
                    input {{ font-size: 16px; padding: 8px 10px; width: 120px; }}
                    button {{ margin-top: 18px; padding: 9px 14px; font-weight: 700; }}
                    .hint {{ color: #52606d; max-width: 620px; }}
                  </style>
                </head>
                <body>
                  <h2>Ignore device issue</h2>
                  <p class="hint">Hide <strong>{escape(hostname)}</strong> for <strong>{escape(client_name)}</strong> from device issue queues. This is reversible from the Devices dashboard.</p>
                  <form method="get" action="/a/ig">
                    <input type="hidden" name="client" value="{escape(client_name)}">
                    <input type="hidden" name="host" value="{escape(hostname)}">
                    <input type="hidden" name="confirm" value="1">
                    <label for="days">Ignore for days</label>
                    <input id="days" name="days" type="number" min="1" max="365" value="30" required>
                    <br>
                    <button type="submit">Ignore device</button>
                  </form>
                </body>
                </html>
            """.encode("utf-8")
            self._respond_html(200, body)
            return

        if path == "/agent-compliance/action/merge-device" and confirm != "1":
            client_name = _text_param("client", "client_name", hex_names=("client_hex",)) or ""
            source_hostname = _text_param("source", "source_host", "host", "hostname", hex_names=("source_hex", "host_hex")) or ""
            target_hostname = _text_param("target", "target_host", hex_names=("target_hex",)) or ""
            if not client_name or not source_hostname:
                self._respond(400, b"missing client or source host\n")
                return
            body = f"""
                <!doctype html>
                <html>
                <head>
                  <meta charset="utf-8">
                  <title>Merge device names</title>
                  <style>
                    body {{ font-family: sans-serif; margin: 24px; color: #1f2933; max-width: 720px; }}
                    label {{ display: block; font-weight: 700; margin: 16px 0 6px; }}
                    input {{ font-size: 16px; padding: 8px 10px; width: 100%; box-sizing: border-box; }}
                    button {{ margin-top: 18px; padding: 9px 14px; font-weight: 700; }}
                    .hint {{ color: #52606d; max-width: 620px; }}
                  </style>
                </head>
                <body>
                  <h2>Merge device names</h2>
                  <p class="hint">Treat <strong>{escape(source_hostname)}</strong> as the same device as the target hostname for <strong>{escape(client_name)}</strong>. This affects matching only; platform device IDs and raw observations are preserved.</p>
                  <form method="get" action="/a/md">
                    <input type="hidden" name="client" value="{escape(client_name)}">
                    <input type="hidden" name="source" value="{escape(source_hostname)}">
                    <input type="hidden" name="confirm" value="1">
                    <label for="target">Target device name</label>
                    <input id="target" name="target" value="{escape(target_hostname)}" required>
                    <button type="submit">Merge device names</button>
                  </form>
                </body>
                </html>
            """.encode("utf-8")
            self._respond_html(200, body)
            return

        if confirm != "1":
            self._respond(400, b"missing confirm=1\n")
            return

        def _respond_with_refresh(message: str, reason: str) -> None:
            scheduled = schedule_agent_compliance_evaluate(reason)
            suffix = "; compliance refresh scheduled" if scheduled else ""
            self._respond(200, f"{message}{suffix}\n".encode("utf-8"))

        if path == "/agent-compliance/action/add-source":
            import re as _re
            customer = _text_param("customer") or ""
            source_slug = (_text_param("source_slug") or "").strip().lower()
            source_name = _text_param("source_name") or ""
            base_url = (_text_param("base_url") or "").strip()
            if not customer or not source_slug or not source_name or not base_url:
                self._respond(400, b"missing field\n")
                return
            if not _re.match(r"^[a-z0-9_]{2,40}$", source_slug):
                self._respond(400, b"invalid slug (lowercase letters/digits/_, 2-40 chars)\n")
                return
            if not (base_url.startswith("http://") or base_url.startswith("https://")):
                self._respond(400, b"base_url must start with http:// or https://\n")
                return
            slug_upper = source_slug.upper()
            ext_guid_ref = f"SC_{slug_upper}_EXT_GUID"
            secret_key_ref = f"SC_{slug_upper}_SECRET_KEY"
            source_key = f"sc_{source_slug}"
            with db.transaction() as cur:
                cur.execute(
                    """
                    INSERT INTO ninja_agent_compliance.platform_sources (
                        source_key, platform, source_name, client_id,
                        is_shared, enabled, base_url,
                        ext_guid_secret_ref, secret_key_secret_ref,
                        source, updated_by
                    )
                    SELECT %s, 'ScreenConnect', %s, c.client_id,
                           false, true, %s,
                           %s, %s,
                           'operator', 'operator_dashboard'
                    FROM ninja_agent_compliance.clients c
                    WHERE c.client_name = %s
                    ON CONFLICT (source_key) DO NOTHING
                    RETURNING source_id
                    """,
                    (source_key, source_name, base_url, ext_guid_ref, secret_key_ref, customer),
                )
                row = cur.fetchone()
            if not row:
                self._respond(
                    400,
                    f"customer '{customer}' not found, or source_key '{source_key}' already exists\n".encode("utf-8"),
                )
                return
            body = f"""
                <!doctype html>
                <html>
                <head>
                  <meta charset="utf-8">
                  <title>ScreenConnect source added</title>
                  <style>
                    body {{ font-family: sans-serif; margin: 24px; color: #1f2933; max-width: 720px; }}
                    .ok {{ background: #dcfce7; padding: 12px; border-radius: 4px; }}
                    .secret-note {{ background: #fef9c3; padding: 16px; border-radius: 4px; margin-top: 18px; }}
                    pre {{ background: #1f2933; color: #f0fdf4; padding: 14px; border-radius: 4px; font-size: 15px; }}
                    code {{ background: #f3f4f6; padding: 1px 6px; border-radius: 3px; }}
                    a.button {{ display: inline-block; margin-top: 18px; padding: 9px 14px; background: #1d4ed8; color: white; text-decoration: none; border-radius: 4px; }}
                  </style>
                </head>
                <body>
                  <h2>ScreenConnect source added</h2>
                  <p class="ok">Added <strong>{escape(source_name)}</strong> for <strong>{escape(customer)}</strong> (source_id <code>{row[0]}</code>).</p>

                  <div class="secret-note">
                    <strong>Next: set the secrets on the host.</strong>
                    <p>Edit <code>/amr-ch-01_data/ninja-dashboard/.env</code> and add:</p>
                    <pre>{escape(ext_guid_ref)}=&lt;extension GUID from SC API extension&gt;
{escape(secret_key_ref)}=&lt;secret key from SC API extension&gt;</pre>
                    <p>Then redeploy via Portainer so the container picks up the new env vars.</p>
                    <p>Once redeployed, trigger a collection:</p>
                    <pre>curl -X POST http://10.61.50.28:8090/run/agent-compliance</pre>
                    <p>And verify the new source_run:</p>
                    <pre>docker exec -it ninja-postgres psql -U ninja -d ninja -c \\
  "SELECT source_id, status, rows_observed, error_text
   FROM ninja_agent_compliance.source_runs
   WHERE source_id = {row[0]} ORDER BY started_at DESC LIMIT 3;"</pre>
                  </div>
                  <a class="button" href="/a/as">Add another</a>
                </body>
                </html>
            """.encode("utf-8")
            self._respond_html(200, body)
            return

        if path == "/agent-compliance/action/manual-alias":
            platform = _text_param("platform") or ""
            alias_value = _text_param("alias", "alias_value", hex_names=("alias_hex",)) or ""
            if not platform or not alias_value:
                self._respond(400, b"missing platform or alias\n")
                return
            with db.transaction() as cur:
                cur.execute(
                    """
                    SELECT client_name
                    FROM ninja_agent_compliance.clients
                    WHERE enabled
                      AND source NOT IN ('alignment', 'demoted')
                      AND lower(trim(client_name)) NOT IN ('default site', 'unknown', 'various', '.default')
                    ORDER BY client_name
                    """
                )
                customers = [row[0] for row in cur.fetchall()]
            rows = []
            for customer in customers:
                href = (
                    "/a/aa?"
                    f"client_name={quote(customer, safe='')}"
                    f"&platform={quote(platform, safe='')}"
                    f"&alias={quote(alias_value, safe='')}"
                    "&confirm=1"
                )
                rows.append(
                    "<tr>"
                    f"<td>{escape(customer)}</td>"
                    f"<td><a href=\"{href}\">Alias here</a></td>"
                    "</tr>"
                )
            body = f"""
                <!doctype html>
                <html>
                <head>
                  <meta charset="utf-8">
                  <title>Alias customer name</title>
                  <style>
                    body {{ font-family: sans-serif; margin: 24px; color: #1f2933; }}
                    table {{ border-collapse: collapse; min-width: 520px; }}
                    th, td {{ border-bottom: 1px solid #d9e2ec; padding: 8px 10px; text-align: left; }}
                    a {{ color: #0b69a3; font-weight: 600; }}
                    .hint {{ color: #52606d; margin-bottom: 16px; }}
                  </style>
                </head>
                <body>
                  <h2>Alias customer name</h2>
                  <p class="hint">Map <strong>{escape(alias_value)}</strong> from <strong>{escape(platform)}</strong> to an existing customer.</p>
                  <table>
                    <thead><tr><th>Customer</th><th>Action</th></tr></thead>
                    <tbody>{''.join(rows)}</tbody>
                  </table>
                </body>
                </html>
            """.encode("utf-8")
            self._respond_html(200, body)
            return

        if path == "/agent-compliance/action/add-alias":
            client_id_value = params.get("client_id", [""])[0]
            client_name = _text_param("client_name", "org", hex_names=("client_hex",))
            if not client_id_value and not client_name:
                self._respond(400, b"missing client_id or client_name\n")
                return
            client_id = None
            if client_id_value:
                try:
                    client_id = int(client_id_value)
                except ValueError:
                    self._respond(400, b"invalid client_id\n")
                    return
            platform = _text_param("platform") or None
            alias_value = _text_param("alias", "alias_value", hex_names=("alias_hex",))
            if client_id is None and client_name:
                with db.transaction() as cur:
                    cur.execute(
                        """
                        SELECT client_id
                        FROM ninja_agent_compliance.clients
                        WHERE client_name = %s
                        ORDER BY client_id
                        LIMIT 1
                        """,
                        (client_name,),
                    )
                    row = cur.fetchone()
                if not row:
                    self._respond(404, b"client not found\n")
                    return
                client_id = int(row[0])
            count = promote_alignment_aliases(client_id, platform=platform, alias_value=alias_value)
            _respond_with_refresh(f"added {count} alias row(s)", "alias added")
            return

        if path == "/agent-compliance/action/approve-customer":
            customer_name = _text_param("name", "customer", "org", hex_names=("name_hex", "customer_hex"))
            if not customer_name:
                self._respond(400, b"missing customer name\n")
                return
            if approve_customer_name(customer_name, updated_by="operator_dashboard"):
                _respond_with_refresh(f"approved customer {customer_name}", "customer approved")
            else:
                self._respond(400, b"blank customer name\n")
            return

        if path == "/agent-compliance/action/set-requirement":
            customer_name = _text_param("customer", "client_name", hex_names=("customer_hex", "client_hex"))
            scope = _text_param("scope") or ""
            profile = _text_param("profile") or ""
            if not customer_name or not scope or not profile:
                self._respond(400, b"missing customer, scope, or profile\n")
                return
            result = set_customer_requirement(
                customer_name,
                scope,
                profile,
                updated_by="operator_dashboard",
            )
            if result is None:
                self._respond(400, b"invalid customer, scope, or profile\n")
                return
            _respond_with_refresh(
                f"set {customer_name} {scope} coverage to {result}",
                "required coverage changed",
            )
            return

        if path == "/agent-compliance/action/toggle-platform-requirement":
            customer_name = _text_param("customer", "client_name", hex_names=("customer_hex", "client_hex"))
            scope = _text_param("scope") or ""
            platform = _text_param("platform") or ""
            if not customer_name or not scope or not platform:
                self._respond(400, b"missing customer, scope, or platform\n")
                return
            result = toggle_customer_required_platform(
                customer_name,
                scope,
                platform,
                updated_by="operator_dashboard",
            )
            if result is None:
                self._respond(400, b"invalid customer, scope, or platform\n")
                return
            _respond_with_refresh(
                f"set {customer_name} {scope} required platforms to {result}",
                "required platform changed",
            )
            return

        if path == "/agent-compliance/action/exclude-org":
            pattern = _text_param("pattern", "org", hex_names=("pattern_hex",))
            if not pattern:
                self._respond(400, b"missing pattern\n")
                return
            if add_org_exclude(pattern, notes="Added from operator dashboard"):
                _respond_with_refresh(f"excluded {pattern}", "customer name excluded")
            else:
                self._respond(400, b"blank pattern\n")
            return

        if path == "/agent-compliance/action/unexclude-org":
            pattern = _text_param("pattern", "org", hex_names=("pattern_hex",))
            if not pattern:
                self._respond(400, b"missing pattern\n")
                return
            if remove_org_exclude(pattern):
                _respond_with_refresh(f"restored {pattern}", "customer name restored")
            else:
                self._respond(404, b"not found or not removable\n")
            return

        if path == "/agent-compliance/action/ignore-device":
            client_name = _text_param("client", "client_name", hex_names=("client_hex",))
            hostname = _text_param("host", "hostname", hex_names=("host_hex",))
            days_value = _text_param("days") or "30"
            if not client_name or not hostname:
                self._respond(400, b"missing client or host\n")
                return
            try:
                expires_days = int(days_value)
            except ValueError:
                self._respond(400, b"invalid days\n")
                return
            if expires_days < 1 or expires_days > 365:
                self._respond(400, b"days must be between 1 and 365\n")
                return
            with db.transaction() as cur:
                cur.execute(
                    """
                    SELECT client_id, norm_name
                    FROM ninja_agent_compliance.compliance_matrix_current
                    WHERE client_name = %s
                      AND hostname = %s
                    ORDER BY evaluated_at DESC
                    LIMIT 1
                    """,
                    (client_name, hostname),
                )
                row = cur.fetchone()
            if not row:
                self._respond(404, b"device not found\n")
                return
            client_id, norm_name = row
            if add_device_ignore(client_id, norm_name, display_name=hostname, expires_days=expires_days):
                _respond_with_refresh(
                    f"ignored {norm_name} for {expires_days} day(s)",
                    "device ignored",
                )
            else:
                self._respond(400, b"blank norm_name\n")
            return

        if path == "/agent-compliance/action/confirm-missing":
            client_name = _text_param("client", "client_name", hex_names=("client_hex",))
            hostname = _text_param("host", "hostname", hex_names=("host_hex",))
            platform = _text_param("platform")
            if not client_name or not hostname:
                self._respond(400, b"missing client or host\n")
                return
            with db.transaction() as cur:
                cur.execute(
                    """
                    SELECT client_id, norm_name, missing_platforms
                    FROM ninja_agent_compliance.v_device_state_current
                    WHERE client_name = %s
                      AND hostname = %s
                    ORDER BY evaluated_at DESC
                    LIMIT 1
                    """,
                    (client_name, hostname),
                )
                row = cur.fetchone()
            if not row:
                self._respond(404, b"device not found\n")
                return
            client_id, norm_name, missing_platforms = row
            platforms = [platform] if platform else list(missing_platforms or [])
            if not platforms:
                self._respond(400, b"no missing platform to confirm\n")
                return
            for item in platforms:
                add_human_decision(
                    "confirm_missing",
                    client_id,
                    norm_name,
                    platform=item,
                    hostname=hostname,
                    updated_by="operator_dashboard",
                    notes="Confirmed as missing after cross-customer review",
                )
            _respond_with_refresh(
                f"confirmed missing for {norm_name}: {', '.join(platforms)}",
                "missing device confirmed",
            )
            return

        if path == "/agent-compliance/action/merge-device":
            client_name = _text_param("client", "client_name", hex_names=("client_hex",))
            source_hostname = _text_param("source", "source_host", "host", "hostname", hex_names=("source_hex", "host_hex"))
            target_hostname = _text_param("target", "target_host", hex_names=("target_hex",))
            if not client_name or not source_hostname or not target_hostname:
                self._respond(400, b"missing client, source host, or target host\n")
                return
            result = add_device_merge_decision(
                client_name,
                source_hostname,
                target_hostname,
                updated_by="operator_dashboard",
            )
            if result is None:
                self._respond(400, b"invalid merge request\n")
                return
            source_norm, target_norm = result
            _respond_with_refresh(
                f"merged {source_norm} into {target_norm}",
                "device merge added",
            )
            return

        if path == "/agent-compliance/action/set-max-age":
            customer_name = _text_param("customer", "client_name", hex_names=("customer_hex", "client_hex"))
            scope = _text_param("scope") or ""
            days_value = _text_param("days") or ""
            if not customer_name or not scope or not days_value:
                self._respond(400, b"missing customer, scope, or days\n")
                return
            result = set_customer_max_age(
                customer_name, scope, days_value, updated_by="operator_dashboard",
            )
            if result is None:
                self._respond(400, b"invalid customer, scope, or days (1-365)\n")
                return
            _respond_with_refresh(
                f"set {customer_name} {scope} max age to {result} days",
                "stale threshold changed",
            )
            return

        if path == "/agent-compliance/action/bulk-ignore-stale":
            client_name = _text_param("client", "client_name", "customer", hex_names=("client_hex", "customer_hex"))
            days_value = _text_param("days") or "30"
            if not client_name:
                self._respond(400, b"missing client\n")
                return
            try:
                expires_days = int(days_value)
            except ValueError:
                self._respond(400, b"invalid days\n")
                return
            if expires_days < 1 or expires_days > 365:
                self._respond(400, b"days must be between 1 and 365\n")
                return
            count = bulk_ignore_devices(
                client_name,
                kind="stale",
                updated_by="operator_dashboard",
                expires_days=expires_days,
            )
            if count is None:
                self._respond(400, b"invalid client or kind\n")
                return
            _respond_with_refresh(
                f"bulk ignored {count} stale device(s) for {client_name} for {expires_days} day(s)",
                "bulk stale devices ignored",
            )
            return

        if path == "/agent-compliance/action/unignore-device":
            client_name = _text_param("client", "client_name", hex_names=("client_hex",))
            hostname = _text_param("host", "hostname", hex_names=("host_hex",))
            if not client_name or not hostname:
                self._respond(400, b"missing client or host\n")
                return
            with db.transaction() as cur:
                cur.execute(
                    """
                    SELECT client_id, norm_name
                    FROM ninja_agent_compliance.compliance_matrix_current
                    WHERE client_name = %s
                      AND hostname = %s
                    ORDER BY evaluated_at DESC
                    LIMIT 1
                    """,
                    (client_name, hostname),
                )
                row = cur.fetchone()
            if not row:
                self._respond(404, b"device not found\n")
                return
            client_id, norm_name = row
            if remove_device_ignore(client_id, norm_name):
                _respond_with_refresh(f"restored {norm_name}", "device ignore removed")
            else:
                self._respond(404, b"not found or not removable\n")
            return

        if path == "/agent-compliance/action/toggle-alert-rule":
            rule_key = _text_param("rule", "rule_key", hex_names=("rule_hex",))
            state = (_text_param("state") or "").lower()
            if not rule_key or state not in {"on", "off"}:
                self._respond(400, b"missing rule or invalid state\n")
                return
            enabled = state == "on"
            with db.transaction() as cur:
                cur.execute(
                    """
                    UPDATE ninja_agent_compliance.alert_rules
                    SET enabled = %s,
                        updated_at = now(),
                        updated_by = 'operator_dashboard'
                    WHERE rule_key = %s
                    RETURNING rule_key
                    """,
                    (enabled, rule_key),
                )
                row = cur.fetchone()
            if not row:
                self._respond(404, b"alert rule not found\n")
                return
            _respond_with_refresh(
                f"alert rule {rule_key} turned {state}",
                "alert rule changed",
            )
            return

        if path == "/agent-compliance/action/set-customer-alert":
            customer_name = _text_param("customer", "client_name", hex_names=("customer_hex", "client_hex"))
            alert_key = (_text_param("alert") or "").lower()
            state = (_text_param("state") or "").lower()
            profiles = {
                "missing_ninja": ("missing_required_platform", "Ninja", "critical"),
                "missing_sentinelone": ("missing_required_platform", "SentinelOne", "critical"),
                "missing_logmein": ("missing_required_platform", "LogMeIn", "high"),
                "missing_screenconnect": ("missing_required_platform", "ScreenConnect", "high"),
                "stale": ("stale_required_platform", None, "medium"),
                "offline": ("stale_required_platform", None, "medium"),
            }
            if not customer_name or alert_key not in profiles or state not in {"on", "off"}:
                self._respond(400, b"missing customer, alert, or valid state\n")
                return
            finding_type, affected_platform, severity = profiles[alert_key]
            rule_key_suffix = "stale" if alert_key == "offline" else alert_key
            enabled = state == "on"
            with db.transaction() as cur:
                cur.execute(
                    """
                    SELECT client_id
                    FROM ninja_agent_compliance.clients
                    WHERE enabled
                      AND client_name = %s
                    ORDER BY client_id
                    LIMIT 1
                    """,
                    (customer_name,),
                )
                client_row = cur.fetchone()
                if not client_row:
                    self._respond(404, b"customer not found\n")
                    return
                client_id = int(client_row[0])
                cur.execute(
                    """
                    SELECT r.cooldown_hours, r.route_id
                    FROM ninja_agent_compliance.alert_rules r
                    WHERE r.client_id IS NULL
                      AND r.finding_type = %s
                      AND r.affected_platform IS NOT DISTINCT FROM %s
                    ORDER BY r.rule_id
                    LIMIT 1
                    """,
                    (finding_type, affected_platform),
                )
                default_row = cur.fetchone()
                cooldown_hours = int(default_row[0]) if default_row else 24
                route_id = default_row[1] if default_row else None
                if route_id is None:
                    cur.execute(
                        """
                        SELECT route_id
                        FROM ninja_agent_compliance.notification_routes
                        WHERE route_key = 'default_webhook'
                        LIMIT 1
                        """
                    )
                    route_row = cur.fetchone()
                    route_id = route_row[0] if route_row else None
                rule_key = f"customer_{client_id}_{rule_key_suffix}"
                cur.execute(
                    """
                    INSERT INTO ninja_agent_compliance.alert_rules (
                        rule_key, finding_type, affected_platform, client_id,
                        device_scope, severity, cooldown_hours, route_id,
                        enabled, updated_by
                    )
                    VALUES (%s, %s, %s, %s, 'all', %s, %s, %s, %s, 'operator_dashboard')
                    ON CONFLICT (rule_key) DO UPDATE
                    SET finding_type = EXCLUDED.finding_type,
                        affected_platform = EXCLUDED.affected_platform,
                        client_id = EXCLUDED.client_id,
                        device_scope = EXCLUDED.device_scope,
                        severity = EXCLUDED.severity,
                        cooldown_hours = EXCLUDED.cooldown_hours,
                        route_id = EXCLUDED.route_id,
                        enabled = EXCLUDED.enabled,
                        updated_at = now(),
                        updated_by = 'operator_dashboard'
                    """,
                    (
                        rule_key,
                        finding_type,
                        affected_platform,
                        client_id,
                        severity,
                        cooldown_hours,
                        route_id,
                        enabled,
                    ),
                )
            _respond_with_refresh(
                f"{customer_name} {alert_key} alerts turned {state}",
                "customer alert setting changed",
            )
            return

        self.send_error(404)

    def _handle_software_scoped(self) -> None:
        if not _READY.is_set():
            self._respond(503, b"still starting - try again shortly\n")
            return
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        confirm = params.get("confirm", ["0"])[0]
        df = (params.get("df", [""])[0]).strip()

        if confirm != "1":
            orgs, devices = _scope_selector.load_scope_choices()
            links_html = (
                '<p style="margin-top:16px;font-size:13px;color:#52606d;">'
                '<a href="/run/software/queue" style="color:#0b69a3;">Queue status</a>'
                '</p>'
            )
            selector_html = _scope_selector.render_scope_selector(
                orgs, devices,
                action="/run/software/enqueue",
                submit_label="Queue scoped refresh",
                redirect_url="/run/software/queue",
                links_html=links_html,
            )
            body = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Software inventory — scoped refresh</title>
  <style>
    body {{ font-family: sans-serif; margin: 24px; color: #1f2933; max-width: 780px; }}
    h2 {{ margin-bottom: 4px; }}
    p.hint {{ color: #52606d; font-size: 14px; margin: 0 0 16px; }}
  </style>
</head>
<body>
  <h2>Software inventory — scoped refresh</h2>
  <p class="hint">Queues software observations for the selected scope. All other devices are unchanged.</p>
  {selector_html}
</body>
</html>""".encode("utf-8")
            self._respond_html(200, body)
            return

        if not df:
            self._respond(400, b"missing df\n")
            return

        entry_id = software_queue.enqueue_demand(df, reason="on_demand")
        if not entry_id:
            self._respond(500, b"failed to enqueue demand entry\n")
            return
        self.send_response(303)
        self.send_header("Location", f"/run/software/demand/{entry_id}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _handle_software_enqueue(self) -> None:
        """Q2 demand queue form and submission."""
        if not _READY.is_set():
            self._respond(503, b"still starting - try again shortly\n")
            return
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        df = (params.get("df", [""])[0]).strip()
        confirm = params.get("confirm", ["0"])[0]

        if self.command == "GET" and confirm != "1":
            orgs, devs = _scope_selector.load_scope_choices()
            links_html = (
                '<p style="margin-top:16px;font-size:13px;color:#52606d;">'
                '<a href="/run/software/queue" style="color:#0b69a3;">Queue status</a>'
                '</p>'
            )
            selector_html = _scope_selector.render_scope_selector(
                orgs, devs,
                action="/run/software/enqueue",
                submit_label="Queue now",
                redirect_url="/run/software/queue",
                links_html=links_html,
            )
            body = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Software inventory — demand run</title>
  <style>
    body {{ font-family: sans-serif; margin: 24px; color: #1f2933; max-width: 780px; }}
    h2 {{ margin-bottom: 4px; }}
    p.hint {{ color: #52606d; font-size: 14px; margin: 0 0 16px; }}
  </style>
</head>
<body>
  <h2>Software inventory — demand run</h2>
  <p class="hint">Select one or more clients or devices. Multiple selections are queued separately.</p>
  {selector_html}
</body>
</html>""".encode("utf-8")
            self._respond_html(200, body)
            return

        if not df:
            self._respond(400, b"missing df\n")
            return

        entry_id = software_queue.enqueue_demand(df, reason="on_demand")
        if not entry_id:
            self._respond(500, b"failed to enqueue demand entry\n")
            return

        # Redirect to status page.
        location = f"/run/software/demand/{entry_id}"
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _handle_software_demand_status(self) -> None:
        """Status page for a Q2 demand run. Auto-refreshes until done/failed."""
        if not _READY.is_set():
            self._respond(503, b"still starting - try again shortly\n")
            return
        parts = self.path.rstrip("/").rsplit("/", 1)
        try:
            entry_id = int(parts[-1])
        except (ValueError, IndexError):
            self._respond(400, b"invalid demand entry id\n")
            return

        entry = software_queue.get_demand_status(entry_id)
        if entry is None:
            self._respond(404, b"demand entry not found\n")
            return

        status = entry["status"]
        terminal = status in ("done", "failed")
        refresh_meta = "" if terminal else '<meta http-equiv="refresh" content="5">'

        status_labels = {
            "pending": "Queued — waiting for worker",
            "processing": "Running…",
            "done": "Completed",
            "failed": "Failed",
        }
        status_label = status_labels.get(status, status)

        def _fmt(v: object) -> str:
            return str(v) if v is not None else "—"

        error_html = (
            f'<div class="error">{escape(entry["error"])}</div>'
            if entry.get("error") else ""
        )

        body = f"""
            <!doctype html>
            <html>
            <head>
              <meta charset="utf-8">
              <title>Demand run #{entry_id}</title>
              {refresh_meta}
              <style>
                body {{ font-family: sans-serif; margin: 24px; color: #1f2933; max-width: 720px; }}
                h2 {{ margin-bottom: 4px; }}
                .status {{ font-size: 18px; font-weight: 700; margin: 12px 0 20px; }}
                .pending   {{ color: #52606d; }}
                .processing {{ color: #0b69a3; }}
                .done {{ color: #27ab83; }}
                .failed {{ color: #ba2525; }}
                table {{ border-collapse: collapse; width: 100%; }}
                th, td {{ text-align: left; padding: 8px 12px; border-bottom: 1px solid #d9e2ec; }}
                th {{ background: #f3f4f6; font-weight: 600; width: 160px; }}
                .error {{ background: #fff5f5; border: 1px solid #fc8181; border-radius: 4px;
                          padding: 12px; margin-top: 16px; font-family: monospace; font-size: 13px;
                          white-space: pre-wrap; word-break: break-all; }}
                a {{ color: #0b69a3; }}
                .links {{ margin-top: 24px; }}
              </style>
            </head>
            <body>
              <h2>Demand run #{entry_id}</h2>
              <p class="status {status}">{escape(status_label)}</p>
              <table>
                <tr><th>Scope (df)</th><td><code>{escape(entry["df"])}</code></td></tr>
                <tr><th>Reason</th><td>{escape(entry["reason"] or "—")}</td></tr>
                <tr><th>Queued</th><td>{_fmt(entry["queued_at"])}</td></tr>
                <tr><th>Started</th><td>{_fmt(entry["started_at"])}</td></tr>
                <tr><th>Completed</th><td>{_fmt(entry["completed_at"])}</td></tr>
                <tr><th>Rows processed</th><td>{_fmt(entry["rows_seen"])}</td></tr>
                <tr><th>Attempts</th><td>{entry["attempts"]} / {entry["max_attempts"]}</td></tr>
              </table>
              {error_html}
              <p class="links">
                <a href="/run/software/enqueue">New demand run</a> &middot;
                <a href="/run/software/queue">Queue status</a>
              </p>
            </body>
            </html>
        """.encode("utf-8")
        self._respond_html(200, body)

    def _handle_software_queue_status(self) -> None:
        """Overview of all three software queues."""
        if not _READY.is_set():
            self._respond(503, b"still starting - try again shortly\n")
            return
        details = software_queue.queue_details()
        statuses = ["pending", "processing", "done", "failed"]

        def _fmt_dt(dt) -> str:
            return dt.strftime("%H:%M:%S") if dt else "—"

        def _count_row(name: str) -> str:
            c = details.get(name, {}).get("counts", {})
            cells = "".join(f"<td>{c.get(s, 0)}</td>" for s in statuses)
            return f"<tr><th>{name}</th>{cells}</tr>"

        def _detail_section(name: str) -> str:
            d = details.get(name, {})
            active = d.get("active", [])
            recent = d.get("recent", [])
            if not active and not recent:
                return ""
            rows_html = ""
            import datetime as _dt
            _now = _dt.datetime.now(_dt.timezone.utc)
            for r in active:
                elapsed = ""
                if r["started_at"]:
                    st = r["started_at"]
                    if st.tzinfo is None:
                        st = st.replace(tzinfo=_dt.timezone.utc)
                    elapsed = f" ({int((_now - st).total_seconds())}s)"
                attempts_str = f"{r['attempts']}/{r['max_attempts']}" if r.get('max_attempts') else str(r.get('attempts', ''))
                scope_cell = (
                    f"<a href='/run/software/demand/{r['id']}'>{r['df']}</a>"
                    if name == "demand" else r['df']
                )
                rows_html += (
                    f"<tr style='background:#fff8e1'>"
                    f"<td>processing</td><td>{scope_cell}</td>"
                    f"<td>{_fmt_dt(r['started_at'])}{elapsed}</td>"
                    f"<td>—</td><td>—</td><td>{attempts_str}</td><td></td></tr>"
                )
            for r in recent:
                err_full = r.get("error") or ""
                err_cell = (
                    f"<span style='color:#c0392b' title='{err_full}'>{err_full[:80]}{'…' if len(err_full) > 80 else ''}</span>"
                    if err_full else ""
                )
                attempts_str = f"{r['attempts']}/{r['max_attempts']}" if r.get('max_attempts') else str(r.get('attempts', ''))
                scope_cell = (
                    f"<a href='/run/software/demand/{r['id']}'>{r['df']}</a>"
                    if name == "demand" else r['df']
                )
                rows_html += (
                    f"<tr>"
                    f"<td>{r['status']}</td><td>{scope_cell}</td>"
                    f"<td>{_fmt_dt(r['started_at'])}</td>"
                    f"<td>{_fmt_dt(r['completed_at'])}</td>"
                    f"<td>{r['rows_seen'] if r['rows_seen'] is not None else '—'}</td>"
                    f"<td>{attempts_str}</td>"
                    f"<td>{err_cell}</td></tr>"
                )
            return f"""
              <h3 style="margin-top:24px;margin-bottom:4px">{name}</h3>
              <table>
                <thead><tr>
                  <th>Status</th><th>Scope</th><th>Started</th>
                  <th>Completed</th><th>Rows</th><th>Attempts</th><th>Error</th>
                </tr></thead>
                <tbody>{rows_html}</tbody>
              </table>"""

        detail_html = "".join(_detail_section(n) for n in ("scheduled", "demand", "activity"))

        body = f"""
            <!doctype html>
            <html>
            <head>
              <meta charset="utf-8">
              <title>Software queue status</title>
              <meta http-equiv="refresh" content="15">
              <style>
                body {{ font-family: sans-serif; margin: 24px; color: #1f2933; max-width: 900px; }}
                table {{ border-collapse: collapse; width: 100%; margin-top: 8px; }}
                th, td {{ text-align: left; padding: 6px 10px; border-bottom: 1px solid #d9e2ec; font-size: 13px; }}
                thead th {{ background: #f3f4f6; font-weight: 600; }}
                .hint {{ color: #52606d; font-size: 14px; }}
                a {{ color: #0b69a3; }}
              </style>
            </head>
            <body>
              <h2>Software queue status</h2>
              <p class="hint">Auto-refreshes every 15 s. Queue enabled: <strong>{"yes" if settings.SOFTWARE_QUEUE_ENABLED else "no"}</strong></p>
              <table>
                <thead>
                  <tr><th>Queue</th><th>Pending</th><th>Processing</th><th>Done</th><th>Failed</th></tr>
                </thead>
                <tbody>
                  {_count_row("scheduled")}
                  {_count_row("demand")}
                  {_count_row("activity")}
                </tbody>
              </table>
              {detail_html}
              <p style="margin-top: 24px;">
                <a href="/run/software/enqueue">New demand run</a>
              </p>
            </body>
            </html>
        """.encode("utf-8")
        self._respond_html(200, body)

    def _respond(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _respond_html(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _start_http_server() -> _ThreadingServer:
    """Bind and start the HTTP server in a daemon thread. Returns the
    server instance so main() can hold a reference (otherwise the
    serve_forever thread exits when the local goes out of scope)."""
    addr = ("0.0.0.0", settings.INGEST_HTTP_PORT)
    httpd = _ThreadingServer(addr, _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    log.info(
        "HTTP server listening on %s:%d "
        "(/healthz liveness, /readyz readiness, /run, /run/patches, "
        "/run/agent-compliance, /run/agent-compliance-evaluate, "
        "/run/resolver, "
            "/run/software/enqueue, /run/software/scoped, /run/software/queue, "
            "/run/software/demand/<id>, /bootstrap-metabase)",
        *addr,
    )
    return httpd


def main() -> None:
    logging.basicConfig(
        level=settings.INGEST_LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    install_log_safety()
    # Schedules are declared by the registry and reconciled into the durable
    # schedule catalog below. There is no second scheduler key list.
    validate_registry(executable_keys=definition_keys())

    # Bind HTTP server FIRST so /healthz is reachable before any
    # potentially-slow startup work. Keeps the Docker HEALTHCHECK
    # green and prevents migration-rollback restart loops.
    httpd = _start_http_server()

    log.info("Initializing DB pool")
    db.init(settings.postgres_dsn)

    log.info("Applying pending migrations")
    migrations.apply_pending()
    operator_job_queue.register_definition_snapshots()
    operator_job_queue.reconcile_schedule_catalog()
    operator_job_queue.record_runtime_heartbeat(
        "scheduler",
        operator_job_queue.SCHEDULER_RUNTIME_ID,
        {
            "definition_count": len(definition_keys()),
            "leader_mode": "short_lived_advisory",
            "poll_seconds": 60,
        },
    )

    scheduler = BackgroundScheduler()
    # Durable schedules retain their cadence and due tick in Postgres.  This
    # poller only admits due work; the dedicated Jobs worker performs it.
    scheduler.add_job(
        operator_job_queue.produce_due_schedules,
        "interval",
        minutes=1,
        id="jobs_durable_schedule_producer",
        max_instances=1,
    )
    scheduler.add_job(
        operator_job_queue.contain_expired_v1,
        "interval",
        minutes=1,
        id="jobs_v1_timeout_containment",
        max_instances=1,
    )
    scheduler.start()
    log.info("Durable Jobs producer and control maintenance started")

    if metabase_bootstrap_enabled():
        try:
            operator_job_queue.request_system_job("metabase-bootstrap", "startup")
        except Exception:
            log.exception("Could not admit the configured Metabase bootstrap Job")
    else:
        log.info("Metabase bootstrap capability is disabled")

    _READY.set()
    log.info("Ingest service ready")

    # Block forever holding the server reference (the daemon thread
    # serving requests dies if this main thread exits).
    try:
        threading.Event().wait()
    finally:
        operator_job_queue.stop_runtime(
            "scheduler", operator_job_queue.SCHEDULER_RUNTIME_ID
        )
        httpd.shutdown()


if __name__ == "__main__":
    main()
