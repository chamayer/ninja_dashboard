# Goal

Redesign the patching dashboard navigation and card placement around the
operator's workflow, so each visible dashboard has a clear job and clear
scope.

# Why

The current dashboards have useful data, fast queries, and working
click-throughs, but the navigation still carries project history:

- dashboard titles mix old names, data concepts, and workflow concepts;
- `Command Center` and `Overall Status` overlap heavily;
- `Device Patching Status` overlaps with all-client, client, and triage
  views;
- `Utilities` is vague and duplicated in live Metabase;
- some card titles do not make clear whether they refer to clients,
  devices, patches, events, or the current filter scope.

The goal is not another query rebuild. The goal is a reviewable
information architecture pass before implementation.

# Scope

- Define the final operator-facing navigation.
- Define the function of each dashboard.
- Audit every current dashboard/card and decide whether it is kept,
  moved, renamed, duplicated intentionally, demoted, or removed.
- Keep useful metric concepts in multiple places when the operational
  question is different.
- Preserve working filters, click-through behavior, and dashboard IDs
  where practical.
- Keep page load targets from the previous blueprint.

> **Q (reviewer):** How is dashboard ID preservation actually achieved
> when the display name changes? Prior responses stated bootstrap is
> idempotent "by name/stable hidden card UID." Renaming `Triage →
> Device Work Queue` will create a new dashboard, not rename the
> existing one, unless a hidden UID or explicit rename path is in play.
> Verify the mechanism in `metabase_bootstrap.py` before Step 2 or the
> renames will silently orphan the old IDs and break external
> bookmarks.
>
> **Response:** Accepted. Verified in `ingest/metabase_bootstrap.py`:
> `_upsert_dashboard()` preserves IDs only when the new dashboard name
> maps to the old display name through `_DASHBOARD_LEGACY_NAMES`. Card
> IDs are preserved separately through hidden card UIDs in the card
> `description`, with `_card_uid_candidates()` checking current and
> legacy dashboard-name slugs. Implementation must therefore update
> `_DASHBOARD_LEGACY_NAMES` for every dashboard rename before running
> bootstrap. This becomes a required Step 4 checklist item, not an
> assumption.

> **Q (reviewer):** The previous blueprint required a page-load
> baseline in its Step 1. Where does the baseline capture live in this
> plan? Suggest folding it into Step 2's audit output, since every
> card is being looked at anyway — otherwise "keep page load targets"
> has no reference point to validate against.
>
> **Response:** Accepted. Step 2 will produce a durable placement map
> that includes live dashboard/card timing columns. The baseline will
> live in `DASHBOARD_PLACEMENT_MAP.md` alongside each card's keep/move/
> drop verdict, so performance is reviewed before implementation and
> retested after implementation.

# Out of scope

- No custom web app.
- No role-based dashboard model.
- No broad query rewrite unless the card audit exposes a real gap or
  performance regression.
- No removal of useful drill-through paths without a replacement.

# Files to change

- `BLUEPRINT.md`
  - This review blueprint.
- `DASHBOARD_PLACEMENT_MAP.md`
  - Card-by-card placement and timing baseline for the dashboard
    cleanup.
- Later, after review approval:
  - `ingest/metabase_bootstrap.py`
    - Dashboard names, nav labels, section headers, card placement,
      card titles, and click-through targets.
  - `CHANGELOG.md`
    - Record the navigation cleanup.
  - `SESSIONS.md`
    - Record review decisions, implementation notes, validation.
  - `TODO.md`
    - Move any deferred dashboard cleanup or rejected alternatives.
  - `VERSION`
    - Bump when implementation ships.

# Naming Principles

- Dashboard names must describe the operator workflow, not the database
  shape.
- A card title must identify the object it counts:
  - clients;
  - devices;
  - patches;
  - activity events;
  - time movement.
- A metric concept may appear in more than one dashboard, but each card
  instance must make scope and purpose obvious.
- Avoid vague titles:
  - `Needs Action`;
  - `Status`;
  - `Patching Enabled`;
  - `Active Devices`;
  - `Utilities`;
  - `Overall`.
- Prefer direct operator names:
  - `Clients Needing Attention`;
  - `Devices Needing Action`;
  - `Included Devices`;
  - `Patch Failures`;
  - `Activity Search`.
