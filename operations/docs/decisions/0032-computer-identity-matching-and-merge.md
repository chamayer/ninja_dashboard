# 0032 — Computer identity: matching, merge over split, and re-check

Status: Accepted 2026-10-16; not yet implemented (see `operations/.work/plan.md`)
Date: 2026-10-16

## Context

A source record (a Ninja agent, a SentinelOne agent, a LogMeIn host, an R-U-ON
monitor, a Hudu asset) must belong to exactly one Computer. Production was
measured read-only on 2026-10-15 and 2026-10-16 to find where that goes wrong.

Name matching is not the problem:

- Of 4,793 Computers whose agents report a usable serial, 11 held records with
  two different serials. After removing placeholder values and reading Ninja's
  BIOS serial (below), one remains: Goflow GF-12/GF-32, which was attached by
  a stale stored serial, not by name. A second Computer holds two machines
  that the serial test misses: Delfasco DEL-PC01 and DEL-LT1, two SentinelOne
  agents both reporting, one with a placeholder serial. Measured: 2 Computers
  have two same-source agents reporting different names within one day and no
  shared serial; both are these.
- All 761 recorded moves of a record between Computers happened because the
  old Computer was tombstoned: 423 by the one-time
  `reconcile_ninja_vmware_guest_duplicates` command on 2026-09-10 and 4 by
  operator merges. The records re-matched by name to the Computer that
  remained. None was shown to be wrong.

Splitting is the problem. 24 same-name groups hold agents on separate
Computers; 13 of them (36 Computers) are one machine whose sources sit on
different Computers. 26 Computers hold a record whose serial is stored on
another Computer. The 99 open "required platform not observed" findings on
same-name Computers include 40 caused by a serial-confirmed split and 7 by a
name-only split. The measured causes:

1. Promotion created a separate "kept separate" Computer for a second record
   of the same source without running any matcher, even when its serial
   matched (`ingest/identity/resolver.py` `_promote_entry_groups`).
2. Name matching requires exactly one Computer with the name and counts empty
   and shell Computers, so once a name has two Computers, every later
   name-only record becomes another Computer. On 2026-10-13, 5 of 22 new
   R-U-ON records were promoted this way; UTA ctxdesktop064 has 13 Computers.
3. An attached record is never matched again. When a serial arrives later, the
   record stays where it was.
4. Ninja re-enrollment creates agent records whose first reports carry a
   domain name and no serial or MAC address. Of 35 such records in history,
   the serial arrived within 6 hours for 22, at 8 and 17 hours for 2, after 7
   to 21 days for 3, and never for 8. 24 current Ninja agents started this
   way; 5 are now split from the Computer that holds their serial.
5. Names reported cut at 15 characters (8 Computers) and Mac name separator
   variants (1) do not match exactly.
6. The stored serial does not follow a hardware change (GF-12 moved to new
   hardware on 2026-07-30; the old laptop, renamed GF-32, matched the stale
   serial on 2026-08-03).
7. Ninja serial is read from `system.serialNumber`. In all 7 Ninja agents
   where it differs from `system.biosSerialNumber` (4 Hyper-V/Azure VMs and 3
   Lenovo desktops), SentinelOne and ScreenConnect report the BIOS value.
8. The 2026-07-13 rebuild most likely split server VMs through concurrent
   promotion (documented in commit `6870b28`); this cannot be proven because
   no record of Computer creation exists (see ADR-0033).

Genuinely different machines that share a name exist and are distinguishable
by serial: KIT "server" (two Ninja serials), UTA laptops 108, 11 and 68, and
UTA Citrix clones (different VMware serials). Domain is not usable for this:
3,415 of 3,478 Computers with two or more domain-reporting records show
different domain values, 3,377 of them on a single serial, because Ninja
reports the DNS domain (`utaw.org`, `ad.rubybpo.com`) and SentinelOne the
NetBIOS domain (`utaw`, `ruby`).

