# 0030 — Software findings by desired-state reconciliation

Status: Accepted
Date: 2026-10-13

## Context

The per-installation classifier looped over about 585,000 installations,
re-evaluating title-only rules for each, and wrote one condition assessment per
(finding, device). A device batch of 25 fanned out to the fleet (about 357,000
device slots), each title finding rewrote its whole participant list on every
assessment, and one transaction per batch could not finish inside its budget:
64 timeouts and no completion in 14 days. Approvals were applied inside
classification, tying title facts to devices, and the exposure read model was
empty. Patching the loop (batching, caches) would have kept all of these causes.

The full discovery, the consumer audit and decisions D1-D16 are in
`.work/software-findings-design.md`.

## Options considered

- Speed up the per-installation loop (batches, caches, narrower selection).
- Compute device-independent facts per title and derive per-device state
  (selected).

## Decision

1. **Reconcile from desired state.** For each software finding type a run
   computes the complete set of findings that should be open, at the type's
   natural grain, and reconciles it with the open findings: new conditions open,
   current ones refresh, conditions no longer true resolve with a recorded reason
   (`no_longer_detected`, `subject_regrained`) and the resolving job. Facts are
   computed once per title or version, never per installation and finding.
   Condition keys are byte-identical to the previous classifier's, so existing
   findings keep their identity.
2. **Grain per type.** Version: `vulnerable_software`, `eol_runtime`.
   Product (title): `known_malicious_hint`, `suspicious_name`,
   `whitelist_suggestion` (non-approved software), `rare_recent`,
   `rejected_software_installed`. Installation: `install_path_suspicious`.
   Device and product: `unauthorized_*`. Title and version findings carry no
   per-device rows; the affected computers are the exposure join.
3. **Per-device readiness once** (`operations.software_device_readiness`): one
   condition-engine decision per (device, software finding type) covering
   settled identity and agent contact, refreshed by the run.
4. **Title assessments are derived (D1, D4).** A title finding has one
   participant (the title) and one aggregate assessment, executable and
   notifiable only while at least one exposed computer is ready. Notification
   code is unchanged: it already requires the aggregate and every non-context
   participant to permit, and a title finding has exactly those two.
5. **Exposure from readiness.** `operations.device_software_exposure_current`
   joins open findings, live installations, source evidence and readiness
   (SQL 114); the public view keeps its columns.
6. **Approvals are a live overlay at every scope** (D2): one effective-decision
   view, title before publisher and device before client before global, with the
   per-type `suppressed_by_approval` flag applied everywhere (SQL 113). A
   publisher approval silences a type only when no other concern signal exists
   on the title (D9, `concern_signal`). A severe or exploited CVE stays visible
   (D3).
7. **Reject raises a finding** (D6): `rejected_software_installed`, per title,
   not silenced by approval.
8. **Rare and non-approved split at one device limit** (D15, D16):
   `rare_max_devices` (default 2); every undecided installed title is exactly
   one of the two. Recency is a severity signal, not part of the definition.
9. **Policy is data with an admin surface** (user, 2026-10-13): classifier
   settings (`software_settings`), finding-type policy fields
   (`suppressed_by_approval`, `concern_signal`, `default_decision_scope`),
   classifier rules (including junk publishers) and suggestion rules. Decision
   precedence and the approval vocabulary stay in code.
10. **Guardrails instead of a shadow period** (D10): a per-type switch, a close
    limit (default 50% of a type per run, refused until an administrator allows
    it), recorded closure reasons, and a post-cutover spot check.
11. **Scope.** The routine run reconciles only the titles in the change feed;
    the full run (daily, and after decisions, settings and policy saves) covers
    the fleet (ADR 0029).

## Rationale

Device-independent facts depend on the title, not the computer, and readiness
depends on the computer, not the finding. Computing each at its own grain turns
a run that never finished into one of about four minutes for the whole fleet,
matched the previous open set exactly in the dry run, and lets approvals take
effect without waiting for a classifier run.

## Consequences

- A resolution no longer requires a per-finding `may_clear` assessment: a finding
  closes when the complete desired state no longer contains it, and the close
  limit and recorded reason are the safeguards. The condition safety-contract
  tests assert those instead.
- `capability_review_candidate` is produced by no run since the previous
  classifier was retired (297 findings frozen since 2026-09-16); it needs its
  own decision.
- The previous classifier (`ingest/software_findings.py`) is removed; the
  capability loaders live in `ingest/software_capabilities.py`.
- Notification delivery is disabled; about 27,700 findings currently qualify
  for it, so enabling delivery needs its own plan.

## Supersedes or superseded by

Amends 0015 (findings are reconciled at the grain above, with no per-device rows
for title and version findings), 0020 and 0021 (title findings have the
aggregate rule in decision 4), and 0028 (exposure is derived from readiness and
refreshed after scoped runs). Relates to 0029.