- Prefix scope only where ambiguity exists. The dashboard context
  should carry the normal scope; add `Fleet`, `Client`, `Device`,
  `Patch`, or `Activity` only when the title would otherwise be
  unclear.

> **Q (reviewer):** The Card Placement Rules example uses `Fleet
> Devices Needing Action` (Command Center) alongside `Devices Needing
> Action` (Client Patch Review, Device Work Queue), implying scope
> prefixes are used *only where ambiguity exists*. But Review Question 7
> still asks whether to prefix consistently or only where ambiguous.
> Pin the answer here — either always prefix, or prefix-on-ambiguity —
> because every card title depends on it, and Step 4 will churn if it's
> decided mid-implementation.
>
> **Response:** Accepted. Decision: prefix only where ambiguity exists.
> The dashboard's context should carry the normal scope. Add `Fleet`,
> `Client`, `Device`, `Patch`, or `Activity` only when a card title
> would otherwise leave the operator unsure what object is being
> counted. Avoid blanket prefixes because they make the dashboard noisy
> without improving comprehension.

# Proposed Navigation

1. `Command Center`
   - Function: all-client operational landing page.
   - Primary object: clients.
   - Operator question: "Where do we need attention across the customer
     base?"
   - Should contain:
     - all-client summary;
     - client ranking;
     - top blockers;
     - data freshness / ingest status;
     - click-through to client review or device work queue.

2. `Client Patch Review`
   - Function: one-client patch review and action planning.
   - Primary object: one client's devices.
   - Operator question: "What is happening for this client, and what
     needs to happen next?"
   - Top band requires exactly one selected client.
   - Should contain:
     - client status;
     - included devices;
     - scan/install coverage;
     - devices needing action;
     - failures/warnings/reboot blockers/approval backlog;
     - client-scoped evidence tables.

3. `Device Work Queue`
   - Current dashboard: `Triage`.
   - Function: devices a tech should work.
   - Primary object: devices/issues.
   - Operator question: "Which devices should I fix next, and why?"
   - Should contain:
     - prioritized device queue;
     - scan gaps;
     - failed installs;
     - reboot blockers;
     - approval backlog;
     - warning/failure grouping and message search.

4. `Device Detail`
   - Current dashboard: `Device Drilldown`.
   - Function: complete evidence for one device.
   - Primary object: one device.
   - Operator question: "What is the full story for this device?"
   - Should contain:
     - current problem and suggested next step;
     - scope/policy/contact;
     - current patch state;
     - install history;
     - warning/failure history;
     - reboot evidence;
     - Ninja link.

5. `Patch Evidence`
   - Current dashboard: `Patch Detail (Filterable)`.
   - Function: KB / patch / install outcome lookup.
   - Primary object: patches and KBs.
   - Operator question: "Which patches or KBs are involved, and where?"
   - Should contain:
     - patch state breakdown;
     - KB counts;
     - install outcomes;
     - patch detail table;
     - patch type breakdown.

6. `Patch Trends`
   - Function: movement over time.
   - Primary object: dates/time series.
   - Operator question: "Is patching improving or getting worse?"
   - Should contain:
     - installs per day;
     - failures per day;
     - reboots per day;
     - active devices over time;
     - fully patched trend;
     - warning/failure trends.

7. `Activity Search`
   - Current dashboard: `Utilities`.
   - Function: raw activity/message lookup.
   - Primary object: activity events.
   - Operator question: "Where else did this message/event happen?"
   - Should contain:
     - activity search table;
     - message, subject, activity type, client, device, severity, and
       days filters.

# Merge / Demote Decisions To Review

- `Overall Patching Status`
  - Proposed decision: remove from primary navigation.
  - Reason: overlaps heavily with `Command Center`.
  - Action: move any uniquely useful cards into `Command Center` or
    `Patch Evidence`; drop redundant cards.

- `Device Patching Status`
  - Proposed decision: demote from primary navigation unless the audit
    proves a unique operator workflow.
  - Reason: overlaps with `Command Center`, `Client Patch Review`, and
    `Device Work Queue`.
  - Action: move useful status breakdowns into those dashboards; keep
    only if it becomes a distinct device status explorer.

- Duplicate `Ninja - Utilities`
  - Proposed decision: keep one as `Activity Search`, remove/hide the
    duplicate.

# Card Placement Rules

- A metric concept may appear in multiple dashboards only when the
  question is different.