Same-name groups with no serial conflict: 30 live groups; 20 share one
serial. Of the 10 with no serial anywhere, 5 are separate VM objects of one
source on different hosts (kept apart by the same-source rule of 2026-07-12,
correctly), 3 are one machine split across sources (Hudu, LogMeIn, Ninja VM),
and 2 are unclear. The 15-character rule pairs 10 names
uniquely: 7 agree on serial, 3 have a serial on one side only, none conflict.

An operator merge already exists (`views.py` `_merge_devices`, audit actions
`device.combine` and `device.group_combine`, 53 open merge candidates): it
moves observations, findings, condition participants and software to the
survivor and tombstones the other Computer with `operator.merged`.

## Options considered

- Allow automatic attachment only on serial, VM UUID or source identity, with
  name matches going to review. Rejected: LogMeIn and R-U-ON report no serial
  (3,251 records attached by name), and the data shows name matching is not
  what goes wrong.
- Keep the rule and fix only the code paths. Rejected as incomplete: the
  splits also need a way to heal, and the wrong merge needs a way to undo.
- Keep automatic name matching, apply it consistently, prefer merging over
  splitting when nothing conflicts, re-check when identifiers arrive, and make
  every merge recorded and reversible. Selected.

## Decision

### Inputs

1. Ninja's serial is `system.biosSerialNumber`, falling back to
   `system.serialNumber`. Placeholder serials stay rejected through
   `identity_value_rejections`.
2. Names compare on the normalized short name. A name of exactly 15
   characters also equals a longer name in the same client that starts with
   it, when exactly one such name exists. Names also compare with separators
   ignored (dash, space, apostrophe, dot): 13 measured pairs (10 cut names, 3
   separator variants), none with a serial conflict, 8 confirmed by serial.

### Hard conflicts

Two records, or a record and a Computer, are different machines only when:

- a usable serial or a VM UUID differs;
- two VM records from the same source both report at the same time from
  different hypervisor hosts (measured: retired copies left on another host,
  and three VMs named "VM1" on three hosts, none with a VM UUID); or
- two records from the same source are both online at the same time, by the
  source's own online flag and last-seen time.

Nothing else blocks a match. Same-source records with no serial whose
activity is sequential (one stopped before the other started) are one machine
re-registered and merge automatically; the stale entry, if the source still
lists it, raises `duplicate_platform_record`. Measured with the sources' own
online flag and timestamps: 296 such pairs are sequential (LogMeIn 292, Ninja
4), 3 overlapped with only one online (LogMeIn reinstalls), and 1 is both
online (KIT "server", `kit.local` and `kou.local`, two machines). LogMeIn's
`last_seen_at` is its `hostStateChangeDate` (the last online/offline change),
not a last-seen time; timing tests read it together with `is_online`.
Same-source records proven to be one machine by serial or VM UUID are one
machine (the 2026-07-13 rule); a shared MAC address is supporting evidence
only and Hyper-V virtual adapters (`00:15:5d`) are ignored: of 310
same-source pairs sharing a MAC that serial can check, 4 were different
machines, and MAC alone would decide only 2. Domain is
supporting evidence only: LogMeIn and R-U-ON never report it; within one
source it separated only 4 same-name groups, all already separated by serial;
and it differed on 3 serial-confirmed single machines (a domain change). In
particular, an existing record of the same source on the Computer does not:
that is a re-enrollment or a duplicate agent, covered by the duplicate-record
finding.

### Matching a newly discovered record

1. Same source record: it stays on its Computer.
2. Serial or VM UUID: attach when exactly one live Computer in the client has
   an active record currently reporting that value. The Computer's stored
   serial is not used for matching.
3. Name in the same client: attach when exactly one live Computer has the name
   and there is no hard conflict.
