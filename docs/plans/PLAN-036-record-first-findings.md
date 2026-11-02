# PLAN-036 — Record-first findings and consistent identity decisions

**Status:** Complete (2026-11-02). Released 0.138.0–0.139.1; follow-ups 0.141.1
(recovered health Issues close; per-source software tables registered for change
history) and 0.141.2. Verified read-only on production 2026-11-02: source-record
queue drained, no intake errors, resolver and evaluations healthy, no open health
Issue without a current assessment.

**Goal:** Ensure actionable source-record risks are evaluated without waiting for
Computer attachment, then apply a consistent association policy across writers
and review paths. Complete relevant PLAN-003/004 gaps and validate the result.

**Scope:** Software and agent-specific risk findings; shared §5 identity policy;
Computer-page aggregation and finding handover; remaining accepted §4 rules;
PLAN-003 client dashboard count alignment; PLAN-004 resolver finding lifecycle
cleanup. Production-only reassessment review and R4-2 timing/queue observation
remain gated by their existing operational approvals. Machine-level coverage
requires sufficient identity and policy evidence. Preserve unrelated work.

**Affected files:** ADR-0050, ingest inventory, findings and identity, Operations
readers, tests and reviewed migrations; inventory exact files per slice.

**Steps:** Implement software, then agent findings; unify §5; finish
remaining rules and UI; validate end-to-end. Production and release gates apply.

**Decisions:** Preserve source claims when sources overlap; each rule determines
record or machine scope. Missing policy context yields unknown, not a fabricated
verdict. Do not resolve a finding during handover until a successor exists.

**Validation:** 140 focused tests and eight disposable PostgreSQL checks pass.
Migrations apply through SQL 118 and Operations 0386 on a fresh synthetic
database. The Operations image builds and passes Django system checks; Compose
configuration, Python compilation, scoped Ruff checks, and `git diff --check`
pass. No fleet processing, performance measurement, or production validation
was run.

Latest focused validation: 140 tests across source-observation failure handling,
observation-run reconciliation, source-record assessment, platform-health
producers, condition safety, software inventory, resolver promotion, and Hudu
card resolution pass. Eight disposable PostgreSQL checks pass. The Operations
image passes Django system checks; `docker compose config --quiet`, Python
compilation, scoped Ruff checks, and `git diff --check` pass. The plan-registry
validator is not present in this checkout.

**Checkpoint:** Work is in isolated worktree `plan003-r3`, based on `253db218`;
main checkout is older and has unrelated edits. ADR-0050 was accepted 2026-10-30.
Local migrations 0376, 0377, 0379, 0380 and 0381 add per-source software current/history and register
source-record severe-vulnerability, rejected-software, unauthorized-capability, suspicious-name and threat-hint rules. Ninja software rows now reach source
record inventory before Computer resolution, and associated records can surface
findings on the Computer page with `Source: <platform>`. Source-only changes trigger
the global catalog projector, allowing product/version identities before attachment.
The rules use shared CVSS, KEV, severity, effective reject-decision, capability
authorization and title/publisher approval helpers; missing software-policy context
remains unknown, and disabled rules leave existing findings untouched.
The Computer page now includes active source-record findings when their episode
overlaps that Computer's source-link history, while retaining the source record as
the finding owner. It displays the compact source label already added to the details.
Source inventory additions and changes are retained; absent rows are not retired
because source records do not yet have the Computer inventory's sharp-shrink
hold/release state. Computer software projection and history remain unchanged.
The page joins source finding IDs through
`entity_source_link_history` without retargeting findings.

