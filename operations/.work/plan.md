# Active Operations implementation plan

Track: **ADR-0010 generic ecosystem completion — Phase E5**

**Status:** E1-E4 and E5.1 deployed; E5.2 release `0.109.0` implemented locally
and under final review.

## Goal

Expose the deployed generic entity, source-evidence, claim/effective/conflict,
candidate, relationship, and source-health contracts through tenant-safe
Operations read models and admin workflows, then cut named consumers to those
contracts only after aggregate parity.

## Scope and affected files

- additive tenant-scoped read views and narrowly scoped reveal functions in
  Django migrations; no canonical ID, source identity, or typed foreign-key
  changes
- unmanaged read models and an explicit restricted-evidence permission
- generic entity list/detail, candidate decision, relationship evidence, and
  row-based source-instance health surfaces under the existing Admin shell
- audited POST-only reveal for protected raw/restricted evidence
- named Operations/ingest/API/export/evaluator/finding/notification consumer
  inventory and parity gates before direct-table privileges are revoked
- focused contract, permission, route/template, migration, and deployed
  aggregate checks

## Confirmed inventory

- Production scale: 5,348 entity anchors, 24,980 generic links, 30,164 current
  observations, 266,594 current claims, 181,380 effective values, 168
  conflicts, 4,890 candidates, zero effective relationships, five source
  instances, and 14 active source-instance/type groups.
- Existing redacted claim/effective views are safe default readers. Django
  admin exposes some E1-E3 evidence, but the custom Operations admin has no
  generic entity/candidate/relationship pages and source health still exposes
  fixed device/client count columns.
- The Device Identity & raw tab reads raw observation JSON on ordinary GET.
  `operations_app` retains `SELECT` on observation current and underlying E3
  effective/conflict tables, although raw claims/history and all protected E4
  evidence are already denied.

## Decisions

- Basic UI visibility is registry/class driven. Source names never select
  templates, fields, or behavior. Typed client/device labels may extend the
  generic entity shell; unknown future classes use a safe generic label.
- Default list/detail reads are redacted and contain counts/placeholders for
  protected evidence. Raw or restricted values require an explicit
  permission, a POST action, tenant validation, and an `audit_log` event that
  records metadata but never the revealed value.
- The new reveal permission defaults denied; superusers retain Django's normal
  permission override. GET, CSV, findings, logs, and aggregate validation never
  include protected values.
- Generic candidate attach/reject actions call the existing E4 atomic services;
  they do not duplicate link/history/audit logic. Observed-only records remain
  visible but are not presented as pending authority decisions.
- Relationship pages initially expose deployed evidence/effective state. No
  relationship is fabricated to exercise an empty production engine.
- Direct-table grants remain until every named reader is cut to a redacted or
  typed effective contract. Revocation is a separate migration in E5.2, not a
  speculative change bundled with the first UI slice.

## Delivery steps

1. E5.1: add generic redacted read views for entity summary, source evidence,
   conflicts, relationships, candidates, and source-instance/type health.
2. E5.1: add Operations Admin entity list/detail and candidate queue/actions;
   extend Sources with row-based type counts and link the new surfaces from the
   existing Admin navigation and landing page.
3. E5.1: validate migration/view security, tenant filters, redaction, service
   reuse, pagination, templates, HTTP behavior, and aggregate production
   parity; release/deploy only after basic checks pass.
4. E5.2: add POST-only permission-checked reveal functions/routes, audit
   metadata-only access, move Device Identity & raw and other named readers,
   then revoke obsolete raw/effective direct-table grants with denial tests.
5. E5.3: inventory and cut APIs, CSV exports, evaluators, findings,
   notifications, and approved typed readers one at a time after aggregate
   parity. Preserve typed device/session/patch/software views where their
   semantics are class-specific.
6. Record any remaining compatibility columns/readers for E6 contract work;
   do not delete history, Agent Compliance, or legacy snapshots here.

## Validation

- Python compile, focused Ruff, Django check, migration drift, focused tests,
  template loading/request smoke checks, and `git diff --check`.
- SQL review for `security_barrier`, `current_tenant_id()`, explicit grants,
  role denial, registry-driven grouping, and no raw values in default views.
- Deployed aggregate row/count parity, tenant filtering, ACLs, route status,
  candidate action/no-op invariants, version/migrations, container health, and
  current HTTP-500/traceback/error counts.
- No local Docker rehearsal; the user requested basic proportional testing.

## Checkpoint and next action

E4 corrective `0.107.3` / `47bb68b` is deployed and mirrored with migration
0115 applied, exact ACLs, forced RLS, enabled triggers, no-op projectors, healthy
services, and zero current errors. Unrelated backlog, instruction, DESIGN, and
probe-file changes remain outside this plan and release staging.

E5.1 release `0.108.0` / `6433f44` is deployed and mirrored. It includes seven
security-barrier tenant read views owned by the
dedicated no-login/non-BYPASSRLS view role; generic entity list/detail and
candidate attach/reject pages; row-based source-instance/type counts; and
Admin navigation/landing integration. Default views exclude raw payloads and
protected source-event actor data. Compile, Django check, migration drift,
nine focused E4/E5 tests, template loading, and diff checks passed. Production
view counts and ACL/owner/tenant checks match the intended contract; six
authenticated read-only renders returned HTTP 200, all containers were
healthy, root/health returned 302/200, and current error counts were zero.

E5.2 release `0.109.0` is implemented locally. A new permission defaults
denied; reveal endpoints are POST-only and non-cacheable; database functions
verify active user, tenant, and direct/group/superuser permission, append a
metadata-only event to the existing audit log, and only then return the
requested current observation or attribute value. Device identity GET no
longer loads raw payloads. Client-candidate and device-merge reads use a safe
observation metadata view, permitting observation payload and E3 protected
table grants to be revoked while retaining the required update path. Django
check and migration drift pass; 11 focused E4/E5 contract tests and template
loading pass. The pre-existing four observation-model DJ008 warnings remain
outside this change.

Next: finish focused lint/diff/migration review, commit `0.109.0`, push
`origin`, immediately redeploy, push the mirror, then verify migration 0117,
exact ACLs, permission/function/audit metadata contracts without revealing
values or fabricating an audit event, authenticated GET/denial route behavior,
containers, version, health, and current error counts. Then begin E5.3 named
consumer inventory/parity and cutover.
