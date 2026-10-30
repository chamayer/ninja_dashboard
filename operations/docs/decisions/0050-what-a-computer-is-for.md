# 0050 — What a Computer is for, and where findings are evaluated

Status: Proposed 2026-10-30. Amends ADR-0005 ("findings are attached to Device") and
extends ADR-0049. Implementation needs separate approval per step.

## Context

No source has a "Computer". Ninja has devices, SentinelOne agents, ScreenConnect
sessions, LogMeIn hosts, R-U-ON monitors and Hudu assets; each knows only its own
records. The Computer (`devices`, entity class `device`) is the platform's own
claim that several source records describe one physical or virtual machine.

It was introduced for one question no source can answer: agent compliance (0.16.0)
— does each machine of a client have every required platform, and is each current?
Answering "Ninja present, SentinelOne missing" requires deciding that two records
from different sources are one machine. ADR-0002 and ADR-0005 then made it a durable
anchor: a reimage or agent reinstall is not a new machine, source silence is not
deletion, and operator context (labels, exemptions, lifecycle) must outlive any
single record.

From there every evaluator was written against the Computer, including findings one
source record fully answers (software on a Ninja device, its patch state, its OS
servicing). ADR-0005 justified this as the "operator triage surface". The costs are
recorded: split and merge errors (ADR-0032, ADR-0043), non-computer records shown as
"unlinked computers" (ADR-0044), and findings that cannot exist until identity is
resolved (ADR-0049). Measured 2026-10-30: about 324 present Computer-role records
were unattached; `software_installations_current.device_id` is NOT NULL, so software
of an unattached record cannot even be stored.

## Decision

### 1. What a Computer is

A Computer is a **learned grouping of source records believed to describe one
machine**, plus the durable operator context that belongs to the machine. It is
evidence-based, may be wrong, and is corrected through `set_source_association`
(the one association authority, ADR-0049) — never by moving findings.

### 2. Where a fact is evaluated is decided by the fact, not by the domain

| Fact | Evaluate on | Examples |
| --- | --- | --- |
| Asserted by **one** source record | That **source record** | Its software list, patch state, OS servicing, agent-specific status and health, invalid identifiers, duplicates within its source |
| Asserted by **several** sources, or **combining** sources | The **Computer**, from the effective value the shared projector selects across its records (ADR-0010/0012 authority policies) | Software reported by two inventory sources, a serial both report differently |
| Inherently **about the machine** | The **Computer** | Required-agent coverage, fully offline (no source has contact), missing from a source it should be in, one machine or two, machine counts, machine client ownership, lifecycle and retirement, operator labels/exemptions |

Which sources assert which facts is registry data (attribute definitions, mappings
and authority policies), so adding a source is configuration. When a second source
starts asserting a fact (for example a second software inventory), that fact moves
from row 1 to row 2 by configuration: records keep contributing claims, and the
Computer's effective value becomes the evaluated input.

### 3. Unattached records are never blocked

While a record is unattached, row-1 facts and row-2 facts it asserts are evaluated
on the record's own claims. Findings appear from intake. Row-3 facts wait for a
Computer by definition; the identity review (`source_record_identity_review`) is what
brings the record to one.

### 4. One owner per correction, with hand-over on attachment change

One correction has exactly one open finding. When a record attaches, a record-level
finding whose correction is now answered at the Computer hands over: the Computer
producer takes it, the record finding resolves with reason `handed_over_to_computer`.
On detach or move, the reverse. Hand-over runs in the association transaction's
queued work, not "when an evaluator next runs".

### 5. Findings point at their subject; the machine view is a join

A finding stores one subject (`subject_type`/`subject_id`) and its participants
(`condition_participants`). Native record findings record the source record as the
affected participant and the attached Computer, if any, as context (implemented
in 0.137.2). The Computer page shows Computer-subject findings plus record and case
findings **joined through link history** for the period the record was on that
machine — never only the current link, so history stays on the machine it happened
on. Findings are never retargeted when a record moves.

### 6. When a Computer is required

Create, keep and correct Computers for row-3 questions and durable machine context.
Do not require one to evaluate, store or show row-1 facts. A record that is not a
machine (ADR-0044 classes) never needs a Computer.

## Consequences and migration

- Each domain moves separately, with its own ownership matrix (ADR-0049 §9.1) and
  approval. Order by risk: software (unwanted, vulnerable, unauthorized tools),
  agent-specific status, patching, Windows servicing.
- Storage that requires a Computer for a row-1 fact (`software_installations_current`,
  patch state) gains a source-record key; the Computer key becomes a projection.
- Strict identity matching (design §5) becomes affordable: a held record delays only
  row-3 questions.
- New: Computer-page aggregation through link history; counts deduplicated by owner.

## How to deal with a Computer (rules for future work)

1. Before writing an evaluator, place its fact in the table above. If it is row 1,
   evaluate the source record. If unsure, it is row 1 until a second source asserts it.
2. Never write `device_id` or a link directly; use `set_source_association`.
3. Never make a finding wait for attachment unless its fact is row 3.
4. Never move or retarget findings to follow a record; join through links.
5. A new source that overlaps an existing fact is a registry change (authority
   policy), not a new evaluator branch.

## Enforcement

Triggers already reject direct `device_id`/link writes (0374). The rest is enforced
by review against this record until each domain's migration adds its constraint
(source-record keys on row-1 stores) and its tests.
