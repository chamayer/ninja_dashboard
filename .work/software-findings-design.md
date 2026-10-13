# Software findings — redesign proposal (v2, DRAFT for review, no code)

Status: draft proposal. Nothing here is implemented or approved for build.
Date: 2026-10-13. All measurements are read-only prod counts taken the same
day. If accepted, promote the durable parts to `operations/docs/decisions/` as
a new ADR and amend ADR-0015 §2, ADR-0020 §6, ADR-0021 and ADR-0028.

## 0. Where this stands

**Decided by the user**

| # | Decision |
| --- | --- |
| D1 | Per-device state for title-level findings is **derived**, not stored per (finding, device). |
| D2 | Approvals are a **live overlay at every scope** (global, client, device), through the per-type `suppressed_by_approval` matrix. |
| D3 | An approved title that still has a severe/exploited CVE **stays visible**. |
| D4 | A title-level finding is notifiable when **at least one ready device** is exposed. |
| D5 | `whitelist_suggestion` **stays a finding**, one row per title. Principle: anything an operator must act on is a finding. |
| D6 | **Reject** raises a finding while the rejected title is installed. |
| D7 | The Ninja `isSystemComponent` flag is **not a reliable measurement** and is not to be trusted as a filter. |

| D8 | Non-approved software: one finding per title, grouped by publisher with two remediation options; a publisher decision resolves its title findings. |
| D9 | A publisher approval silences an anomaly signal only if no other signal of concern exists; title-level approvals keep per-type behavior. |
| D10 | No shadow period; guardrails instead (section 7). |
| D11 | Phase 1 covers all title-level types in one cutover. |
| D12 | The Codex exposure work was released separately (`4508ac7`) and is the baseline; Phase 0 supersedes it with a later migration. |
| D13 | Severities: rejected-software-installed high, non-approved low. |
| D15 | **No volume threshold.** The boundary between rare (<= `rare_max_devices`, default 2) and non-approved (more than that) is the definition of rare; every undecided installed title is exactly one of the two. No cap, no temporary ramp. |
| D16 | **Recent is a signal, not part of the definition.** Rare is any age; recency (first seen in the last 7 days, a setting) raises severity and shapes the suggestion, for rare and non-approved alike. |
| D14 | Publisher evidence: internal first; Ninja software-products maybe; other feeds deferred, skipped or not wanted (4.8). |

**All design questions are answered.** Not decisions: the unexplained 3,871
pending software activity-queue entries (to investigate), and the unaudited
consumers (6.3). Next: promote to an ADR, write the Phase 0 plan, then build.

## 1. What the system is for

Software findings answer four operator questions:

1. **Exposure.** Which devices run software with an exploited or severe
   vulnerability, or past end of life?
2. **Policy.** Is the software on this device allowed for this client?
3. **Review.** Which software needs a human decision?
4. **Coverage.** Is the required protection present? (Same capability evidence;
   out of scope here.)

## 2. Discovery: what exists

### 2.1 Pipeline today

| Stage | Where | State |
| --- | --- | --- |
| Collect installs | `ingest/inventory/software.py`, `queue.py`; jobs `software-queue-drain`, `software-enqueue-orgs` | Works since 78e2b97. Activity queue: 70,334 done, 3,871 pending since 10-06 (0 attempts, unexplained). |
| Store installs | `software_installations_current` (585k live rows, 23.5k titles, 46k versions, 4.7k devices), `software_installation_history` (1.36M) | Healthy. |
| Reference | `catalog.publishers/products/software_versions`, `software_catalog` (52), `software_classifier_rules`, `publisher_aliases`, `platform_product_map` (22), `software_decisions` (418) | Data-driven, small. |
| Intel | `ingest/intel/*`; `intel.cves` 136k, `intel.cpes` 1.8M, `operations.cve_match` 468k (467,726 with `version_range`, 2,562 versions) | Version-bound matching exists (ADR-0015 §4 gap closed). |
| Capability | `catalog.capability_*`, 544 machine assertions, ADR-0018 | Produces `unauthorized_*`. |
| Classify | `ingest/software_findings.py` (1,705 lines); jobs `software-classify-only/-full` | **0 completions in 14 days.** |
| Assess | `ingest/conditions.py`, `shared/conditions/*`, ADR-0020/0021 | One stored assessment per (finding, device): 133k rows, 1.1 GB, 81% past the 48 h window. |
| Expose | `v_device_software_exposure` (live view, migrations 107-110) | Returns 0 rows today. A materialized replacement (migration 112, ADR-0028) exists **uncommitted and undeployed**. |
| Present | Software pages, Issues, device and client pages | Audited in section 6. |

