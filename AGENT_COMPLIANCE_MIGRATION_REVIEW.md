# Agent Compliance Migration Review

Date: 2026-06-10

Original script reviewed:
`C:\Users\chamayer\Documents\Development\script-dev\migrated\Multi_org_agent_compliance.ps1`

## Migrated in v1

- Multi-platform collection for Ninja, SentinelOne, LogMeIn, and
  ScreenConnect.
- DB-backed clients, platform sources, aliases, requirements, source
  runs, observations, matrix rows, findings, and alert state.
- Per-client platform requirements, including UTA server/workstation
  split.
- Source-health handling so failed collectors become unknown/source
  findings instead of false missing-agent findings.
- Alert route support for webhook, email, and Zendesk.

## Parity fixes added in v0.16.1

- LogMeIn `/v2/hostswithgroups` now handles the original response shape:
  `payload.groups` is mapped by ID and hosts resolve group names from
  `groupid`/`groupId`.
- LogMeIn now waits and retries once on HTTP `429`, preserving the
  original script's rate-limit behavior.
- Client alias matching now includes normalized org/site/group names,
  matching the original script's punctuation/space-insensitive org
  normalization.
- Hostname normalization now strips curly apostrophes in addition to
  spaces, straight apostrophes, and backticks.
- Matrix matching now applies a conservative prefix merge for unique
  truncated hostnames with at least 10 matching characters.
- Ninja observations now mark `NO AV` evidence in raw data, and matrix
  evaluation exempts those devices from SentinelOne missing-agent
  findings.
- v0.16.4 corrected org alignment to persist canonical platform aliases
  instead of treating every observed name as its own client. Canonical
  selection now follows the original script: configured client, then
  Ninja, then SentinelOne, then LogMeIn. Fuzzy non-Ninja absorption into
  Ninja is limited to exactly one complementary match.
- v0.17.0 added first-class persisted parity output:
  `org_alignment_current`, `org_alignment_history`, alignment mismatch
  views, PowerShell-style alignment statuses, per-platform matrix
  presence/online/last-seen/device-id fields, `s1_exempt`, and
  `is_degraded`.

## Still intentionally not identical

- ScreenConnect is modeled as per-client sources instead of the original
  UTA-only flat lookup. This is the desired platform model for v1.
- Full PowerShell parity now depends on live validation against the
  original report outputs for the same run window.

## Re-review focus after deployment

Run a fresh Agent Compliance collection and inspect:

- unresolved observations by platform/group
- missing-platform counts
- LogMeIn observations with blank group names
- S1 missing findings where Ninja raw data indicates `NO AV`
- prefix-matched hostnames where `match_name <> norm_name`
