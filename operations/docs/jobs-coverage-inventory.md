# Jobs coverage inventory

Status: Current-implementation audit; ADR-0027 is the design authority
Date: 2026-10-06

## Purpose

The current registry contains 38 executable entries. This inventory records
how those entries map toward ADR-0027; it does not define the product model.
Any entry that is only scheduler, dispatcher, worker, or recovery machinery
must be removed from the Job model during implementation while retaining its
health and diagnostic evidence.

An entry remains a **Job** when it has an independent trigger, status, result,
schedule, or administrator control. A Job may have internal stages. It is not
split unless a stage has a proven, separate operational purpose.

An entry is a **supporting process** only when it schedules, dispatches,
recovers, or carries out a Job already represented elsewhere. A **System
service** operates Jobs or the platform and belongs in Health. A **Legacy**
entry remains available only in administrator configuration.

## Jobs

The following retain independent Job status and appear in the Jobs list when
enabled. The list orders active and attention states first; it does not invent
subject categories.

| Existing registry key | Job name shown to an administrator | Boundary decision |
| --- | --- | --- |
| `patches` | Refresh Ninja data | One source snapshot with a shared source lock. Device, patch, and activity updates are stages in its detail, not new Jobs. |
| `agent-observations` | Refresh connected-agent data | A current source collection Job. Split only if an individual source needs a distinct schedule or control. |
| `documentation-observations` | Refresh Hudu records | A current Hudu CMDB collection Job. It remains one Job while its source cadence and controls are shared. |
| `software-classify-only`, `software-classify-full` | Update software status | One Job with normal and full-update modes. The combined `software-classify` entry is compatibility behavior, not another Job. |
| `patch-classify` | Update patch status | Independent result and dependency target. |
| `platform-evaluate` | Evaluate client status | Independent findings evaluation. |
| `cmdb-evaluate` | Review Hudu records | Independent findings evaluation for current Hudu CMDB records. |
| `resolver` | Match records | One Job until client matching and device matching need separate controls or outcomes. |
| `parity-check` | Check data consistency | Independent diagnostic result. |
| `intel-kev` | Update known exploited vulnerabilities | Independent feed, schedule, status, and retry. |
| `intel-nvd` | Update vulnerability data | Independent feed, schedule, status, and retry. |
| `intel-cpe-dict` | Update software matching data | Independent feed, schedule, status, and retry. |
| `intel-epss` | Update vulnerability likelihood | Independent feed, schedule, status, and retry. |
| `intel-matcher` | Match software to vulnerabilities | Independent processing Job and dependency target. |
| `intel-winget` | Update WinGet software data | Independent feed, schedule, status, and retry. |
| `intel-chocolatey` | Update Chocolatey software data | Independent feed, schedule, status, and retry. |
| `intel-capability` | Update software capabilities | Independent processing Job. |
| `intel-lolrmm` | Update remote-access software data | Independent feed, schedule, status, and retry. |
| `intel-otx` | Update threat information (OTX) | Independent feed, schedule, status, and retry. |
| `intel-abusech` | Update threat information (abuse.ch) | Independent feed, schedule, status, and retry. |
| `intel-endoflife` | Update end-of-life data | Independent feed, schedule, status, and retry. |
| `intel-category` | Update software categories | Independent processing Job. |
| `notifications-dispatch` | Send alerts | Independent delivery Job. |
| `notifications-digest` | Send summary | Independent scheduled delivery Job. |
| `retention-history` | Clean up history | Administrator-only Job; its manual control requires a separate safety review. |

## Supporting processes

| Existing registry key | Represented under | Reason |
| --- | --- | --- |
| `software-enqueue-orgs` | Refresh software inventory | Creates scheduled inventory requests; it has no independent administrator result. |
| `software-queue-drain` | Refresh software inventory | Processes those requests. It is the current run mechanism for the inventory Job. |
| `software-classify` | Update software status | Existing combined compatibility route; its stages remain visible in details. |
| `source-demand` | The requested source-refresh Job | Processes a selected source request; it is not a separate administrator goal. |
| `source-actions` | The source action that requested it | Processes an approved action and remains visible with that action's audit. |
| `source-demand-recovery` | The affected source request | Recovery evidence, not a separately controlled Job. |

`Refresh software inventory` is a visible Job whose status is derived from
the queue and worker above. It has no single current registry key, so the
implementation must give it a stable presentation key without inventing a
second execution path.

## System services

| Existing registry key or path | Where it appears |
| --- | --- |
| `run-log-recovery` | Admin Health / technical diagnostics |
| `platform-health-evaluate` | Admin Health |
| `metabase-bootstrap` | Service diagnostics |
| Scheduler, dispatcher, workers, heartbeats, timeout containment | Admin Health / technical diagnostics |
| HTTP server, migrations, and application startup | Service diagnostics |

## Legacy entries

| Existing registry key | Where it appears |
| --- | --- |
| `agent-compliance`, `agent-compliance-evaluate`, `agent-compliance-review-digest` | Admin > Job configuration when the legacy capability is enabled. They are excluded from the normal Jobs list. |

## Rules for the interface

1. A Job is shown once, even when it has modes or internal stages.
2. An active or failed supporting process is visible from its parent Job
   detail; it is never silently hidden.
3. Every independent feed remains an independent Job. A summary/filter may
   help navigation, but it cannot combine Runs, schedules, status, or controls.
4. The normal list has no artificial category headings. Search and filters can
   find Jobs by name, state, source, or client/scope.
5. Admin > Job configuration > Coverage lists every registry entry, its
   classification, parent Job where applicable, and links to its diagnostics.
6. New registry entries require one classification before release.

## Evidence and limits

This inventory is based on the current 38-entry `shared/jobs_registry.py` and
the source-level audit in `operations/.work/jobs-handler-audit.md`. It does
not certify handler safety or alter runtime behavior.