The existing Computer projection still requires a Ninja-to-Computer map (fleet
refresh fails if it is empty); the additive source inventory maps API node IDs to
admitted subjects using source instance and preserved `ninja_node_id`. Existing
Computer history, removal holds and dirty scheduling remain Computer-keyed. Source
inventory updates do not remove absent titles because the API does not establish
per-record coverage. Existing software findings use product, version, installation
and Computer subjects; retain those owners where they cover the same attached risk.
Verify product linking, suppression and client-policy uncertainty. Required-agent
coverage reads Computer presence and decisions; distinguish it from agent-specific
signals.
Identity inventory: intake, queued resolution, source-record preview,
reassessment, and one-time preview use the shared tiered matcher. It holds on
ambiguity or a hard conflict and does not fall through to a weaker key. Migration
0378 constrains unique matching; local migration 0382 requires independent,
non-roaming name or MAC support from a different source instance for serial/VM
matches and aligns the policy blockers. Promotion now decides each record
independently. Lookup-key candidates remain review evidence; they do not attach.
Exact source-identity matching and resolver association now use the observation's
source instance and ID, so a same-platform external-key collision cannot bind or
bulk-associate a sibling from another instance. Migration 0382 requeues managed
records. Rule revision is now 8: migration 0384 adds MAC validity and 0386 adds
Hudu reference validity; both requeue managed records. Missing optional MACs remain unknown;
attached junk MACs keep their legacy Computer finding owner; other malformed
present MAC claims can open native source-record findings. Unknown identifier
inputs do not resolve existing findings. Hudu stale/divergent evidence keeps its
legacy CMDB owner when the exact source reference is present; otherwise a native
`source_record_reference_review` owns the correction. CMDB findings retain full
source identity references beyond the visible example cap and queue only
assessments whose owner is not current.

Endpoint-agent assessments preserve safe reported connectivity and typed
last-contact values as separate rule results, and the source-record detail page
shows those values and labels the software/status rules. Restricted/missing data
is unknown. No stale-agent finding is emitted because the existing offline
threshold is Computer-scoped and no source-role threshold has been defined.

Migration 0383 registers an admin-health condition for device-link/projection
divergence. The evaluator reads tenant-scoped parity directly and emits one
platform finding with a count and the authoritative link table; it does not
invoke collection sync or repair the projection. A clean evaluation refreshes
an existing finding's assessment so resolution follows current evidence.

Migration 0385 moves the unused `source_record_policy_incomplete` type into
admin health and removes its parent-condition gate. The evaluator groups present
unclassified records by source instance and entity type, emits one configuration
finding with an impact count, and refreshes clean assessments before resolution.
Per-record role results remain unknown.

Acceptance for the software slice: synthetic unattached records with and without
client policy retain inventory and surface supported unwanted/vulnerable/tool
risks; missing context is visible as unknown. Both fleet and targeted refreshes
handle complete and incomplete input without false removals. Attach, detach and
move preserve findings and history, with no lost correction; existing product,
version and installation ownership and suppressions remain correct. Tenant/RLS,
restricted records, replay, migration compatibility, dirty scheduling, relevant
readers and package inclusion must be checked before release.

## Completion evidence to date

- ADR-0050 is accepted. The source-of-fact rule, finding ownership, history-based
  Computer aggregation, and compact `Source: <platform>` detail line are recorded
  in the ADR and implemented. The broader page redesign remains in the backlog.
- Software and endpoint-agent data are admitted and assessed at record scope.
  Unsupported policy context stays unknown. Source inventory absence does not
  retire software rows without an approved coverage/hold contract.
- Identity matching is shared across intake, resolution, reassessment, and
  previews. Ambiguity and hard conflicts stop automatic attachment; serial/VM
  matches require independent evidence. Resolver promotion decides each record
  separately and associates its exact observation.
- Hudu reference assessment preserves the existing CMDB owner when it covers the
  exact source asset; otherwise the native source-record finding opens. Native
  findings resolve when the reference is corrected. Full source references are
  retained for handover scheduling.
- Source attribution is a quiet per-record assessment based on explicit
  source-group links. It does not infer group ownership from Computer client
  inheritance and does not add a per-row issue badge.
- Missing source role configuration and device-link/projection divergence are
  aggregated in platform health. Malformed rows without stable identity are
  durably recorded, fail the snapshot, and skip reconciliation.
- Fresh disposable PostgreSQL accepted the staged migration chain through SQL
  118 and Operations 0386. Migrations 0383 and 0385 were corrected after this
  run exposed stale finding-type schema references. `docker compose config`
  validates the bootstrap model; full Compose startup was not run.
