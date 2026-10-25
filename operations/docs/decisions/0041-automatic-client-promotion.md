# 0041 — Automatic client promotion

Status: Accepted (2026-10-23)
Date: 2026-10-23

## Context

A source group whose name matches no client becomes a client candidate and
waits in "New / discovered clients" until an operator accepts it, maps it to
an existing client or excludes it. Until then nothing from that group is
filed under any client, so operations on it are delayed.

Track C (migration 0123) holds that no source is an authority for clients:
the retired `bootstrap_clients_from_ninja` minted a client for every Ninja
org. That stays true. What changes is that the resolver may act on strong
evidence without waiting, as a recorded, changeable suggestion that an
operator verifies later.

ADR-0040 is the precondition: every automatic mapping is a recorded decision
and every mapped group can be moved, one or many at once.

Production 2026-10-23: 11 open candidates, each reported by one source, none
by Ninja. Their records have no Computers (Computers are created per client),
so the evidence that exists is computer names: "MDA" (R-U-ON) reports 3
names, all owned by Prompt; "SF" and "Regency" match one name each.

## Options considered

- Keep every candidate for an operator (status quo).
- Promote on strong evidence, recorded and changeable, verified later.
- Treat Ninja as the client authority again (rejected by Track C).

## Decision

The resolver promotes a candidate in two cases. Both require the candidate
to have been seen in at least two resolver runs, and neither applies to a
name an operator excluded.

1. **Map to an existing client** when the candidate's live source groups
   report at least two computer names that exactly one client owns (the
   evidence the candidate page shows), no reported name points to another
   client, and none of the candidate's sources already keeps that client as
   a separate group (`_first_unseparated`). It does what Map does (alias and
   attachment) and records an `automatic`/`resolver` decision on each link
   with the evidence as the reason.
2. **Create a provisional client** when at least two sources, one of them
   Ninja, report the same name; no client or alias has that name; and any
   client their computer names point to is kept separate by those sources
   (a spinoff such as NYCD Management from City Painting). The client is
   created as Accept creates it, marked provisional, with
   `automatic`/`resolver` decisions on its links.

Every promotion is listed on Inventory › Clients under "Promoted
automatically — verify", with select one/several/all and Verify, Move
source groups (ADR-0040) or, for a provisional client with no groups left,
Retire. A provisional client is otherwise a normal client: its computers and
findings are filed under it from the first run.

The thresholds (seen twice, two names, two sources) and an on/off switch per
case live in admin-managed settings (`evaluator_config` row
`client_promotion`, edited on Inventory › Clients), not code. The required
source for creation is a setting too (seeded "Ninja"); with none set,
nothing is created. Both cases ship switched on (user decision 2026-10-23).

## Rationale

The evidence is the same an operator uses on the candidate page; acting on
it automatically removes the wait without removing the decision, because the
decision stays visible and changeable. Requiring two names and two runs
keeps single-name coincidences and half-finished renames out.

## Consequences

- Schema: a provisional marker on clients (when and why it was created
  automatically, and when it was verified) and the settings rows.
- The resolver reads computer-name evidence; the views' helpers move to a
  shared module so the candidate page and the resolver use one rule.
- On today's data: "MDA" maps to Prompt; nothing is created.
- Operators review promotions after the fact instead of before.

## Supersedes or superseded by

Builds on ADR-0040. Keeps Track C (migration 0123): no source is a client
authority.
