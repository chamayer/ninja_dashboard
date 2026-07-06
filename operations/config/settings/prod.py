"""Production settings overlay for am-ch-01."""

from __future__ import annotations

import os
import sys

from .base import *  # noqa: F401,F403

DEBUG = False

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
