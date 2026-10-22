# 0038 — Client candidates follow source group renames

Status: Proposed
Date: 2026-10-22

## Context

Client candidates (`operations.client_candidates`) are keyed by normalized
name, while a source group is identified by its source and external id. When
a source renamed an unattached group ("Rise NYC" → "Rize NYC"), the resolver
created a candidate under the new name and left the old candidate Open with
the same group ids, so one group appeared as two unresolved clients.

An attached group renamed at its source is a different case: the attachment
is keyed by id and already follows the rename; `client_name_conflict` reports
any resulting disagreement between the client's sources (ADR-0025).

## Options considered

- Leave both candidates open and mark the stale one only at display time.
- Move the renamed group to the new name's candidate and close the emptied
  candidate with an operator-visible reason.
- Rename the canonical client from the source's new name.

## Decision

When the resolver records an unattached group under its current name, it
removes that group from any other **open** candidate. An open candidate left
with no groups is closed with status `renamed` ("Renamed at source"),
`resolved_by = 'resolver'`, and the new name in `resolved_reason`; it keeps
its last `source_refs` as history. Same source plus same external id is the
identity test; computer membership is not compared.

Candidates already accepted, mapped, or excluded by an operator are not
changed. The canonical client name is never changed by a source rename.

## Rationale

The group id, not its name, identifies the source group, and the current
observation's name is what the source uses now. Moving the reference is
evidence bookkeeping, not a client decision, so it fits ADR-0012 (a source
assertion is evidence, never state). Renaming clients from a source would let
one source write canonical state, which the retired forced-rename action
already rejected.

## Consequences

- The unattached list shows one candidate per live group; the closed name
  remains visible under "all" with its reason, and the change-history trigger
  on `client_candidates` records the status and `source_refs` changes.
- Migration 0337 adds the `renamed` choice; it emits no SQL because the column
  has no database constraint.
- An excluded name that is renamed at the source surfaces as a new open
  candidate; the operator decides it again.
- Display-time marking on Client mappings still covers candidates created
  before this change and decided candidates.

## Supersedes or superseded by

Refines ADR-0025 for unattached source groups.
