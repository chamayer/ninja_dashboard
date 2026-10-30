"""One-key source-record cases (PLAN-004 R4 Stage C).

Stage A queues duplicate-review keys but has no case tables yet. Until Stage C
installs them, claimed keys are acknowledged without effect; the Stage C
migration queues every qualifying key again.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any


def assess_case_keys(
    cur: Any,
    tenant_id: int,
    generation: int,
    keys: list[tuple[uuid.UUID, dict]],
    now: datetime,
) -> None:
    return None
