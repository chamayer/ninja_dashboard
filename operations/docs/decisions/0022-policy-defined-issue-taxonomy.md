# ADR-0022: Policy-defined Issues taxonomy

## Status

Accepted

## Decision

The active condition policy is the authority for the operator-facing Issues
taxonomy. It defines ordered categories, grouped types, and individual issue
labels. The approved registry contains five categories, 34 types, and all 53
condition keys exactly once.

The condition keys remain stable technical identifiers for policy, audit,
URLs, evidence, and diagnostics. Legacy database category names and the
human-label formatter are not taxonomy authorities. They remain available only
for storage compatibility and unrelated surfaces.

The revised registry is seeded as a new immutable, inactive policy version
(`conditions-taxonomy-3`). It separates platform withdrawal from missing
computer evidence, identity conflicts from possible duplicate Computers,
platform-entry duplication, identifier/detail/classification problems, client
organization matching from Computer identity matching, and current reporting
from historical offline status, including a separate historical identity
collision workflow. Hudu archive candidates, incorrect Hudu links,
and unconnected Hudu references are separate Types.
Review and activation use the existing database-governed Operations admin
workflow. The Issues projection never substitutes packaged taxonomy data for
an active policy that lacks the registry; the rejected prior version remains
inactive.

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
