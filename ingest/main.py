"""Ingest entry point.

Boot sequence:
  1. Load settings, configure logging.
  2. Start HTTP server FIRST in a background thread so /healthz is
     reachable immediately. Docker HEALTHCHECK polls this — if the
     server isn't up within start-period, the container gets killed
     mid-startup (which historically caused migration rollback loops).
     /readyz reports starting/ready state; /healthz is always green
     once the listener binds.
  3. Initialise DB pool.
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

from ingest import db, migrations
from ingest.config import settings
from ingest.logging_utils import install_log_safety
from ingest.activities import ingest as activities_ingest
from ingest.agent_compliance import ingest as agent_compliance_ingest
from ingest.agent_compliance import review_digest
from ingest.source_observations import run_source_observations
from ingest import source_run_queue
from ingest.inventory.refresh import refresh_current as refresh_inventory_current
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
from ingest.identity.client_resolver import drain_client_resolution as _drain_client_resolution
from ingest.identity.resolver import drain_resolution as _drain_resolution
from ingest import scope_selector as _scope_selector
from ingest.patches import ingest as patches_ingest
from ingest.summary_views import refresh_device_troubleshooting_signal

log = logging.getLogger("ingest.main")
_AGENT_COMPLIANCE_LOCK = threading.Lock()


def run_once() -> None:
    run_patching_once()


def run_patching_once() -> None:
    """Execute one full patch/Ninja ingest cycle. Modules run in dependency order
    with per-module exception isolation: a failure in one module is
    logged with status='failed' in run_log and the rest continue.
    Shared `snapshot_at` so all rows from a single run carry the
    same first/last_observed_at."""
    log.info("Patch ingest run starting")
    snapshot_at = datetime.now(timezone.utc)
    with NinjaClient(
        base_url=settings.NINJA_BASE_URL,
        token_url=settings.NINJA_TOKEN_URL,
        client_id=settings.NINJA_CLIENT_ID,
        client_secret=settings.NINJA_CLIENT_SECRET.get_secret_value(),
        scope=settings.NINJA_SCOPE,
    ) as client:
        _safe("organizations",  organizations.run, client)
        _safe("locations",      locations.run, client)
        _safe("policies",       policies.run, client)
        _safe("patching_enabled_policies", sync_patching_enabled_policies)
        _safe("devices",        devices.run, client, snapshot_at)
        _safe("device_health",  device_health.run, client, snapshot_at)
        _safe("custom_fields",  custom_fields.run, client, snapshot_at)
        _safe("patches",        patches_ingest.run, client, snapshot_at)
        _safe("activities",     activities_ingest.run, client)
        _safe("troubleshooting_signal", refresh_device_troubleshooting_signal)
        _refresh_inventory_current("patch ingest")
    log.info("Patch ingest run complete")


def _refresh_inventory_current(reason: str) -> None:
    if not settings.AGENT_COMPLIANCE_ENABLED:
        return
    try:
        log.info("Refreshing Inventory current facts after %s", reason)
        refresh_inventory_current()
    except Exception:
        log.exception("Inventory current refresh failed after %s", reason)


def run_identity_resolver_once() -> None:
    """Drain unresolved entity_observations and refresh agent_presence_current."""
    try:
        attached = _drain_client_resolution()
        log.info("Client resolver complete: attached=%d", attached)
    except Exception:
        log.exception("Client resolver failed")
    try:
        resolved = _drain_resolution(batch_size=500)
        log.info("Identity resolver complete: resolved=%d", resolved)
    except Exception:
        log.exception("Identity resolver failed")


def run_ninja_observations_once() -> None:
    """Sync Ninja orgs + devices into Operations without the full patch cycle.

    Runs org/location/device sync only — populates operations.devices,
    device_links, and entity_observations (agent.rmm), then refreshes
    agent_presence_current. Skips device-health, patches, activities,
    and custom fields, so it completes in seconds instead of minutes.
    Used by the source run queue demand trigger.
    """
    log.info("Ninja observations run starting")
    snapshot_at = datetime.now(timezone.utc)
    with NinjaClient(
        base_url=settings.NINJA_BASE_URL,
        token_url=settings.NINJA_TOKEN_URL,
        client_id=settings.NINJA_CLIENT_ID,
        client_secret=settings.NINJA_CLIENT_SECRET.get_secret_value(),
        scope=settings.NINJA_SCOPE,
    ) as client:
        _safe("organizations", organizations.run, client)
        _safe("locations",     locations.run, client)
        _safe("devices",       devices.run, client, snapshot_at)
    log.info("Ninja observations run complete")


def run_agent_observations_once() -> None:
    """Fetch S1/SC/LMI and write to entity_observations, then resolve device IDs."""
    try:
        sources = load_sources()
        observed_at = datetime.now(timezone.utc)
        counts = run_source_observations(sources, observed_at)
        total = sum(counts.values())
        log.info("Agent observations complete: %s total=%d", counts, total)
        if total:
            run_identity_resolver_once()
    except Exception:
        log.exception("Agent observations run failed")


def run_agent_compliance_once() -> None:
    if not settings.AGENT_COMPLIANCE_ENABLED:
        log.info("Agent compliance disabled; skipping run")
        return
    if not _AGENT_COMPLIANCE_LOCK.acquire(blocking=False):
        log.info("Agent compliance run skipped; another agent compliance job is running")
        return
    log.info("Agent compliance run starting")
    try:
        agent_compliance_ingest.run()
        _refresh_inventory_current("agent compliance run")
    finally:
        _AGENT_COMPLIANCE_LOCK.release()
    # Run resolver immediately after AC so new S1/SC/LMI observations get device_ids
    threading.Thread(target=run_identity_resolver_once, daemon=True).start()
    log.info("Agent compliance run complete")


def run_agent_compliance_evaluate_once() -> None:
    if not settings.AGENT_COMPLIANCE_ENABLED:
        log.info("Agent compliance disabled; skipping evaluate")
        return
    if not _AGENT_COMPLIANCE_LOCK.acquire(blocking=False):
        log.info("Agent compliance evaluate skipped; another agent compliance job is running")
        return
    log.info("Agent compliance evaluate starting")
    try:
        agent_compliance_ingest.evaluate(send_alerts=True)
        _refresh_inventory_current("agent compliance evaluate")
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


def run_software_queue_once() -> None:
    """Drain Q3 (activity) then Q1 (scheduled) up to the configured batch size."""
    if not settings.SOFTWARE_QUEUE_ENABLED:
        return
    with NinjaClient(
        base_url=settings.NINJA_BASE_URL,
        token_url=settings.NINJA_TOKEN_URL,
        client_id=settings.NINJA_CLIENT_ID,
        client_secret=settings.NINJA_CLIENT_SECRET.get_secret_value(),
        scope=settings.NINJA_SCOPE,
    ) as client:
        activity, scheduled = software_queue.drain_background(
            client, settings.SOFTWARE_QUEUE_WORKER_BATCH
        )
    log.info(
        "Software queue drain complete: activity=%d scheduled=%d",
        activity, scheduled,
    )


def run_software_scoped(df: str) -> None:
    log.info("Software inventory scoped run starting (df=%r)", df)
    with NinjaClient(
        base_url=settings.NINJA_BASE_URL,
        token_url=settings.NINJA_TOKEN_URL,
        client_id=settings.NINJA_CLIENT_ID,
        client_secret=settings.NINJA_CLIENT_SECRET.get_secret_value(),
        scope=settings.NINJA_SCOPE,
    ) as client:
        _safe("software.scoped", software_ingest.run, client, df)
    log.info("Software inventory scoped run complete (df=%r)", df)


def schedule_agent_compliance_evaluate(reason: str) -> bool:
    if not settings.AGENT_COMPLIANCE_ENABLED or not _READY.is_set():
        return False
    log.info("Scheduling agent compliance evaluate: %s", reason)
    threading.Thread(target=run_agent_compliance_evaluate_once, daemon=True).start()
    return True


def run_platform_evaluate_once() -> None:
    """Run the platform evaluator for tenant 1."""
    try:
        affected = platform_evaluate(tenant_id=1)
        log.info("Platform evaluate complete: findings_affected=%d", affected)
    except Exception:
        log.exception("Platform evaluate failed")


def run_review_digest_once() -> None:
    if not settings.AGENT_COMPLIANCE_ENABLED:
        log.info("Agent compliance disabled; skipping review digest")
        return
    if not settings.AGENT_COMPLIANCE_REVIEW_DIGEST_ENABLED:
        log.info("Review digest disabled; skipping")
        return
    log.info("Review digest starting")
    with run_log("agent_compliance.review_digest") as stats:
        sent = review_digest.send_review_digest(datetime.now(timezone.utc))
        stats["alerts_sent"] = sent
    log.info("Review digest complete")


def _safe(name: str, func, *args) -> None:
    try:
        func(*args)
    except Exception:
        log.exception("%s ingest failed; continuing with next module", name)


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


def bootstrap_metabase() -> None:
    """Provision dashboards in Metabase via API. Tolerates Metabase
    being down, not yet set up, or credentials missing — logs and
    returns rather than raising."""
    user = settings.MB_BOOTSTRAP_USER
    password = settings.MB_BOOTSTRAP_PASS.get_secret_value()
    url = settings.MB_BOOTSTRAP_URL

    if not user or not password:
        log.info(
            "Metabase auto-bootstrap disabled "
            "(MB_BOOTSTRAP_USER / MB_BOOTSTRAP_PASS not set in .env)"
        )
        return

    log.info("Waiting for Metabase at %s", redact_url(url))
    if not _wait_for_metabase(url, timeout=300):
        log.warning("Metabase not reachable after 5 min — skipping bootstrap")
        return

    if not _metabase_setup_complete(url):
        log.info(
            "Metabase first-run wizard not yet complete — skipping bootstrap "
            "(create admin user + Postgres data source in the UI, then "
            "restart ingest or hit POST /bootstrap-metabase)"
        )
        return

    log.info("Running Metabase dashboard bootstrap")
    try:
        from ingest.metabase_bootstrap import run_bootstrap
        from ingest.agent_compliance.metabase_bootstrap import (
            run_bootstrap as run_agent_compliance_bootstrap,
        )
        from ingest.inventory.metabase_bootstrap import (
            run_bootstrap as run_inventory_bootstrap,
        )
        urls = run_bootstrap(
            url=url,
            user=user,
            password=password,
            db_name=settings.MB_BOOTSTRAP_DB_NAME,
        )
        if settings.AGENT_COMPLIANCE_ENABLED:
            urls.extend(run_agent_compliance_bootstrap(
                url=url,
                user=user,
                password=password,
                db_name=settings.MB_BOOTSTRAP_DB_NAME,
            ))
            urls.extend(run_inventory_bootstrap(
                url=url,
                user=user,
                password=password,
                db_name=settings.MB_BOOTSTRAP_DB_NAME,
            ))
        for u in urls:
            log.info("Dashboard ready: %s", u)
    except Exception:
        log.exception("Metabase bootstrap failed (will not retry; trigger via /bootstrap-metabase)")


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
        elif self.path in ("/run/sources", "/run/sources/enqueue") or self.path.startswith("/run/sources/enqueue?"):
            self._handle_sources_enqueue()
        elif self.path == "/run/sources/queue":
            self._handle_sources_queue()
        elif self.path.startswith("/run/sources/demand/"):
            self._handle_sources_demand_status()
        elif self.path.startswith("/agent-compliance/action/") or self.path.startswith("/a/"):
            self._handle_agent_compliance_action()
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        if self.path == "/run":
            if not _READY.is_set():
                self._respond(503, b"still starting - try again shortly\n")
                return
            threading.Thread(target=run_patching_once, daemon=True).start()
            self._respond(202, b"run scheduled\n")
        elif self.path == "/run/patches":
            if not _READY.is_set():
                self._respond(503, b"still starting - try again shortly\n")
                return
            threading.Thread(target=run_patching_once, daemon=True).start()
            self._respond(202, b"patch run scheduled\n")
        elif self.path == "/run/agent-compliance":
            if not _READY.is_set():
                self._respond(503, b"still starting - try again shortly\n")
                return
            threading.Thread(target=run_agent_compliance_once, daemon=True).start()
            self._respond(202, b"agent compliance run scheduled\n")
        elif self.path == "/run/agent-compliance-evaluate":
            if not _READY.is_set():
                self._respond(503, b"still starting - try again shortly\n")
                return
            threading.Thread(target=run_agent_compliance_evaluate_once, daemon=True).start()
            self._respond(202, b"agent compliance evaluate scheduled\n")
        elif self.path == "/run/resolver":
            if not _READY.is_set():
                self._respond(503, b"still starting - try again shortly\n")
                return
            threading.Thread(target=run_identity_resolver_once, daemon=True).start()
            self._respond(202, b"resolver run scheduled\n")
        elif self.path == "/run/agent-compliance-review-digest":
            if not _READY.is_set():
                self._respond(503, b"still starting - try again shortly\n")
                return
            threading.Thread(target=run_review_digest_once, daemon=True).start()
            self._respond(202, b"review digest scheduled\n")
        elif self.path == "/run/software/enqueue" or self.path.startswith("/run/software/enqueue?"):
            self._handle_software_enqueue()
        elif self.path == "/run/software/scoped" or self.path.startswith("/run/software/scoped?"):
            self._handle_software_scoped()
        elif self.path == "/run/sources/enqueue" or self.path.startswith("/run/sources/enqueue?"):
            self._handle_sources_enqueue()
        elif self.path == "/bootstrap-metabase":
            threading.Thread(target=bootstrap_metabase, daemon=True).start()
            self._respond(202, b"metabase bootstrap scheduled\n")
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
                '<a href="/run/software/enqueue" style="color:#0b69a3;">Queue a demand run instead</a>'
                ' &middot; <a href="/run/software/queue" style="color:#0b69a3;">Queue status</a>'
                '</p>'
            )
            selector_html = _scope_selector.render_scope_selector(
                orgs, devices,
                action="/run/software/scoped",
                submit_label="Run scoped refresh",
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
  <p class="hint">Pulls software observations for the selected scope and writes them into Operations. All other devices are unchanged.</p>
  {selector_html}
</body>
</html>""".encode("utf-8")
            self._respond_html(200, body)
            return

        if not df:
            self._respond(400, b"missing df\n")
            return

        threading.Thread(
            target=run_software_scoped, args=(df,), daemon=True
        ).start()
        self._respond(
            202,
            f"software scoped run scheduled (df={df!r})\n".encode("utf-8"),
        )

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
                ' &middot; <a href="/run/software/scoped" style="color:#0b69a3;">Direct scoped run (bypasses queue)</a>'
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

        def _run() -> None:
            with NinjaClient(
                base_url=settings.NINJA_BASE_URL,
                token_url=settings.NINJA_TOKEN_URL,
                client_id=settings.NINJA_CLIENT_ID,
                client_secret=settings.NINJA_CLIENT_SECRET.get_secret_value(),
                scope=settings.NINJA_SCOPE,
            ) as client:
                software_queue.process_demand_entry(entry_id, client)

        threading.Thread(target=_run, daemon=True).start()

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
                <a href="/run/software/enqueue">New demand run</a> &middot;
                <a href="/run/software/scoped">Direct scoped run</a>
              </p>
            </body>
            </html>
        """.encode("utf-8")
        self._respond_html(200, body)

    def _handle_sources_enqueue(self) -> None:
        """Form to trigger on-demand runs for Ninja / S1 / SC / LMI."""
        if not _READY.is_set():
            self._respond(503, b"still starting - try again shortly\n")
            return
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        selected = params.get("source", [])
        confirm = params.get("confirm", ["0"])[0]

        if self.command == "GET" and confirm != "1":
            checkboxes = "\n".join(
                f'<label style="display:block;margin:6px 0">'
                f'<input type="checkbox" name="source" value="{s}" checked> {escape(s)}'
                f"</label>"
                for s in source_run_queue.SOURCES
            )
            body = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Source runs — trigger</title>
  <style>
    body {{ font-family: sans-serif; margin: 24px; color: #1f2933; max-width: 520px; }}
    h2 {{ margin-bottom: 4px; }}
    p.hint {{ color: #52606d; font-size: 14px; margin: 0 0 16px; }}
    button {{ margin-top: 18px; padding: 9px 18px; font-weight: 700; cursor: pointer; }}
    a {{ color: #0b69a3; }}
  </style>
</head>
<body>
  <h2>Trigger source run</h2>
  <p class="hint">Each selected source is enqueued independently and fires in its own thread.
     One pending entry per source is enforced — submitting again while running is safe.</p>
  <form method="get" action="/run/sources/enqueue">
    <input type="hidden" name="confirm" value="1">
    {checkboxes}
    <button type="submit">Run selected</button>
  </form>
  <p style="margin-top:20px;font-size:13px">
    <a href="/run/sources/queue">Queue status</a>
  </p>
</body>
</html>""".encode("utf-8")
            self._respond_html(200, body)
            return

        if not selected:
            self._respond(400, b"no source selected\n")
            return

        invalid = [s for s in selected if s not in source_run_queue.SOURCES]
        if invalid:
            self._respond(400, f"unknown source(s): {', '.join(invalid)}\n".encode())
            return

        for src in selected:
            source_run_queue.enqueue_and_run(src, reason="on_demand")

        location = "/run/sources/queue"
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _handle_sources_queue(self) -> None:
        """Overview of the source run queue."""
        if not _READY.is_set():
            self._respond(503, b"still starting - try again shortly\n")
            return
        details = source_run_queue.queue_details()
        statuses = ["pending", "processing", "done", "failed"]
        counts = details.get("counts", {})
        active = details.get("active", [])
        recent = details.get("recent", [])

        import datetime as _dt
        _now = _dt.datetime.now(_dt.timezone.utc)

        def _fmt_dt(dt) -> str:
            return dt.strftime("%H:%M:%S") if dt else "—"

        rows_html = ""
        for r in active:
            elapsed = ""
            if r.get("started_at"):
                st = r["started_at"]
                if st.tzinfo is None:
                    st = st.replace(tzinfo=_dt.timezone.utc)
                elapsed = f" ({int((_now - st).total_seconds())}s)"
            rows_html += (
                f"<tr style='background:#fff8e1'>"
                f"<td><a href='/run/sources/demand/{r['id']}'>{escape(r['df'])}</a></td><td>processing</td>"
                f"<td>{_fmt_dt(r.get('started_at'))}{elapsed}</td>"
                f"<td>—</td>"
                f"<td>{r['rows_seen'] if r.get('rows_seen') is not None else '—'}</td>"
                f"<td></td></tr>"
            )
        for r in recent:
            err_full = r.get("error") or ""
            err_cell = (
                f"<span style='color:#c0392b' title='{escape(err_full)}'>"
                f"{escape(err_full[:80])}{'…' if len(err_full) > 80 else ''}</span>"
                if err_full else ""
            )
            link = f"<a href='/run/sources/demand/{r['id']}'>{escape(r['df'])}</a>"
            rows_html += (
                f"<tr>"
                f"<td>{link}</td><td>{r['status']}</td>"
                f"<td>{_fmt_dt(r.get('started_at'))}</td>"
                f"<td>{_fmt_dt(r.get('completed_at'))}</td>"
                f"<td>{r['rows_seen'] if r.get('rows_seen') is not None else '—'}</td>"
                f"<td>{err_cell}</td></tr>"
            )

        count_cells = "".join(f"<td>{counts.get(s, 0)}</td>" for s in statuses)
        body = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Source run queue</title>
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
  <h2>Source run queue</h2>
  <p class="hint">Auto-refreshes every 15 s.</p>
  <table>
    <thead><tr><th>Pending</th><th>Processing</th><th>Done</th><th>Failed</th></tr></thead>
    <tbody><tr>{count_cells}</tr></tbody>
  </table>
  <h3 style="margin-top:24px;margin-bottom:4px">Recent runs</h3>
  <table>
    <thead><tr>
      <th>Source</th><th>Status</th><th>Started</th><th>Completed</th><th>Rows</th><th>Error</th>
    </tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
  <p style="margin-top:24px;">
    <a href="/run/sources/enqueue">Trigger a run</a>
  </p>
