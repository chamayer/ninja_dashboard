"""Development settings overlay."""

from __future__ import annotations

import os

from .base import *

DEBUG = True

# Local development host list.
ALLOWED_HOSTS = ["*"]

# Loosen DRF for interactive use.
REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
}

# Enable stricter tenant-GUC assertion in dev (BLUEPRINT §6.3).
OPERATIONS_STRICT_TENANT = os.environ.get("OPERATIONS_STRICT_TENANT", "1") == "1"

# Non-manifest static in dev so hot-reload works without `collectstatic`.
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"
