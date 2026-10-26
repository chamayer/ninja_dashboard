# PLAN-017 — Catalog/reference lifecycle and rebuild checkpoint

2026-10-25. Local static snapshot at HEAD `0c812db`; closing concurrent HEAD `a3fb9df`. This continues the
[third batch](PLAN-017-static-assessment-batch-3.md), feeds the
[gate ledger](PLAN-017-phase-1-gate.md), and neither changes runtime nor selects
a retention period, rebuild, migration, cache or target architecture.

## Stores, authorship, references and expiry

| Class | Grain and authority | Confirmed lifecycle/rebuild mechanism | Remaining verification |
| --- | --- | --- | --- |
| catalog.publishers/products/software_versions | Global publisher → product → version, without tenant/RLS by design; catalog projector normalizes installation names via publisher aliases | SQL 074 establishes RESTRICT references and denies runtime deletion; 075 replaces product uniqueness with NULLS NOT DISTINCT; 076 adds durable product/version UUIDs used as finding subjects | Preserve full forward chain. Do not reopen the nullable-publisher duplicate defect fixed by 075. Verify installed constraints, alias ordering/changes and current writer exclusivity. |
| Installation current/history | Tenant/client/device/title relationship; current source listing with material intervals | Current installation points to catalog version; history retains publisher/version/path/date and intervals, not a full raw package archive. Source-list completeness and removal holds are separate from catalog retention | Account for multiple versions/paths/source cardinality as an explicit grain question; old measured absence of duplicates is not current proof. History expiry limits replay. |
| Catalog reference identity | Numeric PKs plus generated stable UUIDs; finding/capability/category/authorization references | In-place projection inserts missing entities and fills installation references; it does not delete old entities or recreate their UUIDs | Clean reconstruction from only current installations cannot be assumed equivalent to keeping existing anchors and all authorship/references (F07). |
| Capability machine evidence | Product UUID/capability/source, one current assertion with retained withdrawn episodes | Dedicated matcher writes positive evidence; partial current uniqueness, confidence/withdrawal-reason checks; per-pass owned-source withdrawal. Missing/empty rule sets are guarded separately from a valid rule set matching nothing | Existing tests name zero-match, empty-rule and withdrawal cases. A complete current writer/retention audit and source-disappearance replay remain for verification. |
| Capability operator evidence | Product UUID/capability with explicit positive or negative operator assertion | Effective view gives operator polarity precedence; partial current uniqueness, actor/reason/withdrawal fields and column-level mutation permissions preserve superseded assertions | These are authored inputs, not cheaply refetchable global corpus. Exact history/undo horizons and protection against all disposal paths remain unresolved. |
| Category evidence/operator assertions | Product/category/source plus authored decisions | SQL 104 mirrors current/withdrawn episode storage; category actions withdraw prior decisions before inserting replacements; dedicated effective view applies source/decision authority | Configured classification and policy changes need their own invalidation path; do not conflate category labels with immutable vendor facts. |
| Rules, source vocabularies and tag mappings | Capability/category sources/rules/tags are controlled reference/configuration | Guards reject malformed authority/rule shapes; effective capability view filters disabled sources at read time; matcher versions are recorded on assertions | A version string does not preserve executable matcher/config history. Empty-rule preservation is a deliberate safety behavior, not proof every intentional disable operation withdraws old evidence. |
| CVE/CPE/KEV/EPSS corpus | Global external feed rows and changing attributes | NVD deltas use source modified time; CPE has backfill state and later delta path; KEV/EPSS update current corpus fields; raw NVD JSON is latest stored fidelity | Refetch availability, old-rule replay, outage cursor/failure boundaries and historical feed versions unverified. An upsert corpus is not an archive of all published historical answers. |
| EOL corpus and product mapping | Global product/release cycles; Operations mapping rules assign catalog lifecycle | Feed upserts products/releases; projector computes one shared best-match set, writes matching EOL date/source and clears no-longer-matched EOL assignments | Mapping/source-code/reference versions and historical availability are needed for corrected replay; current EOL dates alone do not reproduce an answer published at T. |
| Tenant/client product authorization | Tenant-wide or client-specific product/capability policy | Separate partial unique live-scope indexes; withdrawal rather than deletion; classifier reads current authorization rows | Keep global product identity distinct from scoped permission to install/use it. Validate every scope join and supersession/history reference before expiry. |

