# PLAN-015 — Computer identity reconciliation

## Goal and status

Define one set of machine identity rules for new records, existing Computer
groupings, and identity reviews. Re-evaluate active source evidence daily so
the system can correct earlier automatic decisions. Keep client ownership and
access under the existing ownership projector.

Active. The one-time read-only preview is complete locally and serves as the
baseline for the proposed shared assessment. Partial shared matching and preview
changes exist locally; the expanded contract, validation, and rollout remain
unfinished.

Current user priority: finish the matcher and identity resolution first. Record
side issues here for later instead of expanding the current implementation scope;
the existing unrelated and side-work changes remain in the worktree.

Narrow universal matching work: the standalone read-only preview can now use
`--universal` to assess current serial and VM UUID evidence across clients,
including compatible duplicate candidates, for both attached and unattached
records in one snapshot. Hostname matching retains the
confirmed same-client rule. This mode bypasses ownership as machine evidence
only; the existing writer paths and configured policy remain unchanged. The
original attached-record preview remains available for comparison; the two
report formats and populations differ, so compare corresponding attached
records rather than aggregate totals. Runtime matching now assesses serial and
VM UUID candidates across the tenant before applying the existing association
scope. A result outside that scope defers the write; the current deferred path
does not persist the match evidence. The matcher revision was advanced. Ruff and
Python compilation passed; this behavior has not been exercised against
PostgreSQL. Cross-client writes, merge-candidate findings and access
transitions remain unfinished and are not implied by a preview result.
On 2026-11-20 the user directed that PostgreSQL validation be skipped for this
work. The implementation and migrations remain unverified against PostgreSQL;
do not infer deployed behavior or remove the separate rollout gates.
Daily reassessment and source-record identity assessment now discover serial
and VM UUID candidates across clients and apply the existing client-scope
decision. Unattached findings publish only candidates in the record's current
client scope. The source-record assessment revision is 9. A preview is not
evidence that the runtime action ran. The revised candidate queries, results
and access behavior have not been exercised against PostgreSQL.
The polling resolver invokes matching for records without a mapped client;
inline collection still calls the fast matcher only when the source has an
inline client. Unknown-client intake therefore waits for the polling resolver.
The Django system check passed with the repository root on `PYTHONPATH`.
Static migration review: 0427 follows 0426 and removes the constraint created
by 0382. Its reverse sets corroboration to true for every serial and VM UUID
policy before restoring that constraint, so it would overwrite any later policy
changes to those flags. Review the affected current policies before any approved
rollback. Neither direction has been validated against PostgreSQL.
Automatic merge planning now groups serial and VM UUID evidence across clients
before separating candidate actions by client. A contradictory identifier in
another client can expose an ambiguous shared identifier. The existing merge
authority still acts within one client. This planning change has not been
exercised against PostgreSQL. The separate strong candidate projection matches
hostname plus MAC and is intentionally client-scoped under the approved
hostname rule; it is not a cross-client hardware-identifier projection.
Cross-client identity and client-conflict findings remain separate unfinished
work and require their own scoped presentation contract.

## Findings

### Current user decisions

Matching usable identifiers establish a match when no distinguishing evidence
or applicable operator decision conflicts. A second independent clue is not
required; retain the reporting sources and identify unknown upstream origin.
When conflicts eliminate some candidates and exactly one remains eligible at
the same matching tier, the matcher now selects it; a tier where all candidates
conflict still cannot fall through to a weaker key. Runtime validation is pending.
When several same-client Computers share the matching serial or VM UUID and
their combined current identity evidence has no conflict or separation, the
matcher selects the oldest Computer, matching the existing merge planner's
survivor rule. It retains the other candidate IDs in the match evidence; the
merge planner still performs the Computer merge. Runtime validation is pending.
Simultaneously online records from one source are not by themselves evidence of
different machines; matching identifiers are duplicates unless other evidence
distinguishes them. These decisions supersede
the earlier unknown-origin gate and same-source precedence discussion below;
the implementation and validation are in progress.

