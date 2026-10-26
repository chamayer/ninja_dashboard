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

import http.server
import logging
import socketserver
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from apscheduler.schedulers.background import BackgroundScheduler

from ingest import db, migrations, operator_job_queue, retention_observations
from ingest.activities import ingest as activities_ingest
from ingest.config import settings
from ingest.core import (
    custom_fields,
    device_health,
    devices,
    locations,
    organizations,
    policies,
)
from ingest.derived import refresh_after_collection
from ingest.evaluator import evaluate as platform_evaluate
from ingest.identity.client_resolver import (
    drain_client_resolution as _drain_client_resolution,
)
from ingest.identity import resolver as identity_resolver
from ingest.identity.resolver import drain_resolution as _drain_resolution
from ingest.inventory import queue as software_queue
from ingest.inventory import software as software_ingest
from ingest.logging_utils import install_log_safety
from ingest.ninja_client import NinjaClient
from ingest.notifications import dispatch as notify_dispatch
from ingest.notifications_digest import send_digest as notify_send_digest
from ingest.patch_findings import classify as patch_classify
from ingest.patches import ingest as patches_ingest
from ingest.policy_scope import sync_patching_enabled_policies
from ingest.runlog import run_log
from ingest.source_observations import (
    SourceObservationFailure,
    is_identity_source,
    run_source_observations,
)
from ingest.sources import load_sources
from ingest.summary_views import refresh_device_troubleshooting_signal
from shared.jobs_registry import definition_keys, validate_registry

log = logging.getLogger("ingest.main")
_PATCH_CYCLE_LOCK_ID = 6_803_904_731_027_441
_NINJA_DEVICE_CYCLE_LOCK_ID = 6_803_904_731_027_442
_NINJA_ENRICHMENT_CYCLE_LOCK_ID = 6_803_904_731_027_443


def run_once() -> None:
    run_ninja_devices_once()
    run_ninja_enrichment_once()
    run_patching_once()


def run_ninja_devices_once() -> bool:
    """Collect the Ninja identity snapshot and publish shared device evidence.

    Organizations and devices are the only Ninja inputs that can establish a
    Computer, attach a source record to a client, or change inventory state.
    The device writer projects them through the shared source-observation
    contract before this job reports success.
    """
    with db.pool.connection() as lock_conn, lock_conn.cursor() as lock_cur:
        lock_cur.execute(
            "SELECT pg_try_advisory_lock(%s)", (_NINJA_DEVICE_CYCLE_LOCK_ID,)
        )
        if not lock_cur.fetchone()[0]:
            log.info("Ninja device collection skipped; another process holds the lock")
            return False
        try:
            with run_log("ninja_devices"):
                log.info("Ninja device collection starting")
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
                        _safe("devices", devices.run, client, snapshot_at),
                    ):
                        if failure:
                            failures.append(failure)
                for failure in (
                    _safe(
                        "derived_refresh",
                        refresh_after_collection,
                        "Ninja device collection",
                    ),
                    _safe("windows_servicing", run_windows_servicing_once),
                ):
                    if failure:
                        failures.append(failure)
                _raise_step_failures("Ninja device collection", failures)
                log.info("Ninja device collection complete")
            return True
        finally:
            lock_cur.execute(
                "SELECT pg_advisory_unlock(%s)", (_NINJA_DEVICE_CYCLE_LOCK_ID,)
            )