Open findings (grain): unauthorized_remote_access 6,317 (device),
vulnerable_software 4,181 (version), whitelist_suggestion 1,799 (product),
install_path_suspicious 496 (installation), unauthorized_av 370 (device),
capability_review_candidate 297 (product), eol_runtime 165 (version),
rare_recent 102 (device), known_malicious_hint 68 (product), suspicious_name 6
(product). Title-grain findings carry 85k device participants.

### 2.2 Decisions already made (kept)

- ADR-0015 §2: title/version facts are one row per subject; devices are
  evidence. Installation facts belong to the installation. Device-remedy facts
  stay per device.
- ADR-0015 §3 / ADR-0018: capability is evidence; trust is a decision; policy
  uses exact product identity.
- ADR-0020 §6: a blocked device does not erase a global software fact.
- ADR-0020 §1: finding IDs, condition keys, handling and notification
  fingerprints must not change.
- ADR-0028: approvals apply live; exposure is a rebuildable read model.
- Project rules: mappings and thresholds are data; nothing is silently
  dropped; findings live on the single findings surface; record when and why
  anything leaves the system.

### 2.3 Why it fails today

1. **Per-installation Python loop** over 585k installs; title-only rules are
   re-evaluated for every install of a title. (Confirmed in code.)
2. **A device batch fans out to the fleet.** 25 devices = 3,752 installs,
   2,227 versions, about 357k device slots. Each title finding re-assesses every
   device that has it, and each assessment re-sends, hashes, validates and
   rewrites the full participant list: quadratic in a finding's device count.
   (Confirmed in code; timing not measured.)
3. **Non-hashable selection join** (fixed in 417ea91: about 6 minutes to 2 s).
4. **One transaction per batch that cannot finish in the 90-minute budget**, so
   targets are never consumed and every run repeats the same work. (64
   timeouts, 0 completions.)
5. **Assessments stored per (finding, device)** though device readiness does
   not depend on the finding; the 48 h rule forces N rewrites per finding every
   two days.
6. **Approvals applied inside classification**, tying title facts to devices.

Patching the loop (batching, caches) would speed it up but keeps causes 1, 5
and 6, so it is not the recommended path.

## 3. Principles

1. Separate **evidence**, **knowledge about a title**, **policy and decisions**,
   **derived exposure**, and **work items (findings)**; each has one owner.
2. Compute each fact at its natural grain: titles once per title, devices once
   per device, installs once per install. Never multiply a fact by its fan-out.
3. Set-based SQL for per-row work; Python orchestrates.
4. Incremental by change feed: intel revision, rules digest, decision change,
   install change. Never "everything pending" as a unit of work.
5. Every unit of work is resumable and commits independently; progress is
   visible ("chunk 40 of 190").
6. Overlays (approvals, client policy, device readiness) apply at read time or
   in a cheap join, never baked into title facts.
7. Stable identity: finding IDs and condition keys survive cutover.
8. **Anything an operator must act on is a finding** on the single findings
   surface; a computed queue is not a substitute. A decision is the action that
   closes a review finding and takes effect when saved. Guard: each finding sits
   at the grain of its action, volume is governed by a data setting, and it
   closes itself with a recorded reason.
9. Nothing is hidden: any threshold or exclusion is visible as a count with a
   link, and every automatic closure records when and why.

## 4. Target model

```
Evidence        installs (device x version)       <- collection (unchanged)
Knowledge       title_assessment (per version)    <- intel + rules + catalog
Policy          decisions, client requirements, product map, thresholds (data)
Readiness       device_readiness (per device)     <- identity, offline, coverage
Exposure        device x finding (derived join)   <- findings x installs x readiness x overlays
Work items      findings (per grain)              <- reconcile diff
```

### 4.1 Knowledge layer: `title_assessment`

One row per software version (and per product for product-grain facts) holding
the device-independent results: matched CVE summary (KEV, worst CVSS, max EPSS,
counts), EOL status, name-pattern matches, threat-hit count, capability set,
and the input revision each came from (intel revision, rules digest, catalog
revision). Recomputed only for titles whose inputs changed. About 46k
versions, so a full rebuild is seconds to minutes in SQL.

### 4.2 Findings: grain per type

