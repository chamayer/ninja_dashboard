# 0029 — Software inventory from complete Ninja lists; findings follow the change feed

Status: Accepted
Date: 2026-10-13

## Context

Software inventory was fetched one computer at a time, three computers per
5-minute run, and written row by row (about 12 s per computer). Ninja software
events queued about 250-970 computers a day, so the queue ran a week behind and
the per-client refresh had not run since July: 85% of computers had software
data older than 3 days. Removals were detected only after a whole-fleet fetch
that never ran, so no uninstall had ever been recorded. A version change never
cleared an installation's catalog version link, so 166,310 of 586,435
installations pointed at a version no longer installed. The software findings
run recomputed the whole fleet (about 4 minutes) after every queue drain.

Measured (2026-10-13): Ninja `/v2/queries/software` returns one computer in
about 0.1 s, 20 computers in one `df=id in (...)` request in 0.47 s, and the
whole fleet (about 569,000 rows) in about a minute at 5,000 rows a page.

## Options considered

- Keep the per-computer queue and make the writer faster.
- A whole-fleet snapshot only, on a schedule.
- Ninja software events for freshness plus a daily whole-fleet check, both
  applying complete per-computer lists set-based (selected).

## Decision

1. **Two entry points, one apply.** The device worker fetches every queued
   computer (Ninja software events, operator refreshes) 100 per request; the
   daily full check fetches the whole fleet. Both stream complete per-computer
   lists into a temporary table and apply them in one transaction: new and
   changed installations write current state and open a history interval,
   unchanged ones refresh last seen.
2. **Ninja is authoritative for what is installed.** An installation a listed
   computer no longer reports is removed: `stale_since` with
   `stale_reason = 'ninja.inventory.not_listed'`, and its history interval
   closed. A computer with no rows in a response did not report a list and
   keeps its inventory. Removals require a response that reached Ninja's
   reported total.
3. **Per-computer guard instead of a fleet-wide one.** A computer whose list
   shrinks by the configured share (default 50% of at least 20 programs) has
   its removals held; additions and changes apply. The hold is an admin finding
   (`software_inventory_held`) and is released by an administrator on the
   Software policy page. A computer listed for the first time is never held.
4. **Per-computer state** (`operations.software_inventory_devices`): Ninja's
   collection time, when Operations received the list, the program count and
   any hold. Shown on the computer page; the full check's run summary reports
   fleet freshness.
5. **Version links follow the version.** A link that names a different version
   than installed is cleared on apply; the catalog projection relinks it in the
   same run.
6. **Findings follow the change feed.** Every apply records the titles it
   added, changed, removed or relinked in
   `operations.software_reclassification_targets`, as vulnerability matching
   already did. The routine findings run (`software-classify-only`) reconciles
   only those titles: their evidence, findings and assessments; other findings
   are untouched. A producer that cannot name titles (threat feeds, catalog
   projections, reference software data) records the whole-fleet marker. The
   full run covers the fleet daily and after every decision or settings or
   policy change. A run clears the change-feed rows it covered only after it
   succeeds. The findings run is requested only when inventory changed.

## Rationale

The API returns complete lists cheaply at any scope, so the fetch unit is
whatever is due, not one computer. A set-based apply makes a fleet-wide run a
minute of database work. Events give freshness; the daily check gives
completeness and recovers anything events missed. Holding only the affected
computer keeps a single agent glitch from erasing its inventory without
blocking real removals elsewhere. Scoping the findings run by title is safe
because every software finding is keyed by title (product, version,
installation or computer-and-title), and title-level facts are computed over
all of a title's installations.

## Consequences

- Inventory for computers with software activity is about an hour behind
  Ninja (activity fetch cadence); every reporting computer is at most a day
  behind.
- Device and title readiness changes reach findings of unchanged titles at the
  next full run; the daily full run keeps every assessment within the 48-hour
  policy freshness window.
- The per-client (`software_scheduled_queue`) and demand
  (`software_demand_queue`) queues and the ingest service's software pages are
  retired; Operations refresh actions queue the computer and start the worker.
- Job runs report progress counts and a plain-English result summary
  (migration 0287).

## Supersedes or superseded by

Amends 0028 (the exposure read model is now refreshed after scoped runs as
well). Relates to 0007 (current plus content-hashed history) and 0015 (software
findings onto software subjects).
