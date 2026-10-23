# 0040 — Client source mappings are recorded and movable

Status: Accepted (1, 3, 5, 6 implemented; 2 to an existing client only; 4 on the client page)
Date: 2026-10-23

## Context

A source group (a Ninja org, a SentinelOne site, ...) reaches a client in two
ways: the resolver attaches it when its normalized name matches one client or
an enabled alias (`client_resolver._attach_group`, reason
`resolver.name_match`), or an operator maps a candidate
(`views.client_candidate_map`, which also saves a manual alias). Both set
`client_id` on the group's org and device observations; ingest keeps that
value (`COALESCE` in `observations.py`), and
`sync_entity_source_links_from_observations()` derives the client source link
from it.

An audit of automatic identity decisions (2026-10-23) found two gaps on the
client side:

1. **Automatic attachments leave no decision.** The resolver's reason is
   passed in and discarded. `client_source_mapping_decisions` already allows
   `state = 'automatic'` and `provenance = 'resolver'`, but nothing writes
   them, so an automatic mapping shows as `review` with no record of why.
2. **An attached group cannot be moved.** Both attach paths only fill
   observations whose `client_id IS NULL`. The decide action can confirm
   (`explicit`) or `ignored` a mapping, but no action moves a group to another
   client. A wrong automatic mapping can only be "fixed" by ignoring it, which
   leaves its computers and findings on the wrong client.

Every downstream fact (computers, alerts, software, requirements) follows the
client mapping, and the planned automatic promotion of new clients
(ADR-0041, to follow) adds more automatic mappings. Operators must be able to
see why each mapping exists and change it.

## Options considered

- Keep automatic attachment as is and rely on operators confirming each one.
- Record automatic attachments as decisions, and add a move action that
  re-points a group to another client (or a new client), one or many at once.
- Stop attaching automatically; every group waits for an operator.

## Decision

1. **Every automatic attachment is a recorded decision.** After the link sync,
   the resolver writes `state = 'automatic'`, `provenance = 'resolver'` for
   each client source link with no decision, with the reason (name matches the
   client, or the alias saved when candidate X was mapped). This needs a
   resolver-only decision function, because `decide_client_source_mapping_v1`
   always writes `provenance = 'operator'` and is granted only to the app.
2. **A mapped group can be moved.** One database function moves a source
   group to another client or to a newly created client:
   - re-points the group's org and device observations to the target client;
   - supersedes the link's current decision with an operator decision naming
     the previous client and the reason. The link row keeps its id when its
     client changes, so a decision made for the old client must never carry
     over to the new one;
   - repoints or disables a manual alias that caused the attachment, so the
     next run does not reproduce it;
   - records the move in the change history.
3. **Computers follow their records; their findings follow the Computer.** A
   Computer whose current records all belong to moved groups moves with them.
   A Computer left with records on two clients is not moved; it raises a
   finding for an operator to decide. A finding about a Computer belongs to
   the Computer, and the client inherits it: the `client_id` stored on device
   findings, software installations and requirement state is a copy of the
   Computer's client, updated in the same transaction as the move, never an
   independent relationship.
4. **One place, one or many.** The client page's source references and the
   Issues rows for client mapping offer confirm, move, and ignore for one row,
   the selected rows, or all rows, each with its evidence beside the checkbox.
5. **One finding, "Computer under the wrong client?"**
   (`computer_client_conflict`, implemented with migration 0340). The question
   form is deliberate: some cases are intended (a spinoff, staff on site). It replaces
   `cross_client_serial` and the retired `cross_client_conflict`, which asked
   the same question from different evidence. One finding per Computer:
   - raised by an active record from another client's source group, or by a
     usable serial a live Computer of another client reports;
   - the same name in another client is shown beside it but never raises it
     (on its own it was a coincidence every time);
   - actions on one, several or all selected issues: **Move to the other
     client** (`operations.move_computer_to_client`, only when the evidence
     names one other client), **Keep as is** (intended, or different machines;
     recorded per evidence key in decision dimension
     `client_conflict_accepted`, on both Computers for a shared serial; new
     evidence raises it again), **Source is wrong** (acknowledged, clears when
     the source is corrected);
   - a group move (decision 2) produces this finding for Computers left with
     records on two clients.

   Production 2026-10-23: 23 Computers hold records from another client;
   before this finding only those that also shared a serial were reported.
6. **One name-difference finding per client** (`client_name_conflict`).
   It was one per source link, raised for every link of a client whose
   sources disagreed, including links that agreed with the client (Prompt:
   four findings for one "MDA" group; 177 across about 40 clients). Now one
   finding per client with a row per source group: a name equal to the
   client's under the resolver's comparison (case, spaces, dashes, dots)
   *matches*; a confirmed or ignored mapping is settled; any other row
   *differs*. Critical while any row differs, because everything from that
   group is filed under this client (amends ADR-0025's "low"). The rows are
   decided together on the client page (decision 4).

## Rationale

The decision table and its states already exist; recording automatic
attachments uses them as designed. A move is the remedy operators need for a
wrong mapping, and it is a prerequisite for any further automation, because
every automatic decision must be changeable.

## Consequences

- New migration: the resolver decision function and the move function, with
  grants to `ninja_ingest` and `operations_app` respectively.
- A Computer can change client for the first time. Device findings, software
  installations and requirement state carry `client_id` and must move with it
  or be recomputed; this is the costliest part and needs its own design review
  before implementation.
- An emptied client (all groups moved away) is not deleted; it is flagged for
  an operator to retire.
- Existing links get an `automatic`/`resolver` decision on the first run.

## Supersedes or superseded by

Builds on ADR-0025 (client/source mapping authority), which defined the
`automatic` state this record finally writes, and ADR-0038 (candidates follow
renames). ADR-0041 (automatic client promotion) will depend on this.
