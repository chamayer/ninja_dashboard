# Current Task Blueprint

> Per `Development/DEVELOPMENT.md` Agent Work Rule #5. Overwritten
> per task. Historical record lives in `SESSIONS.md` and `CHANGELOG.md`.

---

## Goal

Make Patch Compliance a single well-defined number across the
whole codebase — exclude REJECTED and DELAYED patches (both
intentional decisions) from the calculation.

## Why

Operator-driven. REJECTED patches are intentional opt-outs
("we are not installing this on this device"). DELAYED patches are
sitting in the 30-day auto-approval window per the org's Ninja
policy (per the v0.7.3 `ninja_patch_status_glossary` memory). Both
are conscious decisions, not gaps in coverage — counting them
against compliance % understates how well the MSP is doing.

This is also a forcing function to write down ONE compliance
formula so future cards don't drift.

## Scope

**In:**
- Define the canonical compliance formula in a code comment + in
  `CONTEXT.md`'s patch status glossary section.
- Centralize the SQL fragments (denominator / numerator) so every
  compliance card uses the same logic.
- Apply across every card that computes "Patch Compliance":
  - `overall_compliance` scalar (Overall Patching Status)
  - `org_compliance` scalar (Org Overview)
  - `compliance_worst` row chart (Overall Patching Status)
  - `compliance_all` table (Overall Patching Status)
  - `org_device_type` bar (Org Overview)
  - `org_os_family` bar (Org Overview)

**Out:**
- Trends / time-series compliance — separate scope, would need
  historical tracking of patch state transitions and isn't reliably
  available from current data.
- Range coloring (red < 80 / amber 80-95 / green ≥ 95) — separate
  follow-up.

## Formula

**Patch Compliance =**
`installed / (installed + missing)`

where:

- **installed** = distinct `(device, patch)` pairs that have at least
  one `fact_type='install_outcome' AND status='INSTALLED'` row in
  `patch_facts`.
- **missing** = distinct `(device, patch)` pairs whose current
  patch_state is one of {`APPROVED`, `MANUAL`, `FAILED`}.
  - APPROVED: queued, hasn't installed yet → counts as missing.
  - MANUAL: needs admin approval → counts as missing.
  - FAILED: install was attempted and failed → counts as missing.
- Explicitly **excluded** from both numerator and denominator:
  - `REJECTED` — intentional opt-out per Ninja policy.
  - `DELAYED` — sitting in the configured auto-approval delay
    window; not yet eligible to install.

In SQL terms the universe of (device, patch) considered is:
`installed ∪ in-state {APPROVED, MANUAL, FAILED}`.
The DENOMINATOR is the size of that union; the NUMERATOR is the
size of `installed`.

## Files to change

- `ingest/metabase_bootstrap.py`
    - Define two reusable SQL CTE fragments at module top
      (`_COMPLIANCE_INSTALLED_CTE`, `_COMPLIANCE_MISSING_STATUSES`)
      or one shared `_compliance_query(scope_predicate: str)`
      helper.
    - Rewrite all 6 compliance SQLs to use the same denominator
      filter `(installed OR status IN ('APPROVED','MANUAL','FAILED'))`
      and numerator `installed`.
- `CONTEXT.md`
    - Update the "Patch status glossary" section with the formula
      and the rationale (REJECTED/DELAYED excluded).
- `VERSION` / `CHANGELOG.md` / `SESSIONS.md` — standard bump.

## Steps

1. Add the helper constants near the existing color/code constants
   at the top of `metabase_bootstrap.py`.
2. Rewrite `overall_compliance` (Overall Status scalar).
3. Rewrite `org_compliance` (Org Overview scalar).
4. Rewrite `compliance_worst` (Overall row chart).
5. Rewrite `compliance_all` (Overall table — most columns kept; only
   the compliance % column logic changes; keep the Approved /
   Manual / Delayed / Failed breakdown columns for context).
6. Rewrite `org_device_type` (Org bar).
7. Rewrite `org_os_family` (Org bar).
8. Update `CONTEXT.md` glossary with the formula.
9. Verify `python -m py_compile` after each card.
10. Bump VERSION → 0.13.7, update CHANGELOG + SESSIONS, commit + push.

## Open questions

- Does the user want PENDING (which appears in `_STATUS_OPTIONS`)
  treated as `missing` or excluded? Currently leaning **missing**
  (it's "we know about it, no decision made yet"). If they want
  it excluded, easy single-line change.

## Status

*done* — committed as v0.13.7 (pending push at time of writing).

## Resolved questions

- PENDING is treated as missing (counted in denominator). Same
  rationale as APPROVED — known about, no resolved decision yet.
  Easy to flip by editing `COMPLIANCE_MISSING_STATES` if operator
  changes mind.
