# Jobs coverage inventory

Status: Current-implementation audit; ADR-0027 is the design authority
Date: 2026-10-06

## Purpose

The current registry contains 37 executable entries. This inventory records
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
| `source-refresh` | Refresh [source] data | One binding-scoped refresh for each configured external source, including Ninja, Hudu, connected tools, and reference feeds. Sources owns schedule and configuration; Jobs shows lifecycle and results. A completed source result starts only its relevant matching or analysis follow-up. |
| `software-classify-only`, `software-classify-full` | Update software status | One Job with normal and full-update modes. The combined `software-classify` entry is compatibility behavior, not another Job. |
| `patch-classify` | Update patch status | Independent result and dependency target. |
| `platform-evaluate` | Evaluate client status | Independent findings evaluation. |
| `cmdb-evaluate` | Review Hudu records | Independent findings evaluation for current Hudu CMDB records. |
| `resolver` | Match records | One Job until client matching and device matching need separate controls or outcomes. |
| `parity-check` | Check data consistency | Independent diagnostic result. |
| `intel-matcher` | Match software to vulnerabilities | Independent processing Job and dependency target. |
| `intel-capability` | Update software capabilities | Independent processing Job. |
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
| `source-actions` | The source action that requested it | Processes an approved action and remains visible with that action's audit. |
| `patches`, `agent-observations`, `documentation-observations`, and reference-feed definitions | The configured source binding | Retained only as compatibility handlers; source-bound schedules and controls use `source-refresh`. |

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
3. Every configured source binding remains independently schedulable,
   controllable, and observable. A shared source-refresh handler never
   combines its Runs, schedules, status, or controls.
4. The normal list has no artificial category headings. Search and filters can
   find Jobs by name, state, source, or client/scope.
5. Admin > Job configuration > Coverage lists every registry entry, its
   classification, parent Job where applicable, and links to its diagnostics.
6. New registry entries require one classification before release.

## Evidence and limits

This inventory is based on the current 38-entry `shared/jobs_registry.py` and
the source-level audit in `operations/.work/jobs-handler-audit.md`. It does
not certify handler safety or alter runtime behavior.