4. Name plus MAC address: unchanged; a MAC supports a match, never decides one.
5. Two or more live Computers have the name: they are merged automatically
   and the record attaches only when they share a usable serial or VM UUID.
   Otherwise (name only, 2026-10-16 review) the record attaches to the
   candidate it does not conflict with that has the most recent activity from
   any source (ties: the oldest Computer), and `duplicate_device_records` names
   the candidates: merge them, or confirm they are separate and move the record
   (one recorded action). No new Computer is created for it.
6. No match, or every candidate conflicts: a new Computer.

No record is ever left unattached: every outcome places it on a Computer.

A live Computer has at least one active record. Every record, including a
second record of the same source in one batch, goes through these steps;
promotion never creates a Computer without matching.

Empty Computers (no active records; 92 measured) take part in the same rule:
an empty Computer with the same name and client merges with the live one, or
receives a returning record when no live Computer has the name, so a
reinstalled or re-enrolled machine keeps its history. Its last-known serial
counts for hard conflicts: of 62 empty Computers sharing a name with a live
one, 3 have a different last-known serial (a replacement machine reusing the
name) and stay separate.

### Re-check

When an attached record first reports a serial or VM UUID, or reports a
different one, the same rules run again. If the result is another Computer and
there is no hard conflict, the two Computers are merged. If there is a hard
conflict, a split-Computer or two-machines finding is raised instead.

### Stored values follow the records

The Computer's stored name and serial are projected from its active records.
A hardware change or rename updates them, and each update is recorded.

### Merge and split

Automatic and operator merges use one merge operation, extended from the
existing `_merge_devices`:

- The absorbed Computer stays as a tombstone, as today, and gains a recorded
  "merged into" pointer with time, reason, evidence and the action. Its
  address shows that it is now part of the survivor.
- Its record links close and links to the survivor open, both tagged with the
  merge action.
- Its findings, condition participants and software move to the survivor, as
  today, with the merge recorded on each moved finding.
- The survivor's timeline shows both full histories (ADR-0033). Merge chains
  resolve to the final survivor.
- A split undoes a merge's memberships, not everything since. It restores
  the record memberships captured by the merge action to the re-opened
  Computer; it keeps all later history where it was written; it moves other
  rows (findings, installations, decisions) only when their merge provenance
  proves they came from the absorbed Computer; and it recomputes derived state
  and findings for both Computers. The split is itself a recorded action with
  its reason.
- Deleting a Computer is no longer how duplicates are resolved.

### Withdrawn records

A withdrawn record is a record its source no longer lists. The withdrawal is
not a finding. It is recorded on the record itself (observation history and
the closed link, with time and reason) and shown on the timeline of every
Computer the record belonged to. When the same machine re-registers under a
new record of the same source (attached to the same Computer under the rules
above), the two records are linked and the timeline shows one entry,
"re-registered: old → new".

The consequences of a withdrawal are reported by the findings that own them:
a required agent gone (`missing_required_platform`), nothing left
(`device_missing_from_source`), or a machine left only in Hudu or as a
stopped VM. A Hudu asset or a powered-off or suspended VM no longer counts as
evidence that a machine exists: 75 Computers today have only those left after
losing every agent (60 Hudu only, 15 stopped VMs, none with a running VM).
They get a finding with two actions: decommissioned (archive in Hudu, or
remove the VM) or still in use (investigate the missing agents, which returns
the Computer to the coverage check). Measured 2026-10-16 over 2,542 open
`device_source_record_withdrawn` findings: 1,477 are replacements, 19 have a
different serial, 1,043 have no replacement; of those, 477 are already
covered by another finding and 176 (on the 75 Computers) were covered by none
because the coverage check skips Computers without agents.
`device_source_record_withdrawn` is retired once the new finding is verified
on those 75 Computers.

### Retirement

A Computer is retired automatically only when nothing lists it anymore: no
source record of it is listed, and Hudu has no asset for it or every asset is
archived (one archived asset beside a current one is superseded
documentation: 54 measured, 48 of them with an active agent). Without Hudu,
retirement waits for the review period. Retirement keeps every record and the
full history, is shown on the timeline with its reason, and is reversed
automatically when the machine reports again (an agent online or contacted
within 30 days, or a running VM). A record that is listed again but silent
does not restore it, so an operator's retirement of a silent machine stands
(implementation note 2026-10-16).

