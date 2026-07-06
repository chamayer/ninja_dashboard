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

# Secure cookies + HSTS assume the LAN reverse proxy handles TLS; if the
# deploy shape ever changes to direct-Gunicorn HTTP, revisit these.
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "SAMEORIGIN"

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
