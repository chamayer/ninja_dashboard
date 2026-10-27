# PLAN-021 candidate review — 2026-10-27

## Result

The read-only production query in [queries.sql](queries.sql) ran under the
documented `operations_migrate` preflight: PostgreSQL 16, transaction read-only,
tenant context set, and expected search path. It returned aggregate rows only;
no candidate IDs, source identifiers, customer values, or payloads were
retained.

At capture time it found 77 non-attached candidates with matching stable source
links. All 77 were `observed_only`, had active current observations, and had
matching material hashes. Seventy-six observations had a later `last_seen_at`
than the candidate's `last_observed_at`. Every source link's entity class
differed from the candidate's proposed entity class. The aggregate count is
three higher than the prior 74-candidate measurement. Because the read retained
no candidate identifiers, continuity between the two populations was not
established.

The class mismatch is material: the projector assigns the linked entity to
`resolved_entity_id`, while the candidate's composite foreign key requires the
resolved entity class to equal `proposed_entity_class_id`. The current
attachment update therefore cannot safely resolve these rows. Their active
observation and matching material hash do not make the old class proposal
valid.

## Design revision

- Withdraw a non-attached `pending` or `observed_only` proposal, with an
  append-only candidate event and reason, when its stable source identity is
  already linked to an entity of a different class.
- Withdraw a non-attached `pending` or `observed_only` proposal when its
  matching current observation is explicitly inactive and no source link
  exists.
- Attach a linked candidate only when source-link and proposed entity classes
  match.
- Preserve `attached` candidates, rejected decisions, canonical entities,
  source links, and source-link history.
- Do not infer inactivity-based withdrawal when no matching current observation
  exists. A conflicting authoritative source link is sufficient evidence to
  withdraw the proposal even if no current observation remains. Do not mutate
  production state or run migrations as part of implementation review.

This design keeps withdrawal auditable and repeatable and prevents invalid
class resolution from aborting the projector. Production migration/data
application and deployment remain separate approvals.
