# Issues page taxonomy and count-contract correction

## Status

**Implementation in progress.** The approved taxonomy is six categories and 26
operator types covering all 53 condition keys. Product implementation is
authorized; deployment remains subject to the repository's explicit push and
automatic-migration rules.

Baseline reviewed: local `master` at `816e574`. The tracked worktree contains
the approved implementation changes;
the pre-existing untracked `.work/probe_*` and bootstrap files are unrelated and
must remain untouched.

## Goal

Make the Issues page understandable without knowledge of database keys:

- one small, stable set of human-facing categories;
- a category-dependent list of human-facing issue types;
- a specific plain-English issue name on every row;
- technical condition keys retained for URLs, policy, audit, and admin use but
  never used as an operator-facing fallback;
- count labels whose populations and filter behavior are explicit; and
- no hidden findings, changed eligibility, changed severity, or lost workflow.

This is corrective completion of the conditions work's human-facing taxonomy
and discovery scope (formerly WP6), not a cosmetic rename.

## Confirmed current behavior and causes

1. The active condition policy already defines three useful levels for all 53
   conditions: `category`, grouped `type`, and individual `label`.
2. `views._issue_taxonomy()` ignores the policy's ordered `issue_categories`
   registry and reconstructs categories from definition display strings plus
   legacy `FindingCategory` rows. The packaged registry still contains an older
   five-category vocabulary that does not match the six definition categories.
3. `views._operator_issue_type_groups()` does not use each definition's grouped
   `type`. It normally creates one filter option per technical finding key,
   except for the single special alias group. This expands 26 intended groups
   into nearly the full condition list.
4. Row headings and row labels use `human_labels._LABELS`, a second hardcoded
   vocabulary. Missing entries fall back to raw keys such as
   `lifecycle_reported_state_conflict`, `unintegrated_source_observed`,
   `capability_review_candidate`, and `vulnerable_software`.
5. The page therefore has four competing authorities: policy metadata, legacy
   database categories, `issue_type_aliases`, and `_LABELS`.
6. The upper category cards are fleet-wide actionable counts and ignore page
   filters; severity counts and result cards inherit different subsets of those
   filters. Policy candidates are mixed into some totals but excluded from
   others. The current labels do not communicate these population differences.
7. Existing tests mainly assert that strings or controls exist. They do not
   prove complete taxonomy coverage, human-readable output, disjoint category
   membership, count conservation, or filter invariants.

## Proposed operator vocabulary

The approved taxonomy supersedes the draft vocabulary below. The authoritative
six-category/26-type registry is now in `shared/conditions/profile.json` and
has been approved by the user; internal finding names remain unchanged.

| Category | Purpose |
| --- | --- |
| Inventory | Computer inventory, matching, duplicates, platform entries, and Hudu maintenance |
| Agents & reporting | Required agents and Computers or agents that are not reporting correctly |
| Software & security | Software approval, classification, risk, and vulnerability work |
| Patching & support | Patch progress, restart requirements, and Windows support |
| Data collection | Source collection, processing, and collector health |

### Complete type mapping

Every one of the 53 condition keys must appear exactly once in this matrix.
Lifecycle state controls whether a condition can currently be emitted; it must
not remove historical retained findings from `status=all` discovery.

| Category | Operator type | Internal condition keys |
| --- | --- | --- |
| Inventory | Inventory gaps | `device_source_record_withdrawn`, `device_missing_from_source` |
| Inventory | Duplicate Computers | `identity_conflict`, `shared_serial`, `cross_client_serial`, `cross_client_conflict` |
| Inventory | Duplicate platform entries | `duplicate_platform_record`, `duplicate_device_records` |
| Inventory | Inventory data problems | `placeholder_serial`, `placeholder_mac`, `device_role_conflict`, `lifecycle_reported_state_conflict`, `lifecycle_unknown_reported_state`, `unmapped_node_class` |
| Inventory | Client matching | `client_name_conflict`, `client_link_collision`, `client_unattached_group`, `unnamed_source_group`, `unmatched_source_group`, `identity_resolution_pending`, `unlinked_external_identity` |
| Inventory | Hudu maintenance | `cmdb_asset_stale`, `cmdb_link_incorrect`, `unintegrated_source_observed` |
| Agents & reporting | Required agents | `missing_required_platform`, `device_unenrolled` |
| Agents & reporting | Agents not reporting | `stale_required_platform` |
| Agents & reporting | Computers not reporting | `device_offline`, `device_stale_data`, `device_long_offline` |
| Software & security | Unapproved software | `unauthorized_remote_access`, `unauthorized_rmm`, `unauthorized_av` |
| Software & security | Software classification | `capability_review_candidate` |
| Software & security | Software approval | `whitelist_suggestion` |
| Software & security | Suspicious software | `rare_recent`, `suspicious_name`, `install_path_suspicious`, `known_malicious_hint` |
| Software & security | Vulnerable software | `vulnerable_software` |
| Software & security | Unsupported software | `eol_runtime` |
| Software & security | Protection conflicts | `multi_av_conflict` |
| Patching & support | Patching not progressing | `device_never_patched`, `patching_stalled`, `patch_approval_backlog` |
| Patching & support | Patch failures | `patch_failing_repeatedly` |
| Patching & support | Restart required | `reboot_pending` |
| Patching & support | Windows support | `windows_servicing_approaching_eol`, `windows_servicing_eol`, `windows_servicing_unknown` |
| Data collection | Collection failures | `source_failure` |
| Data collection | Processing delays | `software_queue_stalled` |
| Data collection | Collector reporting | `stale_collector_binding` |

