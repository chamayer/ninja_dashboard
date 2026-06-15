# Goal
Fix and complete the Today compliance KPIs.

# Why
The Compliant % card used `is_compliant`, but `v_all_devices_human` does
not expose that column. The operator also wants to see the compliant
device count, not only a percentage.

# Scope
- Change only the active Level 1 Today Compliant % query.
- Add a `Compliant devices` KPI beside `Compliant %`.
- Keep stale and ignored devices out of the denominator.
- Do not change compliance evaluation logic or dashboard layout.

# Files to change
- `ingest/agent_compliance/metabase_bootstrap.py` - Today compliance KPI queries.
- `CHANGELOG.md` - note dashboard behavior.
- `SESSIONS.md` - session note.

# Steps
1. Replace `is_compliant` with exposed `state = 'Good'`.
2. Add `Compliant devices` using `state = 'Good' AND NOT ignored`.
3. Keep denominator as non-stale, non-ignored devices.
4. Run syntax and diff checks.

# Open questions
- None for this pass.

# Status
done - pending commit
