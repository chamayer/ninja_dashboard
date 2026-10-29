"""Development settings overlay."""

from __future__ import annotations

import os

from .base import *

DEBUG = True

# Full local Compose uses the same PostgreSQL role split as production.
# The base settings intentionally remain SQLite for lightweight module checks.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("OPERATIONS_DB_NAME", "ninja_dev"),
        "USER": os.environ.get("OPERATIONS_DB_USER", "operations_app"),
        "PASSWORD": os.environ.get("OPERATIONS_DB_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "postgres"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "ATOMIC_REQUESTS": True,
        "OPTIONS": {
            "options": "-c search_path=operations,public",
            "connect_timeout": 5,
            "application_name": "operations-dev",
        },
    },
}

OPERATIONS_MIGRATE_DB_USER = os.environ.get("OPERATIONS_MIGRATE_DB_USER", "operations_migrate")
OPERATIONS_MIGRATE_DB_PASSWORD = os.environ.get("OPERATIONS_MIGRATE_DB_PASSWORD", "")

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