Individual row names come from each condition definition's `label`, not from the
grouped type and not from a technical-key formatter. Before implementation,
review all 53 labels together for capitalization, terminology, tense, and
specificity. The review must preserve meaningful distinctions inside a type;
for example, “Patching not progressing” is a filter group, while “No installed patch
history” and “Patch activity overdue” remain separate row names.

### Operator vocabulary rule

- Do not display “source record” or raw `source_*` terminology to operators.
- Use **platform** for the service where an entry exists, such as Ninja, Hudu,
  LMI, or SentinelOne.
- Use **integration** for the connection or collection mechanism.
- Use **entry** only when distinguishing duplicates inside a platform.
- Name the platform when known: “Duplicate Ninja entries” is better than
  “Duplicate platform entries.”
- Keep `source`, `source_instance`, `source_binding`, external IDs, and condition
  keys available in policy administration, audit, evidence, and diagnostics.

## Count and filtering contract

### Fleet overview (upper section)

- Purpose: answer “Where is actionable work across the fleet?”
- Population: active-status, unsnoozed, currently actionable governed findings.
- Exclude software-policy candidates from incident totals; show them once in a
  clearly separate “Software decisions” card.
- Category cards are intentionally unaffected by category, type, severity,
  client, platform, online, search, subject, or page filters.
- Each category card shows a total and the same five severity buckets.
- Invariant: category totals are disjoint and their sum equals the fleet-wide
  actionable total. Severity buckets within a category sum to its total.
- Use one captured query scope/time so cards cannot disagree during rendering.

### Current results (below filters)

- Purpose: answer “What does my current filter return?”
- Apply category, type, response, status, severity, confidence, client,
  platform, online, subject/evidence drilldown, search, and snooze controls.
- Replace ambiguous fractions/cards with one compact sentence and only useful
  distinct counts: issue rows, affected Computers, affected clients, and
  software decisions when present.
- Severity controls show counts after every current filter except severity, so
  selecting one severity does not make the other choices appear to be zero.
- Type options cascade from the selected category and always include “All
  types”; selecting a type must never reset unrelated filters.
- The page title displays the selected category label, never its key.
- Group headers use the grouped operator type and show the count for the full
  filtered result, not merely the current page. Rows retain their individual
  issue label.

### Reconciliation requirement

Before and after implementation, capture a read-only matrix by response state,
status, category, type, severity, and policy-candidate status. Taxonomy-only
work may redistribute rows between labels but must not change the overall
counts for retained, actionable, blocked, pending, paused, or policy-review
populations. Any difference must be explained by an independently deployed
eligibility/data change, not accepted as a naming side effect.

## Implementation plan

### WP1 — Approve vocabulary and freeze a baseline

- Review the approved six category names and 26 type names with the user.
- Export the active policy's complete 53-condition taxonomy and compare it with
  the matrix above; fail if anything is missing, duplicated, or unmapped.
- Capture the count reconciliation matrix and representative screenshots/URLs
  for unfiltered, category, type, blocked, pending, policy-review, and device
  drilldown views.
- Record whether each count changed during the prior conditions rollout because
  of eligibility, status, snoozing, policy-candidate separation, or a UI bug.

Exit: vocabulary approved. Baseline evidence capture remains part of WP6
validation because production access is not required for local taxonomy work.

### WP2 — Establish one taxonomy authority

- Replace the stale category/alias split in `shared/conditions/profile.json`
  with an ordered registry containing stable category keys, category labels,
  stable type keys, type labels, and complete condition membership.
- Keep the 53 condition keys unchanged. Keep each condition's individual label
  explicit and validated.
- Extend `shared/conditions/policy.py` validation so every definition belongs
  to exactly one declared type, every type belongs to exactly one category,
  keys and labels are unique, and no registry member is unknown.
- Remove `issue_type_aliases` as a partial special-case mechanism after a
  compatibility reader has canonicalized old URLs.
- Do not use legacy `FindingCategory.name` or `_LABELS` as operator taxonomy
  authority. They may remain for storage compatibility or unrelated surfaces.
- Because the active policy is immutable and database-governed, create a new
  policy version through the existing create/review/activate workflow. Review
  the exact migration/seed approach before implementation; do not mutate the
  active policy in place or silently auto-activate an unreviewed policy.

Exit: one validated policy registry maps all 53 keys to six categories, 26
types, and 53 individual labels.

### WP3 — Build a single Issues-page projection

- Add one resolver that returns category/type/issue metadata for every finding
  from the active policy and is shared by filters, cards, headings, rows, CSV,
  and drilldowns.
