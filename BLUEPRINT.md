# Goal
Make the top seven Agent Compliance Today cards readable without removing any of them.

# Why
The current top row is too condensed: seven KPI cards are visually cramped and titles are being cut off.

# Scope
- Keep all seven top KPI cards.
- Shorten only the long labels.
- Reposition the top seven into a readable two-row layout.
- Do not change lower Today tables.
- Do not change device compliance logic.

# Files to change
- `ingest/agent_compliance/metabase_bootstrap.py` - Today dashboard card titles and row/column positions.

# Steps
1. Update top seven KPI labels.
2. Set the summary layout to four cards on the first row and three cards on the second row.
3. Move the lower Today cards down so they do not overlap the second KPI row.
4. Run syntax and diff checks.

# Open questions
- None for this pass.

# Status
done - pending review/commit