</body>
</html>""".encode("utf-8")
        self._respond_html(200, body)

    def _handle_sources_demand_status(self) -> None:
        """Per-entry status page for a source run queue entry."""
        if not _READY.is_set():
            self._respond(503, b"still starting - try again shortly\n")
            return
        parts = self.path.rstrip("/").rsplit("/", 1)
        try:
            entry_id = int(parts[-1])
        except (ValueError, IndexError):
            self._respond(400, b"invalid entry id\n")
            return

        entry = source_run_queue.get_status(entry_id)
        if entry is None:
            self._respond(404, b"entry not found\n")
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

        body = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Source run #{entry_id}</title>
  {refresh_meta}
  <style>
    body {{ font-family: sans-serif; margin: 24px; color: #1f2933; max-width: 720px; }}
    h2 {{ margin-bottom: 4px; }}
    .status {{ font-size: 18px; font-weight: 700; margin: 12px 0 20px; }}
    .pending    {{ color: #52606d; }}
    .processing {{ color: #0b69a3; }}
    .done       {{ color: #27ab83; }}
    .failed     {{ color: #ba2525; }}
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
  <h2>Source run #{entry_id}</h2>
  <p class="status {status}">{escape(status_label)}</p>
  <table>
    <tr><th>Source</th><td>{escape(entry["df"])}</td></tr>
    <tr><th>Reason</th><td>{escape(entry.get("reason") or "—")}</td></tr>
    <tr><th>Queued</th><td>{_fmt(entry.get("queued_at"))}</td></tr>
    <tr><th>Started</th><td>{_fmt(entry.get("started_at"))}</td></tr>
    <tr><th>Completed</th><td>{_fmt(entry.get("completed_at"))}</td></tr>
    <tr><th>Rows seen</th><td>{_fmt(entry.get("rows_seen"))}</td></tr>
    <tr><th>Attempts</th><td>{entry.get("attempts", 0)} / {entry.get("max_attempts", 3)}</td></tr>
  </table>
  {error_html}
  <p class="links">
    <a href="/run/sources/enqueue">Trigger a run</a> &middot;
    <a href="/run/sources/queue">Queue status</a>
  </p>
</body>
</html>""".encode("utf-8")
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
        "/run/software/demand/<id>, /run/sources/enqueue, "
        "/run/sources/queue, /run/sources/demand/<id>, /bootstrap-metabase)",
        *addr,
    )
    return httpd