- Update `_issue_taxonomy()` and `_operator_issue_type_groups()` to consume
  that resolver; delete their dependence on reconstructed legacy categories.
- Replace `humanize_label(finding_type.name)` in Issues grouping and row labels
  with policy `type.label` and definition `label` respectively.
- Preserve dynamic context additions such as the missing agent product and
  offline explanation without replacing the canonical issue label.
- Unknown keys fail visibly as “Unclassified issue” with the technical key in
  an admin-only diagnostic, rather than leaking snake_case to operators.
- Keep legacy category/type query values working through canonical redirects;
  preserve bookmarks and device/detail drilldowns.

Exit: no operator-visible category, type, title, group, row, or CSV field uses
a technical key or a second label dictionary.

### WP4 — Make counts follow the documented contract

- Centralize base querysets for fleet overview, filtered governed findings,
  and software decisions. Name the scopes in code after the contract.
- Compute the upper category/severity matrix in one grouped query where
  practical, using the policy membership map and current response authority.
- Compute current-result and severity-facet counts from one filtered base with
  the deliberate “exclude severity for severity facets” rule.
- Remove or redesign the current five fraction cards; do not compare filtered
  issue counts with unrelated denominators such as total fleet devices unless
  the operator explicitly asks for a fleet percentage.
- Ensure affected-Computer counts include governed software exposure exactly
  once and category totals count issue rows, not affected-device fanout.
- Keep top cards independent of filters and visually separate from the current
  result summary.

Exit: all conservation/filter invariants pass against PostgreSQL fixtures and
the before/after reconciliation has zero unexplained population changes.

### WP5 — Simplify the page layout

- First section: “Actionable work across the fleet,” category cards by severity,
  plus a separate Software decisions card.
- Second section: category and type on their own primary row, with “All
  categories” and “All types” as defaults; remaining filters below.
- Third section: compact current-result summary followed by collapsible type
  groups. Group header shows human type label and full filtered count.
- Row “Issue” cell shows the specific policy label. Preserve subject links,
  evidence, context, status, dates, actions, bulk actions, condition detail,
  Hudu actions, reviewed-distinct, and CSV exports.
- Keep advanced/internal condition keys off the normal page. Existing policy
  admin remains the technical surface; any richer advanced operator view stays
  in `operations/.work/backlog.md` unless separately approved.

Exit: an operator can answer category, type, exact issue, subject, severity,
and available action without interpreting an internal key or conflicting total.

### WP6 — Validation and release

- Unit-test the registry validator with missing, duplicate, cross-category, and
  unknown members.
- Add behavior tests proving all 53 conditions render human category/type/issue
  labels and no raw key appears in HTML or CSV.
- Add PostgreSQL-backed count tests for category and severity conservation,
  software-policy separation, actionable/blocked/pending/paused states,
  snoozing, inherited software exposure, and type/category cascades.
- Add request tests for legacy URL redirects, filter preservation, pagination,
  full-result group counts, device/evidence drilldowns, and `status=all`
  discoverability of historical conditions.
- Run focused Operations tests, `manage.py check`, migration-plan/drift review,
  template loading, `ruff` checks where available, and `git diff --check`.
- Update root `VERSION` and `CHANGELOG.md` only as part of an approved release.
- Commit, push, policy activation, automatic deployment, and live validation
  each follow repository authorization requirements. Verify live category sums,
  representative filters, CSVs, and application health after rollout.

## Expected files

- `shared/conditions/profile.json`
- `shared/conditions/policy.py`
- `operations/apps/core/views.py`
- `operations/apps/core/conditions/live.py` if the projection belongs there
- `operations/apps/core/templatetags/human_labels.py` (remove Issues-specific
  duplicate authority; retain unrelated formatting)
- `operations/templates/findings_queue.html`
- `operations/apps/core/tests/test_conditions.py`
- `operations/apps/core/tests/test_conditions_live.py`
- `operations/apps/core/tests/test_findings_queue.py`
- a reviewed additive Operations migration only if needed to seed the new
  immutable policy version
- `operations/docs/decisions/0022-policy-defined-issue-taxonomy.md`
- root `VERSION` and `CHANGELOG.md` at approved release time

## Out of scope

- Changing condition predicates, response eligibility, severity, suppression,
  notification, clearing, source actions, or internal finding keys.
- Deleting or rewriting retained findings.
- Reclassifying global software as a client-owned entity.
- A general rule editor, arbitrary policy scripting, or the deferred advanced
  issue-columns surface.
- Manual deployment, manual production migration, or data rebuild.

## Current checkpoint and next action

WP1 vocabulary approval is complete. WP2/WP3 are implemented locally: the
registry validates all 53 condition memberships, the immutable policy seed is
prepared, and the Issues resolver drives filters, headings, rows, and CSVs.
WP4/WP5 first-pass count and layout corrections are implemented. Focused
condition and queue tests pass (79 tests), and `manage.py check` passes. The
remaining work is migration-plan review, broader Operations validation, and
deployment authorization if the implementation is accepted.
