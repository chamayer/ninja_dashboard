# Central work queue: design and implementation review

Status: draft for approval. Nothing here is built. Date: 2026-10-14.
Companion documents: `finding-type-review.md` (classification of the 63 types) and
`finding-dependency-review.md` (parents, dependents, evidence).

## 1. Principles (agreed)

1. **One queue, one view.** Every kind of waiting work is a finding and appears in the Issues page, grouped in
   categories. Overviews show counts that link into the queue; they never hold their own lists. Browse pages
   (Products, Publishers, Computers) are data, not work.
2. **Admin findings are in the same queue** (with their history). Storage stays in two tables; no migration of
   `admin_findings`. There is no "staff": admins are the users, and permissions gate actions, not visibility.
3. **Every finding invites a check.** There is no "no action" class. Severity says how urgent it is; info and
   low sort last and collapse within their category.
4. **A change in the world becomes exactly one of three things:** an event on the computer's timeline (expected
   churn that explains itself), a finding hidden under its parent (something else covers it), or a finding.
5. **Dependency suppression keeps the finding.** A dependent stays a real finding (own history, still
   evaluated), is hidden from the default list, shown under the parent as "N hidden", and returns when the
   parent clears if still true. A *gate* (untrustworthy evidence, such as a failed source or unsettled identity)
   neither asserts nor clears the condition.
6. **Alerting is a property of the type, default off.** Decisions and reviews never alert.
7. **Names stay plain.** Five categories keep their names: Inventory, Agents & reporting, Software & security,
   Patching & support, Data collection. Nothing is renamed or split.
8. **Policy is data with an admin surface.** No hard-coded mappings.

## 2. Verified facts that shape the plan

| Fact | Evidence |
|---|---|
| All 63 types already sit in exactly one of 36 sub-groups in the 5 policy categories | active policy, 0 ungrouped |
| Alert eligibility is read in about 10 places, all in the notifier and digest | `ingest/notifications.py`, `ingest/notifications_digest.py` |
| No type has an enabled notification rule | `notification_rules` |
| "Offline" has four definitions: 7 days (`active_device_days`), 35 days (`patch_activity_days`, used by patch and software readiness), 180 days (condition profile `offline_days`, used by `device_offline` and by the stale-agent demotion), and 7/30 days hard-coded in the lifecycle evaluator | `device_status.py`, `evaluator.py`, active policy |
| `device_offline` therefore only exists after 180 days of silence, so it cannot be the parent of problems on computers silent for 7 to 180 days | `evaluator.py` `_evaluate_device_offline` |
| The evaluator already demotes stale and missing agent findings to `info` with `reason_suppressed = device_offline` on fully offline computers; the page only adds "(device offline)" to the label, it hides nothing | `evaluator.py`, `views.py` |
| `missing_required_platform` deliberately stays visible on offline computers (never installed is a real gap) | comment in `evaluator.py` |
| The Issues page buckets assessments into actionable, blocked and pending; a *suppressed* assessment falls into "pending" and would read "Pending current assessment" | `_condition_response_ids` |
| `findings_queue` is a 2,077-line view built on the `Finding` model; `admin_findings` has different column names | `views.py`, `models.py` |
| `jobs_unmet_dependency` carries `prerequisite_job_key` and run id | migration 0259 |
| The withdrawn finding is created per (source, record) from `missing_since` with fixed severity `medium` | `evaluator.py` ~1670 |
| The two registered queue actions are retire computers and archive in Hudu; others are generic (pause, exclude, refresh) | `finding_actions.py` |
| Product capability decisions and software decisions exist as actions but only on other pages | `software_capability_decide`, `software_decision_*` |
| 54% of the findings that qualify for alerts today are decision requests; none can alert yet | assessments, `notification_rules` |

Not verified: whether source-record changes already write to the computer timeline; how the admin Health page
acts on admin findings; whether `jobs_unmet_dependency` maps cleanly to the upstream finding's key.

## 3. Work items