Enforcement: `ingest/computer_listing.py` classifies each Computer;
documentation and stopped VMs are `source_record_lifecycle_mappings` rows
(migration 0310, lifecycles `documentation` and `stopped`), not code.
Retirement and restore are explicit change actions
(`computer.retire.automatic`, `computer.restore.automatic`); tests in
`ingest/tests/test_evaluator_lifecycle_single_transition_postgres.py`. Retired Computers are
shown in search, labeled, and listed after active ones.

While something still lists the machine, it is not retired; the state raises
the finding that says what to do. Subject is always the Computer.

| State | Finding type | Resolves when | Actions |
|---|---|---|---|
| Only Hudu (current) is left | `device_missing_from_source`, reason `documentation_only` | An agent or running VM record attaches, or every Hudu asset is archived (then retired), or an operator confirms it in use (the Computer returns to the coverage check) | Archive in Hudu; investigate the missing agents |
| Only a stopped VM is left | `device_missing_from_source`, reason `stopped_vm_only` | The VM runs or an agent attaches, or the VM record is withdrawn (then retired), or an operator confirms it in use | Remove the VM from the host; investigate |
| Every Hudu asset archived, but a VM is still on a host or agents are still listed (none active) | `device_missing_from_source`, reason `archived_still_listed` | Nothing lists it (then retired), or a record becomes active (next row) | Remove it from those sources |
| Every Hudu asset archived, but an agent is active or a VM is running | **New** `archived_but_reporting` | A current Hudu asset exists again, or nothing is active (previous row) | Restore the asset in Hudu; decommission |

`device_missing_from_source` keeps one open finding per Computer; its
`reason` detail changes with the state and each change is recorded
(ADR-0033).

"Active" means online, or seen by the source within 30 days; a monitoring or
network record (for example R-U-ON) counts like an agent. Machines whose
agents are only silent stay with the offline handling: `device_offline` after
the single offline setting (default 7 days) and Needs review after the review
setting (default 30 days); they are not retired while a source lists them. Measured 2026-10-16:
152 Computers would be retired automatically (92 with nothing left, 60 with
every Hudu asset archived), 304 get a cleanup finding (65 Hudu only, 230
stopped VM only, 9 archived with silent agents), and 41 are archived in Hudu
but still reporting. An archived asset never had a different serial from an
active agent on the same Computer; 58 archived assets carry the serial of an
agent that is still reporting.

### Findings

Existing finding types are reused; their producers are corrected to detect
the measured cases. Two types are new: "two machines on one Computer" (below)
and `archived_but_reporting` (Retirement).

| Situation | Finding type | Producer change | Action |
|---|---|---|---|
| One machine on two or more Computers, same serial or VM UUID | `shared_serial` (1 open) | Compare the serials active records report, not only stored serials (26 Computers missed today) | Merge |
| Same-name Computers with no serial or VM UUID linking them, including where a new record was attached to one of them (step 5) | `duplicate_device_records` (0 open, last 2026-09-10) | Restore the producer for step 5 cases; subject: the Computer that received the record or the oldest candidate; resolves on merge or on "confirmed separate" | Merge; confirm separate and move the record |
| Same name, proven different machines, or a record that cannot be placed between them | `identity_conflict` (41 open) | Reword: it no longer cites "hostname alone never merges" | Rename at the source, confirm, or attach |
| Two machines on one Computer | **New** `two_machines_on_one_computer` (subject: the Computer; resolves when the records no longer show two machines, after a split or a source correction) | Different usable serials or VM UUIDs among active records, or two agents of one source reporting different names within one day with no shared serial (2 today) | Split |
| No active records | `device_missing_from_source` (open on all 92 empty Computers) | Add "replaced by" context when a same-name live Computer has a different serial | Retire or merge |
| Two or more active records of one source and type on one Computer, including Ninja re-enrollment stubs that never report a serial | `duplicate_platform_record` (never fired) | Restore the producer | Remove the duplicate at the source |

