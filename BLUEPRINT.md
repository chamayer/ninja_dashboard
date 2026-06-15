# Goal
Make the Today KPI row match the operator compliance model.

# Why
Compliance means devices that are still in scope have all required
platforms. Stale devices are usually offline/decommissioned candidates,
so they should be counted separately and not pull down compliance
percentage.

# Scope
- Change only the active Level 1 Today top KPI row.
- Add Stale as a first-row KPI.
- Calculate Compliant % as compliant / non-stale, non-ignored devices.
- Keep Ready to notify, Names to review, and Collection issues on row 2.
- Do not change compliance evaluation logic.

# Files to change
- `ingest/agent_compliance/metabase_bootstrap.py` - Today KPI queries and layout.
- `CHANGELOG.md` - note dashboard behavior.
- `SESSIONS.md` - session note.

# Steps
1. Change Compliant % to divide by non-stale, non-ignored devices.
2. Add Stale KPI to row 1.
3. Reflow row 1 to five cards and row 2 to three cards.
4. Move lower Today cards down to avoid overlap.
5. Run syntax and diff checks.

# Open questions
- None for this pass.

# Status
done - pending review/commit
