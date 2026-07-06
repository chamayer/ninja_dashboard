from __future__ import annotations

from django.apps import AppConfig


class OperationsCoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    label = "operations"
    name = "apps.core"
    verbose_name = "Operations"
