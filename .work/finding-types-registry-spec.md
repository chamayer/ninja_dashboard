# Finding types registry and slim policy: spec

Status: spec for one last check. Nothing here is built beyond W5 step 1 (migration 0295, uncommitted). Date: 2026-10-15.

## Goal

Every configurable property of a finding lives in one place, with one name per finding type everywhere. The condition
policy keeps only behavior (rules and which rules apply to which type, freshness), so renaming or regrouping never
invalidates assessments.

## What exists today (measured)

Four overlapping classification layers and two name sets for the same 63 finding types:
- `finding_categories`: 7 data rows (coverage, identity, lifecycle, software, platform_health, data_quality, patching),
  referenced by `finding_types.category_id`. Used by client-page summaries (`client_workspace.py`, `views.py` ~11288).
- Policy definition strings `category` and `type` (legacy labels, e.g. "Computers").
- Policy taxonomy: 5 categories, 36 groups (24 hold one type).
- Names: `human_labels._LABELS` (Issues rows) versus policy `label`: 3 identical, 42 different, 16 missing (row shows the
  code name).
- Two types are not in the packaged policy file (`rejected_software_installed`, `software_inventory_held`) but are live.

## Design (updated 2026-10-15: one table)

### Data (one table: `finding_types`)

Decided 2026-10-15: no separate category or group tables, and no covers table. The 63-row `finding_types` table holds
everything: `display_name` (unique, required), `issue_category`, `issue_group` (plain text, required), `sort_order`
(categories and groups appear where their first type does), `covered_by` (list of parent type names) and `cover_note`.
Database checks: a type cannot cover itself, `covered_by` is a list, name/category/group are not empty. The older
seven-row `finding_categories` table and `finding_types.category` are removed. Tests cover what the database cannot:
covered names exist, no cycles, each group sits in one category.

### The 17 groups

| Category | Group | Types |
|---|---|---|
| Inventory | Computers no source reports | device_source_record_withdrawn, device_missing_from_source |
| | Duplicate computers | identity_conflict, duplicate_platform_record, duplicate_device_records, cross_client_conflict |
| | Computer identity | shared_serial, cross_client_serial, placeholder_serial, placeholder_mac, identity_resolution_pending, unlinked_external_identity |
| | Computer details | device_role_conflict, lifecycle_reported_state_conflict, lifecycle_unknown_reported_state, unmapped_node_class |
| | Client mapping | client_name_conflict, client_link_collision, client_source_group_merge, client_unattached_group, unnamed_source_group, unmatched_source_group |
| | Hudu records | cmdb_asset_stale, cmdb_link_incorrect, unintegrated_source_observed |
| Agents & reporting | Required agents | missing_required_platform, device_unenrolled, stale_required_platform |
| | Computers offline | device_offline, device_long_offline, device_stale_data |
| Software & security | Software approval | rare_recent, whitelist_suggestion |
| | Software classification | capability_review_candidate |
| | Unapproved software | unauthorized_remote_access, unauthorized_rmm, unauthorized_av, multi_av_conflict, rejected_software_installed |
| | Suspicious software | suspicious_name, install_path_suspicious, known_malicious_hint |
| | Vulnerable & unsupported software | vulnerable_software, eol_runtime |
| Patching & support | Patching | device_never_patched, patching_stalled, patch_approval_backlog, patch_failing_repeatedly, reboot_pending |
| | Windows support | windows_servicing_approaching_eol, windows_servicing_eol, windows_servicing_unknown |
| Data collection | Collection and processing | source_failure, software_queue_stalled, stale_collector_binding, software_inventory_held |
| | Jobs control plane | the seven jobs_* types |

### Policy (schema 2, new version)

- Keeps: version, rules, definitions reduced to `name`, `lifecycle`, `rules`; freshness; consumers; identity fields.
- Removes: definition `label`/`category`/`type`, `issue_taxonomy`, `issue_categories`, `issue_type_aliases`,
  `offline_days` (dead since the offline setting moved to Device status).
- Adds the generic `parent_open` rule (suppress_attention), attached to every type that appears as covered.
- The parser accepts schema 1 and 2, so every stored version still loads. Historical assessments are unaffected.
- One new policy version carries all of this, so there is one bump, not two.

### Code

- `_issue_taxonomy()` (`views.py`) keeps its output shape and is rebuilt from the database, so the roughly 40 callers
  do not change. Its source becomes `finding_taxonomy.py`, which reads categories, groups and types.
- One lookup, `finding_type_name(type_name)`, replaces `_LABELS` for finding types in the Issues rows, the dependency
  page, notifications, the digest, admin pages and exports. Display additions stay: the agent suffix and
  "(device offline)".
- Client-page summaries move from the old seven categories to the five.
- The admin Conditions review page (`admin.py`) reads the new source.

### The Finding types page (replaces alert eligibility and finding dependencies)

One table, one row per type. Editable and audited, staff only: display name, category and group, order, default
severity, may alert, auto-resolve, the software flags (silenced by approval, concern signal, decision scope), and
what it covers (the covers pairs, with the cycle and repeat checks already built). Shown read-only: whether the type is
active in the policy, and which rules apply to it, linking to the policy review. Groups and categories are edited in a
section of the same page: rename, reorder, move a type.

## Migrations (in order)

1. `0295_finding_types_registry`: adds the columns, seeds all 63 types, adds the checks, removes the old category table
   and column. No behavior change on its own; the code that reads it ships in the same deploy.
2. `0296_slim_condition_policy`: inserts and activates the schema 2 policy version (generic `parent_open` rule attached to
   every type, no presentation, no `offline_days`). Same mechanism as 0286.

## Effects and risks

- Names and groups change on screen for every finding type; the Issues URLs that used group keys change (one operator;
  the single old alias is dropped).
- Activating 0297 makes every existing assessment non-current until each finding is next evaluated (the Issues page and
  the notifier accept only the active version). Evaluators run hourly and the software runs on change. After the
  deploy I would run the platform, patch and software evaluations once, with your approval, to close the gap.
- The covered findings (W5 step 2) arrive with 0297 and the code that applies the rule, but stay visible until step 3.

## Tests

- Every finding type has a display name, a unique name, and a category (directly or through a group).
- No screen carries its own finding-type name, and none reads a policy label.
- Policy schema 1 and 2 both parse; schema 2 has no presentation fields.
- The taxonomy rebuilt from the database has the old shape: every type exactly once, every group in a category.
- The Finding types page: staff only, audited, rejects duplicate names, cycles and repeated pairs.

## Order of work and approvals

1. Names and groups (0296, with 0295): build, test, commit, push.
2. Policy and the `parent_open` signal (0297): build, test, commit, push, then run the evaluations.
3. Issues page: covered state, "N hidden", "N other findings on this subject" (no migration).
4. First-run measurement.

Each push names its migration.
