from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.template.loader import get_template
from django.test import RequestFactory

from apps.core import views


class _User:
    is_authenticated = True

    def __init__(self, *, is_superuser: bool, may_manage_catalog: bool = False) -> None:
        self.is_superuser = is_superuser
        self._may_manage_catalog = may_manage_catalog

    def has_perm(self, permission: str) -> bool:
        return permission == "operations.manage_catalog" and self._may_manage_catalog


class _Rows:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def order_by(self, *_args: str) -> _Rows:
        return self

    def values(self, *_fields: str) -> _Rows:
        return self

    def __iter__(self):
        return iter(self.rows)

    def __getitem__(self, item):
        return self.rows[item]


class _Cursor:
    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, *_args: object) -> None:
        return None


def test_lifecycle_policy_status_requires_shared_admin_permission():
    request = RequestFactory().get("/admin/lifecycle/")
    request.user = _User(is_superuser=False)

    with pytest.raises(PermissionDenied):
        views.lifecycle_policy_status(request)


def test_lifecycle_policy_status_returns_a_traceable_read_only_transition(monkeypatch):
    device_id = uuid4()
    policies = _Rows(
        [
            {
                "name": "vm.guest",
                "is_identity_signal": True,
                "lifecycle_evidence_mode": "reported_state",
                "description": "VM guest reported by the hypervisor.",
            }
        ]
    )
    transitions = _Rows(
        [
            {
                "entity_id": device_id,
                "occurred_at": None,
                "before_state": {"lifecycle_status": "active"},
                "after_state": {"lifecycle_status": "offline_aging"},
            }
        ]
    )
    captured: dict = {}

    monkeypatch.setattr(views, "EntityType", SimpleNamespace(objects=policies))
    monkeypatch.setattr(
        views,
        "AuditLog",
        SimpleNamespace(objects=SimpleNamespace(filter=lambda **_kwargs: transitions)),
    )
    monkeypatch.setattr(views, "transaction", SimpleNamespace(atomic=lambda: nullcontext()))
    monkeypatch.setattr(
        views,
        "connection",
        SimpleNamespace(cursor=lambda: _Cursor()),
    )

    def fake_render(_request, template, context):
        captured["template"] = template
        captured["context"] = context
        return HttpResponse("ok")

    monkeypatch.setattr(views, "render", fake_render)
    request = RequestFactory().get("/admin/lifecycle/")
    request.user = _User(is_superuser=True)

    response = views.lifecycle_policy_status(request)

    assert response.status_code == 200
    assert captured["template"] == "lifecycle_policy_status.html"
    assert captured["context"]["transitions"][0]["entity_id"] == device_id


def test_lifecycle_policy_template_renders_the_audited_device_id():
    device_id = uuid4()

    rendered = get_template("lifecycle_policy_status.html").render(
        {
            "policies": [],
            "transitions": [
                {
                    "entity_id": device_id,
                    "occurred_at": None,
                    "before_state": {"lifecycle_status": "active"},
                    "after_state": {
                        "lifecycle_status": "offline_aging",
                        "evidence_kind": "reported_state",
                        "evidence_at": "2026-07-31T12:00:00+00:00",
                        "policy_version": "lifecycle-evidence-v1",
                    },
                }
            ],
        }
    )

    assert str(device_id) in rendered
