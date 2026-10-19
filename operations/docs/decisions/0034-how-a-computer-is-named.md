# 0034 — How a Computer is named

Status: Accepted 2026-10-19; not yet implemented (see `operations/.work/plan.md`)
Date: 2026-10-19

## Context

A Computer's name is chosen today as an ordinary attribute: each source record
makes a hostname claim, `attribute_authority_policies` (per source instance and
record type) says whether the claim is eligible and at what priority, the
generic effective projection (migration 0108) picks the highest priority, and
`device_cache_projector` copies the result into `devices.canonical_hostname`.
The stored name is then used as an identity input: matching compares an
incoming record's name with it (`ingest/identity/matching.py`
`_name_candidates`), duplicate detection groups Computers by it
(`ingest/identity/findings.py` `duplicate_groups`), and two identity findings
are keyed by it (`duplicate_device_records`, `identity_conflict`).

Measured read-only on 2026-10-19 for tenant 1, the only tenant (5,542 live
Computers: 5,415 non-retired, 127 retired). The measurement covers one
tenant; the design is tenant-scoped throughout.

- Of the non-retired: 4,996 are named by an eligible claim, 413 (7.6%) by
  nothing current (the projector keeps the stored name), 4 by an
  equal-priority conflict ("unknown"), 2 by "retained last uncontested"; no
  operator names exist.
- Winning sources: Ninja 1,801, SentinelOne 1,557, LogMeIn 1,135,
  ScreenConnect 480, Ninja VM host 26, network device 2, monitor target 1.
- R-U-ON (656 records) has no hostname rule at all, so it can never name a
  Computer and nothing reports that. Hudu and Ninja `vm.guest` (0313) are
  excluded on purpose.
- The first name is written directly at creation from the match group's name
  (`ingest/identity/resolver.py`, promotion), outside the rules above.
- Name evidence reaches a new Computer only after link sync, claim projection
  and effective projection, which run at the end of a source collection
  (`ingest/derived.py`), not in the resolver.
- 19 Computers show Ninja's 15-character Windows name (`3rd_fl_conferen`)
  while SentinelOne reports the full name (`3rd_fl_conference_room`).
- Example: an R-U-ON monitor reporting `UTAW-82-MGT` (a different machine
  from `UTAW-82-MGT03`; different private IP) sits on its own Computer named
  `utaw-82-mgt03`, which it never reported, while a Computer named
  `utaw-82-mgt` exists. The wrong stored name made the pair look like a
  duplicate of mgt03 and would steer a new `utaw-82-mgt03` record to the wrong
  Computer.

Source name forms (active records): Ninja RMM, SentinelOne and ScreenConnect
report the short name and a separate domain field; LogMeIn puts the FQDN in
the name (2,203 of 3,070) with no domain field; Hudu is mixed. On 3,449
Computers the records report one short name with different domains (NetBIOS
domain, DNS suffix, workgroup), so the domain cannot tell machines apart
(ADR-0032 measured the same, 3,377). LogMeIn and Hudu names, R-U-ON monitor
names and VM names are typed by people and editable; ScreenConnect reports
the machine's real hostname (user, 2026-10-19).

## Decision

Identity owns Computer naming. A name is something a source record reports;
identity works on record names; the Computer name is one explainable function
of the Computer's records. A Computer's selected display name cannot influence
identity. Record labels may support matching only under the established
conflict and ambiguity safeguards.

### 1. One normalization function, applied on demand

`operations.record_name_forms(platform, record_type, name, domain)` is the
only normalization of record names (the target: until step 3 of the activation order, matching
still normalizes in Python, and this function serves the shadow naming and
roaming detection). It returns:

- `name_short`: the name before the first dot, lower case, trimmed (the strict
  form);
- `name_key`: `name_short` with separators removed (the loose form);
- `name_domain`: the part after the first dot, or the record's domain field.

It is applied when names are read, not stored: no columns, trigger or
backfill on `entity_observation_current` (2.9 GB, the most frequently
written table). Measured: normalizing every named record of the tenant takes
2.8 seconds and the largest client has 228 records, so a client-scoped match
costs milliseconds. Because nothing is stored, a change to
`source_name_kinds` takes effect on the next read.

Universal normalization is deliberately conservative: short name / FQDN
separation, case, and the two comparison forms. Removing annotations is
source-specific and data-driven (`source_name_kinds.strip_pattern`): a
trailing `(…)` is removed for Ninja `vm.guest`, Hudu and R-U-ON names
(measured: 65, 42 and 2 records carry one; agents none). Further annotations
(`retired #110503`, `_retired`) are not stripped until a record-level review
justifies a pattern. Python never normalizes names on its own; it calls the
function, and a parity test pins it. Record history keeps every value, so name
history needs no new store. The domain is never an identity signal (ADR-0032
unchanged).