Evidence: [catalog creation](../../sql/migrations/074_software_catalog_entities.sql),
[nullable-key repair](../../sql/migrations/075_catalog_products_nulls_not_distinct.sql),
[subject UUIDs](../../sql/migrations/076_catalog_finding_subject_uuids.sql),
[capability authority](../../sql/migrations/093_capability_assertions.sql),
[category authority](../../sql/migrations/104_software_category.sql),
[authorizations](../../sql/migrations/099_product_authorizations.sql),
[catalog projector](../../ingest/software_catalog.py),
[capability matcher](../../ingest/intel/capability_match.py),
[EOL write/clear](../../ingest/intel/eol_match.py#L139).

No general cleanup absence or unbounded-growth claim is made from these
searches. External maintenance, active producer rates, deployed definitions and
actual protection/replay after expiry require later evidence. Global reference
rows may be retained for legitimate learned/authored references even when no
current installation points to them.

## F07 — Catalog clean-rebuild description omits durable reference identity

Independent disposition: **accepted by Claude round 17 (Point 37)**. This accepts
the local contract finding, not a destructive recovery test or remediation.

- Contract/criteria: R06/R08; A4/A5/A8. Grade: code-confirmed mismatch between
  the claimed clean-rebuild inputs and the retained identity/reference model;
  no destructive reconstruction was attempted. Conditional severity: Medium
  if used to justify disposal/rebuild; current runtime loss not demonstrated.
  Likelihood unknown; confidence high in the stated local code/SQL dependency.
- Claim/evidence: `software_catalog.py` says dropping the catalog and rebuilding
  from installations recreates it identically. Its body reads current
  installations and publisher aliases, inserts missing rows and backfills
  references. SQL 074 deliberately retains products after installations vanish;
  076 assigns product/version UUIDs; 093/104/099 and finding subjects depend on
  those stable identities and operator state. Re-fetching current installations
  does not establish reproduction of vanished products, existing generated IDs,
  authored negative assertions or their reference graph.
- Affected consumers: catalog-linked installations, software finding subjects,
  capability/category review state, client/tenant product authorizations and
  historical explanations. Foreign-key/delete protections are positive
  safeguards, not evidence these stores are disposable.
- Competing explanation: the wording may intend safe in-place rerun, not a
  destructive clean rebuild. Existing rows keep their IDs during normal upsert;
  the function can be repeatable without supporting the stronger clean-rebuild
  promise. No normal upsert data-loss defect is claimed.
- Options/dependencies: define in-place repair separately from clean recovery;
  retain anchor/UUID and authored-state checkpoints plus required histories for
  the latter, or narrow the recovery contract with explicit lost guarantees.
  Reconstruct derived values around preserved identities if justified, rather
  than presuming every catalog row is a disposable cache.
- Verification/owner: R06/R08 under PLAN-017; bounded synthetic reconstruction
  with unused products, stable UUID references and operator assertions in
  Phase 2, then Phase 5 recovery alternatives. Future implementation/ADRs require
  their own accepted design/scope. No DROP, delete, FK change or rebuild is
  authorized by this finding.

## Replay and expiry coverage

Three different questions retain different inputs:

1. Current-state repair can use latest evidence and current rules, but must
   preserve learned anchors, authored policy and explicit previous-selected
   state where the selection rule retains it.
2. Reproducing the answer published at T also requires old rule/config/reference
   versions, generation/order and prior decisions. Current upsert corpora and
   a matcher-version label do not establish that coverage.
3. Applying corrected rules to old input requires the old input at the desired
   fidelity. Observation history writes material_data/intervals, not complete
   raw JSON for every heartbeat; the latest current raw row does not restore
   overwritten nonmaterial fields. A → B → A episodes differ from two reused
   content bodies, and daily presence is not continuous contact.

The closed-history purge default is not an undo/authorization/catalog policy.
Daily presence RESTRICT references, change-action/merge provenance and scoped
authorizations create separate retention dependencies. A time policy needs the
cutoff baseline and later transitions; last-N needs an explicit choice of bodies
versus episodes; a hybrid protects their required union. None is selected here.
Existing storage dimensions must be measured before costing those alternatives.

## U04 — Current local disposition

Pending title requests are unique by tenant/key/source, but no generation is
acknowledged when captured IDs are consumed. Inventory and classifier Jobs have
different protected keys; the source indicates narrow ownership on purpose.
The intervening classification reads/publications and later consumption form a
candidate producer/consumer interleaving, not proof of observed loss. Full/no-
target reconciliation can eventually cover it. The remaining action is a
bounded Phase 2 interleaving check plus dependency/supersession audit; no runtime
experiment was run and the lead remains unresolved.

## Fresh inventory and validation boundary

The fresh [gate evidence](PLAN-017-gate-evidence/source-baseline.json) was
generated with `catalog` added to the copied builder's SCHEMAS. It reports
949 baseline files (947 source/packaging plus two original plans), 6,105 lexical
occurrences, 506 allowlisted qualified names and 3,506 Python definitions.
These are generated counts, not hand-patched or live-object counts. Original
evidence remains unchanged; the fresh copy adds no runtime packaging input.
Fresh and original CSVs are still regenerable commit-time exclusion candidates.
Concurrent reader changes and the new metadata migration/test are recorded in
the separate gate-evidence delta; the fresh snapshot predates those changes.
Its generated counts describe that snapshot, not the later worktree.

Closing documentation/evidence checks passed as detailed in the gate ledger;
recorded concurrent source/HEAD drift remains explicit. No local or production DB/testcontainer
was used. Installed object kinds, physical costs, historical feed availability
and destructive-recovery equivalence remain unverified.
