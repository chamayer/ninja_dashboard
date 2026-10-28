# PLAN-034 — Post-cleanup housekeeping: notification settings and rollback archives

**Status: deferred.** Registered 2026-10-28 from the backlog; both items
came from PLAN-022. Each step needs the user's approval.

## Goal

Remove the last legacy names from the host configuration and set how long
the rollback archives are kept.

## Items

| Step | Item | Notes |
| --- | --- | --- |
| 1 | Rename notification delivery settings on the host | The host `.env` still has `AGENT_COMPLIANCE_SMTP_PORT`, `_SMTP_STARTTLS`, `_ZENDESK_URL` and `_ZENDESK_REQUESTER_NAME`, which code no longer reads. Before notifications are switched on: copy them to `NOTIFY_*`, verify, then remove every `AGENT_COMPLIANCE_*` key. This is a production host write; report names and set/empty status only, never values. First confirm with the user that the PLAN-022 rollback window is closed. |
| 2 | Retention for rollback archives | The git-ignored local `archive/` holds the Metabase and PLAN-022 archives (`archive/plan022-legacy-2026-10-26/`); the host copy is in `/amr-ch-01_data/ninja-dashboard/backups/operations/legacy-2026-10-26/`. Decide how long to keep each copy; deleting one is a separate destructive step. |

## Next action

User decision on the retention period and on when to do Step 1.
