# 0031 — Finding state is stored and written in the same transaction as its inputs

Status: Accepted
Date: 2026-10-15

## Context

The Issues page needs a state for every finding (needs action, blocked, pending, covered) to filter,
count and label about 39,000 active findings. The state was derived on every page load from
per-participant assessments, then partly stored in a column that only some writers refreshed, then
derived again through a database view that also applied pause, freshness and a "critical takes
priority" rule. Measured on production (2026-10-15), the filtered Issues page took 14-36 s, and
nearly all of that was recomputing state. The column also went stale: the Python hook that
refreshed it covered `record_assessment` but not the writers that insert assessments in bulk SQL,
so 27,918 of 38,043 active findings had a stored value older than their latest assessment.

## Options considered

- Keep deriving state at read time and make the view faster. Rejected: the cost is the derivation
  itself, and it is paid on every page load by every filter and count.
- Store the roll-up as columns on `findings` and refresh it from Python. Rejected: a refresh in
  application code can be skipped by any new writer.
- Store state in its own table and refresh it from database triggers. Selected.

## Decision

`operations.finding_state` holds one narrow row per finding that has been active: attention, reason,
the covering findings, the policy version and when it was computed. Its only writer is
`operations.refresh_finding_state` (with `touch_finding_state` for unchanged reassessments); the
application roles can only read it. Database triggers call the writer in the same transaction as
every change that affects it: assessments, participants, and a finding's insert, status or
severity. A bounded cascade refreshes the findings that a finding becoming active or closed covers
or uncovers. Pause, closed status, freshness and policy version are not stored; the page compares
them as columns. "Critical takes priority" is no longer a state: critical findings sort first and
a visible row shows a badge.

An hourly check recomputes every active finding, records each disagreement with when and what in
`finding_state_drift`, and repairs it. The Finding state checks page lists them.

## Rationale

A stored value written by the database in the same transaction cannot be stale with respect to
committed data, and no application code path can skip it. Reads become indexed predicates and
grouped counts. Measured after deploy: filtered Issues pages 1-4 s, down from 14-36 s.

## Consequences

- Assessment writes cost more: 129 s extra on a 323 s platform evaluation before migration 0302
  re-stamps unchanged reassessments instead of recomputing them (7.0 -> 2.4 ms in a local
  benchmark). Any new writer of assessments, participants or findings is covered automatically.
- A reassessment that changes nothing only re-stamps `computed_at`. A finding with several
  participants whose other participant stops being reassessed can hold a state longer than the full
  rule would; the hourly check records and repairs it.
- Counts moved when "critical takes priority" stopped being a state: Blocked about 714 -> 448,
  Needs action about 5,389 -> 5,711.
- Notifications, source actions, software exposure and the evaluators still read assessments.
  Moving them to `finding_state` is a separate decision.
- Migration tests must use production column types and the production role attributes. Two
  deploys (0299, 0301) failed on startup because the test schema did not.

## Supersedes or superseded by

Builds on migration 0295 (finding types registry) and ADR 0030. Replaces the interim designs in
migrations 0297-0300, removed by migration 0303.
