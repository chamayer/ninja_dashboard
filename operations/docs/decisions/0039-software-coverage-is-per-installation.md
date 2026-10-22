# 0039 — Software coverage is per installation

Status: Proposed
Date: 2026-10-22

## Context

Decisions are already resolved per installation (migration 113: title before
publisher; device before client before global), and per-computer exposure
applies them per installation. The software reconcile, however, rolled them up
to the title: one installation with no decision opened a title-wide
undecided-software prompt, and the prompt reported the title's whole fleet.

Production, 2026-10-22: "Microsoft Corporation" is approved, yet 23 titles
under it stayed open. Each had thousands of covered installations and 1-11
whose publisher was blank, Russian-localised ("Корпорация Майкрософт"), an
unresolved Windows resource string, or the product name. Microsoft Store read
"undecided on 3,917 machines" when one installation was uncovered. 126 titles
are partly decided with such a remainder.

## Options considered

- Inherit a publisher approval for installations of a covered title whose own
  publisher is blank or different.
- Map publisher variants to one publisher (aliases).
- Keep coverage strict per installation and make prompts describe only the
  uncovered installations.

## Decision

An installation is covered when its own effective decision approves it. A
publisher decision matches the installation's own publisher string; nothing
is inherited. The rule lives once, in `shared/software_coverage.py`, used by
the reconcile and by Operations.

An undecided-software prompt (`whitelist_suggestion`, `rare_recent`) exists
while any installation is uncovered and describes only those installations:
their computer and client counts decide rare versus non-approved, their most
common publisher is the prompt's `publisher` (so grouping, "approve
publisher", and immediate closing act on what they actually report), and their
first sighting dates it. A rare title with another concern is not answered by
a publisher approval (design D9); its prompt covers every installation without
a title decision. Fleet-wide counts stay on the prompt as context and as
supporting evidence (`prevalent`, `established_publisher`).

Every reader shows the uncovered counts: Issues (context line, sort), Software
review (rows, grouping, rare device targets, rare-limit preview), finding
descriptions, and the home dashboard, which counts the prompts themselves.
Prompts written before this change fall back to their fleet counts until the
next reconcile rewrites them.

## Rationale

Inheriting approval would let an installation with a blank or forged
publisher ride on a trusted title; the publisher string is set by the
installer, which is why approval is strict. Aliases are a deliberate,
operator-managed extension (backlogged), not a fix for the roll-up. Describing
the uncovered installations is correct under the existing rule and tells the
operator exactly what to decide.

## Consequences

- Partly covered titles become small prompts about their remaining computers,
  often rare, with those computers as targets.
- A prompt's type can change between rare and non-approved as coverage
  changes; the previous one resolves with a recorded reason.
- Overview-level title status (approved, investigating, rejected, awaiting)
  must use the same rule; computing it live measured 4.5 s on production.

## Supersedes or superseded by

Refines the title roll-up of the software reconcile; migration 113 stands.
