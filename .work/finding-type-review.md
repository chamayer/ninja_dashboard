# Finding type review (draft for confirmation)

Date: 2026-10-14. Counts are open findings across both tables (`findings` and `admin_findings`).

**Audience test: who resolves it, and where is the fix made?**

- `env` (operators): the fix is made on a computer, an agent or a client's systems, or in a source tool
  (install or repair an agent, remove a duplicate record, rename a machine, patch, retire, decide on
  software), however the platform happened to detect it. Identity findings are env: the platform's
  matching is only the lens that exposes a device that needs work.
- `plat` (admins): the fix is made in Operations itself (a client mapping, a state or class mapping,
  a catalog or capability decision, a job, a collector credential, a held inventory release).
- A finding that needs both is assigned to whoever acts first; the other audience can still see it.

Needs: `fix` = something to correct; `decide` = a choice is requested; `info` = awareness only.
Alert: `yes` = may alert, `?` = your call; decisions and info never alert. No type has an enabled
notification rule today.

| Type | Resolved in | Needs | Alert | Open | Note |
|---|---|---|---|---|---|
| device_missing_from_source | env | decide | no | 149 | confirm retired or investigate |
| rare_recent | env | decide | no | 10,272 | software review |
| whitelist_suggestion | env | decide | no | 4,921 | software review (non-approved) |
| cmdb_asset_stale | env | fix | no | 207 | Hudu documentation upkeep: platform or environment? |
| cmdb_link_incorrect | env | fix | no | 15 | Hudu documentation upkeep: platform or environment? |
| cross_client_conflict | env | fix | no | 0 | last fired 2026-07-14; superseded? |
| cross_client_serial | env | fix | no | 10 | same serial at two clients: cloned image, reused hardware or bad data on a device |
| device_long_offline | env | fix | no | 0 | last fired 2026-07-14; superseded by device_offline? |
| device_never_patched | env | fix | ? | 214 |  |
| device_offline | env | fix | no | 744 |  |
| device_role_conflict | env | fix | no | 15 | set the role correctly in the source |
| device_stale_data | env | fix | no | 0 | last fired 2026-08-04; superseded? |
| device_unenrolled | env | fix | no | 538 | tracked by a monitor but no agent |
| duplicate_device_records | env | fix | no | 0 | last fired 2026-09-10; superseded by identity_conflict? |
| duplicate_platform_record | env | fix | no | 90 | remove the duplicate agent record in the source |
| eol_runtime | env | fix | ? | 165 |  |
| identity_conflict | env | fix | no | 41 | two records, one machine or a hostname clash: remove the duplicate, rename the machine, or confirm they are distinct |
| install_path_suspicious | env | fix | yes | 514 |  |
| known_malicious_hint | env | fix | no | 80 | low confidence community signal |
| missing_required_platform | env | fix | yes | 1,005 | required agent not seen on a computer |
| multi_av_conflict | env | fix | no | 0 | disabled: installed packages cannot prove active protection |
| patch_approval_backlog | env | fix | no | 45 | client-level |
| patch_failing_repeatedly | env | fix | ? | 142 |  |
| patching_stalled | env | fix | no | 1,122 | no fresh patch state in 35 days |
| placeholder_mac | env | fix | no | 0 | never fired; a device reports a filler MAC |
| placeholder_serial | env | fix | no | 0 | never fired; a device reports a filler serial |
| reboot_pending | env | fix | no | 201 |  |
| rejected_software_installed | env | fix | yes | 41 |  |
| shared_serial | env | fix | no | 1 | same serial on two devices in a client |
| stale_required_platform | env | fix | no | 643 | agent seen before, not recently; 374,448 rows ever for 643 open (episode churn) |
| suspicious_name | env | fix | no | 6 |  |
| unauthorized_av | env | fix | yes | 306 |  |
| unauthorized_remote_access | env | fix | yes | 6,610 | 6,610 open: check the capability evidence for noise |
| unauthorized_rmm | env | fix | yes | 0 | never fired |
| unmatched_source_group | env | fix | no | 35 | install the missing agent; if the machine exists the matching failed (escalate to an admin) |
| vulnerable_software | env | fix | yes | 4,949 |  |
| windows_servicing_approaching_eol | env | fix | no | 109 |  |
| windows_servicing_eol | env | fix | ? | 1,754 |  |
| device_source_record_withdrawn | env | info | no | 2,534 | a source record for this computer disappeared; purpose to confirm; no category |
| capability_review_candidate | plat | decide | no | 297 | platform catalog knowledge; curator permission |
| client_link_collision | plat | decide | no | 0 | never fired |
| client_name_conflict | plat | decide | no | 126 | agreed admin; rows exist in both ledgers |
| client_source_group_merge | plat | decide | no | 0 | never fired |
| client_unattached_group | plat | decide | no | 43 |  |
| identity_resolution_pending | plat | decide | no | 0 | never fired; no category |
| lifecycle_reported_state_conflict | plat | decide | no | 0 | never fired |
| software_inventory_held | plat | decide | no | 0 | an admin releases the hold in Operations; the cause may be an agent glitch on the computer |
| unlinked_external_identity | plat | decide | no | 0 | never fired; no category |
| jobs_queue_backlog | plat | fix | yes | 0 |  |
| jobs_registry_mismatch | plat | fix | yes | 1 |  |
| jobs_repeated_failure | plat | fix | yes | 4 |  |
| jobs_required_disabled | plat | fix | yes | 9 |  |
| jobs_schedule_failure | plat | fix | yes | 7 |  |
| jobs_timeout | plat | fix | yes | 17 |  |
| jobs_unmet_dependency | plat | fix | yes | 219 | 219 open: expected, or noise? |
| lifecycle_unknown_reported_state | plat | fix | no | 51 | add a state mapping |
| software_queue_stalled | plat | fix | yes | 6 | overlaps jobs_*; open rows in both ledgers (3 + 3); no category |
| source_failure | plat | fix | yes | 9 | open rows in both ledgers (5 + 4) |
| stale_collector_binding | plat | fix | no | 0 | never fired; no category |
| unmapped_node_class | plat | fix | no | 0 | never fired |
| unnamed_source_group | plat | fix | no | 1 |  |
| windows_servicing_unknown | plat | fix | no | 228 | servicing state unresolved: a rule gap (admin), or an odd OS report on the device |
| unintegrated_source_observed | plat | info | no | 75 | a vendor the platform does not ingest directly |

## Totals

| Resolved in / needs | Types | Open |
|---|---|---|
| env / decide | 3 | 15,342 |
| env / fix | 35 | 19,602 |
| env / info | 1 | 2,534 |
| plat / decide | 9 | 466 |
| plat / fix | 14 | 552 |
| plat / info | 1 | 75 |
