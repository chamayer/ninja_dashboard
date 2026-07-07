# Goal

Make the per-client device list fast and stable for large clients by moving
search/filter/pagination server-side.

# Why

Live validation showed `/orgs/uta/devices/` rendered a 504 KB response and a
Gunicorn worker timed out shortly afterward. The current view loads every
device for the client and filters in browser JavaScript, which does not scale
for large clients.

# Scope

In:

- Server-side search by hostname or serial.
- Server-side type filter using existing `Device.DeviceType` values.
- Pagination, defaulting to 100 devices per page.
- Preserve current device-list layout and links.
- Record user questions about client identity coverage and a higher-level
  Operations summary page as backlog items.

Out:

- Broader dashboard/home redesign.
- New client identity panels beyond TODO/backlog capture.
- New schema migrations.
- New ingest/classification behavior.

# Files to change

- `operations/apps/core/views.py` — paginate/filter device query.
- `operations/templates/org_devices.html` — GET search/filter form and
  pagination controls.
- `operations/BUILD_BLUEPRINT.md` — this checkpoint.
- `operations/TODO.md` — backlog user questions and completion state.
- `operations/SESSIONS.md` — implementation and validation result.

# Steps

1. Replace full list materialization in `org_devices` with filtered queryset,
   count, and `Paginator`.
2. Replace browser-only filtering in `org_devices.html` with GET controls.
3. Add pagination controls that preserve search/type query params.
4. Validate locally with Django checks and migration dry-run.
5. After commit/push/redeploy, validate live response size/time for
   `/orgs/uta/devices/`.
6. Pause after this UI change before starting another UI slice.

# Open questions

- Whether to later add richer client identity coverage to the client landing
  page: client links, device-link source coverage, source bindings, and
  client-user identity coverage.
- Whether Operations should get a true top-level operations summary page as a
  future replacement path for high-value Metabase workflows.

# Status

Approved. Implementing server-side device-list search/filter/pagination. Pause
after this UI change before starting another UI slice.