def run_ninja_enrichment_once() -> bool:
    """Collect Ninja facts that enrich existing source records and Computers."""
    with db.pool.connection() as lock_conn, lock_conn.cursor() as lock_cur:
        lock_cur.execute(
            "SELECT pg_try_advisory_lock(%s)", (_NINJA_ENRICHMENT_CYCLE_LOCK_ID,)
        )
        if not lock_cur.fetchone()[0]:
            log.info(
                "Ninja enrichment collection skipped; another process holds the lock"
            )
            return False
        try:
            with run_log("ninja_enrichment"):
                log.info("Ninja enrichment collection starting")
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
                        _safe("locations", locations.run, client),
                        _safe("policies", policies.run, client),
                        _safe(
                            "patching_enabled_policies", sync_patching_enabled_policies
                        ),
                        _safe(
                            "device_exemptions",
                            devices.sync_operations_device_exemptions,
                        ),
                        _safe("device_health", device_health.run, client, snapshot_at),
                        _safe("custom_fields", custom_fields.run, client, snapshot_at),
                    ):
                        if failure:
                            failures.append(failure)
                for failure in (
                    _safe(
                        "patching_scope_refresh", devices.refresh_patching_scope_current
                    ),
                    _safe(
                        "troubleshooting_signal", refresh_device_troubleshooting_signal
                    ),
                    _safe(
                        "derived_refresh",
                        refresh_after_collection,
                        "Ninja enrichment collection",
                    ),
                ):
                    if failure:
                        failures.append(failure)
                _raise_step_failures("Ninja enrichment collection", failures)
                log.info("Ninja enrichment collection complete")
            return True
        finally:
            lock_cur.execute(
                "SELECT pg_advisory_unlock(%s)", (_NINJA_ENRICHMENT_CYCLE_LOCK_ID,)
            )


def run_patching_once() -> bool:
    """Collect Ninja patch and activity domains without changing Computers."""
    with db.pool.connection() as lock_conn, lock_conn.cursor() as lock_cur:
        lock_cur.execute("SELECT pg_try_advisory_lock(%s)", (_PATCH_CYCLE_LOCK_ID,))
        if not lock_cur.fetchone()[0]:
            log.info("Patch ingest run skipped; another process holds the cycle lock")
            return False
        try:
            with run_log("patch_cycle"):
                log.info("Patch and activity collection starting")
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
                        _safe("patches", patches_ingest.run, client, snapshot_at),
                        _safe("activities", activities_ingest.run, client),
                    ):
                        if failure:
                            failures.append(failure)
                _raise_step_failures("Patch collection", failures)
                log.info("Patch and activity collection complete")
            return True
        finally:
            lock_cur.execute("SELECT pg_advisory_unlock(%s)", (_PATCH_CYCLE_LOCK_ID,))


def run_identity_resolver_once(*, refresh_current: bool = True):
    """Drain unresolved observations and optionally refresh presence state.

    Returns the run's aggregate telemetry (counts, durations, which hourly
    maintenance ran) as the Job result.
    """
    identity_resolver.reset_telemetry()
    started = time.monotonic()
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
    telemetry = identity_resolver.take_telemetry()
    telemetry["seconds"] = round(time.monotonic() - started, 1)
    return operator_job_queue.JobExecutionResult(result=telemetry)


def run_ninja_observations_once() -> None:
    """Sync Ninja orgs + devices into Operations without enrichment or patches.

    Runs org/device sync only — populates operations.devices,
    source links, and entity_observations (agent.rmm), then refreshes
    device_agent_presence_current. Skips device-health, patches, activities,
    and custom fields, so it completes in seconds instead of minutes.
    Used by the source run queue demand trigger.
    """
    if run_ninja_devices_once() is False:
        raise RuntimeError(
            "Ninja device collection could not acquire its execution lock"
        )


