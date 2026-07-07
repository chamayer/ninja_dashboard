# Goal

Replace the flat all-clients table at `/orgs/all/` with a fleet overview
dashboard that serves as the Operations front door.

# Why

The current all-clients view is a plain table with client name, slug, and
device count. That undersells the data already in Operations and gives no
fleet-level context. The direction reframe (Operations = operational data
browser + control plane) means the first thing an operator sees should be
a real fleet overview, not a raw list.

# Scope

In:

- Summary tiles at the top of the all-clients view: total clients, total
  devices (with type breakdown), sources represented across the fleet,
  open findings count.
- Source coverage column in the client table: which source(s) each client
  is linked to, so gaps are visible at a glance.
- No new pages, models, migrations, or schema changes.

Out:

- Per-client dashboard changes (landing page is already done).
- Users, Software, or Observations pages (next slices).
- Any chart or graph rendering.

# Files to change

- `operations/apps/core/views.py` — add fleet-level aggregates to the
  all-clients branch of `org_index`.
- `operations/templates/org_index.html` — replace the Fleet card with
  summary tiles + improved client table.
- `operations/BUILD_BLUEPRINT.md` — this checkpoint.
- `operations/SESSIONS.md` — implementation record.
- `operations/TODO.md` — completion state.

# Steps

1. Add to the all-clients view context:
   - device type breakdown across the fleet.
   - distinct source names and per-source client coverage count.
   - global open findings count.
2. Replace the Fleet card in the template with 4 summary tiles (Clients,
   Devices, Sources, Findings) matching the per-client tile style.
3. Add a Sources column to the client table showing which sources each
   client is linked to.
4. Validate: Django check, ruff, template load smoke test.
5. Commit, push, confirm Portainer redeploy, light browser check.

# Open questions

- None. Data is already in Operations; no new ingest or schema work needed.

# Status

Implemented. Committed as `8b452f7`, pushed to both remotes. Portainer
auto-update deploying. Browser validation pending.
