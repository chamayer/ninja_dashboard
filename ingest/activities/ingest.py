"""Activities ingest.

Source: GET /v2/activities
  - Server-side filter: `sourceName` (list from
    settings.activity_sources).
  - Server-side cursor: `after=<last_id>` for incremental pulls.
  - Client-side filter: drop rows whose `activityType` is not in
    settings.activity_types_include (when set; empty = accept all
    from the configured sources).

Target: ninja_activities.activities — insert-once, dedup on
PK (Ninja's activity ID).

State: ninja_core.ingest_state row with key='activities.last_id' holds
the high-water mark. On first run (no state row) we backfill from
`activity_time >= now() - 7 days` to avoid pulling the entire
historical log. After that, incremental from last_id.
"""

from ingest.ninja_client import NinjaClient


def run(client: NinjaClient) -> int:
    """Fetch new activities since the last high-water mark, filter,
    insert. Returns rows inserted (post-filter)."""
    raise NotImplementedError


def _get_last_id() -> int | None:
    """Read ninja_core.ingest_state for key='activities.last_id'."""
    raise NotImplementedError


def _set_last_id(last_id: int) -> None:
    """Upsert ninja_core.ingest_state for key='activities.last_id'."""
    raise NotImplementedError
