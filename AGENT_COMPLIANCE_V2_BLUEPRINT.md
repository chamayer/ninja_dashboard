# Agent Compliance v2 Blueprint

Date: 2026-06-10

## Goal

Make Agent Compliance a durable platform domain, not a report port.
The PowerShell report is the v1 parity contract. v2 should preserve
that behavior while separating collection, alignment, evaluation,
dashboarding, and alerting into auditable phases.

The dashboard must be human-navigatable. The primary experience should
be device-first, with a separate setup/review path and a debug path
that stays out of the way.

## Design Principles

- Raw platform data is immutable per run.
- Org alignment is its own first-class model.
- Compliance evaluation reads a specific alignment snapshot.
- Alerts are generated from findings, not directly from collectors.
- Configuration belongs in Postgres with optional web/UI management,
  not hidden in `.env` except for secrets.
- Primary UI text should be human language, not schema language.
- Primary tables should be concise; raw details belong in debug views.
- Top navigation should mirror the patching dashboards.

## Phase Model

1. Collection
   - Fetch Ninja, SentinelOne, LogMeIn, ScreenConnect.
   - Store raw observations and source-run health.
   - Do not decide compliance in collectors.

2. Alignment
   - Build canonical org map from observed platform names.
   - Preserve PowerShell rules:
     - configured org wins;
     - Ninja name wins over S1, then LMI;
     - normalized-identical names collapse;
     - explicit aliases are additive;
     - fuzzy absorption only when one safe complementary match exists;
     - excluded orgs are ignored.
   - Persist current and history alignment snapshots.
   - Expose unresolved, fuzzy, missing, and mismatched orgs.

3. Evaluation
   - Build compliance matrix from raw observations plus alignment
     snapshot.
   - Preserve PowerShell fields:
     - org alignment status;
     - per-platform presence, online, last seen, device IDs;
     - missing platforms;
     - S1 `NO AV` exemption;
     - stale;
     - degraded;
     - cross-org conflicts.

4. Findings
   - Generate finding rows from matrix deltas.
   - Separate finding types:
     - missing required platform;
     - stale device;
     - degraded device;
     - source failure;
     - org alignment mismatch;
     - cross-org conflict.
   - Expose device and org suppressions as reversible review state,
     not hidden deletes.

5. Alerting
   - Route by finding type, platform, client, severity.
   - Split alerts into device, org review, source, and system levels.
   - Support email and Zendesk early.
   - Keep Ninja API posting optional because Ninja can be the missing
     or unhealthy platform.
   - Do not alert on unchanged review noise; alert on state changes and
     important recoveries.

6. Dashboard
   - One Metabase collection: `Agent Compliance`.
   - Primary dashboards:
     - Today;
     - Devices;
     - Review;
     - Health;
     - Debug.
   - Views/cards:
     - source health;
     - org alignment;
     - unresolved platform mappings;
     - compliance matrix;
     - remediation candidates;
     - stale/degraded devices;
     - active findings;
     - alert delivery history.
   - Primary dashboard text should stay short and action-oriented.
   - Debug dashboards may expose raw IDs, raw payloads, and mapping notes.

## Data Model Targets

- `platform_observations`: raw observed devices per platform.
- `org_alignment_current/history`: canonical org/platform mapping.
- `compliance_matrix_current/history`: evaluated device compliance.
- `compliance_findings`: alertable findings.
- `alert_suppressions`: reversible device/org suppression state.
- `notification_routes`, `alert_rules`, `alert_state`,
  `alert_events`: alert routing and dedupe.
- Future `config_audit_log`: who changed client/source/alias/rule config.

## Web Config Scope

Good idea for v2, with limits:

- Web UI can manage:
  - clients;
  - aliases;
  - per-client requirements;
  - source enablement;
  - alert rules/routes;
  - suppressions.
- Web UI should not store raw secrets directly.
  - Secrets remain env/secret-store references.
  - DB stores secret reference names.
   - Split UI responsibility:
     - main views for device-level actions;
     - setup views for org/system configuration;
     - debug views for raw internal state.

See the main-view navigation and wording contract for the human-facing
dashboard shape.
See `AGENT_COMPLIANCE_ALERT_WORKFLOW.md` for the alert taxonomy and
route behavior.

## v2 Milestones

1. Stabilize v1 parity output after live validation.
2. Add config audit table.
3. Add a small setup web UI or protected endpoint set.
4. Add alignment review workflow:
   - approve generated alias;
   - reject generated alias;
   - promote alignment alias to manual alias.
5. Add alert routing rules per finding type/client/platform.
6. Add retention policies for observations/history.
7. Add main/setup dashboard navigation and humanized labels as the
   default presentation layer.

## Non-Goals

- Do not duplicate Postgres, Metabase, or scheduler containers.
- Do not make `.env` a full config mechanism.
- Do not post all findings to Ninja by default.
- Do not auto-remediate agents in v2 without human approval workflow.