### 2. Each source and record type has a name kind, kept as data

`operations.source_name_kinds(platform, record_type, kind, rank,
strip_pattern)`, keyed by source and record type (LogMeIn and ScreenConnect
share `agent.remote_access`):

- `os_name` — the machine's own hostname: Ninja `agent.rmm` (300),
  SentinelOne `agent.edr` (250), ScreenConnect `agent.remote_access` (225);
- `label` — a name a person gave the machine in another system: LogMeIn
  (150), R-U-ON (140), Ninja `monitor.target` (130), Ninja `vm.host` (125),
  Ninja `network.device` (120), Ninja `vm.guest` (110), Hudu (50). Ninja
  `vm.host` and `network.device` are conservatively labels until shown to
  report the OS name.

Every source has its own rank, so sources never tie. A source and record type
without a row is treated as the lowest-ranked label, never ignored, and raises
an admin finding (`source_name_kind_unclassified`), following the change
history registry and `change_history_unclassified`.

### 3. Roaming records carry no name

A record is roaming when it is in `identity_roaming_records` under the 0318
rule (three or more usable serials and three or more names), or when it is an
agent record that, within 90 days, reported five or more distinct `name_key`
values with no usable serial and no VM UUID. A usable serial is decided as
identity matching decides it (`ingest/normalize.py` `is_usable_serial`,
including `identity_value_rejections`); `operations.usable_serial` is its SQL
parity implementation, pinned by tests. A history interval counts when it
overlaps the 90 days, not only when it began inside them. Formatting and domain changes do
not count as names. A roaming record's name is not evidence for matching or
naming; the record still attaches by its stable source link and is shown.
Because the new condition requires no serial and no VM UUID, adding such
records to `identity_roaming_records` (with `basis = 'names'`) changes nothing
for serial and VM UUID matching today.

Classified 2026-10-19 (identity records with three or more distinct names in
90 days, 31 records): 5 already roaming (SentinelOne on Citrix MCS clones, 5
to 11 names); 2 LogMeIn records on the same clones (38 and 17 names, no
serial), which the new condition adds; 24 legitimate renames of one machine
(exactly 3 names, one serial, all agents of the machine agreeing — for
example `lion65dw → lion65thdw → lion65thnvr` on LogMeIn, Ninja and
SentinelOne), which the condition leaves alone. A threshold of three names
would have stripped those 24 machines of their name evidence.

### 4. Matching and duplicates use record names, never the Computer name

Serial and VM UUID matching run first, unchanged (ADR-0032), including the
automatic merge of Computers proven to be one machine. An incoming record's
name then finds candidates in its client in tiers; the first tier with a
candidate decides, and later tiers are not consulted:

1. current records on active Computers;
2. current records on other non-retired Computers;
3. withdrawn records, only when no current record holds the name;
4. names in the record history of the Computer's records, only when no
   record holds the name now. The lookup follows the indexed record
   identities (`source_instance_id`, `external_id`) of the client's records;
   it never scans all observation history. Its query plan is checked before
   activation.

Within the deciding tier, ADR-0032's rules apply unchanged:

- a strict match (`name_short`) with several candidates attaches to the most
  recently active candidate without a hard conflict and raises
  `duplicate_device_records`;
- a loose match (`name_key`) decides only when it identifies exactly one
  Computer;
- a 15-character match decides only when exactly one distinct longer name
  starts with it;
- a hard conflict (usable serial, VM UUID, the same source live on both)
  excludes a candidate, and an operator "keep separate" decision excludes the
  Computers it names.

Labels may support a name match when no hard conflict exists — LogMeIn and
R-U-ON have no stronger signal — so a bad source label can still produce a
wrong attachment, recorded and reversible. Roaming records (section 3) never
match by name. Duplicate detection groups Computers whose current identity
records share a strict name.

### 5. The Computer name is one function of its records

`operations.computer_names(p_devices uuid[])` (set-based; one Computer or the
whole fleet) returns, per Computer, the name, the rule that decided it and the
record behind it. The first rule with an answer wins:

| Rule (`name_rule`) | Source of the name | Order within the rule |
|---|---|---|
| `operator` | the operator's name | — |
| `reporting_os` | an OS name from a recently reporting record: the record itself is online, a powered-on VM, or reports contact within 30 days (the lifecycle duration of `ingest/computer_listing.py`, evaluated per record, not per source) | rank |
| `silent_os` | an OS name from a current but silent record | rank |
| `stable_os` | with no current OS record, the current name, when any of the Computer's OS records ever reported it (record history) | — |
| `withdrawn_os` | an OS name from a withdrawn record | most recently seen, then rank |
| `current_label` | a label from a current record | rank |
| `withdrawn_label` | a label from a withdrawn record | most recently seen, then rank |
| `unconfirmed` | no named records: the name is kept | — |

Within the OS rules, a name of exactly 15 characters gives way to the one
longer current OS name of the same Computer that starts with it (the Windows
NetBIOS cut; 19 Computers). Roaming records are skipped throughout. Recency in
the two withdrawn rules is an explicit, stated order, not a hidden
tie-breaker (ADR-0010).

Rank beats recency within `reporting_os`: an old name from a higher-ranked,
recently reporting agent can beat a newer name from another. This is
accepted: the Computer page shows every current OS name with the selected one,
and History records when OS names start and stop disagreeing. Measured: 23
Computers have two recently reporting OS names from different sources (22
Ninja vs SentinelOne); in none is the lower-ranked one seen more than a day
later. An issue is added only if persistent disagreement proves actionable.

### 6. One writer, enforced in the database

- `operations.write_computer_names(p_devices uuid[], p_tenant bigint)` compares
  `computer_names` with the stored decision and, only where the name, rule or
  record differs, writes `canonical_hostname`, `name_rule`,
  `name_observation_id` and `name_decided_at` under an explicit change action,
  `computer.rename`, whose evidence names the rule and the record (ADR-0033).
  An unchanged decision writes nothing, so `name_decided_at` moves only when
  the decision changes.
- It is `SECURITY DEFINER`, pins its `search_path`, rejects Computers outside
  `p_tenant`, and is owned by a dedicated no-login role,
  `operations_naming`, which holds `UPDATE` on `devices`.
- A guard trigger on `devices` rejects any change to those four columns unless
  `current_user` is `operations_naming`. A custom session setting is not used
  for this, because runtime roles can set arbitrary custom settings. Tests run
  a direct update as both `operations_app` and `ninja_ingest` and expect a
  refusal.
- A Computer is inserted with `name_rule = 'pending'`; a deferred constraint
  trigger rejects a commit that leaves any Computer `pending`, so creation
  names the Computer in the same transaction.
- `name_rule` is checked against the values in section 5 plus `pending`.
  `name_observation_id` is a tenant-safe reference,
  `(tenant_id, name_observation_id)` to `entity_observation_current
  (tenant_id, observation_id)`, `ON DELETE SET NULL (name_observation_id)`.

When it runs:

- Immediately, for the affected Computers, in the transaction that creates a
  Computer, attaches or detaches a record, merges, splits, or sets or clears
  an operator name.
- A full set-based reconciliation over all Computers in each resolver cycle,
  writing only changed decisions. It catches source updates, name-kind
  changes, missed signals and the 30-day reporting boundary, with no
  per-source trigger queue. The complete shadow reconciliation is timed in
  production before activation; a queue is introduced only if scale proves it
  necessary.

### 7. Operator rename

A Rename action on the Computer, with a reason, stored as the
`device_operator_decisions` dimension `name`; "Use automatic name" clears it.
Both recompute that Computer immediately.

### 8. Identity findings are keyed by Computers, not names

`duplicate_device_records` and `identity_conflict` condition keys are built
from the Computer IDs involved, not from the hostname, so a rename does not
close a finding and open a new one. A migration rekeys the existing open
findings in place, keeping their IDs, acknowledgements, snoozes and history.

### 9. Label drift is surfaced, not hidden (last stage)

Finding type `computer_name_differs_in_source`, one per Computer and labeling
system: a current label (LogMeIn, Hudu asset not archived, R-U-ON, VM name)
whose `name_key` differs from a Computer name decided by an OS rule. The fix
is at the source. It is useful but not required for the identity cutover: it
ships last, non-alerting, and may be delayed without blocking the rest.

### 10. Storage contract

- `devices.canonical_hostname` keeps its current meaning — the lower-case
  short name — so its 191 references (display, search, exports, finding
  details) need no change. Only `write_computer_names` writes it.
- Identity no longer reads it: `matching.py`, the resolver's promotion and
  duplicate steps, and `identity/findings.py` move to record names.
- New columns on `devices`: `name_rule`, `name_observation_id`,
  `name_decided_at`. Nothing is added to `entity_observation_current`.
- The hostname rows of `attribute_authority_policies` are retired and the
  device cache projector stops writing the name; hostname claims remain
  visible evidence (ADR-0010 allows unconfigured attributes as evidence).