| Type | Grain | Open when | Closes when |
| --- | --- | --- | --- |
| vulnerable_software | version | KEV or CVSS >= cutoff match for that version | no match, or no live installs |
| eol_runtime | version | past EOL | no longer past EOL, or no installs |
| known_malicious_hint | product | threat hits >= threshold | below threshold, or no installs |
| suspicious_name | product | name rule matches | rule no longer matches |
| whitelist_suggestion (non-approved software) | product (one per title), grouped by publisher in the queue | undecided at every scope and installed on more than `rare_max_devices` devices | a title or publisher decision, or removal |
| capability_review_candidate | product | candidate capability evidence | curator decision |
| install_path_suspicious | installation | path rule matches | install gone or path changes |
| rare software (was `rare_recent`) | title | undecided and installed on at most `rare_max_devices` devices, any age; recency is a severity signal | a decision, removal, or spread beyond rare |
| unauthorized_* | device x product | alertable capability not permitted by the client's requirement map | permitted, approved, or removed |
| rejected_software_installed (new, D6) | device x title | title has a reject decision and is installed | removed, or decision changed |

Title-grain findings carry **no per-device rows of their own**; the affected
device list is the exposure join (4.4).

### 4.3 Readiness: `device_readiness`

One row per device (about 4.7k), refreshed every cycle: identity settled,
offline state, collection coverage, each with evaluated-at and policy digest.
The pure `shared.conditions` engine keeps deciding what each signal means; it is
called once per device per policy digest, not once per (finding, device).

### 4.4 Exposure

Device exposure = open title finding x live install of that version x device
readiness permits x not silenced by a decision (through the matrix). ADR-0028's
materialized read model is the right shape, refreshed after the reconcile job.
Approvals stay live. The public view keeps its columns, so its roughly twelve
callers do not change.

### 4.5 Assessments for title findings and notifications (D1, D4)

No stored `condition_assessments` row per (title finding, device). The
per-device answer is derived: title finding state x device readiness.
Device-grain findings keep their stored assessment (one participant each).

Notifications: today a finding notifies only if **every** participant permits it,
so one offline or unsettled device among thousands would silence a fleet-wide
vulnerability. For title findings the rule becomes **at least one currently
exposed, ready device**, and the payload carries ready/blocked counts. Both
notification code paths change (`notifications.py`, `notifications_digest.py`).
Notifications are dormant (0 events ever sent), so this changes before anyone
depends on it. Also changes: the Issues readiness query (`views.py` ~405-590),
ADR-0020/0021, and the condition safety-contract tests.

### 4.6 Decisions (D2, D3, D6)

One effective-decision resolution in SQL used by classification, exposure and
the UI: device > client > global, title over publisher, with the per-type
`suppressed_by_approval` matrix applied everywhere (data, not code).

- Approvals are a live overlay at every scope, global included. Saving one no
  longer waits for a classifier run.
- Review-prompt suppression (`whitelist_suggestion`, `rare_recent`) and its
  closing happen as a title-level reconcile for the title (or publisher) the
  decision names.
- `reject` raises `rejected_software_installed`; `investigate` stays a review
  state with no alert.
- An approved title with a KEV/severe CVE stays visible (D3); the view today
  hides it for client and device approvals.

### 4.7 Non-approved software: policy and the system-component flag (proposed)

**Condition.** A title is non-approved when it has no decision at any
applicable scope (title, then publisher; device, client, global).

**Two finding types split the undecided titles by one boundary (user,
2026-10-13).** Every undecided title that is installed on a live device is
exactly one of:

- **Rare software** (anomaly): installed on **at most `rare_max_devices`
  devices** (default 2), any age. Action: look at it, then decide.
- **Non-approved software** (governance, `whitelist_suggestion`): installed on
  **more than `rare_max_devices` devices** (3 or more by default). Action:
  approve or reject the title or its publisher.

There is **no separate threshold, no capacity cap and no temporary ramp.** The
boundary between the two is the definition of "rare", one setting
(`rare_max_devices`, today `rare_recent_max_devices`), editable by an admin
(4.9). Raising or lowering "rare" moves the boundary automatically, so nothing
falls between the two and nothing is counted twice.

**"Recent" is a signal, not part of the definition.** The existing
`rare_recent` finding means rare **and** first seen in the last 7 days, so a
title on one device stops being flagged after a week. In this design recency
affects priority only (`recent_days`, default 7, a setting):

| Condition | Severity | Suggestion reason |
| --- | --- | --- |
| Rare and recent | medium | "Newly appeared on N device(s)" |
| Rare and older | low | "On N device(s) since [date]" |
| Non-approved and recent | raised from low toward medium (rule table) | "New in the last N days across M devices" |
| Non-approved and older | low | "Installed on N devices at M clients" |
| Any of these plus another concern (path, name, threat hit) | per the existing rules | the concern leads |

