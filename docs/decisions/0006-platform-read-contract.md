# 0006 — Platform read contract

Status: Accepted (contract; platform-wide implementation is not claimed)
Date: 2026-11-12
Plan: PLAN-056

## Context

Existing domain contracts define correct populations, decisions and publications,
but do not provide one baseline for interactive reads across the platform.
Repeated derivation and broad detail expansion can make a small page expensive
even when its output is paginated. A shared business-rule helper alone does not
guarantee bounded database execution.

## Decision and scope

All interactive HTML, API and partial/polling reads follow the obligations below,
including navigation, badges, context processors and other shared request work.
Background producers must provide the maintenance needed by their read models.
Exports preserve the same selection semantics but may use a separate execution
budget. This baseline adds no service, store, framework or public interface.

Domain contracts reference this baseline and supply only their specific grain,
population, calculations, access rules, input owners and freshness requirements.
Their existing acceptance status is unchanged. Conflicts must be recorded and
resolved explicitly; this baseline does not weaken security or silently change
accepted business semantics.

## Common obligations

| ID | Obligation | Required implementation mechanism |
| --- | --- | --- |
| R1 | Preserve access boundaries throughout selection, derivation and rendering. | Existing tenant/client authorization, RLS and protected effective readers; caches/publications cannot widen access or bypass masking. |
| R2 | Counts, summaries, lists, links and exports agree on their declared population, filters and counting unit. Pagination changes the displayed slice only. | One domain-owned normalized selector, reused by SQL/ORM adapters; aggregate child evidence before joining where fan-out would change counts. Use one statement or a deliberate consistent snapshot when consistency requires it. |
| R3 | Limit detail work to the selected page or explicit detail scope. Apply filtering and deterministic ordering to the full selected population first. | Select IDs before costly enrichment; use indexed/bounded fetches. A final LIMIT or an ID join alone is insufficient if its execution plan still expands all details. |
| R4 | Resolve shared inputs once rather than repeating equivalent work per record or consumer. | Existing batch readers, distinct-key/group resolution and reusable compact query stages. Keep business rules in their domain owner; extract a helper only when multiple consumers need the same operation. |
| R5 | Expensive fleet-wide derivation must not run on the interactive request path. | Reuse domain-owned maintained results when needed. A direct aggregate is allowed when it meets the declared request budget at representative volume. Page-local caching does not make an expensive cache miss compliant. |
| R6 | Prepared results have a complete, recoverable maintenance lifecycle. | One publication owner and declared input-change/time-expiry hooks, initial population, atomic completion, concurrent-change protection, failure/retry and rebuild behavior. Reuse existing Jobs mechanisms; GETs cannot start competing rebuilds. |
| R7 | Readers distinguish completed empty results from missing, stale, pending and failed results. | Explicit availability/freshness metadata and domain-defined stale-result behavior. Enable a prepared reader only after initialization and maintenance are ready. A failed refresh retains the last completed generation; never fabricate successful zeros. Any live fallback must satisfy the same access and latency obligations. |
| R8 | Judge responsiveness over the complete interactive request, including shared work and the ordinary cache-miss path. | A domain-declared latency budget and existing or focused full-request evidence identifying volume, role, cache state and coverage limits. Query timing or HTTP 200 alone does not establish compliance. Existing stricter targets remain; no new numeric target is invented here. |
| R9 | Exports remain complete without transferring interactive enrichment into an unbounded request. | Reuse the normalized selection with bounded batches/streaming or existing background export facilities as needed. Never export only the visible page or silently truncate results. |

## Domain extensions and adoption

- [Operations ADR-0003](../../operations/docs/decisions/0003-four-layer-domain-storage.md)
  retains domain storage, ownership and effective-view responsibilities.
- [Operations ADR-0037](../../operations/docs/decisions/0037-shared-computer-read-contract.md)
  remains Proposed; its Computer population/evidence rules are domain-specific.
- [Operations ADR-0058](../../operations/docs/decisions/0058-software-summary-publication-contract.md)
  remains Accepted; its Software metrics, publication dependencies, freshness
  and performance target remain authoritative.
- Existing Issues selection and other domain readers remain their semantic
  authorities. No universal query helper replaces those authorities.

For each adopted reader, record its shared selector/entry point, applicable R1–R9
mechanisms, latency budget, existing evidence and remaining gaps in its domain
contract or active implementation record. Reference this document rather than
copying the obligations. A direct simple read need not acquire a publication
system; R6–R7's publication requirements apply when prepared results are used.

Home adoption, 2026-11-17: user authorized a task/navigation page while retaining
inexpensive counts. `views.home` reuses measured domain count readers and the
protected Software publication; shared Home context omits aggregate badges.
Expensive Issues ranking and Source Records history stay on domain pages.
No new publication or summary cache is introduced. See the
[implementation and remaining latency gate](../records/PLAN-056-home-start-implementation.md).

## Enforcement and consequences

This record defines the required mechanisms; it is not a runtime guard and does
not certify existing readers. Compliance requires the actual shared reader,
query boundary, privileges or publication lifecycle named above. Record missing
mechanisms as implementation gaps rather than calling prose enforcement.

Adopt through existing domain readers and consumers, correcting the demonstrated
gap at its shared owner. Do not create a parallel architecture, blanket cache,
new storage or an automatic query-rewriting framework to claim conformance.
This contract does not require a new test suite or new test files. Existing
evidence may be reused when it covers the implementation being assessed;
unverified behavior remains explicitly unverified. No tests or runtime changes
are authorized or required to create this document.

## Relationship to other decisions

Complements existing root and Operations architecture decisions. Domain rules
are extended by reference, not superseded or duplicated. Implementation,
migrations and deployments retain their existing authorization boundaries.
