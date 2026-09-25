# 0025 — Client/source mapping authority

Status: Proposed

## Decision

`operations.v_client_source_link` remains the source-identity-to-canonical-client
relationship. A new tenant-scoped, audited mapping-decision record attaches
operator intent to that relationship; it never stores or overwrites a source
name. Its states are `explicit`, `automatic`, `ignored`, and `review`.

The effective mapping read model combines the source link, current source-name
evidence, and the latest valid decision. It is the sole evaluator and UI
authority. Legacy alias rows are imported as explicit decisions with their
provenance; they are not a second live authority.

## Finding rules

- Explicit or ignored mappings: no active mismatch finding.
- Automatic mappings whose peer source names differ: low-severity review.
- Missing mapping: actionable unmapped-source-group finding.
- Multiple possible clients or incompatible decisions: actionable ambiguity.
- Withdrawn evidence is retained as history and cannot create a new active
  mismatch by itself.

## Consequences

The admin mapping surface writes decisions only. Source observations remain
evidence, canonical clients remain durable, and findings are derived from the
effective mapping view. No replacement `client_links` table is introduced.
