# PLAN-017 — A/B1 stopped preflight

Historical initial-attempt record. The user subsequently authorized a retry;
see [current retry results](PLAN-017-ab1-retry-results.md). Evidence below
is preserved as captured and does not describe the later successful preflight.

Captured at 2026-10-25T22:34:44.869334+00:00. A/B1 remain authorized within their exact reviewed
scopes; B2 is unapproved. Phase 1 is **not complete**.

The user reserved the A/B1 window and confirmed Claude C was paused. The
documented Windows PowerShell 5.1 helper/SSH path was invoked once for initial
P0, requesting a direct `operations_migrate` connection and the privileged
read-only wrapper (tenant 1, pg_catalog, 1-second lock, 5-second statement and
10-second idle-transaction limits). The helper returned **exit code 2**. No
allowlisted role/version/read-only result passed validation. The actual role,
server version and transaction state therefore remain unconfirmed.

Raw stdout/stderr was suppressed and not retained. The exit code alone does
not establish the cause; no missing-role, credential, schema, server-version
or deployed-state claim is made. The submitted command contained no writes
beyond transaction-local settings. No retry, role substitution, schema change,
maintenance, repair, migration, deployment, commit or push was attempted.

**Stop disposition:** all dependent A/B1 work stopped before any numbered D1,
D2, D3 or D5 body. D1 reconciliation could not begin, so dependent checks
cannot proceed. D2 has zero captures; neither snapshot nor a growth delta
exists. D5.2 was not executed or replanned; its reviewed uncapped 30-day,
platform-only aggregate is unchanged. No D3 SELECT or EXPLAIN was submitted.

| B1 query | Actual startup cost | Actual total cost | Estimated rows | Status |
| --- | --- | --- | --- | --- |
| D3.1 | Unknown | Unknown | Unknown | Not submitted; P0 stopped |
| D3.2 | Unknown | Unknown | Unknown | Not submitted; P0 stopped |
| D3.3 | Unknown | Unknown | Unknown | Not submitted; P0 stopped |
| D3.4 | Unknown | Unknown | Unknown | Not submitted; P0 stopped |
| D3.5 | Unknown | Unknown | Unknown | Not submitted; P0 stopped |
| D3.6 | Unknown | Unknown | Unknown | Not submitted; P0 stopped |
| D3.7 | Unknown | Unknown | Unknown | Not submitted; P0 stopped |

No access paths or expensive nodes were observed. Material plan risks cannot
be assessed without B1: a 5,000-key cap does not bound upstream scan/sort/join
work, and correlated history counts can multiply work. Planner costs, when
available, will be estimates in planner units, not milliseconds. Prefix samples
will not prove population-wide integrity or runtime-role visibility. No
conclusion about affordability is justified by this failed preflight.

B2 is not requested prematurely. First resolve the helper/P0 failure in a
reviewed follow-up, recheck the source checkpoint, coordinate a new probe
window, and complete D1 plus B1 under the unchanged approvals/stop conditions.
Then report actual costs/rows/access paths and request B2 separately.

**Scheduling:** Codex's A/B1 window is released; no Codex probe remains active.
Claude retains all C work and its separate command-review/confirmation gate.
No C work or manual measurement task is assigned to the user.

Local source corroboration is in the
[resume checkpoint](PLAN-017-gate-evidence/resume-ab1-source-checkpoint.json);
the [execution metadata](PLAN-017-gate-evidence/resume-ab1-execution.json)
records only safe status. Original snapshots, hashes and existing dirty work
are preserved. Static coverage/U02/U04 and whole-gate review remain open.

Local validation: 18-entry registry, scoped diff check, new JSON parsing,
Markdown links/whitespace, final 951-source and six-original-evidence hash
rechecks passed. Existing unrelated global diff EOF whitespace and root
blueprint size-cap failures remain; no runtime tests or successful database
validation were performed.

Local follow-up: a dummy-only PowerShell 5.1 reproduction demonstrated that
the original embedded double-quote command shape loses SQL quotes and splits
the target argument at a native boundary. This is a confirmed invocation defect
and a plausible failure cause, not a verified production diagnosis. A
base64-encoded SQL stdin command shape, containing no embedded double quotes,
was preserved exactly across both PowerShell native boundaries in a local
dummy helper test; decoded SQL matched its original bytes. No real helper
profile, SSH or database was used in these tests. The shared helper itself
was not changed. No production retry was made. Preserve the stop disposition;
review the corrected exact P0 command and coordinate a new window before any
explicitly directed resumption of the stopped batch.
