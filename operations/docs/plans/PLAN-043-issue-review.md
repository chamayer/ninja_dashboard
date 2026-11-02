# PLAN-043 — Useful issue review

## Goal and scope

Make an issue review explain the detected problem, show evidence relevant to
the decision, and provide existing resolution paths. Prioritize the native
source-record identity review that exposed the missing context. Improve the
common review shell without changing finding production, identity policies,
schema, or action authorization. User approved commit and push on 2026-11-02;
release 0.143.2 contains no migrations or identity-data changes.

## Confirmed behavior and decisions

- The linked finding is `source_record_identity_review` on a source record.
  Its recorded evidence has `device_id`, `proposed_device_id`, and `matcher`.
  The producer emits this form when corroborated serial/VM UUID evidence
  contradicts an attachment. Another form lists ambiguous candidate Computers.
- The old review view handles neither source-record nor case subjects and
  substitutes a client or source-health link. Its short detail formatter does
  not explain this native finding. Do not describe a contradicted attachment
  as simply several matching Computers.
- Safe metadata remains the authority for displayed source names/identifiers.
  Missing or restricted metadata must not fall back to stored finding payloads.
- The page distinguishes recorded detection evidence from current attachment
  and current source records. All additional queries are tenant scoped and
  bounded. No fleet evaluation or production data writes are authorized.
- Reuse registered action permissions and the existing bulk-action handler for
  one finding. Native identity review has no registered move action; explain
  the required comparison and the missing action explicitly.

## Affected files and validation

Review context helper, existing view/template, and synthetic tests. Existing
Dockerfile `COPY operations/apps/` and `COPY operations/templates/` include
the runtime changes without packaging or Compose modifications.

Validation completed 2026-11-02:

- Fourteen new helper/request/template tests pass, covering restricted/missing
  metadata, current/detection attachment roles, changed/deleted records,
  bounded/invalid candidates, empty/JSON-text evidence, existing action permissions
  and resolved-state visibility, OS evidence, return URL safety, and HTML escaping.
- Focused pytest run (`test_issue_review.py`, `test_findings_queue.py`,
  `test_issues_software_review_context.py`): 49 passed, one existing source-text
  assertion failed at `test_findings_queue.py:253`. Its expected LATERAL text is
  also absent from committed HEAD; this change does not touch that query.
- The container's Django test runner passed the initial 13 tests and its system
  checks. The added comparison-render test passed in the focused pytest run.
- New Python files pass full Ruff lint/format; the existing view passes fatal
  lint. Python compilation, plan-registry and whitespace checks pass.
- A reviewed temporary script loaded the new helper/template on the host and
  rendered the exact linked finding in a read-only transaction with a 15-second
  statement timeout: two Computers, four source records, unrestricted subject.
  Only aggregate validation was returned. No finding, attachment, or deployed
  runtime file was changed; staged files were removed.
- Browser layout and deployed UI verification remain outstanding. No migration,
  identity repair or source refresh was performed. Release metadata is prepared
  separately under the user's subsequent commit-and-push authorization.

## Checkpoint

Local implementation complete; release 0.143.2 approved for commit and push.
Pre-push review confirms both remotes match HEAD and no pending Django or ingest
migrations. Next: commit the scoped review changes, push origin then the mirror,
and inspect the automatic deployment without a separate redeploy.
Module handoff: `operations/BLUEPRINT.md`.
The oversized previous handoff is retained verbatim in
`operations/docs/records/OPERATIONS-CHECKPOINT-2026-11-02.md`; its original
relative links are interpreted relative to its former `operations/` location.
Its normalized Git blob matches the former blueprint exactly; no historical
decision, evidence, limitation or recovery instruction was removed.