- Each card instance must have a single clear job and scope.
- Examples:
  - `Command Center`: `Clients Needing Attention`
    - portfolio question;
    - click into client review.
  - `Command Center`: `Fleet Devices Needing Action`
    - work-volume question;
    - click into device work queue.
  - `Client Patch Review`: `Devices Needing Action`
    - one-client question;
    - click into client-scoped devices.
  - `Device Work Queue`: `Devices Needing Action`
    - actual fix list;
    - click into device detail.

# Current Dashboard Audit

## Command Center

Proposed function: keep as all-client landing page.

Review actions:
- Keep client ranking and top blockers.
- Rename ambiguous count cards to make object and scope explicit.
- Pull in only the useful unique `Overall Status` fleet cards.
- Ensure every card click goes to `Client Patch Review`, `Device Work
  Queue`, `Patch Evidence`, or `Device Detail`.

## Overall Patching Status

Proposed function: merge/demote.

Review actions:
- Identify cards that are unique and useful:
  - current patch state;
  - clients with lowest fully patched devices;
  - client fully patched devices;
  - ingest status;
  - devices needing reboot.
- Move useful all-client cards to `Command Center`.
- Move patch/KB evidence cards to `Patch Evidence`.
- Remove from primary nav after replacement.

## Client Patch Status

Proposed new name: `Client Patch Review`.

Review actions:
- Keep one-client guard on top summary.
- Rename titles to be direct and device/client scoped.
- Keep lower evidence tables filterable.
- Ensure it does not present all-client totals as a client report.

## Triage

Proposed new name: `Device Work Queue`.

Review actions:
- Keep prioritized queue and issue-specific work lists.
- Rename cards from triage terminology to work/action terminology where
  useful.
- Keep message search and error grouping.
- Ensure junior tech workflow is obvious:
  - what device;
  - why it matters;
  - next step;
  - where to click.

## Device Patching Status

Proposed function: demote or merge.

Review actions:
- Check whether `Patching Status by Device Type`, `Operating System`,
  `Organization`, and `All Devices by Patching Status` provide unique
  value.
- If unique, move:
  - all-client status breakdowns to `Command Center`;
  - device lists to `Device Work Queue`;
  - client-scoped breakdowns to `Client Patch Review`.
- Remove from primary nav if no distinct workflow remains.

## Patch Detail

Proposed new name: `Patch Evidence`.

Review actions:
- Keep as patch/KB evidence page.
- Rename titles to clarify patches vs devices.
- Keep drill-through from KB, patch state, severity, install result.

## Device Drilldown

Proposed new name: `Device Detail`.

Review actions:
- Keep as one-device evidence page.
- Ensure top cards show action summary before history tables.
- Keep open-in-Ninja link.

## Patch Trends

Proposed function: keep.

Review actions:
- Keep as secondary reporting/trends page.
- Rename cards so every chart says what is moving over time.
- Avoid mixing current-state cards into trends.

## Utilities

Proposed new name: `Activity Search`.

Review actions:
- Keep one dashboard only.
- Remove/hide duplicate live dashboard.
- Keep raw event/message search out of primary work pages except where
  filtered drill-through needs it.

# Locked Review Decisions

1. The one-client page is `Client Patch Review`.
2. `Triage` becomes `Device Work Queue` in both dashboard title and nav
   label.
3. `Overall Patching Status` is removed from primary navigation after
   useful cards are moved or intentionally dropped.
4. `Patch Evidence` stays in primary navigation for now because KB and
   patch lookup is a real support workflow, not just a drill-through.
5. `Patch Trends` stays in primary navigation for now because trend
   review is a real reporting workflow.
6. Card scope prefixes are used only where ambiguity exists.
7. One duplicate `Utilities` dashboard is kept and renamed to
   `Activity Search`; the duplicate is hidden or removed.
8. The implementation review will use `DASHBOARD_PLACEMENT_MAP.md` as
   the durable card-placement artifact.
9. Final acceptance requires a walkthrough by the user and reviewer.
   A junior tech walkthrough is preferred if available, but is not a
   blocker.

# Placement Map Decision

- `Device Patching Status` has a hard proposed verdict in
  `DASHBOARD_PLACEMENT_MAP.md`: remove it from primary navigation and
  merge useful content into `Command Center`, `Client Patch Review`, or
  `Device Work Queue`.
