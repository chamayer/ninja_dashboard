# 0015 — Software ecosystem: classification, categorisation, decisions and findings

Status: Accepted
Date: 2026-08-06

## Context

Operations classifies software, categorises it, records operator decisions
about it, and emits findings from all three. Those four things were built
across BLUEPRINT Track 3 and ADR-0008, but no record defines what each is
*for*, how they relate, or what a software finding's subject should be. The
result has drifted, and the drift is measurable.

### Origin

The system is a port of `inventory-scripts/SW Inventory/analyze_inventory.py`,
a 3,000-line per-client analyser that produced Excel workbooks with an
embedded decision workflow. Its data came from `Ninja_sw_inventory.ps1`, which
pulls `/device/{id}/software` from the Ninja API — the same data
`ingest/inventory/software.py` ingests continuously today.

`CLAUDE_CODE_BRIEF.md` in that folder describes the input as "PDQ Inventory
CSV exports". **That is wrong and has misled at least one reader.** The
collector is the Ninja API script sitting beside it, and the parity audit
records the same. PDQ appears in this system only as a *publisher name* in the
decision corpus (`PDQ.com -> Approve Publisher`), because PDQ software is
installed on managed machines. PDQ was never a data source.

The legacy analyser's structure maps almost one-to-one onto what exists now,
including its thresholds:

===============================================  =====================================
legacy                                           current
===============================================  =====================================
`WHITELIST_HIGH_CONFIDENCE_MIN_MACHINES = 10`    `whitelist_suggestion_min_devices: 10`
`RARE_INSTALL_THRESHOLD = 2`                     `rare_recent_max_devices: 2`
`WHITELIST` / `TRUSTED_PUBLISHERS` lists         `software_catalog`, `software_classifier_rules`
`decisions_global.csv`                           `operations.software_decisions`
"Whitelist Suggestions" sheet                    `whitelist_suggestion` finding
"Rare" section                                   `rare_recent` finding
"CVE Details" sheet                              `vulnerable_software` finding
===============================================  =====================================

### Measured state, 2026-08-06

============================================  =========
titles in fleet (`software_title_current`)       20,631
categorised (`software_catalog`)                     52
classifier rules                                     25
**operator decisions**                            **3**
**decisions in the legacy corpus**              **418**
============================================  =========

Nine software finding types, all emitted with `subject_type = 'device'`:

==========================  ========  ======  =======  ==============
type                        findings  titles  devices  rows per title
==========================  ========  ======  =======  ==============
whitelist_suggestion         134,861   1,633    3,869            82.6
rare_recent                   10,843   9,093      813             1.2
vulnerable_software            1,428      22    1,389            64.9
unauthorized_remote_access     1,200       5    1,022           240.0
eol_runtime                      732     110      452             6.7
install_path_suspicious          400      25      374            16.0
suspicious_name                  385       6      384            64.2
known_malicious_hint             128      11      110            11.6
unauthorized_av                   45       2       45            22.5
==========================  ========  ======  =======  ==============

The classifier has run **three times in its life**, last on 2026-07-27. It has
no scheduled job and never has — `run_software_classify_once` is reachable only
by an HTTP trigger. So every figure above is a frozen snapshot.

## Options considered

- Patch `whitelist_suggestion`'s granularity and leave the rest.
- Suppress the high-volume types.
- Define the ecosystem's four layers and fix each against that definition.

## Decision

### 1. Four layers, each with one job

**Classification** answers *"is this software safe?"* It is derived, never
authored. The legacy `classify_local(name, publisher, location)` returned
`Known Good` / `Suspicious` / `Needs Review`, and its inputs split cleanly:
name and publisher are properties of the **title**; `location` is a property
of the **installation**. That split is the basis of the subject rule below.

**Categorisation** is *not* a general taxonomy today, and describing it as one
would be wrong. `software_catalog` holds 52 rows against 20,631 titles, and its
`categories` array carries two unrelated kinds of label:

- **Functional**: `av` (20), `remote_access` (11), `rmm` (9) — what the
  software *does*. These exist to serve coverage: `_load_sanctioned_per_client`
  resolves them against `RequirementProfile` to answer "does this device run a
  sanctioned AV?", producing `unauthorized_av` and
  `unauthorized_remote_access`.
- **Trust**: `whitelist` (5), `trusted_publisher` (7) — whether we *trust* it.
  In the legacy analyser these were separate lists (`WHITELIST`,
  `TRUSTED_PUBLISHERS`) with no relation to category. The port merged them into
  one array.

**The conflation is load-bearing and wrong.** `whitelist_suggestion` fires on
`not cat_list` — *any* category suppresses it — as does
`rare_recent_skip_categorized`. So labelling a title `av`, a purely functional
statement carrying no judgement, silences the "should we decide about this?"
prompt exactly as `whitelist` does. Function and trust are orthogonal: Trend
Micro Apex One is both AV and trusted, and the field cannot say so.

`eol_date` exists on the table and is populated on **0 of 52** rows;
`eol_runtime` findings come from 9 regex rules in
`software_classifier_rules` instead. The column is dormant.

**Decisions** answer *"what have we decided about it?"* — approve, reject,
investigate, approve-publisher, resolved device > client > global. This is
accumulated human judgement and the most expensive thing in the system to
recreate.

**Findings** answer *"what needs attention now?"* They are derived from the
other three and own no state.

