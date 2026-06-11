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

import http.server
import logging
import socketserver
import threading
import time
from urllib.parse import parse_qs, urlparse
from datetime import datetime, timedelta, timezone

import httpx
from apscheduler.schedulers.background import BackgroundScheduler

from ingest import db, migrations
from ingest.config import settings
from ingest.logging_utils import install_log_safety
from ingest.activities import ingest as activities_ingest
from ingest.agent_compliance import ingest as agent_compliance_ingest
from ingest.agent_compliance.config_loader import (
    add_device_ignore,
    add_org_exclude,
    promote_alignment_aliases,
    remove_org_exclude,
    remove_device_ignore,
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
from ingest.patches import ingest as patches_ingest
from ingest.summary_views import refresh_device_troubleshooting_signal

log = logging.getLogger("ingest.main")


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
    log.info("Patch ingest run complete")


def run_agent_compliance_once() -> None:
    if not settings.AGENT_COMPLIANCE_ENABLED:
        log.info("Agent compliance disabled; skipping run")
        return
    log.info("Agent compliance run starting")
    agent_compliance_ingest.run()
    log.info("Agent compliance run complete")


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
        elif self.path.startswith("/agent-compliance/action/"):
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
        params = parse_qs(parsed.query)
        confirm = params.get("confirm", ["0"])[0]
        if confirm != "1":
            self._respond(400, b"missing confirm=1\n")
            return

        if parsed.path == "/agent-compliance/action/add-alias":
            client_id_value = params.get("client_id", [""])[0]
            try:
                client_id = int(client_id_value)
            except ValueError:
                self._respond(400, b"invalid client_id\n")
                return
            platform = params.get("platform", [""])[0].strip() or None
            alias_hex = params.get("alias_hex", [""])[0]
            alias_value = None
            if alias_hex:
                try:
                    alias_value = bytes.fromhex(alias_hex).decode("utf-8")
                except ValueError:
                    self._respond(400, b"invalid alias_hex\n")
                    return
            count = promote_alignment_aliases(client_id, platform=platform, alias_value=alias_value)
            body = f"added {count} alias row(s)\n".encode("utf-8")
            self._respond(200, body)
            return

        if parsed.path == "/agent-compliance/action/exclude-org":
            pattern_hex = params.get("pattern_hex", [""])[0]
            if not pattern_hex:
                self._respond(400, b"missing pattern_hex\n")
                return
            try:
                pattern = bytes.fromhex(pattern_hex).decode("utf-8")
            except ValueError:
                self._respond(400, b"invalid pattern_hex\n")
                return
            if add_org_exclude(pattern, notes="Added from operator dashboard"):
                body = f"excluded {pattern}\n".encode("utf-8")
                self._respond(200, body)
            else:
                self._respond(400, b"blank pattern\n")
            return

        if parsed.path == "/agent-compliance/action/unexclude-org":
            pattern_hex = params.get("pattern_hex", [""])[0]
            if not pattern_hex:
                self._respond(400, b"missing pattern_hex\n")
                return
            try:
                pattern = bytes.fromhex(pattern_hex).decode("utf-8")
            except ValueError:
                self._respond(400, b"invalid pattern_hex\n")
                return
            if remove_org_exclude(pattern):
                body = f"restored {pattern}\n".encode("utf-8")
                self._respond(200, body)
            else:
                self._respond(404, b"not found or not removable\n")
            return

        if parsed.path == "/agent-compliance/action/ignore-device":
            client_hex = params.get("client_hex", [""])[0]
            host_hex = params.get("host_hex", [""])[0]
            if not client_hex or not host_hex:
                self._respond(400, b"missing client_hex or host_hex\n")
                return
            try:
                client_name = bytes.fromhex(client_hex).decode("utf-8")
                hostname = bytes.fromhex(host_hex).decode("utf-8")
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
            except ValueError:
                self._respond(400, b"invalid device reference\n")
                return
            if add_device_ignore(client_id, norm_name, display_name=hostname):
                body = f"ignored {norm_name}\n".encode("utf-8")
                self._respond(200, body)
            else:
                self._respond(400, b"blank norm_name\n")
            return

        if parsed.path == "/agent-compliance/action/unignore-device":
            client_hex = params.get("client_hex", [""])[0]
            host_hex = params.get("host_hex", [""])[0]
            if not client_hex or not host_hex:
                self._respond(400, b"missing client_hex or host_hex\n")
                return
            try:
                client_name = bytes.fromhex(client_hex).decode("utf-8")
                hostname = bytes.fromhex(host_hex).decode("utf-8")
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
            except ValueError:
                self._respond(400, b"invalid device reference\n")
                return
            if remove_device_ignore(client_id, norm_name):
                body = f"restored {norm_name}\n".encode("utf-8")
                self._respond(200, body)
            else:
                self._respond(404, b"not found or not removable\n")
            return

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
        "/run/agent-compliance, /bootstrap-metabase)",
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
    if settings.AGENT_COMPLIANCE_ENABLED:
        scheduler.add_job(
            run_agent_compliance_once,
            "interval",
            hours=settings.AGENT_COMPLIANCE_SCHEDULE_HOURS,
            id="agent_compliance_cycle",
        )
    scheduler.start()
    log.info(
        "Patch scheduler started (every %dh)",
        settings.patch_ingest_schedule_hours,
    )
    if settings.AGENT_COMPLIANCE_ENABLED:
        log.info(
            "Agent compliance scheduler started (every %dh)",
            settings.AGENT_COMPLIANCE_SCHEDULE_HOURS,
        )

    if should_catch_up("patches", settings.patch_ingest_schedule_hours):
        log.info(
            "Catch-up: last successful run > %dh ago — firing run_once",
            settings.patch_ingest_schedule_hours,
        )
        threading.Thread(target=run_patching_once, daemon=True).start()
    else:
        log.info("No patch catch-up needed (fresh install or recent run)")

    if (
        settings.AGENT_COMPLIANCE_ENABLED
        and should_catch_up("agent_compliance", settings.AGENT_COMPLIANCE_SCHEDULE_HOURS)
    ):
        log.info(
            "Catch-up: last successful agent compliance run > %dh ago",
            settings.AGENT_COMPLIANCE_SCHEDULE_HOURS,
        )
        threading.Thread(target=run_agent_compliance_once, daemon=True).start()

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
