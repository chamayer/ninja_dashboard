# 0016 — Windows servicing lifecycle is corpus-derived

Status: Accepted
Date: 2026-08-11

## Context

Ninja reports Windows `buildNumber` and `releaseId`, while endoflife.date
publishes Windows client and server cycles with build-bearing `latest` versions
and active, base-security, and extended-security support dates. The platform
previously retained the Ninja fields only in source storage and therefore
could not expose the servicing risk of an installed Windows build.

A hand-maintained build-to-cycle map would duplicate the external corpus,
require continual operator upkeep, and turn a precise source join into another
queue. Shared client builds still require edition disambiguation, and ESU
availability does not prove that a device has an ESU entitlement.

## Options considered

- Maintain a build-to-cycle mapping and candidate queue in Operations.
- Hardcode individual Windows build mappings in the projector.
- Derive build candidates from the refreshed corpus and retain only generic,
  version-controlled product and edition rules as data.

## Decision

The servicing projector derives every build candidate from
`intel.eol_releases.latest_version`. Global rules in
`intel.windows_servicing_rules` select the Windows client/server product and
disambiguate shared edition tracks. The rules contain no builds or dates, are
seeded by migration, and are not writable by application or ingest roles.

The projector is the sole writer of
`operations.device_windows_servicing_current`. It records supported,
security-support-only, approaching-EOL, EOL-with-ESU-available, EOL, or unknown
state. A tie, absent build, or absent corpus candidate is unknown rather than a
guess. Device findings are synchronized from that state and resolve when the
state changes.

ESU availability is recorded separately from entitlement. Entitlement remains
unknown unless a future authoritative source supplies it.

## Rationale

This makes normal operation self-maintaining: Ninja refreshes device evidence,
endoflife.date refreshes builds and dates, and either change reruns the same
projector. The small stable rule set remains visible data under ADR-0012 rather
than an invisible domain mapping in code, without creating an operator task.

## Consequences

- Corpus and device refreshes automatically update servicing state and
  findings; no mapping queue or routine operator maintenance exists.
- New or renamed upstream edition conventions fail visibly as unknown until a
  reviewed migration updates the generic rule data.
- Base security EOL remains a high-severity condition even when ESU is
  available, because entitlement is not inferred.
- The Ninja device observation material contract advances to version 4 so
  build and release changes are retained as evidence boundaries.

## Supersedes or superseded by

Applies ADR-0012's evidence/projector and data-owned mapping rules to Windows
servicing lifecycle. It does not supersede another decision.
