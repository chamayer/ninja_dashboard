# Goal

Add a compact identity coverage section to the per-client landing page.

# Why

The client landing page currently shows canonical client identity and
`client_links`, but Operations is meant to be the operator-facing source of
truth for client/source identity resolution. The landing page should expose
enough identity coverage to show whether a client is known across sources and
where resolution gaps may exist.

# Scope

In:

- Keep the current landing page structure.
- Add summary counts for:
  - client external identities;
  - device source links by source;
  - source binding enabled/disabled counts;
  - client users and client-user source links;
  - active `unlinked_external_identity` findings resolvable through this
    client's source bindings.

Out:

- Broader dashboard/home redesign.
- Detail pages for source bindings, user identities, or unlinked identities.
- New schema migrations.
- New ingest/classification behavior.

# Files to change

- `operations/apps/core/views.py` — add identity coverage aggregates.
- `operations/templates/org_index.html` — render compact identity coverage
  section.
- `operations/BUILD_BLUEPRINT.md` — this checkpoint.
- `operations/TODO.md` — completion/backlog state.
- `operations/SESSIONS.md` — implementation and validation result.

# Steps

1. Add aggregate queries in `org_index` for client identity coverage.
2. Render the identity coverage card/table below the summary tiles.
3. Validate locally with Django checks and template load.
4. Pause after this UI change before starting another UI slice.

# Open questions

- Whether Operations should get a true top-level operations summary page as a
  future replacement path for high-value Metabase workflows.
- Whether this summary later deserves detail links for source bindings,
  client users, and unlinked external identities.

# Status

Approved. Implementing compact identity coverage on the client landing page.
Pause after this UI change before starting another UI slice.
