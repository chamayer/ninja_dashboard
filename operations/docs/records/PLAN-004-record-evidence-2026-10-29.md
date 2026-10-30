# PLAN-004 — Record evidence, 2026-10-29

Bounded production SELECT-only review authorized by the user. Separate
repeatable-read, read-only transactions used tenant 1, 15–20 second statement
timeouts, a two-second lock timeout, and rollback through Invoke-DevTool.ps1.
No source fetch, resolver, evaluator, refresh, or data mutation ran. Outputs
contained aggregate counts, anonymous comparisons, and timestamps, not customer
names, identifiers, secrets, or payloads. Queries are not one simultaneous snapshot.
The user then stopped discovery and requested design; no further reads are planned.

## Scope and method

ScreenConnect `agent.remote_access` records present in stored source snapshots.
Pair comparisons use distinct session IDs within the same tenant, source instance,
namespace, parent scope, and record type. Serials are trimmed/case-folded, exclude
short/repeated-character and registry-rejected values, and exclude known roaming
records. Supporting MAC comparison excludes listed junk values and Hyper-V's
virtual-adapter prefix. These guards support investigation, not proven hardware
identity or attachment eligibility. Case labels below are anonymous query-local
labels, not durable identifiers.

## Observations

- At 13:28 UTC: 5,608 present sessions; 297 have neither a Computer nor client.
  3,180 report online, 2,428 offline, and 1,843 lack canonical contact timestamps.
  Current receipts range from 09:49 to 11:31 UTC; this is collected state, not
  a live endpoint observation. Ten ScreenConnect snapshots completed in the
  preceding day, marked complete with zero failed rows.
- 565 same-scope pairs share usable serial evidence. Of these, 506 also share
  supporting MAC evidence. All 506 pairs have the same snapshot within each
  pair; 123 are online/offline, zero both online, 28 have mixed attachment,
  and three specifically have an online unassigned/offline attached session.
  Twenty pairs have conflicting mapped clients; 132 lack contact on at least
  one record. These are overlapping pair counts, not machines or issue counts.
- The three focused pairs have matching raw guest serials, raw guest connections
  only on the online member, different source customer-group attribution, and
  one usable serial across the matching Computer's current evidence. Four attached
  records on one Computer report that serial, spanning Hudu, Ninja, ScreenConnect,
  and SentinelOne. This is corroboration, not an ownership determination.
- Offline members: one reports last activity about 307 days ago; two have no
  usable activity timestamp. All three have year-one guest connected/disconnected
  event sentinels. None is source-ended/deleted. Online members have valid
  guest-connected event timestamps; one nevertheless has sentinel LastActivityTime.
  Do not equate activity, connection events, collection, or installation birth.
- All six focused records have one stored material-history interval beginning
  October 28 at 20:41 UTC, with one reported serial/name per record and no stored
  online/contact fields in those intervals. This history cannot establish prior
  activity overlap, replacement chronology, or original installation dates.
- A separate same-scope, case-insensitive exact-name comparison found 1,718 pairs
  with different usable serials across 307 records. Of those, 1,341 report both
  online with no shared usable MAC; only one of those pairs shares a nonempty
  source customer group, and only one shares a mapped client. None of the 1,718
  pairs shares an attached Computer. Generic names across customers explain much
  of this population; these counts are not defects. Name equivalence cannot
  establish one machine.

## Conclusions and limits

Observed: online unassigned evidence coexists with offline attached evidence for
likely matching hardware; source attribution differs; missing contact can coexist
with a reported active guest connection; same names can describe different
hardware. Not established: proven replacement, unjustified duplicate installations,
two equivalent installations operating on one machine, or collector-created duplicate
session identities. No deletion or attachment recommendation is justified solely
by these counts. Missing time cannot establish a stale duration.

ScreenConnect collector SHA-256 matched the local inspected file. The deployed
shared observations module hash differed from the local file; local implementation
details were not treated as deployed authority. History-field absence above was
measured directly. No full deployed revision or all-source audit was performed.

The [design](../plans/PLAN-004-source-record-design.md) uses these observations
without treating unproven explanations as detected conditions. The
[handoff](../plans/PLAN-004-source-record-review.md) owns next action and validation.
