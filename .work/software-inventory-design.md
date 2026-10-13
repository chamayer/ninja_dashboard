# Software inventory ingest — redesign (DRAFT for review, no code)

Date: 2026-10-13. Measurements are read-only (production database and Ninja API).

## 1. What it is for

Keep an accurate, current list of the software installed on every device,
including what was removed and when, so software findings are true and fresh.

## 2. What exists today (measured)

| Fact | Value |
| --- | --- |
| Trigger | Ninja activities `SOFTWARE_ADDED`, `SOFTWARE_REMOVED` and `SOFTWARE_UPDATED` enqueue the device (`ingest/activities/ingest.py`); the events themselves are not stored |
| Event volume | 250-970 device refreshes queued a day (pending entries are combined per device); 70,493 refreshes across 4,552 devices since 2026-07-08 |
| Queue state | nothing processed since 2026-10-06; 3,789 devices pending; the per-client refresh has not run since July |
| Throughput | 3 devices per 5-minute run, about 12 s per device, mostly row-by-row database writes |
| Data age | 4,045 of 4,759 devices (85%) have software data older than 3 days |
| Removals | **never recorded**: 0 installations ever marked removed. Removal detection runs only after a whole-fleet fetch, which never happens |
| Ninja `/v2/queries/software` (whole fleet, cursor paging) | 568,788 rows; 5,000 rows per page in 1.2-3.9 s, so the whole fleet in about 2.5-8 minutes |
| Ninja's own freshness (device collection timestamp) | median 10 h; 69% of devices within 24 h; the long tail is offline devices |
| Ninja collection time per device | fetched (`timestamp`) and discarded |
| Post-steps | title and safety read models, catalog and end-of-life projection refreshed after every 5-minute run |

The trigger is right. The problems are the slow writer, removals that depend on a
run that never happens, and no recovery for missed events.

## 3. Design: events for freshness, a daily fleet check for completeness

Both paths fetch a **complete list** for the devices they cover and hand it to
the same apply step.

1. **Event path.** A software added, removed or updated event queues the device
   (pending entries combine per device). A worker fetches that device's full
   software list and applies it. Data is minutes behind Ninja.
2. **Daily fleet check.** Once a day (setting) page through `/queries/software`
   for the whole fleet and apply it. It catches missed events, ingest outages
   and devices that never sent an event. The first run is the catch-up.
3. **One apply step, set-based**, for any set of complete device lists:
   - new or changed installations: write current state and open a history
     interval;
   - unchanged: refresh last seen;
   - **removed**: a covered device no longer lists a title, so that installation
     is closed and marked removed, with when and why ("not in Ninja's latest
     inventory");
   - a device that is **not covered** (no rows in a fleet check) is not reporting:
     nothing is removed; it is marked "inventory not reported since".
4. **Completeness check.** A fleet check removes only if rows received equal
   Ninja's reported total and no page failed. Otherwise it adds and updates,
   removes nothing, and says so. A device fetch that fails removes nothing.
5. **Per-device collection time.** Keep Ninja's timestamp as "inventory
   collected at"; evidence ages from when the device reported.
6. **Removal guard, per device.** Ninja is authoritative, so removals apply
   directly. The one failure worth guarding is a device whose list suddenly
   empties or shrinks sharply (agent glitch). Only that device's removals are
   held, with a finding saying why; everything else applies. Thresholds are
   settings. No fleet-wide percentage guard (user decision 2026-10-13).
7. **Change feed.** The apply step records which devices and titles changed. The
   software findings run is requested only when something changed and
   recomputes only those (findings redesign, incremental step).
8. **Post-steps** run once per batch, only when something changed.
9. **On-demand refresh** for a client or device uses the same fetch and apply.
10. **Run record.** Each event batch and fleet check records an observation run
    (devices covered, changed, removed, not reporting) for the source run detail
    page.
11. **Retire.** The row-by-row writer, the per-client scheduled queue (replaced
    by the daily check) and the demand queue (replaced by on-demand refresh, if
    nothing else needs it).

Settings (fleet check time, removal guard, page size, event batch size) are data
on an admin page, not environment variables.

## 4. Effects to expect

- The first fleet check records every uninstall since July. Those installations
  are marked removed and findings that depended on them resolve. The first run
  removes directly (user decision 2026-10-13); the per-device guard still
  applies. The findings close limit may hold large closes for an administrator.
- Devices with software activity are current within minutes; everything else is
  at most a day behind Ninja.

## 5. Open before building

- Measured 2026-10-13: one device takes 0.08-0.12 s; `df=id in (...)` with 20
  devices returns all 20 (1,983 rows) in 0.47 s. The API is not the
  bottleneck; the event path fetches pending devices in batches with one call.
- A device with no rows is indistinguishable from a device that did not
  report; the per-device guard covers a list that suddenly empties.
- The demand queue is used by the ingest service's own "demand run" pages.
  Decision: keep those pages rewired, or move on-demand refresh into Operations.
- The activity queue is not stalled: it drains oldest-first about a week behind
  (2,592 done in 10 days, about 260 a day, against 250-970 queued a day). The
  scheduled queue has never completed an entry; the demand queue was used once
  (2026-07-08).
- Activity events arrive about hourly (p50 38 min, p90 69 min after the event);
  accepted as sufficient (user, 2026-10-13).
