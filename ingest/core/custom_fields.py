"""Custom fields ingest.

Source:
  - GET /v2/queries/custom-fields-detailed  (definitions)
  - GET /v2/queries/custom-fields           (values)

Targets:
  - ninja_core.custom_field_definitions     (upsert on id)
  - ninja_core.custom_field_values          (SCD-2, see below)

Values follow SCD-2 / hash-dedup:
  1. Compute content_hash from the typed value columns + raw_value.
  2. INSERT ... ON CONFLICT (entity_type, entity_id, field_name,
     content_hash) DO UPDATE SET last_observed_at = EXCLUDED.last_observed_at.
  3. Result: a new row only when the value actually changes; otherwise
     the existing row's last_observed_at moves forward.

Side effect: regenerates pivoted views (`v_device_custom_fields`,
`v_organization_custom_fields`, `v_location_custom_fields`) from the
current set of definitions. Views select the latest value per
(entity, field) via DISTINCT ON ... ORDER BY last_observed_at DESC,
so Metabase always sees current values. Adding a new custom field in
Ninja surfaces it as a real column on next ingest — no migration.
"""

from datetime import datetime

from ingest.ninja_client import NinjaClient


def run(client: NinjaClient, snapshot_at: datetime) -> tuple[int, int]:
    """Returns (definitions_upserted, values_changed).
    `values_changed` counts only inserts (new content); same-content
    rows that just bumped last_observed_at are not counted."""
    raise NotImplementedError


def regenerate_pivoted_views() -> None:
    """Drop & recreate v_<entity>_custom_fields views based on the
    current contents of ninja_core.custom_field_definitions. Each
    view selects DISTINCT ON the (entity, field) pair ORDER BY
    last_observed_at DESC to surface current values."""
    raise NotImplementedError
