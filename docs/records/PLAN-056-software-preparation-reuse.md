# PLAN-056 — Reuse completed Software preparation

2026-11-13. User requests the refresh-duration priority fixed within five minutes.
The publisher currently repeats readiness, assessments and exposure refresh after
classification already published them. Previous successful producer took 84.5 s.

Scope: one conditional in the existing writer. Under the claimed begin fence,
preparation may be reused when a certified prior
overview has valid exposure and either identical completed owner checkpoints or
only classifier checkpoints changed, the latest classifier covers every owner
completion, and no stored
exposure deadline has passed. Otherwise retain full preparation. Publication still
calculates current rolling-window totals and applies both input/claim fences.
No reader weakening, timestamp reset, new store or migration. The full preparation
path retains its existing findings guard and lock order. The reuse path writes no
findings or assessments, so it uses only the existing Software publication lock
and pre/post input/claim fences. It rejects input changes between eligibility and
begin. The atomic aggregate uses its existing statement snapshot and effective
exposure readers. This avoids queueing a pure read/aggregate behind fleet writers.

Existing classifier code refreshes readiness and assessments before exposure and
acknowledges captured targets only after successful publication. This is the
completion evidence reused here. Bootstrap without a certified overview uses the
existing full path. Full preparation can still wait behind other writer-guard
holders; reuse does not remove that guard when its writes are required.

Validation/release: focused syntax and Ruff, reviewed packaged files, scoped
commit/push under standing emergency approval, one actual publication and full
authenticated HTML check. No tests created, modified or broad suite.

Preparation: Python syntax and focused Ruff passed. The exact candidate
eligibility SELECT ran read-only in production in 0.012 s, returning false for
the current changed inputs (full-preparation fallback). No producer was invoked
by that check. Handler version advances to v5, with the same reviewed replay-safe
behavior: local reads and one atomic derived summary replacement, no external
mutation. Existing Jobs recovery authority/evidence remains applicable.

The five-minute deadline was missed. At 17:30:09 UTC another platform evaluation
started. Deployment is held until that input finishes so the restart cannot
interrupt it and reintroduce a failed-input gate. No new tests are running.
