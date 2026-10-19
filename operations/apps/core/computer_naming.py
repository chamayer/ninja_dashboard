"""Computer names: the operator's Rename and the one writer (ADR-0034 sections 6-7).

Only ``operations.write_computer_names`` writes a Computer's name; the
database refuses anything else. An operator name is the
``device_operator_decisions`` dimension ``name``; "Use automatic name" clears
it. Both recompute the Computer at once, in the same transaction.
"""

from __future__ import annotations

import json
import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, connection, transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .models import Device

REASON_MAX_LENGTH = 500
NAME_MAX_LENGTH = 255

RULE_LABELS = {
    "operator": "Set by an operator",
    "reporting_os": "Reported by the machine",
    "silent_os": "Reported by the machine (not reporting now)",
    "stable_os": "Kept: the machine reported it before",
    "withdrawn_os": "Last reported by the machine (record withdrawn)",
    "current_label": "Label from a source",
    "withdrawn_label": "Label from a source (record withdrawn)",
    "unconfirmed": "Kept: no record reports a name",
    "kept_collision": "Kept: the proposed name belongs to another Computer",
    "pending": "Being named",
}


def name_now(cur, device_ids) -> int:
    """Recompute these Computers' names now. The cursor's transaction holds the tenant."""
    ids = sorted({str(d) for d in device_ids if d})
    if not ids:
        return 0
    cur.execute("SELECT operations.write_computer_names(%s::uuid[], 1::bigint)", (ids,))
    return cur.fetchone()[0] or 0


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _colliding(device: Device, name: str) -> list[str]:
    """Names of other live Computers of the client with the same name key."""
    key = _key(name)
    return [
        other.canonical_hostname
        for other in Device.objects.filter(
            tenant_id=1, client_id=device.client_id, deleted_at__isnull=True
        )
        .exclude(id=device.id)
        .exclude(lifecycle_status=Device.LifecycleStatus.RETIRED)
        .only("canonical_hostname")
        if _key(other.canonical_hostname) == key
    ]


def _back(device: Device) -> HttpResponse:
    return redirect("device_detail", org_slug=device.client.slug, device_id=device.id)


def _begin(cur, action: str, reason: str, evidence: dict, actor) -> None:
    cur.execute(
        "SELECT operations.begin_change(%s, %s, %s::jsonb, 'operator', %s::bigint, "
        "'operations.ui', '', 1::bigint, true)",
        (action, reason, json.dumps(evidence), actor),
    )


def _named_message(request: HttpRequest, cur, device: Device) -> None:
    cur.execute(
        "SELECT canonical_hostname, name_rule FROM operations.devices WHERE id = %s", (device.id,)
    )
    name, rule = cur.fetchone()
    messages.success(request, f"Computer name: {name} ({RULE_LABELS.get(rule, rule)}).")


@login_required
@require_POST
@transaction.atomic
def device_rename(request: HttpRequest, org_slug: str, device_id: str) -> HttpResponse:
    device = get_object_or_404(
        Device, tenant_id=1, id=device_id, client__slug=org_slug, deleted_at__isnull=True
    )
    name = (request.POST.get("name") or "").strip().lower()
    reason = (request.POST.get("reason") or "").strip()
    confirmed = request.POST.get("confirm_collision") == "1"
    if not name or len(name) > NAME_MAX_LENGTH or not _key(name):
        messages.warning(request, "Enter a name with letters or digits.")
        return _back(device)
    if not reason or len(reason) > REASON_MAX_LENGTH:
        messages.warning(request, f"A reason is required ({REASON_MAX_LENGTH} characters or fewer).")
        return _back(device)
    others = _colliding(device, name)
    if others and not confirmed:
        messages.warning(
            request,
            f"Another Computer of this client is named {', '.join(sorted(set(others)))}. "
            "Confirm that this Computer should have the same name, or merge them if they are "
            "one machine.",
        )
        return _back(device)
    value = {"name": name}
    if others:
        value["collision_confirmed"] = True
    try:
        with connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            _begin(cur, "computer.operator_name", reason,
                   {"device_id": str(device.id), "name": name, "collision_confirmed": bool(others)},
                   request.user.id)
            cur.execute(
                """
                INSERT INTO operations.device_operator_decisions
                    (version, id, dimension, value, reason, set_by, set_at, tenant_id, device_id)
                VALUES (1, gen_random_uuid(), 'name', %s::jsonb, %s, %s, now(), 1, %s)
                ON CONFLICT (tenant_id, device_id, dimension) DO UPDATE
                   SET value = EXCLUDED.value, reason = EXCLUDED.reason,
                       set_by = EXCLUDED.set_by, set_at = EXCLUDED.set_at,
                       version = operations.device_operator_decisions.version + 1
                """,
                (json.dumps(value), reason, request.user.get_username(), device.id),
            )
            name_now(cur, [device.id])
            _named_message(request, cur, device)
    except DatabaseError as exc:
        transaction.set_rollback(True)
        messages.error(request, f"Nothing was changed: {str(exc).splitlines()[0]}")
    return _back(device)


@login_required
@require_POST
@transaction.atomic
def device_name_automatic(request: HttpRequest, org_slug: str, device_id: str) -> HttpResponse:
    device = get_object_or_404(
        Device, tenant_id=1, id=device_id, client__slug=org_slug, deleted_at__isnull=True
    )
    reason = (request.POST.get("reason") or "").strip()
    if not reason or len(reason) > REASON_MAX_LENGTH:
        messages.warning(request, f"A reason is required ({REASON_MAX_LENGTH} characters or fewer).")
        return _back(device)
    try:
        with connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            _begin(cur, "computer.automatic_name", reason, {"device_id": str(device.id)},
                   request.user.id)
            cur.execute(
                "DELETE FROM operations.device_operator_decisions "
                "WHERE tenant_id = 1 AND device_id = %s AND dimension = 'name'",
                (device.id,),
            )
            name_now(cur, [device.id])
            _named_message(request, cur, device)
    except DatabaseError as exc:
        transaction.set_rollback(True)
        messages.error(request, f"Nothing was changed: {str(exc).splitlines()[0]}")
    return _back(device)


def name_provenance(device_id) -> dict:
    """Why the Computer has its name: rule, record and when it was decided."""
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT d.name_rule, d.name_decided_at, o.platform, o.entity_type,
                   coalesce(nullif(o.canonical_data ->> 'hostname', ''), o.canonical_data ->> 'guest_name'),
                   x.value ->> 'name', x.reason, x.set_by
              FROM operations.devices d
              LEFT JOIN operations.entity_observation_current o
                ON o.tenant_id = d.tenant_id AND o.observation_id = d.name_observation_id
              LEFT JOIN operations.device_operator_decisions x
                ON x.tenant_id = d.tenant_id AND x.device_id = d.id AND x.dimension = 'name'
             WHERE d.tenant_id = 1 AND d.id = %s
            """,
            (device_id,),
        )
        row = cur.fetchone()
    if row is None:
        return {}
    rule, decided_at, platform, record_type, record_name, operator_name, reason, set_by = row
    return {
        "rule": rule,
        "label": RULE_LABELS.get(rule, "Not yet decided") if rule else "Not yet decided",
        "decided_at": decided_at,
        "platform": platform,
        "record_type": record_type,
        "record_name": record_name,
        "operator_name": operator_name,
        "operator_reason": reason,
        "operator_set_by": set_by,
    }
