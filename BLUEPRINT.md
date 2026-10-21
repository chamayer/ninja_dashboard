# PLAN-001 — Dashboard navigation performance

## Goal

Make ordinary Dashboard navigation responsive from measured causes, and close PLAN-001 only with current deployed evidence.

## Scope

Measured server/rendering causes on Dashboard navigation and its landing pages. Preserve tenant/RLS, card meanings, URLs, and established data authorities. No cache, duplicate projection, speculative index, migration, or production-data action.

## Status and evidence

Active. The fresh authenticated tenant-1 handler baseline was Dashboard 3.154 s, Computers 12.871 s, Sources 4.474 s, Cleanup 5.368 s, User exposure 5.877 s, and Software Overview/Products over the 20 s request limit. Releases through 0.128.9 are deployed and healthy: Dashboard warmed to 1.308–1.568 s, Sources to 0.935–0.988 s, Software Overview to 1.042–1.068 s, and Products to 2.037–2.082 s. Authenticated headless-browser navigation on the deployed stack independently measured response/duration: Dashboard 1.995/2.399 s, Findings 1.887/2.503 s, Software Overview 2.013/2.477 s, Products 2.588/3.314 s, User exposure 4.302/4.989 s, Computers 6.471/7.108 s, and Sources 1.232/1.638 s. The browser method is documented in `docs/reference/authenticated-browser-measurement.md`; credentials were process-only and no production action occurred.

## Change and measurement plan

Release 0.128.10 is deployed and healthy. It narrows User exposure's HTML page from 100 to 25 ranked users and improved the authenticated browser first response from 4.302 s to 2.961 s, with transfer from 927 KB to 563 KB. Read-only application-role tracing then isolated its single materialized SQL statement as the remaining boundary. Release 0.128.11 keeps the same key-level deduplication, ranking, totals, filters, pagination, and CSV export but joins hostname/client labels only after the selected page is known. Computers is still 6.351 s browser first response: current subquery timing points to full-inventory Python assembly after bounded source evidence, with Hudu lifecycle detail the largest known SQL component (about 1.35 s). Retain the browser pass as the final acceptance check.

## Validation

The 0.128.10 focused User exposure boundary test passes, as do `manage.py check`, `compileall`, registry validation, release governance validation, and diff whitespace checks. Governance reports the known stale `docs/current-state.md` status-date warning. Python 3.14 reports existing Django deprecation warnings; file-wide Ruff has existing unrelated legacy findings. No schema or data changes are included.

## Checkpoint and next action

User approved commits and pushes needed to complete the goal; `origin` automatically deploys, with no separate redeploy. Release `fa0500c` is pushed to `origin` and `a-m-rose`; preserve all unrelated working-tree changes and `.work` probes. Next, release the scoped 0.128.11 SQL-width correction, then repeat authenticated browser timing for User exposure before selecting any Computer change. PLAN-001 stays active until the archived success criteria are verified.
