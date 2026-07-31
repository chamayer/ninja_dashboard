# Active root work plan

Track: **Unified entity model — one ecosystem for sources, types and entities**

## Status

- **Proposed. Awaiting review. No implementation authorised.**
- Design derived from failures observed and measured in production on
  2026-07-30 during the Hudu integration. Every element below traces to a
  specific defect with a measured impact; nothing is speculative.
- Prior track (Hudu integration) is complete and deployed — see
  "Already built" at the end.

## Goal

Make source, observation and entity semantics **declared once in data and read
everywhere**, so that adding a source, an entity class, or a semantic
distinction is an addition rather than a redesign — and so shared code can no
longer make silent assumptions about what an observation means.

## Why — the evidence

Nine defects in one day. Eight pre-existed the Hudu work; Hudu exposed them.
Two were introduced by me during it.

| Defect | Measured impact | Root cause |
|---|---|---|
| Promotion guard `entity_type <> 'org'` | **4,991 junk devices** created; fleet 5,209 → 10,200; cleanup across 6 tables | exclusion list where semantics were needed |
| Resolution guard `<> 'org'` | would have resolved documentation as devices | same |
| Lifecycle counted CMDB as contact | **564 devices** held `active`, **394** kept out of `pending_cleanup` | identity conflated with contact |
| Lifecycle counted powered-off VM listings as contact | **229 devices** held `active` — pre-dates Hudu entirely | identity conflated with contact |
| Duplicate-record detection `<> 'software'` | **572 false findings** queued | licence semantics conflated with identity |
| `fast_path` private copy of the identity set | fourth copy of one rule | no single definition |
| Ninja location id vs device id collision | **188 Hudu pages** linked to unrelated machines | keys not namespaced by class |
| `_SOURCES` hardcoded tuple | Hudu absent from dashboard despite collecting 9,866 rows | registration in code |
| Missing alias for `hudu` | source would be **silently skipped** | registration in code |
| Missing fact "which pipeline owns this source" | Ninja reported failed, **coverage evaluation disabled** | fact existed nowhere |

Two structural duplications already in the codebase, independent of Hudu:

- `DeviceLink` and `ClientLink` are the **same table shape written twice**
  (`operations/apps/core/models.py:202`, `:487`).
- `resolver.py` and `client_resolver.py` are the **same algorithm written
  twice** — match on evidence, raise candidates on ambiguity, promote when
  unmatched.

An `AssetLink` was proposed during the Hudu work and would have been a third.
A full CMDB has roughly twenty entity classes; on the current shape that is
twenty link tables and twenty resolvers.

## Design

### Layer 1 — Vocabulary: what things mean

```sql
entity_classes(name, description)
    device, client, site, person, application, license, certificate,
    network, credential, vendor, contract, circuit, backup_job, document

entity_types(name, entity_class,
             is_identity_signal, is_contact_evidence, is_installed_agent,
             description)
```

| name | class | identity | contact | agent |
|---|---|---|---|---|
| `agent.rmm` | device | t | t | t |
| `agent.edr` | device | t | t | t |
| `vm.guest` | device | t | **f** | f |
| `vm.host` | device | t | t | f |
| `network.device` | device | t | t | f |
| `cmdb.asset` | device | f | f | f |
| `cmdb.location` | site | – | – | – |
| `org` | client | – | – | – |

**One flag per question shared code actually asks.** Today all three collapse
into one, which is why the CMDB-as-contact bug needed a separate fix from the
CMDB-as-identity bug, and why the 229-device powered-off-VM bug is still live.

Flags are class-scoped: they are meaningless outside `device`. A new class is
a row. A new question is a column.

### Layer 2 — Sources: who tells us

```sql
sources(id, name, collected_by, discriminator_path, default_entity_type)
source_entity_type_map(source_id, discriminator, entity_type)  -- FK
source_relay_map(source_id, array_path, vendor_path, key_path, kind_path)
platform_aliases(alias, canonical)
```

Exact-match only — **no patterns, operators or precedence.** Ninja has 12
node classes in use; enumeration plus the existing `unmapped_node_class`
finding is stricter than `NMS_%`, which silently types future vendor classes
nobody has reviewed.

A single-type source needs no map rows, only `default_entity_type`.

### Layer 3 — Observations: what was said

Identity tuple unchanged — it already works. Two additions:

```sql
provenance     first_party | relayed
relayed_from   source name, nullable
```

Relay *extraction* is declared in `source_relay_map`. Relay *resolution* —
resolve each relayed key, cluster the results, decide linked / divergent /
stale — becomes generic platform code written once, rather than living inside
`hudu.py`. Any future aggregator inherits it.

### Layer 4 — Canonical entities: what we believe exists

```sql
entities(id, tenant, entity_class, client_id, canonical_key,
         lifecycle_status, first_seen_at, last_seen_at, deleted_at)

entity_links(entity_id, source_id, external_id, external_name,
             match_method, match_confidence)
    UNIQUE(tenant, source_id, entity_class, external_id)

entity_match_rules(entity_class, field, is_proof, weight, scope)
entity_relationships(from_entity, to_entity, relation_type, source_id)

<class>_attributes   -- per-class typed columns, added per class
```

One resolver, parameterised by `entity_match_rules`:

```
device       serial       proof   client-scoped
device       vm_uuid      proof   client-scoped
device       hostname     weak    cross-source only
person       email        proof   tenant-scoped
certificate  common_name  proof   client-scoped
```