The recent signal is reusable by any software finding. First-seen dates only go
back to 2026-07-13 (when tracking started), so "recent" is meaningful only for
titles that appeared after that.

**Volume today (prod, 2026-10-13; every undecided title with a publisher):**

| Undecided titles by devices | Titles | Type |
| --- | --- | --- |
| 1 device | 7,373 | rare |
| 2 devices | 2,417 | rare |
| 3 or more devices | 4,804 (1,634 publisher groups) | non-approved |

About 14,600 findings in total at first, almost all low. The backlog is a
one-time job, worked down by publisher decisions: at 3+ devices, approving 41
publishers clears half of the 4,804 and 674 clear 80%. Of the 7,373
single-device titles, 74% belong to a publisher whose decision resolves them
(5,425 titles); 1,948 are the only undecided title from their publisher. 2,652
single-device titles carry a version-like number in the name (the same product
at different versions), so product-name grouping is a candidate follow-up that
has not been designed or measured. Steady-state inflow at any prevalence is
about 100 to 180 new undecided titles a month (106 first seen in the last 30
days, 43 in the last 7), so a permanent rule that covers every undecided title
is workable.

**Decision scope follows the case.** For a rare title the title-level option
defaults to the narrowest meaningful scope (this device or this client), with
"everywhere" available. For non-approved software the options are approve the
title (any scope) or approve the publisher. Publisher approvals resolve their
title findings automatically.

**Issues performance is a separate requirement.** About 14,600 low-severity
findings must not slow the queue: the Issues page was measured at 6.2 s before
this, so the build must keep it paginated, grouped by publisher by default, and
free of request-time fleet aggregation. Not yet verified for this volume.

**Residual risk accepted:** none by design for undecided titles. A title is a
finding until a decision covers it or it is removed.

**Fewest operator actions.** Each finding offers the broadest action: "approve
publisher (N undecided titles)". About 629 publishers cover the widespread
titles; the rare tail barely compresses (4,380 publishers for 9,424 titles).
The first backlog is worked through the existing bulk-decision page.

**System-component flag (D7).** The flag is Ninja's `isSystemComponent`, an
installer-set property that hides an entry from Add/Remove Programs. Measured:
146k installs (25%) and 9,309 titles flagged, 10,465 installs with no value, 270
titles flagged on some devices and not others. It flags third-party
applications (SAP BusinessObjects 666 titles, 20-20 Technologies 528, Python
477, National Instruments 451, Autodesk, Citrix) and misses platform items
(Microsoft Edge, Edge Update, Windows app packages). Because the installer author
sets it, using it to exclude software would let hidden software skip review.
Proposal:

1. Never exclude on it. Store it and show it as evidence; use it only to sort
   or group.
2. Handle volume with publisher approvals (above), which already work.
3. If volume still hurts later, add baseline-component rules as an
   operator-managed table, each with a reason, evaluated in the knowledge layer
   and visible as "N titles recognized as baseline components". A trial of
   obvious families (VC++ runtimes, Office click-to-run, WebView2/Edge, Windows
   app packages, .NET) matched only about 150 of the 1,809 widespread
   undecided titles, so this is a later refinement, not a prerequisite.

### 4.8 Publisher-level review with suggestions (proposed, user-directed)

**Grain: every qualifying title keeps its own finding; the publisher is a
combined view with two remediation options (user, 2026-10-13).** Title-level
findings are never hidden under a publisher finding.

- **One finding per undecided title installed on more than `rare_max_devices`
  devices** (no decision at any applicable scope); titles at or below that
  boundary are rare-software findings (above). Its lifecycle, severity,
  suggestion and adverse signals are its own.
- **Combined by publisher in presentation, not in storage.** The finding
  carries the publisher and the count of that publisher's other undecided
  titles, and the queue groups findings by publisher. Each finding offers
  **two remediation options**: *approve this title*, or *approve the publisher
  (N undecided titles)*; reject and investigate are available at both grains.
- **Publisher decision resolves automatically:** once a publisher is decided,
  every title-level non-approved finding under it resolves, with a recorded
  reason. Findings carrying another signal of concern are unaffected (see the
  conditional-silencing rule below).
- A title decision resolves only that title. A publisher with an empty or junk
  string cannot group; its titles stand alone and only the title option applies.
- No separate publisher finding and no `software_publisher` subject type is
  needed, and there are no grain transitions to manage; the publisher is an
  attribute and a grouping key (`catalog.publishers` keeps its role as the
  hierarchy per ADR-0012 §5).

Measured 2026-10-13 for the non-approved type (3 or more devices): **4,804
title findings** across **1,634 publisher groups** (435 publishers with two or
more titles covering 3,605 titles, 1,199 with one). Whether the Issues queue
can group by publisher is not yet verified.

