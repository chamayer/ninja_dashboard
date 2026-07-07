"""Production settings overlay for am-ch-01."""

from __future__ import annotations

import os
import sys

from .base import *

DEBUG = False

# ---------------------------------------------------------------------------
# Postgres
# ---------------------------------------------------------------------------
# All keys sourced from /amr-ch-01_data/ninja-dashboard/.env (bind-mounted).
# Missing values fail loud below alongside SECRET_KEY / ALLOWED_HOSTS.
#
# Runtime workers use operations_app. The entrypoint temporarily exports
# OPERATIONS_DB_USER/PASSWORD from the migration variables below before
# running `manage.py migrate`, then switches back to runtime credentials
# before launching Gunicorn.

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("OPERATIONS_DB_NAME", "ninja"),
        "USER": os.environ.get("OPERATIONS_DB_USER", "operations_app"),
        "PASSWORD": os.environ.get("OPERATIONS_DB_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "postgres"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        # BLUEPRINT §6.3 — every request runs inside one transaction so the
        # SET LOCAL operations.tenant_id issued by TenantMiddleware persists
        # for the whole request.
        "ATOMIC_REQUESTS": True,
        "OPTIONS": {
            # Django tables + operations schema first on search_path.
            # ninja_* schemas readable when granted (managed=False models).
            "options": "-c search_path=operations,public",
            "connect_timeout": 5,
        },
    },
}

OPERATIONS_MIGRATE_DB_USER = os.environ.get("OPERATIONS_MIGRATE_DB_USER", "operations_migrate")
OPERATIONS_MIGRATE_DB_PASSWORD = os.environ.get("OPERATIONS_MIGRATE_DB_PASSWORD", "")


# Refuse to start without an explicit secret key in prod.
if os.environ.get("OPERATIONS_SECRET_KEY") in (None, "", "insecure-dev-key-change-me"):
    sys.stderr.write(
        "OPERATIONS_SECRET_KEY must be set in prod. Refusing to start.\n"
    )
    sys.exit(1)

# ALLOWED_HOSTS must be explicit in prod.
_allowed = os.environ.get("OPERATIONS_ALLOWED_HOSTS", "").strip()
if not _allowed:
    sys.stderr.write(
        "OPERATIONS_ALLOWED_HOSTS must be set in prod. Refusing to start.\n"
    )
    sys.exit(1)
ALLOWED_HOSTS = [h.strip() for h in _allowed.split(",") if h.strip()]

if not os.environ.get("OPERATIONS_DB_PASSWORD"):
    sys.stderr.write(
        "OPERATIONS_DB_PASSWORD must be set for the runtime operations_app role. Refusing to start.\n"
    )
    sys.exit(1)

if not OPERATIONS_MIGRATE_DB_PASSWORD:
    sys.stderr.write(
        "OPERATIONS_MIGRATE_DB_PASSWORD must be set for migrations. Refusing to start.\n"
    )
    sys.exit(1)

# TLS-dependent settings toggled by OPERATIONS_HTTPS env var. Default is
# off (direct-Gunicorn HTTP on port 3002). Flip to "1" once a TLS
# reverse proxy is in front.
#
# SESSION_COOKIE_SECURE=True + HTTP breaks logins: the browser refuses
# to send the session cookie back, so every POST looks anonymous.
# Same story for CSRF_COOKIE_SECURE — the CSRF token never returns and
# every form submit 403s.
_https_mode = os.environ.get("OPERATIONS_HTTPS", "0") == "1"

SESSION_COOKIE_SECURE = _https_mode
CSRF_COOKIE_SECURE = _https_mode
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30 if _https_mode else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = _https_mode
SECURE_HSTS_PRELOAD = False
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "SAMEORIGIN"

# Django's CSRF check requires the Origin/Referer host+port to appear in
# CSRF_TRUSTED_ORIGINS for cross-origin form submits (which admin login
# on a non-standard port qualifies as). Auto-derive from ALLOWED_HOSTS
# with the current scheme so LAN hostnames + IPs both work.
_scheme = "https" if _https_mode else "http"
_default_port = "443" if _https_mode else "3002"
CSRF_TRUSTED_ORIGINS = [
    f"{_scheme}://{host}" if ":" in host or host in ("localhost", "127.0.0.1")
    else f"{_scheme}://{host}:{_default_port}"
    for host in ALLOWED_HOSTS
    if host not in ("*",)
]

# Strict tenant assertion off in prod (would panic on any missing GUC —
# want it in dev only per BLUEPRINT §6.3).
OPERATIONS_STRICT_TENANT = False

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# Django's default routes django.request ERROR to mail_admins only. Without
# an admin email configured, 500 tracebacks disappear silently and only the
# status line reaches stdout via gunicorn. Route django.request ERROR to
# stderr so tracebacks land in `docker logs`.

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}
