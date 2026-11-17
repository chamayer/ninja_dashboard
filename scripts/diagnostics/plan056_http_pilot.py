"""Approved-use-only task 4 pilot: normal admin login and one Settings GET.

Uses mounted credentials in memory. Never prints credentials, cookies, bodies,
user identifiers or exception text. Does not import Django or use its test client.
Authentication/session/last-login effects and logout require explicit approval.
"""

from __future__ import annotations

import http.cookiejar
import json
import secrets
import signal
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path


BASE = "http://127.0.0.1:3002"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class CSRFParser(HTMLParser):
    token = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("name") == "csrfmiddlewaretoken":
            self.token = attrs.get("value")


def emit(section, **data):
    print(
        json.dumps(
            {"utc": datetime.now(timezone.utc).isoformat(), "section": section, **data}
        ),
        flush=True,
    )


def main(measure=None):
    from dotenv import dotenv_values

    candidates = [Path("/app/envdir/.env"), Path("/app/.env")]
    env_path = next((p for p in candidates if p.is_file()), None)
    if env_path is None:
        emit("stopped", reason="mounted_environment_unavailable")
        return 1
    # Existing seed convention is username admin. Do not enumerate/select users.
    password = str(
        dotenv_values(env_path).get("OPERATIONS_INITIAL_ADMIN_PASSWORD") or ""
    ).strip()
    if not password:
        emit("stopped", reason="configured_password_unavailable")
        return 1
    cookies = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cookies), NoRedirect
    )
    marker = secrets.token_hex(16) + "_1"
    emit(
        "scope",
        marker=marker,
        role="configured_admin",
        endpoint="internal_loopback",
        page="/admin/settings/" if measure is None else "reviewed_matrix",
        deadline_s=20,
        cache="first_observed_unknown",
    )

    def request(path, data=None, *, timeout=20):
        req = urllib.request.Request(
            BASE + path,
            data=data,
            headers={
                "Accept": "text/html",
                "User-Agent": "PLAN-056-approved-pilot"
                if measure is None
                else "PLAN-056-approved-matrix",
                "Referer": BASE + "/login/",
            },
        )
        try:
            return opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as response:
            return response

    logged_in = False
    try:
        with request("/login/") as response:
            if response.status != 200:
                emit("stopped", reason="login_form_unavailable", status=response.status)
                return 1
            parser = CSRFParser()
            parser.feed(response.read(262144).decode("utf-8", errors="replace"))
        if not parser.token:
            emit("stopped", reason="csrf_token_unavailable")
            return 1
        data = urllib.parse.urlencode(
            {
                "username": "admin",
                "password": password,
                "csrfmiddlewaretoken": parser.token,
                "next": "/admin/settings/",
            }
        ).encode()
        with request("/login/", data=data) as response:
            logged_in = any(cookie.name == "sessionid" for cookie in cookies)
            if (
                response.status != 302
                or response.headers.get("Location") != "/admin/settings/"
            ):
                emit("stopped", reason="login_not_confirmed", status=response.status)
                return 1
        if not logged_in:
            emit("stopped", reason="session_cookie_unavailable")
            return 1
        if measure is not None:
            return measure(request, marker.rsplit("_", 1)[0])
        started = time.monotonic()

        def deadline(signum, frame):
            raise TimeoutError()

        signal.signal(signal.SIGALRM, deadline)
        signal.setitimer(signal.ITIMER_REAL, 20)
        try:
            with request("/admin/settings/?_plan056=" + marker) as response:
                headers_s = time.monotonic() - started
                size = 0
                while True:
                    if time.monotonic() - started >= 20:
                        raise TimeoutError()
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    size += len(chunk)
                emit(
                    "page",
                    marker=marker,
                    status=response.status,
                    headers_s=round(headers_s, 3),
                    elapsed_s=round(time.monotonic() - started, 3),
                    bytes=size,
                    success=response.status == 200,
                )
                return 0 if response.status == 200 else 1
        except Exception as error:
            emit(
                "page_incomplete",
                marker=marker,
                error=type(error).__name__,
                elapsed_s=round(time.monotonic() - started, 3),
                server_completion="unverified",
            )
            return 1
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
    finally:
        # Normal logout is housekeeping, not another measured page or a user/job
        # cancellation. A failed logout is reported; do not claim session cleanup.
        if logged_in:
            token = next((c.value for c in cookies if c.name == "csrftoken"), None)
            if token:
                try:
                    data = urllib.parse.urlencode(
                        {"csrfmiddlewaretoken": token}
                    ).encode()
                    with request("/logout/", data=data) as response:
                        emit(
                            "logout",
                            status=response.status,
                            confirmed=response.status in (200, 302)
                            and not any(c.name == "sessionid" for c in cookies),
                        )
                except Exception as error:
                    emit("logout_incomplete", error=type(error).__name__)
            else:
                emit("logout_incomplete", reason="csrf_cookie_unavailable")
        cookies.clear()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        emit("setup_failed", error=type(error).__name__)
        raise SystemExit(1) from None
