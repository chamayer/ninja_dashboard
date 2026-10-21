# PLAN-001 — Dashboard navigation performance

## Goal

Make ordinary Dashboard navigation responsive from measured causes, and close PLAN-001 only with current deployed evidence.

## Scope

Measured server/rendering causes on Dashboard navigation and its landing pages. Preserve tenant/RLS, card meanings, URLs, and established data authorities. No cache, duplicate projection, speculative index, migration, or production-data action.

## Status and evidence

Active. The fresh authenticated tenant-1 handler baseline was Dashboard 3.154 s, Computers 12.871 s, Sources 4.474 s, Cleanup 5.368 s, User exposure 5.877 s, and Software Overview/Products over the 20 s request limit. Releases through 0.128.9 are deployed and healthy: Dashboard warmed to 1.308–1.568 s, Sources to 0.935–0.988 s, Software Overview to 1.042–1.068 s, and Products to 2.037–2.082 s. Authenticated headless-browser navigation on the deployed stack independently measured response/duration: Dashboard 1.995/2.399 s, Findings 1.887/2.503 s, Software Overview 2.013/2.477 s, Products 2.588/3.314 s, User exposure 4.302/4.989 s, Computers 6.471/7.108 s, and Sources 1.232/1.638 s. The browser method is documented in `docs/reference/authenticated-browser-measurement.md`; credentials were process-only and no production action occurred.

## Change and measurement plan

Release 0.128.10 is deployed and healthy. It narrows User exposure's HTML page from 100 to 25 ranked users and improved authenticated browser first response from 4.302 s to 2.961 s, with transfer from 927 KB to 563 KB. The 0.128.11 lightweight-key materialization experiment regressed that same route to 4.637 s/5.188 s response/duration; releases 0.128.12 and 0.128.13 repaired and then restored the proven 0.128.10 query shape. Computers remains 6.351 s browser first response: pagination already bounds rendered source timestamp detail, but full-inventory Python assembly and Hudu lifecycle evidence (about 1.35 s SQL) still occur before pagination. Retain the browser pass as the final acceptance check.

On 2026-10-21, a fresh read-only deployed handler trace (template rendering excluded) measured 7.525 s of Computers assembly: Hudu evidence 2.054 s, coverage requirements 0.990 s, page-only source timestamps 0.475 s, compact source-observation state 0.463 s, and about 3.3 s of Python full-fleet assembly. The measured correction is to retain Hudu presence/lifecycle/link-filter facts for the fleet summaries and filters, but fetch Hudu links and record presentation only for the selected HTML page. CSV deliberately retains complete detail. This keeps `v_hudu_computer_inventory_evidence_current` as the evidence authority and does not add storage, a cache, a projection, or a schema change.

## Validation

The 0.128.13 rollback focused User exposure test, `manage.py check`, diff whitespace, and release governance validation pass. The scoped Computers change passes `pytest apps/core/tests/test_coverage.py -q` (14 passed), `manage.py check`, `compileall`, plan-registry validation, and diff whitespace. File-wide Ruff continues to report pre-existing legacy findings; no schema or data changes are included.

## Checkpoint and next action

User approved commits and pushes needed to complete the goal; `origin` automatically deploys, with no separate redeploy. Release `520a967` is deployed and mirrored to `a-m-rose`; preserve all unrelated working-tree changes and `.work` probes. Release 0.128.14 contains the local measured bounded Hudu-presentation read; after its approved release, repeat deployed handler and authenticated-browser timing for Computers. PLAN-001 stays active until the archived success criteria are verified.
