"""Say when a queued Job waits on an interrupted run rather than a live one.

``jobs_dispatch_ready_v1`` reported "Waiting for another update to finish" for
every protected-data wait.  When the holder is a contained claim of a run that
was interrupted, nothing is finishing and the wait lasts until the hold is
reviewed or released, so the text now says that.  Wait category, promotion rules
and claim handling are unchanged.
"""

from __future__ import annotations

import importlib
from typing import ClassVar

from django.db import migrations

_PREVIOUS = importlib.import_module("apps.core.migrations.0261_jobs_wait_reason_truth")

_REPLACEMENTS = (
    (
        "    v_active_claims BIGINT;\n",
        "    v_active_claims BIGINT;\n    v_contained_claims BIGINT;\n",
    ),
    (
        "            SELECT count(*) INTO v_active_claims FROM operations.job_resource_claims\n",
        "            SELECT count(*), count(*) FILTER (WHERE state = 'contained')\n"
        "              INTO v_active_claims, v_contained_claims\n"
        "              FROM operations.job_resource_claims\n",
    ),
    (
        "THEN 'Waiting for another update to finish with the same data.'",
        "THEN CASE WHEN v_contained_claims > 0\n"
        "                           THEN 'An interrupted update still holds this data and needs review.'\n"
        "                           ELSE 'Waiting for another update to finish with the same data.' END",
    ),
)

FORWARD_SQL = _PREVIOUS.FORWARD_SQL
for _old, _new in _REPLACEMENTS:
    assert FORWARD_SQL.count(_old) == 1, "0261 dispatcher text changed"
    FORWARD_SQL = FORWARD_SQL.replace(_old, _new)


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0280_jobs_local_work_replay_safe_recovery"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, _PREVIOUS.FORWARD_SQL)]