On 2026-11-23 the user confirmed that a Computer can have at most one active
Ninja record for all current processing. A superseded Ninja record remains
linked in association history only, even while Ninja continues to list it.
See [ADR-0032](../decisions/0032-computer-identity-matching-and-merge.md#one-active-ninja-record-per-computer-2026-11-23).

### Contract review: governing rules and implementation gaps

On 2026-11-19 the user confirmed that this plan's new identity and ownership
rules govern. Existing behavior and older decisions identify implementation
gaps; they do not override the new target. Schema changes and production writes
still require the separate authorization specified in repository instructions.
The user authorized preparation and local testing of the required migration on
2026-11-19. The user subsequently authorized commits, pushes, and production
performance measurement. Pending migrations still need review and explicit
inclusion in deployment approval before the production-triggering push.

The user confirmed that a unique same-client hostname match with no hard
conflict attaches automatically even without hardware corroboration, consistent
with ADR-0032. This does not settle cases with multiple candidates, contradictory
evidence, or unverified client ownership; those require separate assessment.
Unknown origin does not prevent a match; preserve reporting-source information.
The local matcher and automatic merge planner now accept a shared usable serial
or VM UUID without independent corroboration, subject to conflicts and explicit
decisions. Identifier matches retain both the incoming reporting source and a
current matching observation's reporting source; automatic merge evidence records
the reporting source observations on both Computers.
Migration 0427 prepares removal of the old corroboration constraint and updates
stored hardware policy flags and policy versions. Neither the SQL nor migration
is validated yet.
Existing tests still encode the former corroboration rule; per user instruction
they were neither run nor modified. Targeted Ruff (excluding the nine pre-existing
model findings), compilation, Django system check, offline model migration-drift
check, registry validation and
`git diff --check` passed using the project environment. Docker status did not respond.
The unused independent-corroboration helpers were removed from runtime; the
legacy test references to them also remain unchanged under the no-test instruction.
Name-collision findings keep pairs available for review unless the shared
contradiction assessment shows they differ; eligible identifier matches can also
be considered by automatic merge planning.
Duplicate findings identify the actual reported name used for their grouping,
rather than substituting the selected Computer's cached name.
If a larger name-review group connects Computers through a third member, an
operator's existing separation between two members is now included in the
finding's different-machine pairs, preventing the group merge action from
overlooking that decision.
Findings and the merge resolver now share the lookup for explicit separations,
excluded records and previously split merges. The Issues merge guard uses that
lookup through its permitted metadata view. PostgreSQL permission and behavior
validation remain pending.
Counterfactual record matching now checks the same separation history between
the record's currently attached Computer and a candidate; a prior Computer split
or explicit separation cannot be bypassed by moving that record individually.
The direct record exclusion remains in force for detached records. This does not
establish a full historical-membership contract; SQL validation is pending.
An empty, successfully read serial-rejection set is treated consistently in
matching and Issues actions; a failed database read still fails the action.
Matcher previews retain attempts and blockers when a candidate cannot be selected.
Reassessment reports now retain the matcher attempts and, for unattached records,
the candidate IDs even when no candidate can be selected; this preserves the
evidence and blocker reasons needed for identity review.
Attached-record previews also retain unresolved candidate IDs and explicitly
report deferred ownership; reassessment carries those fields forward.
Reassessment entries identify the reporting source instance even when no match
was selected and label upstream field origin unknown.
The local matcher also refuses empty normalized name keys as identity evidence,
including when punctuation-only names would otherwise compare as equal. Candidate
discovery, findings and Issues action rechecks now apply the same restriction;
the changed SQL requires PostgreSQL validation.
Unscoped matcher policies now also require stable, locked target ownership for
writes, without treating the target's client as machine-identity proof. The
ownership transition and lock behavior remain unvalidated against PostgreSQL.
Null or non-array MAC fields are treated as unavailable evidence in both
matcher MAC lookups; the changed SQL still needs PostgreSQL validation.
Incoming MACs use the existing normalization and placeholder rejection before
either lookup; matcher comparisons accept equivalent colon, hyphen, compact,
case and surrounding-whitespace formats on existing source records. The SQL
still needs PostgreSQL validation.
Multiple hostname candidates remain ambiguous even if an unverified MAC would
select one; the approved hostname path requires a unique hostname candidate.
When a full source key is available, matching excludes that record by the full
key even if its legacy display key differs. Candidate discovery and conflict
assessment share the exclusion SQL. PostgreSQL validation is still needed.
The incoming roaming-record lookup also uses the source key's external ID when
available, rather than assuming the legacy display key is the external ID.
Inline intake matching now uses the final canonical hostname and serial after
connector overrides, matching the values that the polling resolver later reads.
Existing-record dispositions now accept any unique match selected by the same
matcher, including an eligible hostname match, instead of applying a separate
hardware-only move rule. The writer still re-runs that matcher before a move;
this behavior has not been run or tested. Its disposition record retains the
matcher comparison and reporting source information.
The source-record assessment now uses the shared matcher for all attached
records in its batch, rather than a separate key pre-filter that could miss
supported name variants. Its runtime impact has not been measured.
It also supplies the observation's legacy entity key to the matcher, while still
passing the complete source identity, so existing record-exclusion decisions use
the same key as intake and the polling resolver.
For unattached records it no longer flags an ambiguity after the shared matcher
has selected a Computer from compatible duplicates or excluded competitors.
The identity Job now invokes that reassessment once daily and writes dispositions
only for proposed association changes. This is local code only: the fleet-wide
preview, runtime and production behavior have not been run or validated.
Review of the daily path found two remaining action-policy gaps. `run_daily`
commits the cadence claim before the preview and `run` commits each disposition
separately; a later failure can leave earlier moves committed and defer a retry
until the claim is eligible again. The cadence is based on the last start, not
successful completion, and does not by itself fence a run lasting over a day.
The matcher returns its selected survivor as the sole result candidate and
records the other compatible candidates in comparison evidence; the writer's
single-candidate check therefore does not by itself reject that selection.
Review partial completion and retry as part of the daily action policy before
rollout; no runtime change was made in that review.
The resolver's standalone schedule is retired; the source-refresh workflow admits
it as a dependent step. The cadence therefore means at most once per day when
the identity Job runs, not a guaranteed daily run if no source refresh admits it.
The resolver's candidate projections exclude non-identity, roaming, malformed
and placeholder MAC evidence. The strong-candidate projection now applies the
same shared whole-pair contradiction assessment as automatic merge before
publishing a candidate. Its discovery and proof qualification are still
separate from the matcher, and its SQL has not been validated against PostgreSQL.
Discovery no longer filters pairs by cached VM UUID before the current-record
contradiction assessment can evaluate them.
Finding and candidate name discovery now exclude archived record names from
current-name evidence, as the matcher already does. The underlying records
remain available for other evidence; corroboration also avoids recording an
archived hostname as current support when a MAC selected the same record. SQL
and runtime impact need validation. Issues merge and split rechecks apply the
same archived-name rule through the permitted lifecycle view.
The resolver's existing-group name check now uses the same source-name forms
and archived-name exclusion instead of a separate hostname-only normalization.
Shared conflict checks no longer treat simultaneous same-source reports alone
as a contradiction, and Issues merge rechecks allow matching identifiers, as clarified in
[ADR-0032](../decisions/0032-computer-identity-matching-and-merge.md). Split
findings also accept a shared VM UUID in their existing same-source name check.
The matcher no longer supplies simultaneous-online streams as conflict proof;
the old policy field remains for compatibility while the migration is reviewed.
The paths still need review for complete equivalence and SQL validation.
That discovery now shares the matcher's SQL MAC qualification expression for
colon, hyphen, compact, case and whitespace formats. PostgreSQL validation is
pending; discovery and other proof qualification remain separate from the matcher.
Review candidate discovery also considers separator-insensitive source name keys;
it does not itself establish a unique hostname match or authorize an attachment.
Each candidate snapshot retains its own Computer name instead of copying the
first Computer's name onto both members. SQL validation is pending.
Previously published candidates whose current evidence conflicts or is missing
remain reviewable with their stale confidence cleared and reason updated; they
are not labeled as merged. This also applies when the discovery pair disappears:
disappearance alone does not establish that a merge occurred. Candidate text
identifies unverified field origin. SQL validation remains pending.
The name-collision projection applies the same review treatment and restricts
its update to its own candidate keys, avoiding accidental updates to candidates
created by the separate strong-evidence projection.
Local intake and resolver changes retain the selected matcher in association
history; the linked source record identifies the reporting source. This records
how the association was selected, not the hostname's upstream origin. Existing
generic history is not retroactively classified; database validation is pending.
Matcher previews and reviewed reassessment history also retain the compared
value, reporting source and source instance, explicitly marking field origin as
unknown until a reliable origin contract is available.
Automatic-merge evidence identifies the reporting source and source instance for
each identifier observation and marks upstream origin unknown when unavailable.

The current incoming matcher also reads configured client-scoped policies and
defers when candidate ownership is unsettled. The automatic merge planner
uses a separate same-client shared-serial/VM rule. ADR-0052's proposed ownership
contract makes conflict and unknown distinct from an effective client, but
its reader transition and concurrency guarantees remain unvalidated. A shared
machine assessment therefore cannot by itself authorize a cross-client write:
first verify every affected reader and writer against the effective ownership
contract, including the transition while projection is pending.

ADR-0032 describes moving findings on merge; ADR-0050 says source-record
findings remain owned by their records and must not be retargeted. The newer
record-level rule governs those findings; audit Computer-subject findings and
the existing merge SQL separately before implementing changes. The proposed
daily reassessment and automatic repairs also require a reviewed action policy,
drift checks, and a separate rollout approval.

The software decision queue's `software_review.DEVICES_SQL` joins a Computer's
installations to the installation's stored client and uses
`current_computer_sql` only as a lifecycle filter. It does not verify effective
Computer ownership before displaying that client or using the installation as
a decision target. This is a concrete reader to include in the cross-client
transition review; its query alone does not establish the application's complete
client-access policy. Any page-query change also needs the required authorized
page-load comparison.
The Software Installations page and CSV also filter by the stored installation
client through `_INSTALLATION_FROM`; that join has no effective-ownership
predicate, and `v_device` exposes the stored client. A stale installation can
therefore appear under an old client's filter while ownership is dirty or
conflicted. Review both the page and export before allowing cross-client moves.
The ownership projector updates installation client copies when it settles on
a client; that update does not protect readers during dirty or conflict states,
which have no effective client. Reader fencing is therefore required before
the merge guard can be relaxed.
The current merge link writer retires and queues relationships on the absorbed
entity; the merge-reversal writer retires relationships on the survivor. That
does not by itself establish that every survivor relationship is reassessed after
a merge or that a successor relationship is created. Association changes also
invoke the scoped Computer-value refresh from migration 0400. The replacement
must account for both paths and their lock ordering before relaxing merge guards.
The local Software Installations page/CSV and software decision-target query
now require the installation client and stored Computer client to match a
resolved or decision-protected effective owner. Django's system check passes;
SQL behavior, concurrent streaming, and before/after page load time remain
unverified. The required authorized rehearsal environment has been requested.
The shared recent-installations reader used by Software Overview and Products
now applies the same owner check; those pages need the same rehearsal comparison.
Software product, publisher and detail readers now use a shared ownership
predicate for installation counts, client labels and decision targets. Their
SQL, result parity, concurrent-read behavior and page load time remain
unverified; the tenant-wide published Software overview has a separate producer
and is not covered by these reader changes.
The local `User` model contains tenant membership but no client membership,
and `ClientScopeMiddleware` derives the selected client from the URL. These
facts establish filtering behavior, not a complete user-to-client authorization
contract; confirm any external or separate authorization before claiming that
a particular user can no longer access another client's data.
The targeted refresh page previously listed Computers and accepted refresh
requests based on the stored client without checking effective ownership. Its
local GET and POST lookups now use the existing effective-owner selector.
The POST lookup is not a transaction-held ownership lock; review a concurrent
ownership transition separately. SQL behavior and the required page-load
comparison remain unverified, as PostgreSQL validation was skipped and no
authorized rehearsal measurement has been made for this change.

The incoming matcher's scoped candidate check currently defers unless each
candidate has a resolved or decision-protected effective client equal to its
stored client; its write path also locks and rechecks candidate scopes. The
issue action instead takes Computer IDs from saved finding details and invokes
the merge function; migration 0374's merge checks stored client IDs. No later
replacement definition was found in the repository migrations. These are
different authorization and freshness boundaries, not proof that a cross-client
merge is safe. Review the latest function definitions and all action callers
alongside ownership invalidation and reader transitions before changes.

Migration 0374 is the latest repository definition of merge and record split.
Merge also retargets every Computer-subject finding, rewrites device
participants and assessments, combines software installations, and records
the survivor's stored client; reversal uses the saved moved-finding and link
lists. A safe replacement must address those operations together with ownership
invalidation and reversal, not simply remove the saved-client check. Record
split accepts observation IDs and detaches their corresponding source subjects;
the caller must revalidate the proposed membership and decision at action time.
In particular, the current merge folds duplicate software rows only when their
stored clients match. After a cross-client merge, two rows for the same title
could therefore share a device but retain different clients; migration 0402's
ownership projector then sets both clients to the chosen owner, colliding with
the installation primary key. The merge/reversal and installation-identity
behavior must be resolved together before relaxing the SQL guard.
An authorized read-only production aggregate on 2026-11-22 at 20:57 UTC found
65 cross-client pairs sharing current usable serial or VM UUID evidence. Four
pairs had resolved or decision-protected owners, 215 overlapping installation
pairs, no identifier conflict, and no recorded separation in the checks
performed. No installation-subject finding was found on those overlaps. The
deployed installation primary key includes tenant, client, Computer and title;
the deployed ownership projector reassigns the installation client. These are
candidates, not proof of a complete matcher outcome or an actual collision: the
deployed merge guard still rejects cross-client merges. The inspection did not
execute a merge or validate the local implementation.
Installation identity is also a finding subject: migration 0135 identifies it
by `installation_uuid`, and condition readers join that UUID back to the
current installation row. Simply deleting one duplicate installation during a
cross-client fold can therefore strand its installation-subject finding. The
existing merge reversal restores links and selected device findings, but does
not restore the moved or folded software rows. Preserve the intended finding
history and re-evaluate both sides when implementing the merge and reversal.
The dedicated software installation history is keyed by source binding,
Computer and title; it does not contain `installation_uuid`. It cannot by
itself reconstruct an installation-subject UUID if the current row is deleted.

The historical-name lookup previously omitted the external and parent
namespaces and parent ID used by the association authority. The user approved
adding those fields to the live matcher join. The local change requires
PostgreSQL validation; the existing opt-in fixture lacks those columns and
would need updating before it can exercise the revised query.

Relay provenance remains unresolved at the value level. Hudu stores cards in
`canonical_extra.relayed` separately from its asset name and primary serial;
the attribute-claim projection records the observation, mapping, document kind,
and source field but does not establish a field's originating vendor. A card's
presence therefore cannot classify every field on that observation as relayed.
Hudu's `doc.asset` is excluded from identity-signal types, but that observation
type guard alone is not a general claim-level relay contract. Identify reliable
field origins and their enforcement before using relayed values as independent
proof; unknown provenance must not be assumed independent.
`load_device_map` currently indexes links by external ID after filtering by
source name; it does not include the source instance or external namespace in
the key. If distinct links share an external ID, the dictionary can silently
overwrite one destination. Hudu cards do not currently supply an instance ID,
so their lookup needs an explicit ambiguity outcome rather than selecting an
arbitrary Computer or labeling an ambiguous pointer stale.
The current matcher and resolver consume `canonical_data` identity fields
directly rather than claim records. Ninja's collector maps its device system
data and MAC addresses into those fields; this identifies their collection path,
not necessarily their upstream origin. A claim-aware replacement must cover both
incoming values and every candidate, contradiction, historical-name, and group
assessment path; filtering only corroboration would leave other paths inconsistent.
The existing attribute-claim projector only emits claims for observations with
an entity association, so those claims alone cannot assess an unattached record.
Any field-origin contract must also cover incoming observations before attachment,
retain source-record and field provenance, and represent unknown origin without
silently treating it as independent evidence.

| Current path | Where it differs |
| --- | --- |
| [Incoming matching](../../../ingest/identity/matching.py#L128) and [intake](../../../ingest/source_observations.py#L520) | The matcher reads database policies. Serial and VM UUID matches no longer require independent corroboration. Intake uses the shared matcher when it has inline client scope. The polling resolver primarily processes unassigned records, so ordinary matching leaves old groupings in place. |
| [Automatic merge planner](../../../ingest/identity/resolver.py#L1374) and [candidate projection](../../../ingest/identity/resolver.py#L536) | The automatic planner has its own shared serial or VM UUID rules; the local change removes its last-known identifier fallback for a Computer with no active records. The candidate projection can group by name and uses a separate name-plus-shared-MAC rule for strong candidates. |
| [Source-record assessment](../../../ingest/source_records.py#L1147) and [Computer split findings](../../../ingest/identity/findings.py#L623) | Source-record assessment previews the matcher with the record's own observation excluded, then applies additional guards for flagging another Computer. Split findings independently group by divergent serial, VM UUID, or same-source names, in that order. They can use hostname to place remaining records. |
| [Computer and group actions](../../apps/core/views.py#L18602), [Issues queue action](../../apps/core/identity_actions.py#L93), and [SQL merge and split](../../apps/core/migrations/0374_source_association_authority.py#L546) | The Computer page checks effective ownership. The group review uses saved clients and the issue action uses saved participants and flags. The shared merge checks saved client IDs, so it can reject a proven one-machine grouping that spans saved clients. It also retargets Computer findings. A confirmed split records an exclusion that affects later matches. |
| [Hudu lookup](../../../ingest/connectors/hudu.py#L182) and [ownership projection](../../apps/core/migrations/0402_computer_client_projector.py#L284) | A Hudu integration card names a Ninja record directly. Resolving that pointer can attach documentation. The attached Hudu record can independently contribute client evidence, even though the pointer supplies no independent proof that two Computers describe one machine. |

The motivating case and two additional current issues were examined read-only.
They showed why an incoming-record preview, a whole-machine assessment, and an
ownership result can differ. In one comparison, a Hudu record changed the
ownership conclusion reached from the identity streams alone. These samples
establish cases to reproduce in rehearsal. They do not establish a fleet repair
count. Keep case identifiers and live evidence in the approved private location.

## Read-only baseline and repair controls

On 2026-11-20, an authorized production measurement of the deployed Software
page returned HTTP 200 in 2.109 seconds for one complete authenticated internal
HTTP response (cache state unknown). This is a single-page baseline, not a
before-and-after comparison or evidence for other modified pages. The diagnostic
logged in and out normally and discarded response contents; its temporary files
were removed. Measure the changed page in a comparable authorized environment
and cover the other affected pages before claiming the performance gate passes.
On 2026-11-20, one authorized authenticated production GET per page returned
HTTP 200: Products 10.302 s, Installations 5.941 s, and Publishers 4.572 s.
These are complete internal HTTP response timings with unknown cache state; they
are deployed baselines only, not comparisons with the local changes. Response
contents were discarded and the temporary remote diagnostic files were removed.

The read-only preview implementation is complete locally. It uses the shared matcher
with source identity skipped and excludes the reviewed observation from candidate
names, identifiers, conflicts, and activity ranking. Current observations are
evaluated; inactive observations are listed as retained evidence rather than
proposed moves. The output is a new private JSON file outside the repository,
and the command has no apply option. Focused PostgreSQL matcher coverage passed
(15 tests), as did Python compilation, Ruff, plan-registry validation, and the
repository whitespace check.

An authorized production read-only hostname/client footprint query completed on
2026-10-21. It found 131 attached active records with exactly one peer and 40
with multiple peers, before serial/VM, roaming, operator-exclusion, and
simultaneous-agent guards. The guard-aware follow-up reduced the one-peer set
to 110 and retained 40 multi-peer review cases. Neither made a change; both
are discovery evidence only.

All 40 multi-peer records were confirmed covered by an open
`duplicate_device_records` or `identity_conflict` Finding; multiple records can
belong to one Finding group.

The original preview answers where a record could match under the existing
rules if it arrived unattached today. Include configured identity streams
across authorized scope, with inactive or withdrawn records available as
history. Pin source generations, the policy revision and explicit decisions.
Use the complete stable source identity, and exclude the record's own evidence,
including siblings, historical names and cached inputs, before assessing its
candidates. Keep the existing Computer eligible on independent evidence.
A unique same-client hostname match with no hard conflict can establish an
automatic attachment. Keep previews private, read-only, and scoped.

Before any apply, separately review record reattachments and whole-Computer
merges. Verify the combined resulting memberships for conflicting evidence,
competing destinations and cycles. Use an approved scope and digest for one-time
repairs. Recheck the pinned evidence, memberships and decisions at write time,
retain partial completion for retry, and verify reversal and dependent
projections without rewriting earlier evidence. The daily run requires a
reviewed automatic action policy before rollout.

## Proposed behavior

- **One assessment from current evidence.** Evaluate the stable source records
  and return same machine, different machines, or unresolved with the evidence
  and blockers. A matching usable serial or VM UUID and a unique same-client
  hostname can establish a match when no distinguishing evidence conflicts.
  Prior automatic links can identify candidates. Identify reporting sources and
  unknown upstream origin. Exclude self-evidence and stale evidence, and
  respect applicable explicit operator decisions. Assess the whole group so a
  chain of pair matches cannot hide a contradiction.
- **One Computer for a proven machine.** Use the same assessment in intake,
  reconciliation, and finding/action paths. Re-evaluate current attached and
  unattached records daily through Jobs. Automatically correct proven earlier
  automatic groupings and record the reason, rule revision, evidence, and
  membership changes. Keep ambiguous records available for their own findings,
  show what evidence is missing, and reassess when evidence changes. Preserve
  applicable explicit separation, attachment, and ownership decisions and show
  any current contradiction that needs review.
- **One active Ninja record.** After proving two Ninja records belong to
  the same Computer, use recent agent contact to select the active record
  when its predecessor is offline. Retain the predecessor and its association
  as history. Supersession survives fresh snapshots that still list the
  predecessor. All current readers and writers use the shared current
  assignment. A database uniqueness rule and the association authority
  enforce the limit. Unresolved or contradictory evidence returns for review.
- **Client ownership remains a separate decision.** A proven machine keeps one
  Computer when client evidence disagrees. The ownership projector controls
  effective client access. A known disagreement gets one actionable issue that
  names the conflicting source records and the correction needed at the source.
  An unknown mapping remains unknown. Verify dependent reads and writes before
  permitting regrouping across saved clients. The previous client must lose access
  when evidence or scope no longer authorizes it, including during transition.
- **Keep record relationships and reassess Computer relationships.** Source-record
  relationships, issues, and history keep their source-record IDs. End invalidated
  Computer-bound relationships and evaluate any successor from its resulting
  membership. Re-evaluate Computer issues and coverage for both sides, retaining
  historical issue ownership and avoiding duplicate actionable issues for one
  correction. Review the current SQL retargeting and split behavior against this
  contract. Re-resolve Hudu pointers and refresh affected derived state through
  existing projectors.

## Milestone 2 — Reversible cross-client installation projection

**Status:** Revised on 2026-11-23. The user confirmed that software
installations belong to source records and the Computer inherits current
inventory. This supersedes the previous design that ended and reminted
Computer installation UUIDs on a client or association change. The local
repair implementation uses parts of the previous design. Align it with
this contract before rehearsal or rollout.

### Installation identity and current inventory

- A source installation UUID identifies one source record and one
  canonical software title within a tenant. Enforce uniqueness on
  `(tenant_id, source_record_id, canonical_name)`. Software version,
  collection time, Computer association and client ownership do not form
  part of the identity. Keep the source installation UUID as reported
  attributes change and when its evidence becomes historical.
- Ninja software collection writes source-record evidence. A Computer
  inherits current software from its single active Ninja record as
  established by [ADR-0032](../decisions/0032-computer-identity-matching-and-merge.md#one-active-ninja-record-per-computer-2026-11-23).
  Superseded records retain their installations in history. The Computer
  projection is keyed by tenant, Computer, and title and carries the
  source installation UUID. If persisted, enforce that key in the database.
- Client ownership lives on the Computer. Resolve effective ownership at
  client-scoped reads, exports and actions. Installation identity and
  source inventory contain no client key. A change of owner updates access
  and applicable client decisions. Historical findings keep their recorded
  scope and subject IDs. A scope change can require a new finding episode
  against the same installation UUID, using the current client and evidence.
- Track listing completeness per source record. A confirmed complete empty
  list establishes absence. An omitted device, interrupted response or
  removal hold leaves the affected evidence unresolved. Current actions
  and notifications require a current, eligible installation under
  effective ownership.

### Merge, supersession and reversal

1. Take the tenant guard and version-check the reviewed machine evidence,
   ownership and source associations. Apply the merge, active Ninja
   selection and historic links through the shared association authority.
   Record the repair and enqueue projection and reevaluation for both
   Computers in the same transaction.
2. Invalidate Computer inventory and finding eligibility at the association
   change. Rebuild from the active Ninja record's latest eligible listing.
   Reuse its installation UUIDs and retain all source history. Until ownership
   settles, client-scoped access follows the effective-ownership contract.
3. On reversal, verify every saved move is still current before restoring
   membership. Recompute the active Ninja record and inventory on each
   resulting Computer. Use the latest source evidence, including installations
   added, updated or removed after the merge. Queue both former and current
   title keys for reevaluation. Retry the same revision idempotently.

### Worked overlap

Ninja records A and B each reported Title T while attached to different
Computers. Their source installations have UUIDs A1 and B1. The hardware
evidence proves the Computers are one machine. B has recent agent contact
and A is offline, so the merged Computer inherits T from B under UUID B1.
A1 remains accessible as history. A subsequent owner change keeps B1.
If the repair is reversed, each Computer inherits the inventory of its
resulting active record. If B removed T in a complete listing after the
merge, B's Computer has no current T after reversal.

### Compatibility and acceptance

- Migration 0376 and the collector already retain source-record inventory.
  Add stable source installation IDs there and move current installation
  decisions and readers to that identity. Audit current permission and
  performance requirements for every affected page and export.
- Preserve existing installation finding IDs and client scopes during the
  transition. A read-only production check found 525 distinct finding
  subjects. Of these, 499 had exactly one matching current source record,
  25 had a current Computer installation row but no matching source record,
  and one had no matching current installation row. No finding subject had
  more than one matching current source record. Validate mappings before use
  and keep unresolved legacy references addressable in history.
- Keep the legacy Computer installation merge, client rewrite, and
  client-keyed inventory writer outside the revised repair path. Review
  local migrations 0428–0431 and preserve the reusable membership, audit and
  ownership-fencing work. The superseded archive-and-remint workflow needs
  revision before any repair is rehearsed.
- Rehearse the repurposed-hardware overlap, complete empty and held
  listings, owner change, merge and reversal after a later software change.
  Verify that every live path uses one active Ninja record, source
  installation UUIDs survive ownership and affiliation changes, historical
  findings preserve scope, and client access follows effective ownership.

## Milestone 3 — Operational continuity through identity changes

- **Estimated identity:** Keep a verified assignment while supported.
  Give a reporting Ninja record with no verified home a stable working
  Computer when the matching evidence is inconclusive. Begin coverage from
  its own assigned records and label identity as estimated. Resolve the
  estimate automatically when evidence changes. Establish the client
  independently from source ownership evidence and preserve explicit
  operator decisions.
- **Legacy reversal:** An automatic serial merge can be undone when
  reliable current evidence establishes separate machines and the audited
  merge and source-link history identify the original anchors and records.
  Recheck the anchors, current memberships, association versions, and later
  operator decisions. Restore both Computers atomically, record pair-specific
  separation, and re-evaluate coverage. Preserve working assignments while
  recovery inputs are incomplete. No per-case operator approval is required.
- **Installation finding episodes:** The source installation UUID survives
  changes to Computer membership and ownership. End client-scoped current
  episodes when their scope ends, preserve their subject and history, and
  evaluate the same installation under its new effective client. Tenant-scoped
  episodes can continue under the same subject. A stable installation UUID
  does not carry the previous client's policy decisions into another scope.

Verify the repurposed-OS successor, a legacy serial-merge reversal, and the
ownership transition in PostgreSQL before closing this milestone. Daily Jobs
scheduling remains Milestone 4.

Local checkpoint (2026-11-23). The resolver can open an estimated Computer
from an independently attributed Ninja record and consolidate it into a
verified Computer when the current match, hardware and contact evidence agree.
Supersession and consolidation commit together. Guarded legacy reversal covers
one audited moved Ninja record. Migrations 0433–0435 project software, exposure
and suspicious-path finding episodes from the current source and effective
client. Repair publication queues affected titles using the source projection.
Legacy rows and finding IDs are retained for compatibility and history.
Rehearse the repurposed OS and estimate consolidation, legacy reversal, and
ownership transition in PostgreSQL. Compare affected page timings before
deployment. Migration 0435 rebuilds the software read models.

Production read-only rehearsal (2026-11-23). Production was at migration 0425.
The two Ninja records for the reimaged Computer shared serial, hardware address,
and independent client evidence. The older agent was offline and the newer
agent had later contact. They retained 128 and 455 current source inventory
rows, respectively. The ownership replay on one production installation kept
the installation UUID and changed the finding episode key and effective access.
These SELECTs exercised the evidence and derived identities.

The draft reversal returned zero candidates for the known bad merge. The audit
has two moved link IDs and five observation IDs. Four live links on the survivor
have original absorbed-anchor history, and three of those live link IDs differ
from the old audit IDs. The fifth observation has historical membership and no
current link. Recover and pin membership from the audit observations plus
source-link history before applying the split.

Traced SQL on the reimaged Computer showed 2.62–2.85 seconds of execution for
the draft inventory projection versus 1.95–3.46 milliseconds for the legacy
query in two repeated paired runs. A read-only probe that scoped device links
before evaluating lifecycle ran in 5.15 milliseconds. Rework the production
reader and compare full-page timing after the revised migrations can be
rehearsed. No production data or schema was changed.

Revised read-only replay. The reversal query selected the target merge once,
recovered all four live links with pinned input and association versions, and
kept the unlinked fifth observation as history. The revised scoped inventory
query returned 455 successor installations. It ran in 9.28–9.68 milliseconds
versus 1.20–4.82 milliseconds for the legacy query in two paired runs. Ruff,
Python compilation, Django checks, migration drift, and plan registry checks
passed. The mutation path and full-page performance remain unverified.

## Implementation steps

1. **Agree on the rules.** Trace runtime callers and current policy rows. Resolve
   the difference between the existing same-client matcher and merge contracts
   and the proposed separation of machine identity from client access. Decide
   how stale or explicitly overridden actions are checked and audited. Record
   approved changes to the applicable decision records, including ADR-0049,
   ADR-0050, and the ownership contract in ADR-0052.
2. **Unify assessment in preview.** Reuse the current normalization, policy,
   association, and candidate lookup code in `ingest/identity/`. Compare shared
   results for intake, already attached records, proposed merges/splits, and
   findings in `ingest/source_records.py` and `ingest/identity/findings.py`.
   Replay the motivating case and two recent issues in an authorized read-only
   environment. Compare the shared assessment with the original preview before
   proposing repairs.
3. **Wire the existing writers and reviews.** Revalidate current evidence and
   applicable decisions at action time. Keep `set_source_association` as the
   association writer. Review Operations merge and split SQL, issue actions,
   ownership guards, and projections together. Retire overlapping evidence
   rules when their replacement is verified. Show a concise reason and the source
   evidence in issue reviews. Preserve any authorized operator override as an
   explicit audited choice.
4. **Rehearse writes and daily scheduling.** Reuse the existing Jobs workflow
   and locking model, with bounded transactions, drift checks, retry, and restart
   behavior. Review runtime packaging. Verify a scoped merge, split and reversal,
   then rehearse a full
   preview and compare planned changes, lock waits, and runtime in an authorized
   environment. Obtain rollout and production-change approvals before enabling
   automated repairs.

## Acceptance

- The same evidence produces the same machine conclusion across incoming
  matching, reconciliation, split and merge review, and identity findings.
- Reused serials, same names, conflicting identifiers, roaming records, relayed
  evidence, and ambiguous groups do not create false merges or splits. Explicit
  decisions survive and later contradictions remain visible.
- A reimaged Computer with matching hardware and an older offline Ninja node
  uses only the recently contacted node in all live paths. Repeated complete
  snapshots that still list both nodes preserve the older link as history.
  Conflicting hardware evidence or unresolved activity cannot create two
  active Ninja assignments. The history retains the supersession reason and
  original source-record IDs.
- A proven machine with conflicting client records ends up as one Computer and
  one actionable client issue. Cross-client reads, writes, exports, and issue
  actions remain protected before, during, and after correction.
- Record relationships and findings retain their IDs. The old and new Computer's
  coverage and relationships reflect their current membership. Hudu pointers
  converge when their underlying records do. The audit supports a scoped reversal,
  and a repeated run leaves unchanged evidence and memberships alone.
- Focused existing checks and small synthetic PostgreSQL cases pass locally,
  including source namespaces, returning records, and stale decisions/actions.
  Fleet behavior, runtime, and lock costs are verified in rehearsal. Record
  results, limitations, and approval scope before rollout.

## Checkpoint

Resume review (2026-11-23). The shared Ninja successor selector now uses the
matcher's MAC normalization and placeholder rejection. Missing, malformed, or
timezone-free contact times leave succession unresolved. This affects incoming
replacement, estimated consolidation, existing duplicate repair, and the scoped
review command. Ruff, Python compilation, CLI help, the Django system check,
and the offline model migration-drift check passed for that change.

The local resolver already calls the bounded duplicate and legacy reversal paths.
Draft migrations 0428–0433 now compose cross-client membership repair with
source-owned inventory. Under the reviewed transaction's tenant guard and
membership locks, a pair with two primary Ninja links must prove one successor
from its hardware and agent contact. The repair closes the predecessor before
moving memberships. Reversal checks the saved post-repair versions, moves the
current associations first, and restores the predecessor to its original
Computer. Ambiguous succession or changed membership fails the transaction.

The repair retains source installation UUIDs, archives legacy finding context
in its recorded scope, and queues affected titles from current source inventory.
The ownership projector preserves repaired Computers' legacy software and
decision scopes. The collector bypasses the legacy Computer writer for these
repairs and publishes ready queue entries even when a restored Computer has no
active Ninja inventory. Rehearse both predecessor positions, ambiguous contact,
stale reversal, latest source inventory, and effective client access. Focused
Ruff, Python compilation, Django checks, migration graph and model drift,
registry validation, and the Git whitespace check passed.

Targeted PostgreSQL 16 rehearsal passed in a disposable synthetic database.
The actual archive, membership and successor functions completed merge and
reversal with the predecessor on either Computer. The checks covered equivalent
MAC formats, title changes after merge, preserved legacy inventory, and
rollback for ambiguous succession and stale reversal. The scratch database
was dropped. The fixture substituted the association writer and tenant guard.
The development database is at migration 0391. Full migration execution,
real association triggers and role permissions, and comparable page timings
remain open.

Static review found references to `metabase_ro` in seven pending migrations.
Those references were removed because migration 0359 drops the role. The
isolated local migration attempt stopped during container startup and applied
no migrations. The temporary container was removed. The user directed that
local testing stop. Continue validation in an authorized non-local rehearsal.

Authorized am-ch-01 rehearsal. Fresh bootstrap stopped at historical
migration 0134 because the bootstrap ordering had not created
`finding_types.creates_device_exposure`. A separate disposable instance
restored only schema and the Django migration ledger from the existing
0425 rehearsal baseline. Migrations 0426–0435 applied successfully after
0435 was corrected to remove inherited grants to the retired Metabase role.
Catalog checks verified Operations repair execution, private successor
execution, read-only access to the source installation projection, and the
enabled Ninja association guard. No customer rows were copied.
The disposable Docker resources and staging files were removed. A read-only
check confirmed live production remained at 0425. Full repair execution
under real roles with linked synthetic rows, migration rollback, and comparable
page timings remain open.

Follow-up real-role rehearsal on am-ch-01 applied 0426–0435 and ran the
reviewed merge and reversal as `operations_app` with synthetic source records,
the real tenant guard, and the real association writer and triggers. Both
predecessor positions passed. In the second case the projection returned both
original installation UUIDs and client scopes after reversal using seeded
effective ownership. The fixture did not exercise ownership settlement itself.
The disposable databases and networks and staging files were removed.

The schema-only am-ch-01 rehearsal applied 0426–0435, reversed to 0425, and
reapplied through 0435. Catalog checks confirmed the old exposure view after
rollback and the source projection and Ninja link guard after reapply. This
check used an empty repair history. The migrations separately guard rollback
when historical repair data would be lost. The temporary resources were removed.

The existing rehearsal database has representative data volume. With approval
to copy it within am-ch-01, compare the deployed baseline and reviewed
candidate on the same rehearsal data, request scope, and runtime roles. Include
Software overview, Products, Installations, Publishers, Computer detail,
and the affected identity and finding review pages. Capture full response
status and elapsed time, consume the response body, and retain no response
content or customer identifiers. The existing deployed measurements have
unknown cache state and cannot establish a non-regression on their own.

Two-minute in-place rehearsal on am-ch-01. The Software Installations first
page returned HTTP 200 in 6.628 s at 0425 and HTTP 500 after 19.696 s with the
worktree candidate and migrations through 0435. Each run used the same
rehearsal data, a synthetic staff session, and the Operations runtime role.
The harness set a 10-second statement timeout and retained status and elapsed
time only, so the candidate error cause is unconfirmed. The single pair is a
failed candidate request, not a completed performance comparison. The
rehearsal database remains at 0435. Temporary credentials, user and staged
files were removed. Diagnose the candidate failure before timing the other
pages. Live production was outside this run.

Follow-up identified the timed-out statement as the Installations page-row
query. The deployed rehearsal plan repeated source-instance scans inside the
per-Computer link lookup. The candidate now resolves the source instance after
selecting the lone primary link. The Installations reader also uses the
projection's existing ownership check and joins the Computer table for names
and serials. The revised view was applied only on the rehearsal database.
The full page returned HTTP 200 in 14.486 s. The count took 1.933 s, page rows
2.849 s, and the three filter-option queries 3.715, 1.898 and 2.767 s. Repeated
projection scans remain a regression against the 6.628 s baseline. Optimize
their reuse before widening the page timing comparison or releasing.

The Installations domain reader now derives the count, rows and filter options
from one current inventory snapshot. CSV shares the source and filter contract.
The updated full page returned HTTP 200 in 6.338 s, including 5.015 s for its
inventory query. Empty search, the last decision-filtered page, and empty CSV
returned HTTP 200. This was a single representative sample. The user rejected
the latency. Software Overview's existing publication stores tenant summary
counts and cannot supply current installation rows or filter options. The next
design decision is whether to authorize maintained installation state and how
to fence its client access and freshness. Live production was untouched.

The user authorized the maintained reader with a first-page target under
two seconds. Migration 0436 maintains the unfiltered first page and filter
options. Trigger-backed transaction invalidations fence access to the
published snapshot. Software decisions remain live. The existing Software
Overview job invokes the independent publication after its own refresh.
Filtered and later pages, CSV, and a missing or invalid publication use the
live reader.

Migration 0436 applied on the existing am-ch-01 rehearsal database.
Publication as `ninja_ingest` and protected read as `operations_app`
passed, including wrong-tenant denial and withholding the snapshot after an
ownership change within a rolled-back transaction. A no-op update kept it
readable. The default page used the publication and returned HTTP 200 in
1.306 s and 0.621 s. The production scheduler was not exercised. Steady-state
publication availability, filtered request performance, and the other
affected pages still need validation. Temporary resources were removed.

Scheduled Jobs follow-up on am-ch-01. The expiry admission and governed claim
selected Software Overview. The restricted ingest role hit the existing
`software_overview_inputs` permission denial; a production-equivalent
effective role reached the 18-second statement deadline in Overview work.
The Installations publication now runs first as an independent transaction.
The replay invalidated the previous snapshot, admitted and claimed the same
job, and confirmed a current publication as `operations_app` after the
later Overview timeout. This verifies one scheduled refresh and isolation
from a later failure. It does not validate sustained availability or successful
Overview completion. Temporary staging and login were removed. No grants or
live production settings changed.

Candidate-only page smoke on the existing 0436 rehearsal baseline.
Installation Finding Review returned HTTP 200 in 0.835 s. Publishers returned
HTTP 200 in 7.570 s. Products reached the 12-second request cap, and
client-filtered Issues hit its SQL deadline, returning HTTP 500 after 10.356 s.
Computer detail failed because `device_session_current` was unpopulated on
the rehearsal database. Software Overview rendered its uncertified state.
These results identify rollout blockers and rehearsal setup gaps. They do
not constitute paired timing comparisons. Temporary files and login were
removed. Live production was outside the run.

Scope reconciliation. A bounded paired Products title-aggregate probe on
the same rehearsal database measured the legacy input at 1.957 s and the
PLAN-015 source input at 5.862 s. Removing the redundant Computer and
ownership joins reduced the source query to 3.901 s. The Products reader
now uses that simplified query and retains the source projection's current
ownership and lifecycle fence. The full page has not been retimed. This
component still needs a PLAN-015 comparison before rollout.

[PLAN-056](../../../docs/records/PLAN-056-filtered-issues-2026-11-19.md)
documented the client-filtered Issues timeout before PLAN-015. PLAN-056 owns
the broader query performance work. PLAN-015 owns access parity and any
incremental cost from its installation-subject guard. Computer detail and
Overview still need valid rehearsal inputs to assess the affected readers.

Resume comparison on am-ch-01. On the same 0436 rehearsal database and
`operations_app` role, the `11d880b5` Products handler rendered HTTP 200 in
8.620 s. The worktree handler stopped at the 10-second SQL deadline in its
main title query, 17.698 s into the request. Disabling JIT still reached the
same deadline, 16.595 s into the request. These are same-schema, default-page
handler measurements with full rendering and discarded response bodies. They
exclude HTTP transport and do not establish cache-controlled performance or
filtered and CSV parity.

An isolated query variant deferred decision joins until after pagination when
no decision filter was active. The main query completed in 3.663 s, but the
full handler reached its 25-second deadline after additional inventory and
display-name reads. A read-only distinct-version category probe completed in
2.122 s and returned no linked category rows on this rehearsal data. It did
not validate category parity on populated data. No variant was adopted. The
next Products change needs to avoid repeated source-projection reads and be
compared on data with populated category and decision inputs.

In one read-only snapshot, the client-scoped Issues summary returned the same
38 groups with the installation guard enabled and bypassed, in 1.806 s and
1.212 s, respectively. This single ordered pair cannot isolate guard cost:
572 stored installation findings were visible and none had a stored client.
Using a current installation and synthetic finding inputs, the exact predicate
allowed the current owner and resolved history, denied a wrong client and a
missing installation, and left an unrelated device issue eligible. These probes
used the runtime role. They do not exercise a populated client-scoped finding
set or establish end-to-end Issues access parity.

Follow-up read-only rehearsal combined the client filter and exact live
installation guard against seven synthetic finding rows and one protected
current installation. All cases passed. The current owner saw an open issue
in its scope. Neither client saw the open issue recorded in the old scope.
Resolved history stayed available only in its recorded client scope. The
fixture also denied a missing installation. The database still has no durable
client-assigned installation findings. Computer detail still lacks a populated
session projection, and the protected Software Overview read remains
uncertified. Neither missing input was changed during the check.

Products performance fix. One materialized read of the ownership-fenced source
projection supplies the active title rollup, both taxonomies, and the latest
retained source spelling for visible titles. Taxonomies deduplicate the
title/product pairs before enrichment. Decision joins run after pagination
unless a decision filter needs them to select the page. The reader skips
Overview summary queries because neither Products nor the CSV exports consume
that summary. The endpoint-security filter and the displayed `av` chip use the
same key. An empty risk band uses an empty match set.

Read-only am-ch-01 rehearsal against 0436 as `operations_app`: default
Products returned HTTP 200 in 6.268 s and 6.174 s, bracketing the `11d880b5`
baseline at 8.562 s. Decision-filtered, category-filtered, and empty-search
requests returned HTTP 200 in 5.661 s, 6.458 s, and 4.814 s. Products and
Overview CSV returned populated responses in 6.589 s and 7.134 s. A synthetic
relational fixture verified both populated taxonomies, their combined filters,
an investigate decision, distinct active Computer and client counts, the
latest retained spelling, and exclusion of a foreign-tenant row. Django system
checks passed. These are rendered-handler measurements. The populated
taxonomy fixture verifies behavior; it does not establish timing at production
category volume. No migration was required for the Products fix.

Remaining page comparisons on the same 0436 rehearsal database as
`operations_app`. Installation Finding Review rendered in 0.778 s against
1.081 s on `11d880b5`. One identity Finding Review rendered in 0.042 s against
0.074 s. Both samples returned HTTP 200. These samples do not cover restricted
viewers or review actions.

The initial Publishers candidate took 7.490 s against 6.408 s. Publishers now
uses the source projection's ownership fence directly, aggregates distinct
counts with grouping sets, and renders one form for the three actions per
publisher. Bulk checkboxes identify their form explicitly. A repeatable-read
comparison matched all 4,462 publisher rollups exactly against the previous
source-based query. The final handler returned HTTP 200 in 4.720 s and 4.288 s,
bracketing a 6.895 s baseline. Both candidate samples were also faster than
the fastest earlier baseline sample, 4.800 s. Form structure and five
comment and confirmation cases passed. No decision actions or migrations ran.
Computer detail and Software Overview still need valid rehearsal inputs.

The user directed light testing after these comparisons. Reuse the existing
rehearsal and its recorded evidence. Defer a separate database copy and the
associated fixture writes and refreshes. Representative client-assigned
Issues, Computer detail with session data, and the certified Overview path
remain unverified.

Read-only rollout review. The draft Django chain is linear from 0425 through
0426–0436. Existing Dockerfile copies cover all eleven migrations and the new
runtime modules in `ingest/`, `operations/apps/`, and `shared/`. Those new files
are untracked and must accompany the existing code when preparing a commit.
The worktree also contains other plans' work, so review and stage only the
PLAN-015 paths and hunks.

An approved production push applies the Django chain at Operations startup.
0427 changes stored serial and VM UUID match policies. 0435 rebuilds the
software exposure materialized view and marks the previous Software Overview
publication uncertified. 0436 installs the new Installations publication.
Once the schema is present, the existing scheduled identity resolver can run
bounded automatic Ninja successor selection and legacy serial-merge reversal.
Rollout approval must cover all eleven migrations and those automatic repair
effects. The earlier schema-only rollback does not cover retained repair data:
the archival and supersession migrations refuse rollback with history, and
the pending-inventory migration refuses rollback while publication is pending.
This review used tracked and worktree files only. It did not verify current
production state, apply migrations, schedule jobs, or rerun the tests.

The revised Milestone 2 design governs new work. Migrations 0428–0431 and
the reviewed repair action remain local drafts built against the earlier
Computer-installation model. Retain useful membership versioning and audit
work. Replace the archive-and-remint behavior with source-owned inventory
and the shared active Ninja assignment before rehearsal. The implementation
notes below record earlier work and its validation limits.

Local migration 0432 prepares the historical-only Ninja transition. The
private operation checks the pinned source versions and agent contact
ordering, closes the old Computer association through
`set_source_association`, and records the successor and audit action.
A link trigger blocks a superseded record from becoming current again. It
also serializes new Ninja assignments by Computer and rejects a second
current link. The matcher defers occupied Ninja targets before writing,
and the resolver skips superseded rows when selecting work.
The normal resolver now passes an occupied Ninja match to the shared
successor selector. A proven incoming successor with clear agent contact
replaces the older links and attaches in the same guarded transaction,
without individual operator approval. An unresolved successor uses the
source-record identity review flow within its effective client scope. The
scoped `ingest.ninja_record_supersession` command shares that selector and
writer for rehearsal and reviewed repairs. Existing duplicate groups still need
reviewed reconciliation, and source-record findings and inventory readers
still need the revised historical scope and source-owned projection.
Compilation, Ruff, Django checks, migration graph loading and CLI help
passed. PostgreSQL concurrency and automatic apply have yet to be rehearsed.
No stored source records were changed.

The local Computer merge review and reversal now call 0430 for cross-client
repairs. The manual actions use the existing Computer lifecycle permission.
The merge review requires a shared usable hardware identifier, a signed
digest of both owners and source memberships, and a reason.
The POST holds the tenant,
Computer, ownership and source-subject locks, rechecks the digest and machine
evidence, and uses the reviewed membership in the repair transaction. Reversal
dispatches by the audit action and uses the saved post-merge versions. Same-client
repairs continue through their established functions. Compilation, focused
Ruff, Django checks, migration graph and template loading passed. An
overlapping-installation repair and reversal have yet to run in PostgreSQL.
The extra merge-approval permission was removed from proven cross-client
merges and reversals on 2026-11-23. Existing conflict overrides use that
permission. Separate rollout approval applies to automatic repairs as a
feature. Proven automatic repairs do not require an individual operator approval.
The shared writer accepts audited process or system actions from the ingest
role as well as operator actions from the Operations role. The merge review
requires that the signed evidence still matches, without a clock-based expiry.
Migration 0431 preserves the existing client IDs on Computer findings when
ownership is projected for an anchor involved in a cross-client repair.

Local migration 0430 connects archive and membership work to the private
merge and reversal transaction. It saves the merge or reversal and queued
inventory for both Computers, and invalidates ownership and relationship
projections before commit. Ninja inventory collection records fresh listing
completeness, skips the legacy Computer writer for pending repairs, and
attempts a bounded rebuild for affected pending Computers. The rebuild
requires a settled effective owner and fresh complete listings from the
applicable contributors in that owner's scope. Source records with recorded
inventory or listings can contribute regardless of entity type. A record
independently scoped to a different client does not participate in the new
client's software projection or block the eligible listings from publishing.
The rebuild selects one report per title, inserts new current
installation subjects and history intervals, and queues title reevaluation
before consuming pending work. A missing or held report stays pending.
Compilation, Ruff, Django checks and migration graph loading passed.

Verify the actionable client conflict and historical Computer finding scope
when rehearsing the reviewed operator entry points.
Explicit empty listings, database-wide title uniqueness, catalog relinking,
refresh execution fencing, and the overlap and reversal rehearsal remain
open. Migrations 0428–0430 have not run against PostgreSQL. No production
repair has been performed.

Local migration 0428 prepares an append-only, tenant-scoped installation
archive. Its private retirement function requires a matching explicit repair
action, archives both affected Computers' old subjects, closes their open
Computer inventory intervals, and returns the affected titles in one
transaction. Rollback refuses to drop a populated archive. Finding review
can show an archived subject in its recorded scope, and state, refresh and
bulk actions require current effective installation scope. The existing merge
authority has yet to call the retirement function. Neither 0428 nor the new
history reader has been exercised in PostgreSQL. Compilation, focused Ruff,
Django checks, migration graph loading and template loading passed.

Local migration 0429 prepares a private operation that retires installations
and moves source memberships through `set_source_association` in one
transaction. It checks the exclusive tenant guard, locks reviewed source
subjects, and rejects a changed or incomplete merge snapshot. For reversal it
reads the saved post-merge versions from the original merge record and rejects
the whole reversal if any version or association changed. It returns the new
versions and affected title keys to the caller for durable recording and
reprojection. The caller still needs to fence and recheck both Computers'
machine evidence and ownership, save the merge or reversal, and enqueue the
projector in the same transaction. 0429 is private to the migration owner.
Ruff, compilation, Django checks and migration graph loading passed.
PostgreSQL execution remains unverified.

Milestone 3 is in progress. Attached reassessment moves now take the existing
transaction-held ownership locks for both Computers, require the same stable
owner, and then rerun the matcher before writing. The identity Job no longer
invokes daily reassessment while repairs await rollout. Current
installation-subject findings in client Issues selection, client workspace
counts and related software findings require an active installation under
effective ownership. The software assessor drops the live Computer participant
while the installation's owner is unresolved or has changed, leaving its
response unavailable until valid evidence returns. The client Issues history
path still accepts resolved findings. The shared Ninja refresh link lookup checks current
ownership and the client captured by the action when available. Its Jobs
worker still needs an end-to-end ownership and membership fence.

Compilation, focused Ruff syntax and name checks, and Django system checks
passed. Full lint has pre-existing complexity findings. The new read queries,
concurrency and required comparable page timings remain unverified. Next wire
version-checked merge and reversal to the archive and source inventory
projector before enabling cross-client writes.

The hostname guard now uses the split review's recent-agent rule across matching,
merge planning and review, and duplicate findings. Matching checks the full
proposed group with the incoming report when its timestamp is available.
Matcher revision 8 and source-record assessment revision 10 identify the new
behavior. Ruff, compilation, Django system checks, plan registry validation
and the Git whitespace check passed. The runtime SQL and original case replay
remain unverified. The workspace contains checkpoint summaries but no saved
source rows for the original cases.

On 2026-11-22, an authorized read-only production query sampled the most recent
split finding for each available dividing signal. The hostname case had nine
current identity reports and the serial case had four. The query exported only
case-local equality keys and relative ages. Local replay of the shared
assessment and split classifier reproduced both recorded dividing signals.
No VM UUID split case was returned by the bounded query. This replay exercised
the shared Python rules.

A separate read-only production replay used the local candidate and a single
repeatable-read snapshot of the same two Computers. Candidate matching and
merge planning reported hostname and serial conflicts, matching the two findings.
Merge evidence review blocked both and reassessment returned all 13 records for
review. Split evidence review accepted the hostname proposal and required a
refreshed serial proposal. The probe used a read-only ownership lookup in place
of the split action's row lock. It exercised evidence reads, not association or
operator writes, and did not exercise positive, ambiguous, VM UUID, or
operator-separation cases. The observed active ingest role could read identity
decisions; the restricted `ninja_ingest` role got SQLSTATE 42501 for that read.
Operations evidence queries ran as `operations_app`. No production changes
were made, and only aggregate results were returned for the checkpoint.
Eight additional open two-member merge candidates exercised the Operations
review. Four conflicted, three had no qualified proof, and one lacked sufficient
current evidence. A follow-up bounded 94-pair search found six pairs with shared
usable identifiers, all assessed as the same machine by serial in merge review.
A prior merge reversal triggered the explicit separation guard. A live-data
hostname-only replay returned unresolved for multiple eligible Computers.

Milestone 1 evidence validation is complete. For the six serial pairs, merge
planning and review agreed. The matcher agreed with the first two pair checks,
and both scoped reassessment records matched by serial. The recorded reversal
blocked matching, merge planning and merge review. Production had 1,965
VM UUID observations, all inactive, including 1,633 attached to Computers.
The database-backed matcher and planner excluded the sampled withdrawn
records. A read-only query exposed two of those actual reports as active
solely during replay. An equal VM UUID produced a match, while divergent UUIDs
produced `vm_uuid_conflict` in matching and planning and blocked merge review.
The same divergent reports grouped into one Computer produced a VM UUID split
finding that split evidence review accepted. Replays changed no production
rows and exercised a read-only substitute for the split ownership lock.
The old Ninja collector populated this field with node UIDs. The VM UUID
replay exercised the matcher branch with historical values. It did not verify
collection of genuine hypervisor UUIDs.
Association writes, write-time locking and the restricted ingest-role
deployment issue remain open for later gates.

The duplicate survivor and automatic merge planner now require the selected
identifier type to be present in every member of the candidate group. The same
shared assessment supplies identifier decisions for merge review, split review,
and duplicate findings. Merge review records the identifier conclusion and its
reason in the action evidence when review permits proceeding. Matcher
revision 7 invalidates reassessment reports prepared under the former rule.
Ruff, Python compilation, Django system checks, plan registry validation and
the Git whitespace check passed. The saved case payload was unavailable in the
workspace. Replay remains open. PostgreSQL and test
suites were skipped under the current user direction.

The preview, source-record assessments and reassessment use one
sibling-and-companion exclusion reader. The merge planner selects configured
identity-signal types and uses the shared identifier rule. Reassessment apply explicitly rejects
records that are no longer active or are already attached. These recent changes
passed Ruff and compilation but have not been validated against PostgreSQL.
Automatic merges now recheck the shared identifier on both Computers and record
its reporting observations and sources. A scoped write-time recheck also revisits group
contradictions and operator separations for each pair. Field-origin proof,
evidence fencing and concurrency remain unverified; the planner is not the
complete shared assessment.
The local automatic merge no longer locks every Computer's ownership row for
candidate discovery. It locks the selected pair and rechecks effective ownership
and evidence before writing; the impact and lock ordering need rehearsal.
Merge planning and Issues actions now pass serials, VM UUIDs, active streams and
separations together through one shared group-conflict assessment. This unifies
that decision with the candidate-review and merge write-time pair checks, but
not yet discovery, provenance, or the complete matcher.
When a serial or VM UUID is reused across conflicting groups, the merge planner
can now merge a subgroup sharing the distinguishing identifier; records missing
that identifier are not assigned to one of the conflicting subgroups. The new
planning behavior has not been run or tested.
Automatic and Issues merges record `conflict_rule_revision` for the shared
contradiction checks. This is not a revision or digest of the full assessment,
source policy, or provenance contract, which remain to be implemented.
The incoming matcher now checks serial and VM UUID contradictions for every
matching tier, including contradictions within the candidate group even when
the incoming record lacks that identifier. This change remains unvalidated
against PostgreSQL.
The matcher passes each current candidate record separately to the shared
conflict assessment. Simultaneous same-source reports alone do not establish a
conflict under the user's clarified rule.
Its source-identity tier excludes withdrawn observations and now requires the
complete namespace, parent and external ID from intake and the polling resolver.
Callers without that key skip the shortcut. Serial, VM UUID, conflict and name
exclusions use the complete key when supplied. Preview and reassessment callers
now pass it through. Callers without it retain conservative exclusions; the SQL
and compatibility of the changed name-reader shape need database review.
The local polling resolver and promotion path now exclude each managed record's
own observation and companions through the same reader as preview; records
without a managed subject are deferred. Promotion does not create a Computer
when matching found candidates but could not select one; the SQL and runtime
behavior remain unvalidated against PostgreSQL.
VM UUID candidate and conflict lookups now trim whitespace and ignore empty
values, matching the existing merge and split normalization.
Serial and VM UUID contradictions apply across intake policies. The earlier
same-source-live blocker was superseded by the clarified rule above: simultaneous
reports alone do not establish different machines. Roaming observations are
excluded from hardware identity evidence. The complete assessment and policy
contract still need PostgreSQL validation.
The disposition writer rechecks current record versions and runs the shared
matcher before association. It no longer blocks all later moves when an unrelated
record changes the tenant-wide generation. Association history records the
matcher and compared source evidence. Its SQL and concurrency remain unvalidated.
Reassessment previews now fingerprint policy rows, identity types and enabled
serial rejections, and both apply paths reject a missing or changed fingerprint.
The fingerprint and proposed reference lock also include source-name rules,
which `record_name_forms` reads. Lifecycle mappings also affect name eligibility
and are now included in the proposed write-time reference lock. They are not yet
fingerprinted; ingest lacks direct read access, so detecting changes between
preview and apply remains unresolved and needs database review. The matcher is
re-run under the lock, but that does not establish full preview equivalence.
The fingerprint now includes declared matcher and conflict rule revisions, so
a correctly bumped revision also invalidates an older preview. This manual
revision mechanism does not itself detect unversioned code or database function
changes and does not complete the evidence-fencing contract.
Standalone preview reads serial rejections and identity types from its snapshot;
the matcher receives an immutable rejection set for preview and apply instead of
the process-global cache. Apply reloads both before matching. Local migration
0426 adds a non-waiting, transaction-scoped SHARE lock on the three reference
tables before the fingerprint check, preventing edits during an action; lock
permissions, contention and ordering are unvalidated. The preview now records
the source generation; apply checks it under lock and advances its expected value
after each committed association, relying on the deferred trigger's one increment
per tenant and transaction. External drift returns later actions for review.
The command saves the preview and a run ID before applying, then atomically
replaces that file with the completed report. Each local association write now
records the run ID, preview digest, matcher and preview generation in history.
The local `--recover-from` path reads that history without writes and reports
whether each scoped action is current, changed later, or not recorded. It checks
the saved preview digest and rejects mismatched run history; it does not resume
writes automatically. Recovery, the generation protocol and
PostgreSQL behavior remain unvalidated.
The command now defaults to preview and requires `--apply` plus the reviewed
preview digest and explicit `--subject-id` scope to attempt writes. The preview
rejects unavailable or unsupported scoped records, and the digest covers the
scope and report. The command is not authorized for production use; these gates
do not satisfy the full repair and concurrency contract and need PostgreSQL
validation.
Migration 0370 grants runtime roles only SELECT on the input generation table,
while a row lock also requires UPDATE privilege. Local migration 0426 now
prepares tenant-checked security-definer functions to lock the generation and
subject rows without granting table writes. Both lock attempts use NOWAIT: an
ingest transaction can hold a subject while its deferred trigger waits to update
the generation, so waiting for that subject while holding the generation would
deadlock. A busy lock returns the action to review. The effective ingest role,
remaining lock ordering and PostgreSQL behavior still need validation.
Stale or ambiguous name evidence no longer counts as a proven machine
contradiction in source-record assessment; it remains unresolved evidence.
Portable identifier and group conflict checks now live in
`shared/identity_evidence.py`, which both service images package. Incoming
matching, merge planning and findings now use the same contradiction function;
it checks all identifiers in the combined group, including conflicts already
within either side. A shared same/different/unresolved result now wraps those
checks and is used for the intake and automatic-merge decisions. Evidence
qualification, including field origin, is still separate and incomplete; the
three-way result is not yet the full universal assessment. Hostname policies
must require client scope. Split assessment now calls the same shared result for
serial and VM UUID contradictions; intake and duplicate findings route their
contradiction conclusions through that result as well. The Issues merge action
locks effective ownership and rechecks current identity-type records, conflicting
identifiers, online streams and operator separations through the safe metadata
view. Merge and split reviews now both use `record_name_forms` for current
source names. It refuses missing or restricted evidence and records the checked
observation IDs in the merge audit. This is a conflict guard, not a full
same-machine proof; other Operations actions and concurrency still need review.
These changes remain unvalidated against PostgreSQL.
The merge-candidate group POST now locks and rechecks its saved candidate,
effective client scopes and current group conflicts, and records the checked
observation IDs and conflict-rule revision. The group review GET now limits
its members to the candidate's current effective client; its page load time
must be compared in the authorized rehearsal. Direct Computer-page merges now
recheck current group evidence. An authorized operator can explicitly override
conflicting or incomplete evidence with a reason recorded in the merge audit;
an existing separation decision remains protected. Restricted evidence and
unavailable rejection policy are not overrideable through this path. Split
findings and the Issues split action now use the same current-record grouping;
the action compares dividing values and memberships with the saved proposal.
Ambiguous name-only placement stays unassigned and equal-ranked groups use a
deterministic tie-break. Write fencing and cross-client behavior remain
unverified. The changed actions and pages have not been validated against
PostgreSQL or for page load time.

Partial local matching and preview changes remain unvalidated against PostgreSQL.
The claim-level relay contract and cross-client access contract remain unresolved.
Next, determine reliable field-origin evidence and review the client-access
transition before wiring writers; compare the shared assessment with the baseline.
The project virtual environment runs the focused matcher policy tests (8 pass),
Ruff, and compilation. Isolated synthetic PostgreSQL checks passed for excluding
documentation serials from conflicts and documentation MACs from hostname-plus-MAC
qualification; the scratch database was dropped. A synthetic loose-name check
also passed. These checks do not establish claim-level origin or validate the
complete preview. Isolated synthetic PostgreSQL checks also passed for full
history identity matching and companion exclusions. The broader findings/policy run had 19 passes and
one failure: the standalone findings fixture neither initializes the registered
identity-type cache nor normalizes mixed-case hostnames as the production load
path does. Initializing the cache alone did not fix the failure.
The earlier source-record reassessment classified multiple usable candidates as
ambiguous and used shared same-key/companion exclusions in preview and apply;
its then-current checks passed before the user requested no tests. The identifier
rule above now selects a survivor for a consistent duplicate group. The complete write
path has not been validated against PostgreSQL.
Local migration 0426 rejects incomplete, missing, duplicate, null, or unmanaged
record selections before splitting, locking selected source subjects in stable
order before checking membership. Forward, reverse, and synthetic valid and
invalid cases pass in an isolated PostgreSQL database. Concurrency and lock
impact remain unverified; this is not full evidence revalidation. The migration
is not deployed and does not implement cross-client merge behavior.
The source-record reassessment now reads attached and unattached previews in one
repeatable-read snapshot. Its apply path takes the existing exclusive tenant
guard and holds the input-generation row while rechecking the current match and
associating. This fence has not been concurrency validated and does not complete
the shared assessment or establish a PLAN-015 repair authority.
Counterfactual name and history lookups bypass cross-transaction caches; a
synthetic cursor check confirms each lookup uses the current transaction.
Withdrawn or historical names now require review instead of proving attachment;
withdrawn hardware cannot establish a current contradiction. Multiple distinct
long names matching one truncated name also require review even when they belong
to one Computer. Synthetic PostgreSQL checks passed for withdrawn name and
serial behavior; a synthetic cursor check covers ambiguous truncated names.
