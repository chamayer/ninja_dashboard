"""Production settings overlay for am-ch-01."""

from __future__ import annotations

import os
import sys

from .base import *  # noqa: F401,F403
from .base import BASE_DIR  # noqa: F401  (kept for future overrides)

DEBUG = False

# ---------------------------------------------------------------------------
# Postgres
# ---------------------------------------------------------------------------
# All keys sourced from /amr-ch-01_data/ninja-dashboard/.env (bind-mounted).
# Missing values fail loud below alongside SECRET_KEY / ALLOWED_HOSTS.

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
