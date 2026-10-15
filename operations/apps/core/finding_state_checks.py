"""Finding state checks: every time the hourly check found the stored state out of line.

``operations.finding_state`` is written in the same transaction as each change that affects it
(migrations 0301, 0302), so a disagreement means an input was missed. The hourly check records
what was stored, what the rule says and when, then repairs it; this page lists them. Read only.
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from .templatetags.human_labels import humanize_label

_LIMIT = 200


@login_required
def finding_state_checks(request: HttpRequest) -> HttpResponse:
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*), max(found_at) FROM operations.finding_state_drift")
        total, latest = cursor.fetchone()
        cursor.execute(
            """
            SELECT d.finding_id, d.finding_type, d.stored_attention, d.computed_attention, d.found_at
              FROM operations.finding_state_drift d
             ORDER BY d.found_at DESC, d.id DESC
             LIMIT %s
            """,
            [_LIMIT],
        )
        rows = [
            {
                "finding_id": finding_id,
                "finding_type": humanize_label(finding_type),
                "stored": stored or "(none)",
                "computed": computed or "(none)",
                "found_at": found_at,
            }
            for finding_id, finding_type, stored, computed, found_at in cursor.fetchall()
        ]
    return render(
        request,
        "finding_state_checks.html",
        {"rows": rows, "total": total, "latest": latest, "limit": _LIMIT},
    )
