# Goal
Show both sides of a cross-customer device match in the existing device drilldown current-state table.

# Why
When a device is missing a platform that is found under another customer,
the drilldown only filters by exact hostname. That can hide the matching
row because the other platform may report a longer or different hostname
with the same normalized identity.

# Scope
- Change only the active Level 1 `drilldown_current` card.
- Resolve the clicked row to its normalized device identity.
- Return all current device rows sharing that normalized identity.
- Preserve ordinary single-device drilldown behavior.
- Do not add another card.
- Do not change compliance evaluation logic.

# Files to change
- `ingest/agent_compliance/metabase_bootstrap.py` - current device drilldown query.
- `CHANGELOG.md` - note dashboard behavior.
- `SESSIONS.md` - session note.

# Steps
1. Anchor the selected device by `(customer, host)` when customer is present.
2. Fall back to host-only when customer is not present.
3. Return all `v_all_devices_human` rows with the anchor `norm_name`.
4. Keep useful columns in the existing current-state table.
5. Run syntax and diff checks.

# Open questions
- None for this pass.

# Status
done - pending review/commit
