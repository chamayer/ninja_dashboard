"""Ingest entry point.

Boot sequence:
  1. Load settings, configure logging.
  2. Initialise DB pool.
  3. Apply pending migrations.
  4. Start APScheduler at the configured interval. No jobs wired yet —
     each ingest module adds its job once it lands.
  5. Catch-up: if the last successful core run is older than the
     schedule interval, fire run_once now in a background thread.
     Fresh installs (no run_log rows) wait for the first scheduled tick.
  6. Start HTTP server for /healthz and /run, block forever.
"""

from __future__ import annotations

import http.server
import logging
import socketserver
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
from apscheduler.schedulers.background import BackgroundScheduler

from ingest import db, migrations
from ingest.config import settings
from ingest.activities import ingest as activities_ingest
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
from ingest.patches import ingest as patches_ingest
from ingest.summary_views import refresh_device_troubleshooting_signal

log = logging.getLogger("ingest.main")


def run_once() -> None:
    """Execute one full ingest cycle. Modules run in dependency order
    with per-module exception isolation: a failure in one module is
    logged with status='failed' in run_log and the rest continue.
    Shared `snapshot_at` so all rows from a single run carry the
    same first/last_observed_at."""
    log.info("Ingest run starting")
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
    log.info("Ingest run complete")


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

    log.info("Waiting for Metabase at %s", url)
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
        urls = run_bootstrap(
            url=url,
            user=user,
            password=password,
            db_name=settings.MB_BOOTSTRAP_DB_NAME,
        )
        for u in urls:
            log.info("Dashboard ready: %s", u)
    except Exception:
        log.exception("Metabase bootstrap failed (will not retry; trigger via /bootstrap-metabase)")


def last_successful_run_at() -> datetime | None:
    with db.transaction() as cur:
        cur.execute(
            "SELECT MAX(finished_at) FROM ninja_core.run_log "
            "WHERE status = 'ok'"
        )
        row = cur.fetchone()
        return row[0] if row else None


def should_catch_up(now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    last = last_successful_run_at()
    if last is None:
        return False
    return (now - last) > timedelta(hours=settings.INGEST_SCHEDULE_HOURS)


# ── HTTP endpoints ──────────────────────────────────────────────────

class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        log.info("http %s - %s", self.address_string(), fmt % args)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._respond(200, b"ok\n")
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        if self.path == "/run":
            threading.Thread(target=run_once, daemon=True).start()
            self._respond(202, b"run scheduled\n")
        elif self.path == "/bootstrap-metabase":
            threading.Thread(target=bootstrap_metabase, daemon=True).start()
            self._respond(202, b"metabase bootstrap scheduled\n")
        else:
            self.send_error(404)

    def _respond(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> None:
    logging.basicConfig(
        level=settings.INGEST_LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    log.info("Initialising DB pool")
    db.init(settings.postgres_dsn)

    log.info("Applying pending migrations")
    migrations.apply_pending()

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_once,
        "interval",
        hours=settings.INGEST_SCHEDULE_HOURS,
        id="ingest_cycle",
    )
    scheduler.start()
    log.info(
        "Scheduler started (every %dh, no jobs wired yet)",
        settings.INGEST_SCHEDULE_HOURS,
    )

    if should_catch_up():
        log.info(
            "Catch-up: last successful run > %dh ago — firing run_once",
            settings.INGEST_SCHEDULE_HOURS,
        )
        threading.Thread(target=run_once, daemon=True).start()
    else:
        log.info("No catch-up needed (fresh install or recent run)")

    # Kick off Metabase bootstrap in the background — won't block
    # startup if Metabase isn't ready or creds aren't set.
    threading.Thread(target=bootstrap_metabase, daemon=True).start()

    addr = ("0.0.0.0", settings.INGEST_HTTP_PORT)
    log.info(
        "HTTP server listening on %s:%d (/healthz, /run, /bootstrap-metabase)",
        *addr,
    )
    with _ThreadingServer(addr, _Handler) as httpd:
        httpd.serve_forever()


if __name__ == "__main__":
    main()
