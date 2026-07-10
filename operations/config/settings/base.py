"""
Base Django settings for Operations.

Environment-driven; per-env modules (dev.py, prod.py) import from here and
override for their context. See BLUEPRINT.md §11 for the environment story.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load .env from the ninja-dashboard host data root (matches BLUEPRINT §11).
# Falls back silently in dev when the file is not present.
load_dotenv(os.environ.get("OPERATIONS_ENV_FILE", "/amr-ch-01_data/ninja-dashboard/.env"))
load_dotenv(BASE_DIR / ".env", override=False)

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

SECRET_KEY = os.environ.get(
    "OPERATIONS_SECRET_KEY",
    # Dev-only fallback; prod refuses to start without an explicit key.
    "insecure-dev-key-change-me",
)

DEBUG = os.environ.get("OPERATIONS_DEBUG", "0") == "1"

ALLOWED_HOSTS = [h.strip() for h in os.environ.get("OPERATIONS_ALLOWED_HOSTS", "*").split(",") if h.strip()]

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "drf_spectacular",
    "django_htmx",
    # First-party
    "apps.core.apps.OperationsCoreConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.TenantMiddleware",
    "apps.core.middleware.ClientScopeMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.brand",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# Real config lands with the schema commit; skeleton uses SQLite so
# `manage.py check` runs. Prod / dev override this to Postgres.

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "skeleton.sqlite3",
        # ATOMIC_REQUESTS mandated by BLUEPRINT §6.3 (RLS lifecycle) — set
        # here so it applies to every DB configured for this project once
        # the schema commit swaps SQLite for Postgres.
        "ATOMIC_REQUESTS": True,
    },
}

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "operations.User"

# login_required redirects here. Admin login gets us into the app until
# we ship dedicated login views.
LOGIN_URL = "/admin/login/"
LOGIN_REDIRECT_URL = "/"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# I18n / TZ
# ---------------------------------------------------------------------------
# UTC in DB per BLUEPRINT §4.13 (USE_TZ keeps storage UTC); TIME_ZONE only
# controls template rendering.

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/New_York"
USE_I18N = False   # non-goal per BLUEPRINT §2
USE_TZ = True

# ---------------------------------------------------------------------------
# Static / Media
# ---------------------------------------------------------------------------

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Compressed (gzip/brotli) but NOT manifest-strict. Manifest storage 500s
# hard if any {% static %} tag references a file that isn't in the
# manifest (common with third-party admin apps + Django admin). Revisit
# when we ship a real static-asset pipeline.
STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"

# ---------------------------------------------------------------------------
# DRF
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        # Bearer token auth added with user_tokens table.
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Operations API",
    "DESCRIPTION": "Write-side companion to Metabase for the ninja-dashboard stack.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Brand (BLUEPRINT §4.16 appliance rebrand path)
# ---------------------------------------------------------------------------

OPERATIONS_BRAND_NAME = os.environ.get("OPERATIONS_BRAND_NAME", "AMRose Operations")
OPERATIONS_BRAND_SHORT = os.environ.get("OPERATIONS_BRAND_SHORT", "Operations")
OPERATIONS_BRAND_TAGLINE = os.environ.get("OPERATIONS_BRAND_TAGLINE", "")
OPERATIONS_SUPPORT_URL = os.environ.get("OPERATIONS_SUPPORT_URL", "")
OPERATIONS_PRIVACY_URL = os.environ.get("OPERATIONS_PRIVACY_URL", "")
OPERATIONS_BASE_URL = os.environ.get("OPERATIONS_BASE_URL", "http://localhost:3002")

# ---------------------------------------------------------------------------
# Ports
# ---------------------------------------------------------------------------
# UI + API on 3002 (LAN); health / internal ops on 8091 (loopback).
# Gunicorn bind is configured by the container entrypoint, not Django.
