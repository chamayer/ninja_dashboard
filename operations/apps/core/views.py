from __future__ import annotations

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
@transaction.non_atomic_requests
def healthz(request):
    return JsonResponse({"status": "ok"})