### 11. Activation order

1. `record_name_forms`, `source_name_kinds`, the roaming condition, the shadow
   `computer_names` and a shadow full-fleet reconciliation that computes and
   compares but writes nothing; the unclassified finding. No change to
   matching or to Computer names.
2. Activation review: the complete shadow reconciliation timed in production,
   the historical-name query plan checked, and the rename list reviewed,
   including the retired Computers renamed from archived Hudu labels (10).
3. Identity finding keys moved to Computer IDs (in-place rekey); matching and
   duplicate detection on record names.
4. The writer, its role and guard, provenance, immediate and full
   recomputation, the Rename action and history.
5. Retire the hostname authority policies and the remaining legacy readers.
6. Label drift presentation and finding.

The writer must not be active while the matcher still reads
`canonical_hostname`.

## Dry-run results (read-only, 2026-10-19, tenant 1)

All figures use the roaming condition of section 3 and the `(…)` rule of
section 1. They predate fixes A and B of the 2026-10-19 re-review (the 15-
character rule and the order of `silent_os` and `stable_os`); the order change
affected no measured Computer, and the 15-character rule affects 19.

Naming, 5,415 non-retired Computers (categories do not overlap):

| Outcome | Computers | Detail |
|---|---|---|
| Unchanged | 5,273 | |
| Rename | 45 | OS name from withdrawn agents 12 (e.g. `rd13_retired → rd13`, `cp-hook-mgt → cp-hood-p-mgt`); labels 33: VM names 26, Hudu 5, R-U-ON 2 (incl. `utaw-82-mgt03 → utaw-82-mgt`) |
| Same key, different form | 93 | VM names 84, Hudu 5, R-U-ON 2, monitor target 1, SentinelOne 1 (spaces and annotations kept) |
| Kept by `stable_os` | 3 | Citrix clones whose agents last reported the image name |
| `unconfirmed` | 1 | no named records |

Retired Computers (127): 108 unchanged, 10 renamed from archived Hudu labels,
9 same key in a different form.

Label drift: 114 distinct Computers (Hudu 86, Ninja labels — mostly VM names —
24, LogMeIn 16, R-U-ON 4; a Computer can drift in more than one system).

Matching replay, 5,516 client-and-name pairs, today's rule against tiers 1–3,
compared on `name_key` (identity record types only; the 15-character rule
and tie-breaking were not replayed):

| Outcome | Pairs |
|---|---|
| Same candidates | 5,393 |
| Finds a Computer where today a new one is created (split avoided) | 102 |
| Narrows to live Computers (e.g. 4 `dc1` → the 2 active) | 12 |
| Adds candidates (exposes `utaw-82-mgt` / `-mgt03`, `del-lt1` / `del-pc01`, a rename) | 4 |
| Different Computers (`gf-32` / `gf-12`, the known two-machine case) | 1 |
| Today finds a Computer, tiers 1–3 do not | 4 |

Of the last 4, tier 4 (record history) recovers 3 (`ac-vm`, `cp-hook-mgt`,
`yidelscomputer`); 1 (`gld1`) is a stored name no record has reported in
retained history. Before the `(…)` rule the same row was 48.

## Consequences

- A Computer's selected name can no longer misdirect matching or duplicate
  detection; record labels still can, under the existing safeguards.
- Every Computer name is explained (rule and record) and every change is
  recorded; direct writes are refused by the database.
- New sources and record types are visible from day one and can name a
  Computer only below every OS name.
- Renames no longer reopen identity findings.
- A returning machine whose only remaining evidence is a stored name no record
  ever reported (1 measured) gets a new Computer; the old one stays findable
  through search over every record a Computer has had.
- No schema or trigger change touches `entity_observation_current`.

## Open questions

- Additional annotation patterns for VM and Hudu names (`retired #110503`,
  `_retired`, `created by mistake`), after a record-level review.
- Whether Ninja `vm.host` and `network.device` names are OS names (labels
  meanwhile).
- The 30-day "recently reporting" window is the lifecycle one; kept as the
  initial position.

## Relationships

Amends ADR-0010: hostname leaves the generic attribute authority; a
Computer's identity fields (its name, and the serial and VM UUID ADR-0032
already projects from records) are derived by identity code from its records.
Honors ADR-0012: `write_computer_names` is the single writer, creation
included. Amends ADR-0032: matching and duplicates use record names; identity
findings are keyed by Computers; "stored values follow the records" is
restated by sections 5 and 6; the 0313 `vm.guest` exclusion is replaced by the
label kind; the roaming condition is extended (section 3). ADR-0033: renames
are explicit change actions.
