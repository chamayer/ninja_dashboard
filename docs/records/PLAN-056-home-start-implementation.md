# PLAN-056 — Home start page, 2026-11-17

User authorized a five-minute compliant Home fix, including content changes.
Implemented locally: an authenticated start page with Issues guidance, six
domain links and staff-only Sources/Jobs/Data links. User then clarified that
inexpensive available counts should remain. Home now reuses Clients, Computers,
Coverage and Patching domain readers, plus protected published Software counts;
Sources and Jobs status counts are staff-only. Expensive Source Records totals/
history and automatic Issues ranking stay off Home; domain workflows remain.

## Scope and contract mechanisms

Runtime files: `operations/apps/core/views.py`,
`operations/apps/core/context_processors.py`, and new
`operations/templates/home.html`. Existing Docker directory COPY packages
the template. No schema, dependency, service, role or public URL change.

R1: login/tenant middleware and destination authorization remain. Software uses
`read_overview` with its existing tenant/client/permission boundary; denied
summaries expose no counts. R2–R5: existing domain owners supply exact populations
and definitions without Home reimplementing them. Device policy is resolved once
for Computer and Patching reads. Prior deployed trace measured Computer 0.098 s,
Coverage 0.106 s, Patching 0.330 s, source status 0.102 s and Jobs diagnostic
0.061 s; these motivate reuse, not full-request certification. Clients use their
small existing aggregate. Software reads compact protected results, not raw
installations. Source Records/Issues expensive reads and aggregate navigation
badges remain excluded; no cache masks their misses.

R6–R7: Software retains its existing maintenance/freshness lifecycle and explicit
pending/stale/unavailable messages, with no live fallback. Direct counts are read
on request. Database failures use savepoints and render unavailable; genuine
zero counts remain zero. No new cache, publication or fake healthy empty state.
Coverage shows the latest evaluation timestamp. R8: complete deployed HTTP
latency with this mix of counts remains a release gate; prior measurements are
not an exact sum or representative proof of the new page.
R9: Home has no export; destination exports are unchanged.

All-worktree reconciliation superseded the earlier preservation-only boundary.
The final release retires the unrouted legacy dashboard, obsolete cache candidate
and unused live Software Home helper; existing tests were reconciled with light
coverage approved by the user. See [release reconciliation](PLAN-056-worktree-reconciliation.md).

## Actual validation and limits

- Staff/nonstaff rendering with domain readers stubbed: HTTP 200, actual zero
  displayed, Software pending and permission-denied states handled, failed Client
  count unavailable, policy read once, staff status reads omitted for nonstaff.
  Expensive Issues/Source Records readers were replaced with raising sentinels
  and were not called. This validates composition, not database performance.
- All 19/22 internal links were resolved in the earlier start-page smoke; those
  destinations are unchanged. Administrative links remain hidden for nonstaff.
- Anonymous requests redirect to login; no empty-Issues health claim is rendered.
- Three focused existing navigation/Jobs tests pass; Django system check passes using
  base settings and both repository/Operations import roots. Python compiles.
- Context-processor Ruff has preexisting PLR0911 on `_active_section`, reproduced
  against HEAD. Whole-file views lint retains unrelated findings; none reported
  in the new Home function.
- Registry validation and whitespace pass. No test-file edits or broad suite.
  The inherited dashboard-composition test describes the replaced content;
  it was not updated or claimed passing.
- Release 0.144.23 is prepared under the subsequent all-worktree commit/push
  authorization. No production hotpatch or manual redeploy; no further tests
  after the user stopped testing. Deployment observation remains next.

Next: complete the authorized reconciled release. Migration preflight found none
pending. Full HTTP latency acceptance remains open; user stopped further testing.
Navigation item 5 remains open until the user accepts content and latency.