def run_agent_observations_once() -> None:
    """Fetch S1/SC/LMI and write to entity_observations, then resolve device IDs.

    INTERIM (legacy evidence is archived under docs/archive): the
    source list is filtered to identity-signal sources so slow documentation
    collectors do not delay live agent telemetry on this cycle. Reverting to
    a single unified cycle means dropping this filter and the companion
    `run_documentation_observations_once` job.
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


def _ninja_client() -> NinjaClient:
    return NinjaClient(
        base_url=settings.NINJA_BASE_URL,
        token_url=settings.NINJA_TOKEN_URL,
        client_id=settings.NINJA_CLIENT_ID,
        client_secret=settings.NINJA_CLIENT_SECRET.get_secret_value(),
        scope=settings.NINJA_SCOPE,
    )


def run_software_fleet_check_once(
    count=None,
) -> operator_job_queue.JobExecutionResult | None:
    """Fetch every computer's software list and apply it (daily completeness check).

    The software findings run follows only when something changed.
    """
    if not settings.SOFTWARE_QUEUE_ENABLED:
        return None
    started = datetime.now(timezone.utc)
    with _ninja_client() as client:
        result = software_ingest.fleet_check(client, count)
    if result.material_changed:
        software_ingest.refresh_read_models()
    details = result.as_result("Full check")
    stats = software_ingest.freshness(started)
    details["freshness"] = stats
    freshness_text = software_ingest.describe_freshness(stats)
    if freshness_text:
        details["summary"] = f"{details['summary']} {freshness_text}"
    return operator_job_queue.JobExecutionResult(
        rows=result.devices,
        signals=("material_change",) if result.material_changed else (),
        result=details,
    )


def run_software_queue_once(
    job_run_id: object, count=None
) -> operator_job_queue.JobExecutionResult | None:
    """Fetch and apply the software lists of every queued computer."""
    if not settings.SOFTWARE_QUEUE_ENABLED:
        return None
    with _ninja_client() as client:
        outcome = software_queue.drain(client, job_run_id, count)
    if outcome.material_changed:
        software_ingest.refresh_read_models()
    if outcome.failed:
        raise RuntimeError(
            f"{outcome.failed} queued computer(s) could not be refreshed; they are retried "
            "until their attempt limit and then kept as failed with the error."
        )
    result = outcome.result.as_result("Changed computers")
    if not outcome.entries:
        result["summary"] = "No computer was waiting for a software refresh."
    return operator_job_queue.JobExecutionResult(
        rows=outcome.entries,
        signals=("material_change",) if outcome.material_changed else (),
        result=result,
    )


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


def software_classify(tenant_id: int = 1, incremental: bool = True) -> int:
    """Reconcile every software finding type (rebuild design v2).

    ``incremental`` is accepted for the existing callers and ignored: one
    reconcile covers the whole fleet, so there is no partial mode.
    """
    from ingest import software_reconcile

    del incremental
    report = software_reconcile.run(tenant_id).as_result()
    return sum(sum(report[key].values()) for key in ("opened", "refreshed", "resolved"))


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
            ("intel matcher pre-classify", run_intel_matcher_once),
            ("intel Winget pre-classify", run_intel_winget_once),
            ("intel Chocolatey pre-classify", run_intel_chocolatey_once),
        ):
            try:
                step_fn()
            except Exception:
                log.exception("Best-effort intel step failed: %s", step_name)
    try:
        affected = software_classify(tenant_id=1, incremental=not with_intel_pre_steps)
        log.info("Software classifier complete: affected=%d", affected)
    except Exception:
        log.exception("Software classifier failed")
        return
    # Refresh the software risk matview so the UI reflects fresh
    # findings + decisions. Best-effort — never blocks the classifier.
    try:
        with db.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("REFRESH MATERIALIZED VIEW operations.v_software_safety")
        log.info("Refreshed operations.v_software_safety matview")
        software_ingest.refresh_exposure_read_model()
    except Exception:
        log.exception("Failed to publish software read models")


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
                """,
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
        raise RuntimeError(
            f"{context} had {len(failures)} failed required step(s): {names}"
        )


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
                "SELECT MAX(finished_at) FROM ninja_core.run_log " "WHERE status = 'ok'"
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
    return (now - last) > timedelta(
        hours=schedule_hours or settings.INGEST_SCHEDULE_HOURS
    )


# ── HTTP endpoints ──────────────────────────────────────────────────