**Suggestion.** Every finding carries a suggested action and its reasons, from
a data table (signal -> suggestion, priority). Suggestions are advisory;
nothing is approved automatically, because approval is a trust decision.

**Override rule (user-directed).** The suggestion is computed from the most
specific signal upward: installation (suspicious install path), version
(vulnerable, end of life), title (suspicious name, threat-intel hits,
capability such as RMM / remote access, new and rare), then publisher
evidence. **Any adverse lower-level signal overrides a favorable publisher
suggestion**: the suggestion becomes "review these titles/installations" with
the reasons listed, and those titles are excluded from the "approve all"
recommendation.

**Enforcement side (user, 2026-10-13: conditional silencing).** Today approval
does not silence `eol_runtime`, `install_path_suspicious`,
`known_malicious_hint`, `vulnerable_software` or `capability_review_candidate`,
but does silence `suspicious_name`, `rare_recent`, `whitelist_suggestion` and
`unauthorized_*`. Decision: a **publisher-level approval silences an anomaly
signal only if no other signal of concern exists on that title or installation**
(for example an install-path anomaly). Interpretation to confirm: "signals of
concern" are trust/anomaly signals (`suspicious_name`, `install_path_suspicious`,
`known_malicious_hint`, capability review or unauthorized capability,
`rare_recent`, junk publisher string); vulnerability and end-of-life are facts
about a version and do not count. The anomaly signal being silenced is excluded
when counting others. A title-level approval keeps today's per-type behavior
(someone looked at that exact title); confirm that assumption.

**Publisher evidence** (stored as sourced assertions with authority and
`may_alert`, following ADR-0018; a community tag cannot promote itself):

| Signal | Direction | Status |
| --- | --- | --- |
| Threat-intel hits on publisher/title (OTX, ThreatFox) | adverse | exists; 148 publishers |
| Used by 5 or more clients; first-seen age; prior decisions | favorable | internal, to build |
| Vendor name in NVD CPE dictionary | favorable (identity, not trust) | exists; first-word match is loose |
| Package registries (winget, Chocolatey) publisher field | favorable | stored without publisher today; fix at ingest |
| GLEIF legal-entity match (free, open) | favorable, positive-only | **checked 2026-10-13, not building now.** Top 150 undecided widespread publishers searched by normalized name: 41 exact matches (27%; 35 issued, 6 lapsed), 106 no exact match, 3 skipped (non-Latin). Many large vendors miss because GLEIF holds a different legal name (for example Adobe Systems Incorporated vs Adobe Inc.), and several publisher strings are junk ("linux", "Your Company Name", GUIDs, misspellings). Revisit only with publisher-alias normalization. |
| abuse.ch MalwareBazaar code-signing certificate blocklist (signer names) | adverse | **deferred** until signer data exists |
| Publisher string quality (placeholder, GUID-like, generic, misspelled) | adverse/neutral | internal rule, to build: a junk publisher string is itself a review reason |
| Signer / code-signing data from inventory | strongest identity evidence | **not collected.** The Ninja API document (`NinjaRMM-API-v2_formatted.json`) lists, for `/v2/queries/software` and `/v2/device/{id}/software`: installDate, location, name, publisher, size, version, productCode, isSystemComponent (plus deviceId, timestamp): **no signer**. SentinelOne `installed-applications` returned **403 Insufficient permissions** to our token on 2026-10-13 (the same token reads agents and sites), so the role lacks the permission or Application Risk is not licensed; not distinguishable from the API. LogMeIn Central offers an Installed Applications report (subscription-dependent; fields unverified). R-U-ON: no API documentation found. |
| Ninja `/v2/software-products` (vendorName, productName, installable, active) | favorable (vendor/product Ninja can patch) | **maybe** (user, 2026-10-13); unused today; same credentials; small catalogue |
| Ninja `/v2/queries/antivirus-threats` (name, category, level, status, detectionSource, traceList) | adverse | **not wanted** (user, 2026-10-13) |
| Ninja `/v2/queries/windows-services` (name, displayName, description, startType, userName, state) | lower-level | **skipped** (user): high volume |
| SentinelOne installed-applications | EDR risk level per application | **ignored** (user): blocked by 403 |
| NIST NSRL | favorable, positive-only | **skipped** (user): hash-based |
| Signer collection by endpoint script | strongest identity evidence | **deferred** (user); needs approval |
| Install location (already stored for every install) | lower-level override signal | in hand; used by `install_path_suspicious` rules |
| NIST NSRL manufacturer data | favorable, positive-only | to evaluate; hash-based and quarterly |

