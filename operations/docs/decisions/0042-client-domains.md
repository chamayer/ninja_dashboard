# 0042 — Client domains: learned from computers, editable by operators

Status: Accepted (2026-10-23)
Date: 2026-10-23

## Context

Operators want a client's domain(s) on the client (user, 2026-10-22). Computers
already report one: Ninja `system.domain` becomes observation field `domain`
(e.g. `starfire.local`), and computer names carry it (`DC.starfire.local`).
A domain helps tell generic computer names apart (two clients each with a
`DC`), check a new source group against its likely client (ADR-0041), and
show who a client is.

User decision 2026-10-23: learned from computers **and** editable.

ADR-0012 governs: a domain learned this way is *derived by us* (origin), an
attribute of the client entity (structure), and operator edits are decisions,
not overwrites. The generic attribute system already has set-valued
definitions (`attribute_definitions`), operator decisions
(`entity_attribute_decision_current`) and an effective value
(`entity_attribute_effective_current`). Its claims today come from source
fields on the entity's own records; a client's domains come from its
computers' records.

## Options considered

- A text column on `clients` written by the resolver (rejected by ADR-0012:
  no evidence producer writes state).
- A set attribute `client.domains` in the generic attribute system, with
  derived claims produced from the client's computers and operator add/remove
  decisions.
- Typed only by operators (rejected: the user chose learned and editable).

## Decision

1. Register attribute `domains` on entity class `client`: text, set,
   sensitivity internal, merge `all_eligible_union`.
2. **Learned:** a derived producer claims a domain for a client when at least
   `min_computers` of its live Computers report it (default 2) and it is not
   on the ignored list. The ignored list (`WORKGROUP`, empty, `local`,
   `localdomain`, ...) and the threshold are admin-managed data
   (`evaluator_config` row `client_domains`), not code. Claims are withdrawn
   when the evidence ends, with the reason.
3. **Editable:** an operator adds or removes a domain on the client page; each
   edit is an attribute decision with a reason and wins over the learned
   claims. Removing a learned domain keeps it out until the operator restores
   it.
4. **Shown** on the client page and Inventory › Clients, each domain marked
   learned (with its computer count) or added by an operator.
5. **Used later**, each by its own change: ADR-0041 evidence (a candidate's
   computers in a client's domain), and name matching (follow-up 9).

## Open point to settle before building

Whether the claim tables accept a derived producer as it stands (a claim
keyed to a producer and the client, not to one source record), or need a
small extension. This is checked against the schema first; the extension, if
any, is part of this record's migration.

## Consequences

- A migration registers the definition and the settings row, plus any claim
  extension.
- A new projector step in the resolver cycle; no source code changes.
- Domains become visible per client and available as evidence.

## Supersedes or superseded by

Applies ADR-0012. Feeds ADR-0041.