### 2. A software finding's subject is the thing an operator acts on

Three kinds, determined by where the fact actually lives:

- **Title facts** — true of the software wherever it is installed:
  `vulnerable_software`, `eol_runtime`, `suspicious_name`,
  `known_malicious_hint`, `whitelist_suggestion`. The remedy is one decision.
  **Subject is the title; one row; devices are evidence carried as a count
  and a list.**
- **Installation facts** — true of this copy on this device:
  `install_path_suspicious`. The same title is legitimate in `Program Files`
  and suspicious in `AppData`. **Subject is the installation.**
- **Device policy facts** — true of the device's posture:
  `unauthorized_remote_access`, `unauthorized_av`. The remedy is per device.
  **Subject is the device.**

Emitting a title fact per device multiplies one fact by its install count.
That is what turned 1,633 titles into 134,861 findings, and it is a
regression against the legacy behaviour. Verified in
`generate_whitelist_suggestions`: it iterates the frequency frame — one row
per software name — and appends a single suggestion per title carrying
`"# Machines": n_machines` as a count. The title was the unit of decision and
the machines were a number beside it.

### 3. The decision corpus is authoritative and must be migrated

418 accumulated decisions exist in `decisions_global.csv` — 303 title-scope
and 115 publisher-scope — against 3 in production. Publisher decisions are the
leverage: one `Microsoft Corporation -> Approve Publisher` resolves thousands
of titles at once. `SoftwareDecision` already models every value and scope the
corpus needs, so this is an import, not a schema change.

### 4. Separate function from trust; a general taxonomy is out of scope

Split the two meanings rather than adding to the confusion:

- Functional categories stay as the coverage mechanism they are.
- Trust becomes what it already is elsewhere — a **decision**. `whitelist` and
  `trusted_publisher` are approvals, and `software_decisions` already models
  approval at title and publisher scope with proper scoping and audit. The 5
  `whitelist` and 7 `trusted_publisher` catalog entries are decisions living in
  the wrong table.
- Suppression conditions then test the right thing: `whitelist_suggestion`
  should skip a title because it is **decided**, not because it is *labelled*.

**A general taxonomy — browser, productivity, developer tool — is deliberately
not adopted here.** Nothing in the system needs it: no finding, no coverage
requirement, no page. Authoring it for 20,631 titles would be a large manual
effort serving no current consumer, and this repository has repeatedly shipped
structures ahead of their engines. If a consumer appears, revisit it then.

### 5. Classification without a corpus is noise

`whitelist_suggestion` fires on *uncategorised + undecided + widespread*.
With 52 of 20,631 titles categorised and 3 decisions recorded, it is not
reporting a software problem — it is reporting that the reference data is
empty. **Fix the inputs before tuning the detector.**

### 6. Scheduling comes last

The classifier must not be scheduled until the subject rule and the corpus
import are done. Scheduling first would regenerate 134,861+ rows on the first
run and undo the page-load work in 0.115.0.

## Rationale

Every quantity above was measured against production rather than inferred, and
two prior readings of this area were wrong in ways that measuring corrected:
the software page was called "already fast" from a query the page does not run,
and `whitelist_suggestion` was called unbounded growth when the classifier had
not run in ten days.

The subject rule is not invented — it restores the legacy structure. The
analyser treated a title as the unit of decision and machines as evidence,
which is why its whitelist sheet had a machine-list column with a documented
truncation limit rather than one row per machine.

## Consequences

- Five of nine finding types change subject from device to title. 137,534 rows
  collapse to 1,782 — the sum of each type's distinct titles, since a title
  carrying two kinds of fact still yields one row per kind. The queue becomes
  readable; the devices move into evidence.
- `unauthorized_remote_access` and `unauthorized_av` stay per-device, correctly
  — the 240 rows per title there are 1,022 real devices needing individual
  remediation.
- Importing the corpus decides **814 of the 1,867** open
  `whitelist_suggestion` (title, publisher) pairs — **44%** — measured by
  matching the corpus against production. 740 of those come from
  publisher-scope decisions and only 215 from title-scope, which is the
  leverage argument in numbers: 115 publisher decisions outperform 303 title
  decisions by more than three to one.
- Existing findings must be closed and re-emitted under the new subject. That
  is operator-visible and needs its own approval.
- `rare_recent` at 1.2 rows per title is already near title-level; it and
  `whitelist_suggestion` are the same question at opposite prevalence ends and
  should be reviewed for merging into one finding with a prevalence attribute.
- The classifier still needs a schedule. Until it has one, all software
  findings including `vulnerable_software` and `known_malicious_hint` are stale
  — currently by ten days.
- Moving `whitelist` and `trusted_publisher` out of `categories` and into
  `software_decisions` changes what suppresses a suggestion. Titles labelled
  only functionally (`av`, `rmm`, `remote_access`) stop being suppressed and
  will surface for decision — correctly, since nobody ever decided them.
- `software_catalog.eol_date` is either populated or dropped. Leaving a
  dormant column beside a working regex path invites the next reader to
  believe it is the source, as it did here.

## Supersedes or superseded by

Complements ADR-0008 (software safety intel layer), which defines the intel
inputs feeding `vulnerable_software` and `known_malicious_hint` but not their
subject or granularity. Applies the single-findings-surface rule from
ADR-0012's amendment. Implements BLUEPRINT Track 3's intent.
