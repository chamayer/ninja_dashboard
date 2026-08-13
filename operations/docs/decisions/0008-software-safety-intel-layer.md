# 0008 — Software safety intel layer

Status: Accepted
Date: 2026-07-24

## Context

Operations classifies software with pattern rules + operator decisions but
has no independent safety data. The legacy analyzer surfaced CVE hits,
publisher trust, and community verdicts by hand-authored spreadsheets;
that workflow does not exist in Operations. Batches 1–5 of the software
rebuild closed every internal parity gap. What is still missing is
external safety intel: CVEs, exploit-likelihood, active-exploitation
flags, and OSINT signals about the software itself.

The user requirement is: maximum free data, ingested continuously, with
an on-demand click for the two sources whose free tier only supports
per-request use (VirusTotal, MetaDefender). No paid tiers.

## Options considered

- **Single-source (NVD only).** Simplest ingest; no OSINT dimension; no
  categorization boost; leaves categorization dependent on hand-curation.
- **Ensemble of free sources bulk-ingested + free on-demand click.**
  Bulk: NVD, CPE, CISA KEV, EPSS, Winget, Chocolatey, abuse.ch dump
  files, AlienVault OTX. On-demand: VirusTotal, MetaDefender, abuse.ch
  API queries. Composite safety score across signals.
- **Paid data source (VulnDB / Recorded Future / etc.).** Excluded by
  the no-cost constraint.

## Decision

Adopt the ensemble-of-free-sources model. Introduce a new `intel`
Postgres schema owning the CVE + OSINT surface. Keep matcher, scorer,
and UI inside `operations`. Bulk ingest lives inside the existing
`ingest/` runner under a new `ingest/intel/` package, feature-flagged so
a broken intel source cannot take down the primary Ninja / patch cycle.

Matching is intentionally conservative on day one: `cpe_exact` (vendor +
product name only, drop version) with an explicit `confidence` field so
the scorer can weight down fuzzy matches later without re-encoding.

## Rationale

- **Maximum coverage per dollar.** Every free source contributes an
  independent signal. Composite score smooths over any single source
  being wrong or thin.
- **OSINT-shaped constraints respected.** abuse.ch's 2026-07 fair-use
  update means we consume their dump files (single HTTPS GET) at bulk
  cadence, not per-hash API loops. VirusTotal / MetaDefender free tiers
  only support small volumes, so those become operator-click actions
  with per-operator rate limiting and a 48-hour cache
  (`title_intel_cache`).
- **Schema separation.** `ninja_patches` and `ninja_activities` already
  isolate source-specific matviews; the new `intel` schema mirrors that
  pattern for external threat data. Operations still owns the matcher
  and the composite score so Operations remains the reader authority.
- **Findings-first surfacing.** New `vulnerable_software` and
  `known_malicious_hint` finding types put safety signals on the same
  standard surface every other operator queue uses
  (`feedback_findings_single_surface`).

## Consequences

**Easier**

- Every canonical software title gets a defensible per-title safety
  panel and a composite score visible on the fleet page.
- Publisher- and title-scope operator decisions (Batches 2–5) compose
  cleanly with the new score — a decision reduces or negates the score
  contribution.
- Adding a new free intel source later is a new `ingest/intel/<name>.py`
  connector plus a new `safety_signal.source` value; no schema change.

**Harder**

- Requires six free API-key secrets in the ops env (NVD, OTX, abuse.ch,
  VirusTotal, MetaDefender, optional CIRCL). Ops needs to keep them
  rotated.
- CPE matching is inherently fuzzy; expect a period of tuning
  `cve_match.confidence` weights before the score matches operator
  intuition. Conservative default matching (exact vendor + product,
  ignore version) is the safest starting point.
- Intel tables grow. `cves` will hit ~250k rows steady-state. `cve_match`
  scales with the fleet catalog; ~100k rows at the current
  ~8k canonical titles is a plausible upper bound. Both are indexable
  and bounded; no matview needed initially.

**Required**

- Every silent skip in the intel ingest (source down, quota hit, parse
  error) must surface as an operator-visible signal — matches the
  "nothing hidden" rule.
- On-demand VirusTotal / MetaDefender lookups must be per-operator
  rate-limited (10/h cap) and cache 48 h so re-clicks are free.

**Prohibited**

- No calls to paid tiers of any source.
- No per-hash API calls to abuse.ch at bulk cadence; only dump files
  bulk, single-hash queries on the on-demand click path.
- No categorization data from an external source overwrites an operator
  category on `SoftwareCatalog.categories` — external tags merge, not
  replace, and are stored on `safety_signal` when the operator hasn't
  set a category yet.

## Supersedes or superseded by

None. Sits alongside the finding-single-surface rule and the
data-driven categorization decisions.

## Amendment — 2026-08-06: version-dropped matching is superseded in intent

This record specifies `cpe_exact` matching on "vendor + product name only,
drop version", and a per-title safety panel. ADR-0012 §5, accepted later,
binds CVEs, EOL dates and safety scores to the **software+version** entity.
Both were Accepted and neither cited the other; ADR-0015 raises the conflict
and resolves it in favour of ADR-0012 §5.

The effect of dropping version is measurable. As of 2026-08-06 all 2,636
`operations.cve_match` rows carry an **empty `version_range`** — a column that
exists for this purpose — and `vulnerable_software` covers **22 titles across
1,389 devices**. Every device running any version of a matched product is
flagged identically, including patched ones, so the finding currently reports
*product-level suspicion* rather than per-device vulnerability.

This is not a reversal of the original reasoning. This record framed the
conservatism as temporary — "so the scorer can weight down fuzzy matches
later" — and the ensemble, schema separation and findings-first surfacing
decisions all stand. What changes is that the target is now named: populate
`version_range` and match against the installed version, at which point the
safety panel becomes per software+version rather than per title.

Until then `vulnerable_software` must state on its face that it is
product-level, so an operator does not read it as "this device is vulnerable".
