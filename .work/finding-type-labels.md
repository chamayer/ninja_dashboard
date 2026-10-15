# Finding type names: the registry seed (final)

Date: 2026-10-15. Seeded by migration 0295 into `finding_types.display_name`, `issue_category`, `issue_group`, `sort_order`, `covered_by`. Edited afterwards on the Finding types page.

| Category | Group | Type (internal) | Name shown everywhere | Covered by |
|---|---|---|---|---|
| Inventory | Computers no source reports | `device_source_record_withdrawn` | **Computer no longer reported by a source** | `device_missing_from_source` |
| Inventory | Computers no source reports | `device_missing_from_source` | **Computer not reported by any source** |  |
| Inventory | Duplicate computers | `identity_conflict` | **Possible duplicate computers** |  |
| Inventory | Duplicate computers | `duplicate_platform_record` | **Duplicate entries in one platform** |  |
| Inventory | Duplicate computers | `duplicate_device_records` | **Duplicate Hudu entries (historical)** |  |
| Inventory | Duplicate computers | `cross_client_conflict` | **Same hostname on two clients** |  |
| Inventory | Computer identity | `shared_serial` | **Shared identifier** |  |
| Inventory | Computer identity | `cross_client_serial` | **Shared identifier across clients** |  |
| Inventory | Computer identity | `placeholder_serial` | **Placeholder serial number** |  |
| Inventory | Computer identity | `placeholder_mac` | **Placeholder MAC address** |  |
| Inventory | Computer identity | `identity_resolution_pending` | **Awaiting computer identity match** |  |
| Inventory | Computer identity | `unlinked_external_identity` | **Unresolved computer from source** |  |
| Inventory | Computer details | `device_role_conflict` | **Computer role changed** |  |
| Inventory | Computer details | `lifecycle_reported_state_conflict` | **Platforms disagree on lifecycle status** |  |
| Inventory | Computer details | `lifecycle_unknown_reported_state` | **Unknown lifecycle status** |  |
| Inventory | Computer details | `unmapped_node_class` | **Unrecognized computer type** |  |
| Inventory | Client mapping | `client_name_conflict` | **Client renamed at source** |  |
| Inventory | Client mapping | `client_link_collision` | **Multiple clients claim this name** |  |
| Inventory | Client mapping | `client_source_group_merge` | **Duplicate source groups mapped to one client** |  |
| Inventory | Client mapping | `client_unattached_group` | **Group not attached to a client** |  |
| Inventory | Client mapping | `unnamed_source_group` | **Unnamed platform organization** |  |
| Inventory | Client mapping | `unmatched_source_group` | **Platform group awaiting matching** |  |
| Inventory | Hudu records | `cmdb_asset_stale` | **Hudu archive candidate** |  |
| Inventory | Hudu records | `cmdb_link_incorrect` | **Hudu record linked to different Computers** |  |
| Inventory | Hudu records | `unintegrated_source_observed` | **Hudu references an unconnected platform** |  |
| Agents & reporting | Required agents | `missing_required_platform` | **Required agent not installed** | `device_missing_from_source` |
| Agents & reporting | Required agents | `device_unenrolled` | **No management agent installed** |  |
| Agents & reporting | Required agents | `stale_required_platform` | **Required agent not checking in** | `device_offline`, `device_missing_from_source` |
| Agents & reporting | Computers offline | `device_offline` | **Computer offline** | `device_missing_from_source` |
| Agents & reporting | Computers offline | `device_long_offline` | **Offline for an extended period** |  |
| Agents & reporting | Computers offline | `device_stale_data` | **No recent data** |  |
| Software & security | Software approval | `rare_recent` | **Rare software** |  |
| Software & security | Software approval | `whitelist_suggestion` | **Widespread software without a decision** |  |
| Software & security | Software classification | `capability_review_candidate` | **Software capability not confirmed** |  |
| Software & security | Unapproved software | `unauthorized_remote_access` | **Unauthorized remote access tool** |  |
| Software & security | Unapproved software | `unauthorized_rmm` | **Unauthorized RMM tool** |  |
| Software & security | Unapproved software | `unauthorized_av` | **Unauthorized AV product** |  |
| Software & security | Unapproved software | `multi_av_conflict` | **Multiple AV products installed** |  |
| Software & security | Unapproved software | `rejected_software_installed` | **Rejected software installed** |  |
| Software & security | Suspicious software | `suspicious_name` | **Suspicious name** |  |
| Software & security | Suspicious software | `install_path_suspicious` | **Installed from suspicious location** |  |
| Software & security | Suspicious software | `known_malicious_hint` | **Software matches threat-report indicators** |  |
| Software & security | Vulnerable & unsupported software | `vulnerable_software` | **Software vulnerability detected** |  |
| Software & security | Vulnerable & unsupported software | `eol_runtime` | **End-of-life runtime** |  |
| Patching & support | Patching | `device_never_patched` | **No patch installed yet** |  |
| Patching & support | Patching | `patching_stalled` | **No recent patch activity** | `device_offline`, `device_missing_from_source` |
| Patching & support | Patching | `patch_approval_backlog` | **Approved updates not installed** |  |
| Patching & support | Patching | `patch_failing_repeatedly` | **Update repeatedly failing** |  |
| Patching & support | Patching | `reboot_pending` | **Restart required** | `device_offline`, `device_missing_from_source`, `patching_stalled` |
| Patching & support | Windows support | `windows_servicing_approaching_eol` | **Windows support ending soon** |  |
| Patching & support | Windows support | `windows_servicing_eol` | **Windows build out of support** |  |
| Patching & support | Windows support | `windows_servicing_unknown` | **Windows support state unknown** | `device_missing_from_source`, `missing_required_platform` |
| Data collection | Collection and processing | `source_failure` | **Data source not responding** |  |
| Data collection | Collection and processing | `software_queue_stalled` | **Software scan queue stalled** |  |
| Data collection | Collection and processing | `stale_collector_binding` | **Ingest connector stopped** |  |
| Data collection | Collection and processing | `software_inventory_held` | **Software list held for review** |  |
| Data collection | Jobs control plane | `jobs_schedule_failure` | **Scheduled Job failed** |  |
| Data collection | Jobs control plane | `jobs_required_disabled` | **Required Job is disabled** |  |
| Data collection | Jobs control plane | `jobs_queue_backlog` | **Jobs queue delayed** |  |
| Data collection | Jobs control plane | `jobs_repeated_failure` | **Job fails repeatedly** |  |
| Data collection | Jobs control plane | `jobs_timeout` | **Job timed out** |  |
| Data collection | Jobs control plane | `jobs_registry_mismatch` | **Jobs registry mismatch** |  |
| Data collection | Jobs control plane | `jobs_unmet_dependency` | **Job dependency is unmet** |  |