Hudu: two or more current (not archived) Hudu assets with the same name in
one client are duplicates (`duplicate_platform_record`, action: archive the
extra asset), unless their usable serials differ (different hardware). An
archived asset beside a current one is replaced documentation, not a
duplicate; it appears on the timeline, not as a finding (54 Computers measured
with both, 48 of them with an active agent).

Hudu documentation is a coverage requirement: a Computer without a current
(not archived) Hudu asset raises `missing_required_platform` for Hudu.

Enforcement (migration 0312): Hudu joins the requirement catalog
(`operations.agents`, which migration 0092 had kept CMDB-free because a CMDB
is not installed software; this decision supersedes that note, since only
catalog entries can be required or disabled per profile and client), with a
row in every requirement profile and a global row. A source whose every
current record of the Computer is archived, retired or decommissioned does
not satisfy a requirement (`ingest/evaluator.py` `_PRESENCE_SATISFIES`,
tested against the production view).

A Ninja record that never reports a serial is not a finding by itself: of 8
measured, 4 were withdrawn by Ninja, 3 sit beside a proper Ninja record of the
same machine (a duplicate), and 1 is the only record of its machine.

Re-enrollment, hardware change and rename are timeline events, not findings.

## Enforcement

- Inputs: connector mapping tests for the Ninja BIOS serial; normalizer tests
  for the 15-character and Mac name rules.
- Matching: resolver tests for each step, each hard conflict, live-Computer
  counting, same-source records, and the merge in step 5; a test that
  promotion never creates a Computer without running the matchers.
- Hard conflicts are data: `identity_match_policies.blocking_signal_keys`
  lists `serial` and `vm_uuid`, and the resolver reads only that column.
- Merge: a merge relation table with foreign keys to both Computers, the
  action that created it and the action that reversed it; the merge operation
  is the only writer of a tombstone with reason `merged`, and a database check
  requires the relation for it.
- Every link change goes through one validated writer that requires the
  matching rule, the compared values and the action (ADR-0033). Links existing
  before this decision are marked as pre-rule by the migration; the writer
  cannot set that mark.
- Findings: evaluator tests for each finding in the table, including the
  placeholder and Ninja-field exclusions for "two machines on one Computer".

## Rationale

The data shows that wrong merges are rare (two: one from a stale serial this
decision removes, one caught by the same-source name test) and splits are
common (dozens of Computers, false
"missing platform" findings). A merge that is recorded and reversible costs
one review when wrong; a split hides coverage and history until someone
notices. Hard conflicts are the only measured signals that separate
same-name machines, so they are the only blockers.

## Consequences

- Same-name Computers are merged automatically, including existing ones
  during remediation after a dry run, only when they share a serial or VM
  UUID. Name-only groups (about 7 today) get `duplicate_device_records` for a
  person to merge or confirm separate.
- Existing links stay; their history is marked pre-rule.
- Name history from deleted Computers before this decision is incomplete;
  that cannot be recovered.

## Supersedes or superseded by

Supersedes the hostname rule in ADR-0005 ("hostname alone never merges") and
ADR-0013, and the 2026-09-08 amendment of ADR-0011 ("a shared name ... never
causes an automatic retirement or merge"), for the case defined here: a name
match with no hard conflict. Amends the 2026-09-09 amendment of ADR-0011:
CMDB evidence (Hudu) and powered-off or suspended VM records no longer keep a
Computer out of Needs review, and the per-record
`device_source_record_withdrawn` finding is replaced as described under
Withdrawn records. Replaces the 2026-10-15 draft of this ADR, which
proposed review-only name matching. Related: ADR-0012 (source assertions are
evidence), ADR-0014 (links derived from observations), ADR-0033 (change
history).
