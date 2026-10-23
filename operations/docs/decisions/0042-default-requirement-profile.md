# 0042 — Default requirement profile is inherited, not assigned

Status: Accepted
Date: 2026-10-23

## Context

Requirement profiles replaced legacy tenant-global coverage rows. The first
transition retained those rows as the fallback for clients with no profile,
while the profile marked default was assigned during onboarding. That created
two baseline authorities: Global for existing unassigned clients and Standard
for newly accepted ones.

## Decision

- The one tenant-default requirement profile is the inherited baseline. The
  intended default is Standard, but the selected data row is authoritative.
- A null `clients.requirement_profile_id` means the client inherits that
  default. It is not an incomplete configuration and is not an explicit
  assignment.
- A non-null profile is an explicit override. Clearing it returns the client
  to the tenant default.
- Client onboarding leaves the profile null when the operator chooses the
  default. It writes a profile only for an explicit override.
- Legacy client-less `coverage_requirements` rows are retained for historical
  safety but are no longer read by requirement evaluation, requirement display,
  or sanctioned-product derivation. They are not editable in the profile UI.
- A tenant default cannot be removed or deleted until another default is
  selected.

## Consequences

- Changing the tenant-default profile changes the inherited baseline for every
  client without an override.
- The Requirements page distinguishes clients using the default from clients
  explicitly assigned to an override, and can bulk-add default clients to an
  override.
- Legacy Global rows can be separately reviewed and retired later; this
  decision does not delete or migrate production data.
