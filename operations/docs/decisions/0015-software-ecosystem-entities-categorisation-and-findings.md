# 0015 — Software ecosystem: entities, categorisation, decisions and findings

Status: Accepted
Date: 2026-08-06

## Context

Software is the platform's largest domain by row count and its least defined by
decision record. ADR-0008 covers the intel layer feeding it; ADR-0012 §5 states
the entity hierarchy in three sentences. Nothing defined how those meet: what a
software finding's subject is, what categorisation is for, or which of the four
moving parts owns what.

This record was first drafted from the legacy analyser alone, re-deriving a
model that ADR-0012 and `docs/glossary.md` already specify. That draft is
replaced. `operations/AGENTS.md` requires both to be read before entity,
attribute, relationship or scope work, and this revision is the cost of not
having done so.

### Origin

A port of `inventory-scripts/SW Inventory/analyze_inventory.py`, a per-client
analyser producing Excel workbooks with an embedded decision workflow. Its data
came from `Ninja_sw_inventory.ps1` pulling `/device/{id}/software` from the
Ninja API — the same data `ingest/inventory/software.py` ingests continuously.

`CLAUDE_CODE_BRIEF.md` beside it calls the input "PDQ Inventory CSV exports".
That is wrong. PDQ appears here only as a publisher name in the decision
corpus, because PDQ software is installed on managed machines. PDQ was never a
data source.

Thresholds carried over verbatim: `WHITELIST_HIGH_CONFIDENCE_MIN_MACHINES = 10`
became `whitelist_suggestion_min_devices`; `RARE_INSTALL_THRESHOLD = 2` became
`rare_recent_max_devices`.

### Measured state, 2026-08-06

**Ingested** — 481,411 current installations carrying `canonical_name`,
`publisher`, `version`, `install_location`, `install_date`. Version is present
on 467,674 (97%). This resolves to **20,631 titles**, **39,321 title+version
pairs**, and **4,789 publishers**.

**Reference and judgement** — `software_catalog` 52, `software_classifier_rules`
25, `publisher_aliases` 56, `intel_matcher_hints` 24, **`software_decisions` 3**,
against **418** in the un-imported legacy corpus.

**Intel** — `intel.cves` 92,514, `intel.cpes` 164,860, `operations.cve_match`
2,636 across 541 titles, `safety_signal` 1,582, `title_intel_cache` 0.

**Findings** — nine types, every one emitted with `subject_type = 'device'`:

| type | findings | titles | devices | rows per title |
| --- | --- | --- | --- | --- |
| whitelist_suggestion | 134,861 | 1,633 | 3,869 | 82.6 |
| rare_recent | 10,843 | 9,093 | 813 | 1.2 |
| vulnerable_software | 1,428 | 22 | 1,389 | 64.9 |
| unauthorized_remote_access | 1,200 | 5 | 1,022 | 240.0 |
| eol_runtime | 732 | 110 | 452 | 6.7 |
| install_path_suspicious | 400 | 25 | 374 | 16.0 |
| suspicious_name | 385 | 6 | 384 | 64.2 |
| known_malicious_hint | 128 | 11 | 110 | 11.6 |
| unauthorized_av | 45 | 2 | 45 | 22.5 |

The classifier has run **three times ever**, last 2026-07-27, and has never had
a scheduled job. Every figure above is a frozen snapshot.

## Decision

### 1. The entity hierarchy is ADR-0012 §5; software gets no separate model

`publisher -> product -> software+version`, joined by plain relationships,
unscoped. **Software+version is the entity CVEs, EOL dates and safety scores
bind to.** An **installation is a relationship** between a device and a
software+version carrying `install_location` and `install_date` — precisely the
glossary's example of relationship-owned attributes.

The raw material exists: 4,789 publishers, 39,321 title+version pairs, and
`install_location` on every row. None of the three levels is instantiated;
`software_catalog` (52 rows) stands in for `publisher` and `product`, which is
why it cannot express that a title is both AV and trusted.

### 2. A finding's subject follows the glossary's identity test

- **Software+version facts** — `vulnerable_software`, `eol_runtime`,
  `known_malicious_hint`, `suspicious_name`, `whitelist_suggestion`. One row
  per subject; devices are evidence carried as a count and a list.
- **Installation facts** — `install_path_suspicious`. The path belongs to the
  device-and-software pair, so the finding belongs to the **relationship**.
- **Device facts** — `unauthorized_av`, `unauthorized_remote_access`. The
  remedy is per device; these stay as they are.

Emitting a subject-level fact per device multiplies one fact by its install
count. That is what turned 1,633 titles into 134,861 findings, and it is a
regression against the legacy analyser: `generate_whitelist_suggestions`
iterates the frequency frame and emits one row per title carrying
`# Machines: n_machines` as a count.