- That verdict must be accepted or revised during placement-map review
  before implementation starts.

> **Q (reviewer):** Questions 5 (Patch Evidence in primary nav?) and 7
> (scope-prefix policy) materially shape the nav bar and every card
> title. They must be resolved before Step 4, not carried through
> implementation. Suggest resolving all seven review questions during
> the Step 1 blueprint review pass and moving them into Naming
> Principles / Proposed Navigation as decisions.
>
> **Response:** Accepted. The review questions are now converted into
> locked decisions above. `Patch Evidence` and `Patch Trends` stay in
> primary navigation for now, and the scope-prefix policy is
> prefix-on-ambiguity only. The only unresolved decision is
> `Device Patching Status`, and that decision is explicitly blocked
> from crossing the placement-map review.

# Acceptance Checks

- A new operator can explain what each visible dashboard is for from
  the nav labels alone.

> **Q (reviewer):** How is this actually tested? Self-review by the
> author, or a real walkthrough with someone unfamiliar with the
> current design? The prior blueprint required an operator walkthrough
> as a required acceptance check — suggest reusing that here so this
> check isn't just an assertion.
>
> **Response:** Accepted. Acceptance requires a walkthrough by the user
> and reviewer using the final visible dashboard names and top-level
> cards. The walkthrough must answer: where do I start across all
> clients, where do I review one client, where do I find devices to fix,
> where do I inspect one device, and where do I search a repeated error.
> A junior tech walkthrough is preferred if available.
- No visible dashboard exists only because it existed before.
- No top-level card leaves the operator guessing whether it counts
  clients, devices, patches, or events.
- No client page shows all-client status as if it were a client report.
- Cross-client work starts in `Command Center`.
- One-client review starts in `Client Patch Review`.
- Device fixing starts in `Device Work Queue`.
- One-device evidence starts in `Device Detail`.
- Patch/KB lookup starts in `Patch Evidence`.
- Raw message lookup starts in `Activity Search`.
- Page-load targets from the previous blueprint still pass after the
  nav/content cleanup.
- Existing click-through filter propagation still works.

# Steps

1. Review and approve/revise this blueprint.
2. Produce `DASHBOARD_PLACEMENT_MAP.md` from live dashboards:
   - source dashboard;
   - source card;
   - current card ID;
   - baseline dashboard/card timing;
   - keep;
   - move;
   - rename;
   - duplicate/drop;
   - demote from nav.
   - target dashboard;
   - target card title;
   - click-through/filter notes.
3. Review the placement map before implementation. This review cannot
   pass while `Device Patching Status` still has an unresolved verdict.

> **Q (reviewer):** Where does the placement map live? It's not in the
> Files to change list, and without a durable artifact (a section of
> this blueprint, a `PLACEMENT_MAP.md`, or a table appended here) the
> Step 3 review happens in chat and won't survive. Suggest making it a
> committed file so it can be diffed, reviewed, and referenced during
> Step 4.
>
> **Response:** Accepted. The placement map lives in
> `DASHBOARD_PLACEMENT_MAP.md` and is listed in Files to change. Step 3
> review is against that committed artifact, not chat-only notes.

> **Q (reviewer):** Step 2 must also return a verdict on
> `Device Patching Status` (Review Question 4) — the deferred keep/
> demote/remove decision cannot cross Step 3 unresolved, or Step 4
> can't finalize the nav bar. Call that out explicitly as a Step 2
> deliverable.
>
> **Response:** Accepted. Step 2 must produce a hard
> `Device Patching Status` verdict. Step 3 cannot approve the placement
> map until that verdict is keep, merge, or remove with the affected
> cards mapped to their final homes.
4. Implement dashboard/nav names and section headings.
5. Move or remove duplicate/overlapping cards.
6. Preserve dashboard IDs where practical.
7. Remove/hide duplicate `Utilities`.
8. Run local compile and dashboard spec build.
9. Apply to live Metabase.
10. Validate:
    - dashboard load speed;
    - filter carryover;
    - click-throughs;
    - no-client vs one-client behavior;
    - card titles and scope clarity.
11. Update `CHANGELOG.md`, `SESSIONS.md`, `TODO.md`, and `VERSION`.
12. Commit and push after review-approved implementation.

# Status

in progress - implemented locally as v0.35.0; live bootstrap and timing validation pending
