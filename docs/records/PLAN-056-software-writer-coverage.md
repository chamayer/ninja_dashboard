# PLAN-056 — Software writer coverage

## Boundary and current result

The finite W1–W4 implementation pass is complete locally as of 2026-11-12.
This covers the seven input families in the
[implementation requirements](PLAN-056-software-implementation-requirements.md),
using existing domain owners and Jobs. It does not certify deployed behavior,
all writer permutations, source age or the 60-second completion budget.
The [acceptance record](PLAN-056-release-acceptance.md) owns actual evidence
and limitations; earlier missing-path findings there remain historical.

## Seven input families

| Family | Current maintenance path |
| --- | --- |
| Installations and relinking | Material inventory changes publish existing title/catalog/safety inputs and reach classifier/overview through Jobs. Authoritative association changes additionally request existing ownership work. |
| Computer lifecycle, association and ownership | Existing lifecycle/identity actions and relevant admin/candidate writes admit ownership or overview work. Protected reads and publication reject dirty ownership; the existing scheduler admits its owner before overview. |
| Catalog/capability inputs | Ordinary and bulk capability decisions admit full classification. Publisher aliases and matcher hints admit local catalog-policy work; platform capability mappings admit classification. Descriptive taxonomy is excluded. |
| Intelligence/safety | Existing material intelligence edges reach matcher/classifier. Matcher completion requests overview even when membership is unchanged. Local catalog-policy work uses existing catalog/lifecycle/matcher functions without fetching source data. |
| Findings, type policy and settings | Shared relevance covers category/source/scope and named compatibility types. Relevant finding CRUD/status actions admit overview; classifier/type/decision policies retain appropriate full classification. Readiness-setting and active condition-policy changes admit overview. |
| Decisions and product authorizations | Ordinary authorization, capability and existing decision/remote-access paths couple admission with the write/audit transaction. Existing client/global precedence is preserved. |
| Readiness, conditions, source support and time | Source-support/admin changes admit ownership, then overview. Overview atomically prepares existing readiness, evaluator-owned assessments and exposure before publishing. Existing minute expiry admission remains; throughput/cadence are uncertified. |

## W1 — Direct decision/finding admission: locally wired

Ordinary capability and product-authorization actions now request the existing
full classifier in their write/audit transaction. Finding resolve/suppress/bulk
actions and FindingAdmin share the relevance boundary in finding_registry.
FindingAdmin uses the existing findings-write guard and admits overview for
material changes. Preparation preserves manually resolved findings: it neither
emits nor reopens them. Existing admin hooks skip unrelated/cosmetic changes.

## W2 — Catalog/matching policy ownership: locally wired

PublisherAliasAdmin and IntelMatcherHintAdmin admit one internal software-catalog
Job invoking existing catalog projection, lifecycle projection and local matcher.
Its declared successor is full classification, then overview. It performs no
source HTTP acquisition. PlatformProductMapAdmin uses full classification;
existing deletion restrictions remain. This adds an invocation to the existing
Jobs registry, not a competing domain producer, service, schedule or store.
It uses existing catalog/CVE resources; overview shares Software state capacity.

## W3 — Computer/association/support invalidation: locally wired

Relevant Source, SourceInstance, SourceBinding (including inline), Device,
Client and source-lifecycle-mapping admin writes request the existing ownership
Job. Generic candidate acceptance still uses set_source_association_by_key and
admits ownership in that transaction. Existing dirty rows remain authoritative:
0409 and 0410 inspect them, and the existing scheduler admits ownership before
a due overview. No second association writer or dirty store was added.

The integration fixture exercised the empty ownership Job and its successor;
it did not exhaustively exercise every PostgreSQL admin field/trigger transition.

## W4 — Readiness/exposure prerequisite: locally wired

Overview holds one transaction and valid publication fence while invoking
existing readiness preparation, refreshing existing Software-evaluator-owned
assessments, refreshing exposure and replacing the aggregate. The owner/request
checkpoint is compared before and after calculation, and the claim is rechecked
before commit. Preparation neither emits findings nor takes ownership of other
evaluators' assessments. Active condition-policy creation and client/global
readiness settings admit overview in the source transaction.

An induced failure after actual preparation rolled back assessments, exposure
and overview; original generation/timestamps survived. Existing retry admission
and subsequent actual Job publication passed.

## Paths deliberately excluded from new work

- `software_category_decide` changes descriptive taxonomy. M03 is effective
  capability coverage; taxonomy is not a substitute input. No new summary
  maintenance is justified solely by descriptive category edits.
- `SoftwareCatalogAdmin` edits the legacy `operations.software_catalog` detail
  record. The reviewed aggregate SQL, readiness/reconcile inputs and source-label
  reader do not consume that relation. This is distinct from the catalog projector
  module and `catalog.software_versions`; do not conflate their names.
- `EolProductMapAdmin` disallows add/change/delete. Generic Entity/evidence,
  mapping and source-link admin surfaces marked read-only are not missing CRUD
  hooks. Actual accepted associations belong to W3.
- Acknowledgement preserves the active predicates used by the metrics; snooze/
  resume modify pause metadata. These do not justify a new summary request by
  themselves. Client display labels remain permitted bounded live detail.
- `SuppressionRuleAdmin` is not directly read by the aggregate or the current
  Software reconcile input query. Prove any required downstream status effect
  before adding work; actual finding changes are already W1/W4.
- Repository call-site review found the old `main.run_software_classify_once`/
  scheduled wrapper definitions and their internal call, not a current external
  caller. The registered dispatcher uses its own governed reconcile path.
  Do not repair dormant helpers as a shortcut. Out-of-band SQL/module invocation
  remains separately authorized maintenance and must preserve the contract.

## Bounded Jobs integration result and remaining gates

Completed using an isolated synthetic PostgreSQL fixture and actual Jobs
admission, dependency release, dispatch, claim, progress and finish APIs:
classifier → overview, catalog → classifier → overview, ownership → overview,
finding create/resolve pending-to-current behavior, queued successor/coalescing,
wrong/stale-claim rejection, failure retention and retry. Protected application
reads denied private storage/old-view bypasses and client-scoped metrics; reads
did not enqueue work. Certification switches existed only in the fixture.

Functional worker execution used the fixture's migration-owner login because
the local development ingest role lacks a preexisting finding_types SELECT
grant. No runtime grants were broadened. Protected application reads used
operations_app. This proves local functional flow, not complete worker-role
authorization. Verify the actual runtime role before certification.

No test files were changed in this pass. Six known existing Jobs expectation
failures were not rerun or repaired; five predate this work. Their registry/edge
expectations remain unresolved and must not be described as passing. Focused
existing Software checks pass; broader coverage requires its separate approval.

Remaining acceptance is runtime-role/security verification, representative
freshness and full HTTP proof, reviewed service migrations, certification and
approved route cutover/release. Results remain contract_ready=false and the
default page retains live reads. All 15 navigation items remain open.
