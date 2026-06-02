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
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from ingest import db, migrations
from ingest.config import settings
from ingest.core import organizations
from ingest.ninja_client import NinjaClient

log = logging.getLogger("ingest.main")


def run_once() -> None:
    """Execute one full ingest cycle. Modules added here in order:
    core lookups → devices → custom fields → patches → activities."""
    log.info("Ingest run starting")
    with NinjaClient(
        base_url=settings.NINJA_BASE_URL,
        token_url=settings.NINJA_TOKEN_URL,
        client_id=settings.NINJA_CLIENT_ID,
        client_secret=settings.NINJA_CLIENT_SECRET.get_secret_value(),
        scope=settings.NINJA_SCOPE,
    ) as client:
        organizations.run(client)
        # TODO: locations.run, policies.run, devices.run,
        # custom_fields.run, patches.run, activities.run
    log.info("Ingest run complete")


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

    addr = ("0.0.0.0", settings.INGEST_HTTP_PORT)
    log.info("HTTP server listening on %s:%d (/healthz, /run)", *addr)
    with _ThreadingServer(addr, _Handler) as httpd:
        httpd.serve_forever()


if __name__ == "__main__":
    main()