Spoofing caveat: the publisher is an installer-set string, so a publisher
approval covers anything claiming that name; the finding states this.
Publisher names need normalization beyond the 56 current aliases.

### 4.10 Suggestions (where they live and the rules)

**Storage.** Each title finding carries `finding_details.suggestion` =
{action, reasons[], caveats[], evidence_revision, computed_at}. The rules are a
data table (`software_suggestion_rules`: signal, direction, resulting action,
priority, enabled), editable by an admin with the other classifier settings;
thresholds used by the rules (clients, age) are settings (4.9). Suggestions are
recomputed by the reconcile job when evidence changes. Nothing is built yet and
today's findings carry no suggestion.

**Presentation.** A suggestion panel on each finding ("Suggested: Approve
publisher. Used by 12 clients; known vendor; no concerns on 14 titles. Note: the
publisher name is installer-set."). The publisher group header shows an
aggregate: "Approve publisher" only if none of the publisher's undecided titles
has a concern, else "Review titles first (N with concerns)".

**Rules (first adverse rule wins; adverse always beats favorable):**

| # | Evidence | Suggestion |
| --- | --- | --- |
| 1 | Threat-intel hit on title or publisher | Investigate |
| 2 | Install-path anomaly on any install | Investigate |
| 3 | Suspicious name pattern | Investigate |
| 4 | Alertable capability not authorized for the client | Review capability |
| 5 | Junk or placeholder publisher string | Investigate |
| 6 | Used by >= 5 clients, known vendor, first seen >= 30 days ago, no concern | Approve publisher |
| 7 | Non-approved (more than `rare_max_devices` devices) with no concern | Approve title |
| 8 | Otherwise | No suggestion (insufficient evidence) |

Suggestions are advisory; nothing is approved automatically.

### 4.9 Admin settings for the classifier (fix, user-directed)

**Where it lives today.** Admin > Settings > "Software classification"
(`/admin/classifier/`, the "Classifier" tab) edits the `software_classifier` row
of `operations.evaluator_config`. It exposes only the `rare_recent_*` settings
and `installation_evidence_max_age_hours`. The rare/non-approved boundary
(`rare_recent_max_devices`, to be renamed `rare_max_devices`, default 2) is on
the page, but the recency window is tied to the old finding; the severities, the
vulnerable-software CVSS cutoff, the known-malicious hit threshold and similar
settings are code defaults with no admin control (the old
`whitelist_suggestion_min_devices` is replaced by the rare boundary);
production's stored config is `{}`.

**Latent bug.** The page's save replaces the whole stored config with only the
keys the form knows, so any other stored key (for example a threshold set in the
database) would be silently deleted by the next save.

**Fix (Phase 0 prerequisite).**
1. Save by **merging** into the stored config, never replacing it; unknown keys
   are preserved.
2. Expose on the page, with validation ranges: the rare boundary
   (`rare_max_devices`, default 2), the recency window (`recent_days`, default 7),
   the severities for rare, non-approved and rejected software, the
   vulnerable-software CVSS cutoff, the known-malicious hit threshold, and the
   other title-level thresholds.
3. One shared list of defaults for ingest and Operations (today `_CLASSIFIER_DEFAULTS`
   in `views.py` and `_DEFAULT_CONFIG` in `ingest/software_findings.py` are two
   copies), so the page shows the effective value the classifier actually uses.
4. Show the consequence of the rare boundary next to it ("N undecided titles are
   rare, M are non-approved; changing it to K moves L titles").
5. Audit every change (who, when, old and new value); confirm whether the page
   already writes an audit event.

## 5. Computation and jobs

| Job | Trigger | Work | Unit / commit |
| --- | --- | --- | --- |
| software-collect (existing drain) | schedule, activity | install ingest | per device (unchanged) |
| software-title-assess | new/changed title, intel revision, rules digest | recompute `title_assessment` | chunk of versions, keyset cursor |
| software-device-readiness | each cycle | device signals | all devices (cheap) |
| software-reconcile-findings | after the above, and on decision save | diff desired vs open findings; open/update/close | per finding type, chunked; per title on decision save |
| software-exposure-refresh | after reconcile | refresh read model | one concurrent refresh |

Dependencies reuse the existing workflow graph. Each job reports stage text
with chunk progress and writes a run summary (opened/updated/closed counts) so
the Jobs page can show what a run did. Device-grain findings reconcile per
changed device, not per fleet. The weekly full reconciliation becomes a
verification pass reporting drift, not a separate code path.

## 6. Consumers and decisions (audited 2026-10-13)

### 6.1 What reads software findings today

| Consumer | Reads | Needs stored per-device assessments? |
| --- | --- | --- |
| `v_device_software_exposure` (sole runtime exposure surface) | findings x installs x evidence x assessments x approvals | **Yes**: a fresh `may_execute` assessment per (finding, device) |
| Client workspace counts (`client_workspace.py:139`) | exposure view | via the view |
| Issues affected-device rows (`views.py` ~831), client severe issues (~2099), offline-device severe count (~2147) | exposure view | via the view |
| Device detail and filter (~2913, ~4158), Computers list severe count (~11129) | exposure view | via the view |
| Software title / client / checklist / user-risk pages (~7364, ~8587, ~10722, ~13593) | exposure view | via the view |
| Issues readiness (Ready/Blocked/Pending, `views.py` ~405-590) | findings + assessments + participants | **Yes** |
| Notifications and digest | findings + assessments + participants | **Yes** (every participant must permit) |
| Decision queue, software pages, safety-score matview | decisions, installs, catalog | no |

Not audited: client-health history, coverage requirement evaluation, source
actions, external SQL.

### 6.2 What consumers see now (read-only, prod)

- The exposure view returns **0 rows**; every exposure-driven page is empty.
  (Queried as the database owner role; a runtime-role difference is possible
  but the cause is consistent with 6.1.)
- **0 of 14k** open software findings has a fresh `may_notify` assessment.
- Notifications are dormant: 3 catch-all routes, 0 events ever sent.

### 6.3 Decisions today

- 418 rows, **all global** (308 by title, 119 by publisher): investigate 223,
  approve 92, approve_publisher 81, reject 31. The UI can create client and
  device decisions; none exist.
- Each save refreshes the safety-score matview and **queues a classifier
  rebuild**. The classifier resolves device > client > global, title over
  publisher, in Python.
- Only approve / approve_publisher change finding behavior; reject and
  investigate only suppress review prompts. No code turns a reject into a
  finding.
- The live exposure view applies only device/client approvals, ignores the
  per-type matrix, and does not apply global approvals at all.
- Consequences: every real approval takes effect only when the classifier
  completes (it has not in 14 days); the classifier and view disagree on
  whether approval hides a CVE; precedence logic exists twice.

## 7. Phases and cutover

Each phase ends with a validation gate and, where it changes production data or
operator-visible behavior, its own approval (commit and push each separate).

**Phase 0: foundations (no operator-visible change)**
- ADR drafted and accepted; amendments to ADR-0020/0021/0028.
- Exposure layer designed fresh within this rebuild, **independent of** the
  Codex session's uncommitted exposure work (migration 112, ADR-0028 draft,
  refresh calls, tests). User decision 2026-10-13: not included, not touched;
  the user will have Codex reevaluate it after this rebuild. Use distinct
  object names for new tables. The public view `v_device_software_exposure` is
  shared: this rebuild redefines it (columns kept), so the Codex migration 112,
  which also redefines it from the stored-assessment model, conflicts and must
  be reevaluated against the new model before any release.
- `device_readiness` table and job; single SQL effective-decision function.
- Classifier admin page fix (4.9): merge-on-save, expose the thresholds, one
  shared defaults list, audit.
- Explain the 3,871 pending software activity-queue entries.

**Phase 1: all title-level types in one cutover (decided 2026-10-13)**
- `title_assess` and `reconcile` for `vulnerable_software`,
  `whitelist_suggestion` (with 4.7 and 4.8), `eol_runtime`,
  `known_malicious_hint`, `suspicious_name` and `capability_review_candidate`;
  derived exposure view; notification and Issues readiness changes for title
  findings.
- **No shadow period (user, 2026-10-13).** One cutover for the title-level
  group; the old loop stops emitting these types (which also relieves it). Keep
  condition keys identical. Each type has exactly one owner at any time (a flag
  per type) so nothing double-emits.
- Guardrails that are not a shadow period (proposed, for confirmation): a
  per-type enable flag for instant stop; a close-rate circuit breaker (a reconcile
  run refuses to close more than a set share of a type's open findings without an
  explicit override); every automatic closure records when and why; after
  cutover, spot-check 20 findings per type and compare counts to the previous
  open set, reported once. Each commit and push still needs your approval.
- Cost accepted: more rules to port before the first visible result
  (end-of-life rules, threat-hit logic, name patterns, capability review) and no
  parity window.

**Phase 2: (folded into phase 1).**

**Phase 3: device-grain types** onto set-based per-device reconcile:
unauthorized_*, rare_recent, install_path_suspicious, plus
rejected_software_installed.

**Phase 4: retire** the per-installation loop,
`software_reclassification_targets`, and stored assessments for title-grain
findings. Operator-visible; own approval.

## 8. Open decisions

1. ~~Phase 1 scope~~ **decided 2026-10-13: all title-level types at once.**
2. ~~Uncommitted exposure work~~ **decided 2026-10-13: not included and not
   touched.** It belongs to a separate Codex session (goal: dashboard navigation
   performance; it reported "ready to commit and deploy" awaiting its own
   separate approval at 2026-10-13 01:02 UTC). The user will have Codex
   reevaluate after this rebuild. Original note follows for reference:
3. **Non-approved software (4.7, 4.8): decided 2026-10-13.** One finding per
   title, grouped by publisher in the queue, with two remediation options
   (approve title, approve publisher); a publisher decision resolves its title
   findings automatically. **No volume threshold and no cap (D15):** undecided
   titles split into rare (at most `rare_max_devices`, default 2, any age) and
   non-approved (more than that); recency is a signal (D16). Initial volume
   about 14,600 findings (7,373 on one device, 2,417 on two, 4,804 on three or
   more in 1,634 publisher groups). The interpretations in 4.8 (signals of
   concern, title-level approvals, guardrails instead of a shadow period) were
   confirmed the same day. The system-component flag is never used as a filter;
   baseline-component rules deferred.
4. ~~Shadow period~~ **decided 2026-10-13: no shadow.** Guardrails in section 7
   are proposed for confirmation.
5. ~~Backfill~~ **settled by data, no decision needed:** all 418 global
   decisions were made 2026-07-26 to 2026-08-07, none after the classifier last
   ran (2026-09-23), so all have already been applied; the overlay should
   reproduce current effect.
6. ~~Severity~~ **decided 2026-10-13:** `rejected_software_installed` high,
   non-approved low; new and rare stays medium via `rare_recent`.
7. ~~Publisher-level approval and anomaly signals~~ **decided 2026-10-13:**
   conditional silencing, only if no other signal of concern exists (4.8).
8. **Publisher evidence sources (4.8):** decided 2026-10-13 (user): build on
   internal evidence (install location, cross-client prevalence, first-seen
   age, prior decisions, existing threat hits, publisher-string quality);
   Ninja `software-products` is a maybe; antivirus-threats, SentinelOne
   applications, services and NSRL are out; MalwareBazaar blocklist and signer
   collection are deferred; GLEIF was checked (27% exact on the top 150) and is
   not being built now.

## 9. Risks and unknowns

- **Shared working tree with another agent: resolved.** The Codex exposure
  work was committed and pushed as `4508ac7` and migration 112 applied in
  production at 2026-10-13 16:50:42 UTC; the tree no longer holds foreign
  changes. Phase 0 supersedes the stored-assessment exposure table with a later
  migration. Remaining care: Codex's goal persists, so check `git status` before
  editing, stage by explicit path, and expect `.work/plan.md` edits to collide.
- **No shadow period means no parity baseline.** The close-rate circuit breaker,
  per-type flags, recorded closure reasons and the post-cutover spot check
  (section 7) are the only protections against a wrong bulk close.

- Condition keys must be reproduced exactly; not verified for every type.
- Shadow parity for exposure must be checked against an expected result computed
  from installs and findings (current output is empty).
- Consumers not audited (6.1): client-health history, coverage requirements,
  source actions, external SQL.
- Condition safety-contract tests encode per-participant assessment; the
  amendment must show the derived model stays fail-closed.
- No local Postgres; database paths need prod-shaped validation (rolled-back
  transactions on prod need explicit approval).
- Weeks, not days. The deployed fixes (78e2b97, a2599b3, 417ea91) may not bring
  findings current meanwhile.
- `unauthorized_*` volume (6,317) depends on capability flags and 22 product
  mappings; precision not reviewed here.
- First-backlog size is fixed by the data, not a setting: about 14,600
  low-severity findings (9,790 rare, 4,804 non-approved). Issues must stay
  responsive at that volume (4.7).

## 10. Validation plan

No shadow period. Per type, at and after cutover: a one-time comparison of the
new open set to the previous one (counts and keys, differences explained),
spot-check 20 findings against source data, timing of each job on prod-sized
data, a run that completes within
its budget, no stored title-grain assessments after cutover, Issues readiness
identical for a sample of devices, notifications fire for a title finding with
one ready device, an approval takes effect at every scope without a classifier
run, and the full test suites (ingest, operations, condition safety contract).
