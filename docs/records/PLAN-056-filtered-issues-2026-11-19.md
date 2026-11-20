# PLAN-056 — Filtered Issues latency

One configured-admin, internal HTTP request to the reported client and Computer
identity filter on release 0.144.44 hit the 20-second client deadline. Logout
succeeded. Two bounded log checks did not find the request completion marker;
server completion was not established. No retry or cancellation was performed.

A read-only aggregate activity check subsequently saw one active Operations
query involving source records and ownership, over two minutes old and not
waiting on a database lock at that instant. Its relationship to the timed-out
request was not proven. Temporary diagnostic files were removed.

Static review shows that filtered Issues computes global counts, filtered counts,
and selected-page data via the shared Issues selector. This is not attribution:
the slow statement or responsible component remains unconfirmed. Preserve client
scope, independent-action deduplication and existing uncommitted Issues UI work.
Next verify whether the prior work finished before another bounded trace; use the
existing production helper, do not cancel work, and do not run local performance
measurements. No application code changed during this diagnosis.

Continuation: the previously observed active Operations query later disappeared;
its relationship to the timed-out HTTP request remains unknown. A bounded
read-only direct-handler trace on 0.144.44 showed the global open count at 1.932 s
and the following paused count hitting its 8-second statement limit. Repeating
the trace with JIT disabled still hit the limit. An isolated existing compact
global summary completed in 1.593 s; when substituted in a diagnostic handler,
the subsequent client-filtered count hit the 8-second limit too. An early-client
predicate candidate also hit that limit and was not adopted.

A non-ANALYZE plan for the client-filtered open count estimates broad findings
and candidate scans; its costs are estimates, not measured attribution. Both
global and filtered counts require attention. No query rewrite has established
full-page parity or a usable speedup; no application code was changed. All
diagnostic transactions closed and temporary staging was removed. Next identify
a bounded client-scoped selection that preserves current source-record and
software ownership, action deduplication and covered-issue semantics, and
compare against the existing reader before changing the page.

Further read-only analysis identified the existing protected batch client
attribution reader. A set-based candidate for the broad client counts completed
open in 4.094 s and paused in 0.055 s (the original broad count exceeded 8 s).
For the selected identity type, grouped counts matched in one snapshot: original
0.565/0.043 s and batch 2.612/0.044 s for open/paused. This does not prove
full-population parity. A local candidate now limits batch attribution to the
broad unfiltered-client summary; narrower scopes keep the original selection.
For filtered pages, global open/paused totals reuse the existing compact Issues
selection; unfiltered pages retain existing category/severity counts. JIT is
disabled only during the batch summary and restored within a savepoint. No
schema change or new tests. Full-page behavior, restricted and cross-client
cases, output parity, and performance non-regression remain unverified. The
candidate is not deployed. No local tests per user instruction.

User directed production validation. With deployed 0.144.44 healthy and source
hashes matching commit ae235b45, an isolated read-only handler comparison
stopped the deployed baseline at its 8 s statement limit (9.306 s overall).
The first candidate completed HTTP 200 in 18.661 s; selected count and page SQL
each took about 7 s. A second isolated run with JIT disabled completed in 6.624 s.
The final candidate scopes JIT off to those client page queries and returned
HTTP 200 in 6.239 s; its broad client summary took 3.945 s, fleet totals 1.181 s.
The baseline produced no HTML, so full-page parity was not established. These
are direct-handler timings, not browser/network or controlled cold-cache results.

In one read-only snapshot, global compact and client-batch grouped counts matched
the original for the Computer identity and client-mapping types (open status).
One earlier narrow comparison also matched paused counts. Other types, statuses,
clients, restricted cases, complete HTML and counts remain unverified. Candidate
code ran only in an isolated process; serving files were unchanged. Transactions
closed and exact temporary staging was removed. No local tests were run.

Further production read-only comparison reused compact action selection while
retaining source-record ownership checks for the client summary. Open grouped
counts matched the prior batch candidate across 29 groups, with 4.161 s versus
2.657 s in that snapshot; paused counts also matched (both empty). All 5,127
source observations were open and eligible, so status/covered prefiltering did
not reduce the batch. The revised full page has not yet been timed, and parity
against the deployed reader for all groups and other scopes remains unverified.
