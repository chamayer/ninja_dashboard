# ADR-0023: Issues operator state and count contract

## Status

Accepted and implemented locally.

## Context

Condition assessments contain policy and evidence details that are useful to
the evaluator and administrators but are too technical for the Issues queue.
The queue also needs counts that remain stable while an operator applies
filters, opens a group, or paginates its findings.

## Decision

The Issues queue projects every retained finding into three independent
operator values:

- **Status**: Open, Acknowledged, Paused, or Resolved. This reflects operator
  handling and snooze state.
- **Attention**: Needs action, Blocked, or Pending. This reflects the
  current assessment and never substitutes for Status.
- **Severity**: the finding's existing severity, unchanged by assessment.

An unresolved finding without a fresh current assessment remains visible and
is classified as Pending. It is not actionable. Internal disposition,
policy version and digest, participant scope, blockers, rules, and
reevaluation keys remain restricted to administrator and audit surfaces.

The six Issues summary cards are fleet-wide and unfiltered. Group headers are
computed from the complete scoped result set before row pagination and show
both current matches and unresolved totals. Table filters and sorting apply to
the complete selected group before pagination; Clear removes only table
parameters and preserves the surrounding scope.

Software policy candidates are not Issues. They are counted and linked only
through Software Decisions. Genuine software incidents remain in Issues.

## Consequences

Operators can distinguish work, blocked evidence, and missing assessment data
without interpreting policy-engine vocabulary. Administrators retain the
technical evidence needed to diagnose coverage. Any new producer must provide
fresh, type-specific assessments and complete recovery evidence before a
finding may become actionable or clear.
