# Goal

Reframe Operations' next build direction as an operational data browser and
control plane, not only an issue-resolution console.

# Why

Recent UI slices improved issue/workflow surfaces, but the product intent is
broader: Operations should become the primary place to view and work with the
canonical operational data model. Findings and decisions remain important, but
the app should also let operators browse current clients, devices, users,
software, sources, observations, evidence, status, and history without going
to SQL or Metabase for routine inspection.

# Scope

In:

- Document the product framing:
  - Operations = operational data browser + control plane.
  - Metabase = exploratory BI and broad historical analytics.
- Define the next dashboard/page direction around data viewing, status, and
  drilldown, not only issue queues.
- Preserve the rule that Operations pages should be model-aware and
  operator-useful, not generic chart clones.

Out:

- Implementing the top-level dashboard in this slice.
- New schema, ingest, or UI pages.

# Files to change

- `operations/BUILD_BLUEPRINT.md` — active product-direction checkpoint.
- `operations/TODO.md` — backlog the next dashboard/data-browser slices.
- `operations/SESSIONS.md` — record the direction decision.

# Steps

1. Update this build checkpoint with the broader product direction.
2. Update TODO with the next data-browser/dashboard slices.
3. Record the decision in `operations/SESSIONS.md`.
4. Ask before implementing the next UI slice.

# Open questions

- Which data domain should get the first dedicated browse/detail experience
  after clients/devices: users, software, sources/collectors, or observations.
- How much historical trend/status belongs in Operations before it becomes BI
  and should stay in Metabase.

# Status

Planning checkpoint. Next implementation should be an Operations dashboard or
data-browser slice, approved separately.