| # | Item | Change | Size | Migration | Depends on |
|---|---|---|---|---|---|
| W1 | `alertable` | Column on `finding_types`, default false; seed the types that may alert; one shared SQL fragment used by the notifier and digest; small admin editor listing all 63 types | S-M | yes | none |
| W2 | Counts that agree | Overview cards and the Issues tile use one definition of "needs a decision" and link into the queue filtered; fix the stale `?decision=pending` link | S | no | none |
| W3 | Decisions in the queue | Register actions for undecided software (approve title, approve publisher, reject, investigate) and for capability review (confirm, reject), permission-gated, reusing the decision handlers and prompt resolution | M | no | none |
| W4 | One offline definition | Decide and implement a single offline threshold for the agent and patching family (see D1) | S-M | maybe | decision D1 |
| W5 | Dependency engine | `finding_type_dependencies` data (parent, dependent, kind) with an admin editor; a `dependency` rule in the policy (new policy version) attached to dependents; `record_assessment` adds a signal naming the open parent on the same scope; new "suppressed" attention state, an "N hidden" line on the parent and a reveal filter in the queue; tests for scope, chains and cycles | L | yes (+ policy version) | W4 |
| W6 | Withdrawn records — **superseded 2026-10-15** | Moved to the Computer identity plan (`operations/.work/plan.md`, workstream 7, ADR-0032); its replacement rule is an open decision there | — | — | — |
| W7 | Jobs chain | `jobs_unmet_dependency` hidden under the upstream job's failure; retire the overlapping `software_queue_stalled` | M | no | W5 |
| W8 | Admin findings in the queue | Spike first: a SQL view that gives both tables one row shape, read-only in the queue; then actions; no storage move | L | yes (view) | none |
| W9 | Housekeeping | Retire the dormant and superseded types; find duplicate open rows across the two tables; look at the `unauthorized_remote_access` authorization gap | S-M | policy version | none; classify Hyper-V and VMware monitoring records so they never read as a second agent id (626 computers) |

Also pending and separate: the local, uncommitted changes from this session (old classifier removal, ADR 0030,
Issues context line, rare-limit preview).

## 4. Phases

| Phase | Items | Why this order |
|---|---|---|
| 1 | W1, W2 | Safety first (nothing can alert by accident) and consistent numbers; small and independent |
| 2 | W3 | Cuts the work: 15,193 undecided titles become actionable in the queue |
| 3 | W4, W5, W7 | Removes the noise (4,418 findings on 2,761 computers, 219 job symptoms); withdrawn records moved to the Computer identity plan |
| 4 | W8 | Completes the single queue; the biggest and riskiest change to the page |
| 5 | W9 | Clean up once the model is settled |

Each phase ends with a validation step and its own commit and push approval. Deployment applies migrations
automatically, so each push approval names the migrations it includes.

## 5. Safeguards for dependency suppression

1. Every hidden finding shows why and under what, with a one-click reveal.
2. Parent and dependent must match on the exact scope (the same computer, source, job chain or title); tested.
3. Chains resolve to the root, and cycles are rejected by the policy parser.
4. Hidden findings are excluded from needs-attention counts but counted as "N hidden" on the parent.
5. Each pair is reviewed for severity inversion (a high finding hidden under a lower one).
6. Facts about installed state (end-of-life OS, software findings) are never hidden by an offline parent.

## 6. Decisions needed

- **D1: what is "offline"?** For the agent and patching family the parent must exist for computers silent 7 days
  or more. Options: lower `device_offline` to the 7-day `active_device_days` (about 1,194 computers instead of
  744), or add a separate "agents silent" signal and keep `device_offline` at 180 days as the decommission
  candidate. Recommendation: the separate signal, so decommission candidates and "currently silent" stay
  distinct. Needs your call.
- **D2: which types may alert.** Proposed in `finding-type-review.md` (`yes` and `?` columns).
- **D3: severity of a vanished security agent** (left open by you).
- **D4: phase order.** Recommended above.