### 3. Categorisation is a coverage mechanism, not a taxonomy

`software_catalog.categories` conflates two unrelated labels:

- **Functional** — `av` (20), `remote_access` (11), `rmm` (9), serving
  coverage: `_load_sanctioned_per_client` resolves them against
  `RequirementProfile` to produce `unauthorized_av` and
  `unauthorized_remote_access`.
- **Trust** — `whitelist` (5), `trusted_publisher` (7), separate lists in the
  legacy script merged into one array by the port.

**The conflation is load-bearing.** `whitelist_suggestion` fires on
`not cat_list`, so labelling a title `av` — a functional statement carrying no
judgement — silences a decision prompt exactly as `whitelist` does.

Trust becomes what it already is elsewhere: a **decision** at title or
publisher scope, which `software_decisions` models with scoping and audit.
Suppression then tests *decided*, not *labelled*.

**A general taxonomy is out of scope.** No finding, coverage requirement or
page consumes one, and per the glossary `entity_type` "is not a taxonomy"
either — the platform has no taxonomy concept and does not need one here.

### 4. ADR-0008's version-dropping match conflicts with §1 and is resolved here

ADR-0008 specifies `cpe_exact` matching on "vendor + product name only, **drop
version**", with a per-title safety panel. ADR-0012 §5 binds CVEs to
software+version. Both are Accepted; neither cites the other.

The consequence is measurable: `vulnerable_software` covers **22 titles across
1,389 devices**, and all 2,636 `cve_match` rows carry an **empty
`version_range`** — a column that exists for exactly this. Every device running
any version of a matched product is flagged identically, including patched
ones.

**ADR-0012 §5 governs.** It is later, it is the general model, and the
version-dropped match is a day-one conservatism ADR-0008 framed as temporary
("so the scorer can weight down fuzzy matches later"). Populating
`version_range` and matching against the installed version is the path. Until
then `vulnerable_software` is *product-level suspicion*, not per-device
vulnerability, and must say so on its face rather than implying the latter.

### 5. Classification without a decision corpus is noise

`whitelist_suggestion` fires on *uncategorised + undecided + widespread*. With
52 of 20,631 titles categorised and 3 decisions recorded, it does not report a
software problem — it reports that the reference data is empty. Fix the inputs
before tuning the detector.

### 6. Sequencing

The corpus import comes first and is forward-compatible: decisions are keyed by
title and publisher, which map onto `product` and `publisher` in §1. The
subject change (§2) precedes scheduling the classifier, because scheduling
first regenerates 134,861+ rows and undoes the page-load work in 0.115.0.

## Rationale

Every quantity was measured against production. Three claims in the first draft
did not survive verification and were corrected: an arithmetic error, an
inferred mechanism stated as fact, and an unverified prediction — the corpus
decides **814 of 1,867** open `whitelist_suggestion` (title, publisher) pairs,
44%, with publisher-scope decisions carrying 740. That ratio is itself the
argument for §1: 115 publisher decisions outperform 303 title decisions by more
than three to one, because publisher sits above product in the hierarchy.

## Consequences

- Five finding types change subject; 137,534 rows collapse to 1,782 — the sum
  of each type's distinct titles, since a subject carrying two kinds of fact
  still yields one row per kind. Existing rows must be closed and re-emitted:
  operator-visible, own approval.
- `install_path_suspicious` becomes the platform's first finding on a
  relationship rather than an entity. `operations.findings` already carries
  `subject_type`; whether a relationship subject needs more than that is an
  implementation question this record does not settle.
- Moving trust out of `categories` un-suppresses titles labelled only
  functionally. They surface for decision, correctly, because nobody decided
  them.
- `software_catalog.eol_date` is populated on **0 of 52** rows while
  `eol_runtime` runs off 9 regex rules. Populate it or drop it; a dormant
  column beside a working path misleads the next reader.
- Instantiating `publisher` and `product` entities is larger work not scheduled
  here. Until it exists, `software_decisions`' title and publisher scopes are
  the hierarchy in flat form.
- ADR-0008 needs an amendment recording that its version-dropping match is
  superseded in intent by ADR-0012 §5.
- The classifier still needs a schedule. Until it has one every software
  finding, including `vulnerable_software` and `known_malicious_hint`, is
  stale — currently by ten days.

## Supersedes or superseded by

Applies ADR-0012 §5 and `docs/glossary.md`'s identity test to the software
domain. Raises and resolves a conflict with **ADR-0008** in favour of
ADR-0012 §5. Complements ADR-0004 (findings state conditions; responses are
separate). Implements BLUEPRINT Track 3's intent.
