# ADR-0022: Policy-defined Issues taxonomy

## Status

Accepted

## Decision

The active condition policy is the authority for the operator-facing Issues
taxonomy. It defines ordered categories, grouped types, and individual issue
labels. The approved registry contains six categories, 26 types, and all 53
condition keys exactly once.

The condition keys remain stable technical identifiers for policy, audit,
URLs, evidence, and diagnostics. Legacy database category names and the
human-label formatter are not taxonomy authorities. They remain available only
for storage compatibility and unrelated surfaces.

The new registry is seeded as an immutable, inactive policy version. Review
and activation use the existing database-governed Operations admin workflow.
Until activation, the Issues projection can read the packaged registry while
retaining labels from the active policy, so deployment does not make the queue
unavailable during the review window.

## Consequences

- Category and type filters, cards, group headings, rows, CSV exports, and
  selected-category headings share one resolver.
- A condition missing from the registry fails validation rather than silently
  appearing under a technical-key fallback.
- Existing bookmarks using legacy category or grouped-type values continue to
  work and are normalized to canonical values.
- Activating the policy invalidates prior condition response authority through
  the existing policy activation function; producers must write fresh
  assessments under the new version.
