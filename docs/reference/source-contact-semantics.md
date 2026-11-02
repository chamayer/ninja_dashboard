# Source contact and status semantics

What each collector's `is_online` and `last_seen_at` mean, read from the
connector code on 2026-11-02 (PLAN-012 completion-gate item 3). `last_seen_at`
becomes a record's reported last contact
(`v_entity_observation_admin_metadata.reported_last_contact_at`) and feeds
`device_agent_presence_current.last_contact_at`. `observed_at` is when *we*
polled the source and is never contact evidence.

| Source | `is_online` | `last_seen_at` (contact) | Notes |
|---|---|---|---|
| Ninja (`ninja_presence.py`) | `NOT offline` from Ninja device detail; null when Ninja omits it | Ninja `lastContact` | Only `AgentDevice` records count as agents. |
| SentinelOne (`sentinelone.py`) | `isActive` | `lastActiveDate` | `isActive` is agent activity, not machine power. |
| ScreenConnect (`screenconnect.py`) | a guest (`ProcessType = 2`) connection is active now | `GuestInfo.LastActivityTime`; year ≤ 1 is treated as unknown | Deleted or ended sessions are skipped. |
| LogMeIn (`logmein.py`) | `isHostOnline`, else `isOnline`, else `online` | `hostStateChangeDate`, else `lastSeen`, else `lastOnline` | `hostStateChangeDate` is the last online/offline transition, so a host online for weeks may show an old contact time while `is_online` is true. |
| R-U-ON (`ruon.py`) | parsed console state | always null | The console shows times without a time zone; the text is kept in `raw_data.last_contact_text` and a time is never guessed. |
| Hudu (`hudu.py`) | always null | always null | Documentation, not contact evidence. `archived` drives record lifecycle (`documentation`/`archived`). |

## Label presence versus lifecycle evidence

- **Presence** (online/offline/stale on Computers, Coverage and Home) uses
  only `is_online` and `last_seen_at`, compared with the Computer's offline
  window: the client's `offline_after_days`, else the tenant
  `active_device_days` (`operations/apps/core/device_status.py`,
  `ingest/device_status_settings.py`).
- **Lifecycle evidence** (whether a source still lists the machine) comes from
  `source_record_lifecycle_mappings` through
  `v_device_source_record_lifecycle_current`: a current Hudu asset is
  `documentation`, an archived one `archived`, a powered-off VM `stopped`.
  `ingest/computer_listing.py` treats a record as "reporting" when it is
  online, powered on, or contacted within the tenant review period
  (`retire_review_days`).
- A source with null contact (R-U-ON, Hudu) can never make a Computer
  "recently contacted". An R-U-ON record that reports online still counts as
  online.