# Set by main() after migrations + scheduler are up. /healthz is
# liveness (always 200 once HTTP server binds); /readyz is readiness
# (503 with "starting" body until this event is set).
_READY = threading.Event()

_HTTP_JOB_PATHS = {
    "/run": "patches",
    "/run/patches": "patches",
    "/run/ninja-enrichment": "ninja-enrichment",
    "/run/agent-compliance": "agent-compliance",
    "/run/agent-compliance-evaluate": "agent-compliance-evaluate",
    "/run/agent-compliance-review-digest": "agent-compliance-review-digest",
    "/run/resolver": "resolver",
    "/run/notifications/dispatch": "notifications-dispatch",
    "/run/platform-evaluate": "platform-evaluate",
    "/run/software-classify": "software-classify",
    "/run/software-classify-only": "software-classify-only",
    "/run/intel-capability": "intel-capability",
    "/run/intel-category": "intel-category",
    "/run/intel-lolrmm": "intel-lolrmm",
    "/run/patch-classify": "patch-classify",
    "/run/notifications/digest": "notifications-digest",
    "/run/intel-nvd": "intel-nvd",
    "/run/intel-cpe-dict": "intel-cpe-dict",
    "/run/intel-kev": "intel-kev",
    "/run/intel-epss": "intel-epss",
    "/run/intel-matcher": "intel-matcher",
    "/run/intel-winget": "intel-winget",
    "/run/intel-chocolatey": "intel-chocolatey",
    "/run/intel-otx": "intel-otx",
    "/run/intel-abusech": "intel-abusech",
    "/run/intel-endoflife": "intel-endoflife",
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
        elif self.path.startswith("/run/software/"):
            self._respond(410, b"software refreshes are requested from Operations\n")
        elif self.path.startswith("/run/sources"):
            self._respond(410, b"source refreshes are managed in Operations Sources\n")
        elif self.path.startswith("/agent-compliance/action/") or self.path.startswith(
            "/a/"
        ):
            self._respond(410, b"agent compliance was retired; use Operations\n")
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        governed_job = _HTTP_JOB_PATHS.get(self.path)
        if governed_job is not None:
            if not _READY.is_set():
                self._respond(503, b"still starting - try again shortly\n")
                return
            try:
                run_id = operator_job_queue.request_system_job(governed_job, self.path)
            except Exception:
                log.exception("governed HTTP Job request failed: %s", governed_job)
                self._respond(503, b"job admission unavailable\n")
                return
            self._respond(202, f"job queued: {run_id}\n".encode())
            return
        if self.path.startswith("/run/software/device?"):
            self._handle_software_device_refresh()
        elif self.path.startswith("/run/software/"):
            self._respond(410, b"software refreshes are requested from Operations\n")
        elif self.path.startswith("/run/sources"):
            self._respond(410, b"source refreshes are managed in Operations Sources\n")
        elif self.path.startswith("/agent-compliance/action/"):
            self._respond(410, b"agent compliance was retired; use Operations\n")
        else:
            self.send_error(404)

    def _handle_software_device_refresh(self) -> None:
        """Queue one computer's software list and start the device worker now.

        Operations calls this for its "refresh this computer" actions.
        """
        if not _READY.is_set():
            self._respond(503, b"still starting - try again shortly\n")
            return
        raw = (parse_qs(urlparse(self.path).query).get("id", [""])[0]).strip()
        if not raw.isascii() or not raw.isdecimal():
            self._respond(400, b"id must be a Ninja device number\n")
            return
        try:
            software_queue.enqueue_activity(int(raw), reason="operator.refresh")
            run_id = operator_job_queue.request_system_job(
                "software-queue-drain", self.path
            )
        except Exception:
            log.exception("software device refresh request failed")
            self._respond(503, b"refresh could not be queued\n")
            return
        self._respond(202, f"software refresh queued: {run_id}\n".encode())

    def _respond(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
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
        "/run/resolver, /run/software/device?id=<ninja id>)",
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