def main() -> None:
    logging.basicConfig(
        level=settings.INGEST_LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    install_log_safety()

    # Bind HTTP server FIRST so /healthz is reachable before any
    # potentially-slow startup work. Keeps the Docker HEALTHCHECK
    # green and prevents migration-rollback restart loops.
    httpd = _start_http_server()

    log.info("Initialising DB pool")
    db.init(settings.postgres_dsn)

    log.info("Applying pending migrations")
    migrations.apply_pending()

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_patching_once,
        "interval",
        hours=settings.patch_ingest_schedule_hours,
        id="patch_ingest_cycle",
    )
    scheduler.add_job(
        run_agent_observations_once,
        "interval",
        hours=settings.AGENT_COMPLIANCE_SCHEDULE_HOURS,
        id="agent_observations_cycle",
        max_instances=1,
    )
    scheduler.add_job(
        source_run_queue.recover_stale,
        "interval",
        minutes=15,
        id="source_run_queue_stale_recovery",
    )
    # Legacy AC remains available by manual endpoint during cutover, but no
    # longer auto-runs. Operations validation uses source_observations,
    # identity resolver, and platform evaluator.
    scheduler.add_job(
        run_identity_resolver_once,
        "interval",
        minutes=30,
        id="identity_resolver_cycle",
        max_instances=1,
    )
    scheduler.add_job(
        run_platform_evaluate_once,
        "interval",
        hours=4,
        id="platform_evaluate_cycle",
        max_instances=1,
    )
    if settings.SOFTWARE_QUEUE_ENABLED:
        scheduler.add_job(
            enqueue_all_orgs_once,
            "interval",
            hours=settings.SOFTWARE_INGEST_SCHEDULE_HOURS,
            id="software_enqueue_orgs_cycle",
            max_instances=1,
        )
        scheduler.add_job(
            run_software_queue_once,
            "interval",
            minutes=settings.SOFTWARE_QUEUE_POLL_MINUTES,
            id="software_queue_drain_cycle",
            max_instances=1,
        )
    scheduler.start()
    log.info(
        "Patch scheduler started (every %dh)",
        settings.patch_ingest_schedule_hours,
    )
    if settings.SOFTWARE_QUEUE_ENABLED:
        log.info(
            "Software queue enabled: org enqueue every %dh, worker every %dm (batch=%d)",
            settings.SOFTWARE_INGEST_SCHEDULE_HOURS,
            settings.SOFTWARE_QUEUE_POLL_MINUTES,
            settings.SOFTWARE_QUEUE_WORKER_BATCH,
        )
    else:
        log.info("Software queue disabled (SOFTWARE_QUEUE_ENABLED=false)")
    log.info(
        "Agent observations scheduler started (every %dh)",
        settings.AGENT_COMPLIANCE_SCHEDULE_HOURS,
    )
    log.info("Legacy agent compliance auto-scheduler disabled")

    if should_catch_up("patches", settings.patch_ingest_schedule_hours):
        log.info(
            "Catch-up: last successful run > %dh ago — firing run_once",
            settings.patch_ingest_schedule_hours,
        )
        threading.Thread(target=run_patching_once, daemon=True).start()
    else:
        log.info("No patch catch-up needed (fresh install or recent run)")

    threading.Thread(target=run_agent_observations_once, daemon=True).start()
    log.info("Agent observations: firing immediately on startup")

    log.info("Legacy agent compliance catch-up disabled")

    # Kick off Metabase bootstrap in the background — won't block
    # startup if Metabase isn't ready or creds aren't set.
    threading.Thread(target=bootstrap_metabase, daemon=True).start()

    _READY.set()
    log.info("Ingest service ready")

    # Block forever holding the server reference (the daemon thread
    # serving requests dies if this main thread exits).
    try:
        threading.Event().wait()
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    main()
