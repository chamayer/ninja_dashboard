# Operations development checkpoint

Plan lifecycle status belongs to the [registry](../docs/records/PLAN_REGISTRY.md).
Earlier mixed implementation notes, evidence, limitations and recovery instructions
are preserved verbatim in the [retained checkpoint](docs/records/OPERATIONS-CHECKPOINT-2026-11-02.md).
That record is historical and must be verified against current files before reuse.

## PLAN-056 — Platform performance recovery

**Goal:** Complete Software item 1 under ADR-0058 and the fixed
[six-step worklist](../docs/records/PLAN-056-software-implementation-requirements.md).
All 15 items remain open; the
[cross-service handoff](../docs/plans/PLAN-056-platform-performance-assessment.md)
owns navigation routing.

**Local checkpoint (2026-11-12):** Software components and W1–W4 owner wiring
are locally implemented. The
[writer map](../docs/records/PLAN-056-software-writer-coverage.md) owns coverage.
Existing Jobs admission/ownership dirtiness and atomic preparation/publication
preserve manual finding state; no new service/store/cadence or role redesign.
contract_ready=false; default page retains live reads, Products/CSV compatible.
ADR-0037/0039 remain Proposed. Unrelated work is preserved.

**Release checkpoint:** User chose production. Software-only 0.144.12 candidate
is prepared from ae45b463, excluding Home, local 0406 and test edits.
Affected: core Software admin/views/actions/registry/reader/template,
ingest owner/preparation/dispatch, shared Jobs, 0407–0410 and release/contract docs.
[Release review](../docs/records/PLAN-056-release-0.144.12.md) owns exact scope,
migration effects, checks, packaging, limitations and approval effects.
Isolated Django, 22 focused checks, templates, migration graph, compilation,
helper lint and registries pass. Known Jobs expectations/baseline lint remain.
Earlier synthetic Jobs checks used an owner role with intelligence disabled.

**Production metadata:** Approved read-only check: 0406 applied; 0407–0410 absent;
SQL through 119 applied. Observed ingest pools use superuser access. Restricted
ninja_ingest lacks necessary rights. This existing security limitation remains
recorded; no role/config/grant change or security waiver. No production write.

**Next action:** Exact candidate is staged; patch/manifest retained locally and
temporary worktree removed. Obtain commit approval, then push approval including automatic
deployment and 0407–0410. Origin first, mirror second; no manual redeploy.
Governed initial publication, representative freshness/full-HTTP proof,
certification and sustained reader activation remain separately gated.

## PLAN-015 — Identity reconciliation

Independent of PLAN-043's read-only display work. Registry remains active.
The retained checkpoint reports a validated preview and a guard-aware 110-candidate
follow-up; these historical counts have not been rerun for this task.
**Next:** Verify current state and review candidates before proposing repairs.
Any reattachment, merge or derived refresh needs its own approval.
See the [plan](docs/plans/PLAN-015-identity-reconciliation.md) and retained checkpoint.

## PLAN-016 — Admin SQL explorer

Independent scope; registry remains active with an approval gate. The retained
checkpoint describes planned work; no implementation is claimed here.
**Next:** Obtain implementation approval, then inspect Admin Data routing/tests.
See the [plan](docs/plans/PLAN-016-admin-sql-explorer.md).
