# 0050 — What a Computer is for, and where findings are evaluated

Status: Accepted by the user 2026-10-30. Amends ADR-0005 ("findings are attached
to Device") and extends ADR-0049. Acceptance settles the design direction; each
implementation and production step follows the applicable plan and release gates.

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

From there evaluators came to use the Computer even for findings one source record
can answer (software on a Ninja device, its patch state, its OS servicing). ADR-0005
justified this as the "operator triage surface". The costs are
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
(the one association authority, ADR-0049). Association does not copy every source
fact onto the Computer, make it authoritative for those facts, or move their
findings.

### 2. Where a fact is evaluated is decided by the fact, not by the domain

| Fact | Evaluate on | Examples |
| --- | --- | --- |
| Asserted by **one** source record | That **source record** | Its software list, patch state, OS servicing, agent-specific status and health, invalid identifiers, duplicates within its source |
| Requires a **combined** view of several sources | The **Computer**, using reconciled evidence and applicable shared-projector authority policies (ADR-0010/0012) | Conflicting serial reports, a machine-level software conclusion |
| Inherently **about the machine** | The **Computer** | Required-agent coverage, fully offline (no source has contact), missing from a source it should be in, one machine or two, machine counts, machine client ownership, lifecycle and retirement, operator labels/exemptions |

Records retain their individual claims when sources overlap. Each rule defines
whether it evaluates an individual report or needs a reconciled machine-level
result. Only inputs that the rule needs are combined, under the applicable
authority policy; other source facts remain on their records. Adding a source can
also require mapping or reconciliation work. A second source does not
automatically change the subject of every existing rule.

### 3. Findings do not wait for attachment

While a record is unattached, applicable record-level rules evaluate its own claims
without waiting for identity. Findings appear when their required evidence and
policy context are available; missing context yields an explicit unknown. Machine
coverage and other row-3 questions require a sufficiently supported Computer.

### 4. Preserve finding ownership across attachment changes

One correction should have one actionable owner. When a record attaches, a
record-level finding whose correction is now answered at the Computer hands over
only after its successor exists. On detach or move, reassess both the old and new
owners. Each domain defines which findings represent the same correction and makes
handover durable and retryable; a failed transition must not silently lose the
issue. A temporary overlap during a retry is preferable to a missing finding.

### 5. The Computer page is the operator's combined machine view

The Computer page presents the attached source records together, with each
record's source identity and provenance visible. It may show a comparison of
source-reported claims side by side. A reconciled machine-level value is shown
only where a shared projector or explicit rule has selected it; disagreement and
missing evidence stay visible as such. Merely attaching a record does not promote
all of its values into Computer state.

The page also lists Computer-subject findings and findings on records associated
with that Computer through association history. This is a navigation and review
view, not inherited Computer state. Record findings remain owned by their records;
only a rule that needs a reconciled machine conclusion publishes to the Computer.
Findings are never retargeted when a record moves. Historical association evidence
and finding episode times must support historical display; until then, the page
must not imply an association it cannot establish.

When the finding data identifies its contributing source or sources, show a
compact `Source: …` line in its existing details (for example, `Source: Ninja`).
For a combined conclusion, list the contributing sources. Omit the line when
provenance is unavailable; do not infer it from the Computer association. Do not
add a source column or badge to every issue row as part of this decision.

A finding stores one subject (`subject_type`/`subject_id`) and may have participants
(`condition_participants`). Native record findings record the source record as the
affected participant and the attached Computer, if any, as context (implemented
in 0.137.2).

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
3. Never make a record-level finding wait for attachment; a combined or
   machine-level conclusion needs the evidence and identity it actually uses.
4. Never move or retarget findings to follow a record; join through links.
5. When a new source overlaps an existing fact, retain provenance and review the
   rule's reconciliation and authority policy.

## Enforcement

Migration 0374 enforces association writes through the protected procedure. Migration
0375 writes assessments and participants for native source-record findings. Neither
enforces per-domain evaluation scope, single-owner handover or Computer-page joins.
Those rules become enforced only as each domain implements them with storage,
projector, permission and test changes. Review against this ADR is a design check,
not runtime enforcement.