- Eight bounded PostgreSQL checks pass for attribution/Hudu source loading,
  intake helper and full-writer failure behavior, policy-health reassessment,
  Computer history overlap, CMDB handover, Hudu native-finding lifecycle, and
  source-software current/history writes. The 140-test focused suite passes,
  including resolver promotion and Hudu card resolution. The Operations image
  builds and passes `manage.py check`; scoped Ruff, Python compilation, and
  `git diff --check` pass.

## Remaining boundaries

General purpose classification and source-role age/staleness remain unknown
until policy is authored. Source software rows are not retired on absence without
a coverage/hold contract. Ingest load measurement was waived by the accepted
R4-2 decision; watch timings and queue drain after an approved release. The
observation dual-write PostgreSQL suite still has its baseline assertion failure
(expected material projection version 3, actual 4). Full-file Ruff on the large
Operations views module reports unrelated existing findings. The plan-registry
validator script is absent from this checkout. No production database, commit,
push, or deployment was used or authorized in this task.

## Current checkpoint (2026-10-30)

The missed local PLAN-003/004 work is implemented. The client dashboard counts
independent corrective actions through the shared Issues selection. The client
resolver retires stale per-group unattached, unnamed, and non-topology collision
findings with closure reasons. Admin findings require current-observation clear
assessments; unnamed entity findings close only open/acknowledged episodes when
source state no longer meets the condition. Operator-managed `investigating`
items and topology collisions remain untouched.
60 focused ingest tests and 21 focused Operations client-mapping/Issues queue
tests pass; Python compilation, scoped resolver Ruff, and `git diff --check`
pass. The full Operations suite was not run; full-file Ruff on the large views
module reports existing findings. `scripts/validate_plan_registry.py` is absent
from this checkout, so registry structure was reconciled manually. The goal
remains active for the
production reassessment review and post-release timing/queue observation, which
require their existing operational gate and are not evidenced by local tests.



## Release checkpoint (2026-11-01)

- Read-only production measurement of the strict §5 matcher (worktree code, policies
  simulated as 0378/0382 set them, against the 2026-10-30 reassessment): of 22,278
  records the old rules re-attach identically, 35 would no longer attach
  automatically (28 unmatched, 6 ambiguous, 1 changed); 32 more re-attach;
  ambiguous falls from 88 to 60. Existing links are not moved.
- Condition definitions consolidated: 0377–0386 register types only; 0387 activates
  one policy (`conditions-registry-12`) so finding state is recomputed once, and
  publishes findings contract 6 as the version boundary.
- Re-validated: Django check and `makemigrations --check` clean; 136 focused ingest
  tests pass (22 PostgreSQL opt-in skipped locally); dev database applies 0376–0387,
  active policy covers 82/82 types; production pre-checks pass (0385's type and an
  active policy exist; no display-name collision). Operations and PostgreSQL suites
  were not run locally (light-checks rule); final testing is the user's.
- Released as 0.138.0 (`4fb92c48`), deployed 05:24 UTC: 0376–0387 applied, policy 12,
  contract 6, parity 0. Two regressions followed and were fixed the same morning:
  0.138.1 (`5ea0a6cc`) — software-signal query passed 8 parameters to 2 placeholders,
  so every source-record batch failed; 0.138.2 (`b0c847dd`) — presentation keys in two
  schema 2 definitions made the active policy unparseable, so all condition assessments
  failed ~05:24–05:42 UTC. Verified after 0.138.2: assessments resume platform-wide,
  worker log clean, all open native findings assessed, queue draining.
- Two further 0.138.0 regressions were found read-only on production and fixed in
  0.139.0. First, the client resolver's closure-reason parameter had no type, so 6 of
  23 resolver runs failed and their evaluations were marked prerequisite-failed.
  Second, source-record software history opened two rows for a list that named one
  title twice: 441 Computers' refreshes failed, and 0392 queues them again.
- 0.139.1 (`87d870cb`) closes superseded failed software refreshes. The one-time
  disposition run kept all 1,271 reassessment rows that changed, matched ambiguously
  or lost their match, and moved none. Details are in `operations/BLUEPRINT.md`
  (leave-nothing-in-limbo follow-up).