`UNIQUE(tenant, source_id, entity_class, external_id)` is load-bearing: it is
what makes Ninja location `192` and Ninja device `192` distinct keys. That
collision mislinked 188 pages.

Per-class attribute tables rather than a generic JSONB blob — typing and
indexing are worth more than uniformity here, and adding one is additive.

### Layer 5 — Enforcement: why it stays true

1. FK chain `entity_type → entity_types → entity_classes`. A type no gate
   understands cannot be written.
2. Unmapped discriminator → `unknown`, all flags false, plus a finding.
   Never a guess.
3. Every skip recorded as a visible run outcome with a reason. Nothing
   collects nothing silently.
4. CI test failing on `entity_type <>`, `entity_type LIKE 'agent.`, or a
   local entity-type set outside the helper. **This test alone would have
   caught five of the nine defects at commit time**, including both I
   introduced.
5. `provenance='relayed'` can never promote to canonical.

## Scope

**In:** layers 1–5 above; retirement of `device_links`, `client_links`,
`resolver.py`/`client_resolver.py` duplication; retyping existing observations
where the class is currently wrong.

**Out:** Metabase (deprecated); legacy `ingest/agent_compliance/`
(retirement path, ~9 hardcoded platform lists remain there deliberately);
the observation UI (separate track); honouring `source_bindings.schedule`
(separate backlog item).

## Suggested slices

Each independently deployable and reversible.

- **S1 — Vocabulary.** `entity_classes`, extend `entity_types` with
  `entity_class` + the two additional flags. Backfill. Readers unchanged.
- **S2 — Read the flags.** Point resolution, promotion, lifecycle,
  duplicate-detection and coverage at the flags. Retires the four `'org'`
  literals and the eight `LIKE 'agent.%'` tests. **Fixes the live 229-device
  bug.** Add the CI guard test.
- **S3 — Source registration.** `collected_by`, `discriminator_path`,
  `default_entity_type`, `source_entity_type_map`. Retire the remaining
  hardcoded lists.
- **S4 — Retype existing observations.** Split Hudu's flat `cmdb.asset` into
  the correct classes. Requires withdrawal handling — `entity_type` is part
  of the identity tuple, so retyping creates new identities and orphans old
  ones (~9,795 Hudu rows; Ninja unaffected, its mapping yields identical
  values).
- **S5 — Provenance + generic relay resolution.** Move Hudu's card logic into
  the platform.
- **S6 — Canonical unification.** `entities`, `entity_links`,
  `entity_match_rules`, `entity_relationships`; migrate `devices`/`clients`;
  collapse the two resolvers. Largest slice; `device_links` has 13,948 rows
  and everything from coverage to findings joins it.

## Questions for the reviewer

1. **S6 is the expensive half.** S1–S3 fix every measured defect and stop
   recurrence. S4–S6 deliver the "one ecosystem" property. Is S6 in scope
   now, or does the track stop at S5 with the duplication documented?
2. **Runtime editability.** Moving policy into data means a wrong row is a
   production incident with no pull request — mapping Hudu Locations to
   `agent.rmm` would have documentation minting devices. Proposal: seeds ship
   in migrations; `is_identity_signal` and `entity_class` are
   migration-only; the rest is admin-editable with `updated_by`/`updated_at`.
   Acceptable?
3. **`vm.guest` contact semantics.** Setting `is_contact_evidence=false` will
   transition ~229 devices out of `active` on the next evaluator pass, on top
   of the ~564 from the already-shipped lifecycle fix. Wanted, and should it
   be staged?
4. **Per-class attribute tables vs JSONB** on `entities`.
5. **Is `entity_class` the right cut?** `site`, `person`, `license` are
   speculative until those sources exist; only `device` and `client` are
   proven today.

## Validation plan

- Every slice measured against production before and after, using the same
  queries that produced the numbers in the evidence table.
- S2: assert the flag-driven query returns the identical set to the current
  hardcoded one for every existing type — byte-identical, as was done for
  `identity_entity_types` in migration 0092.
- S4: observation counts per class reconcile to the pre-retype total;
  orphaned identities explicitly withdrawn, not left active.
- S6: `entity_links` row count matches `device_links` + `client_links`;
  resolver output compared tuple-by-tuple against the current resolvers on a
  full pass before cutover.
- CI guard test added in S2 and required from then on.

## Already built (prior track, deployed)

- Hudu ingesting 9,795 `cmdb.asset` observations on a 24-hour cycle; 4,948
  linked via Ninja card resolution; zero devices created; zero
  `device_links`.
- `operations.entity_types` (single flag), `platform_aliases`,
  `sources.entity_type` — migration 0092.
- Four CMDB finding types — migration 0091; dry-run verified at 86 findings.
- Five defects fixed: resolution, promotion, lifecycle, duplicate-records,
  `fast_path`.
- FK indexes on `software_installations_current.device_id` and
  `software_installation_history.device_id` — migration 0090. Device deletion
  went from never-completing to 1.9s.

## Deferred, recorded in `.work/backlog.md`

- Honour `source_bindings.schedule` (replaces cadence-by-capability).
- `device_session_current` counts CMDB syncs in `last_observed_at` — 31
  devices, unread column; migration written, validated, deliberately
  discarded.

## Next action

- Review this plan. No code until the questions above are answered,
  particularly (1) scope of S6 and (3) staging of the `vm.guest` transition.
