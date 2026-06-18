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
from ingest.runlog import run_log
from ingest.agent_compliance.config_loader import (
    add_device_ignore,
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
    log.info("Patch ingest run complete")


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
    finally:
        _AGENT_COMPLIANCE_LOCK.release()
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
    finally:
        _AGENT_COMPLIANCE_LOCK.release()
    log.info("Agent compliance evaluate complete")


def schedule_agent_compliance_evaluate(reason: str) -> bool:
    if not settings.AGENT_COMPLIANCE_ENABLED or not _READY.is_set():
        return False
    log.info("Scheduling agent compliance evaluate: %s", reason)
    threading.Thread(target=run_agent_compliance_evaluate_once, daemon=True).start()
    return True


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
        elif self.path == "/run/agent-compliance-review-digest":
            if not _READY.is_set():
                self._respond(503, b"still starting - try again shortly\n")
                return
            threading.Thread(target=run_review_digest_once, daemon=True).start()
            self._respond(202, b"review digest scheduled\n")
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
        "/run/agent-compliance, /run/agent-compliance-evaluate, /bootstrap-metabase)",
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
            max_instances=1,
        )
        scheduler.add_job(
            run_agent_compliance_evaluate_once,
            "interval",
            minutes=settings.AGENT_COMPLIANCE_EVALUATE_SCHEDULE_MINUTES,
            id="agent_compliance_evaluate_cycle",
            max_instances=1,
        )
        if settings.AGENT_COMPLIANCE_REVIEW_DIGEST_ENABLED:
            scheduler.add_job(
                run_review_digest_once,
                "cron",
                hour=settings.AGENT_COMPLIANCE_REVIEW_DIGEST_HOUR,
                minute=0,
                id="agent_compliance_review_digest",
                max_instances=1,
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
        log.info(
            "Agent compliance evaluate scheduler started (every %dm)",
            settings.AGENT_COMPLIANCE_EVALUATE_SCHEDULE_MINUTES,
        )
        if settings.AGENT_COMPLIANCE_REVIEW_DIGEST_ENABLED:
            log.info(
                "Review digest scheduler started (daily at %02d:00 UTC)",
                settings.AGENT_COMPLIANCE_REVIEW_DIGEST_HOUR,
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
