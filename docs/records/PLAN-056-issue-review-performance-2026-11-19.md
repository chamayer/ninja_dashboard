# PLAN-056 — Issue review performance

Two configured-admin internal HTTP samples on 0.144.43 completed with HTTP 200
in 3.484 s and 4.423 s. They are individual samples, not a controlled baseline
or browser measurements. A read-only direct-handler trace took 5.064 s, with
2.324 s in source subject loading and 2.445 s in comparison metadata loading.
JIT on/off handler samples were 4.084/3.812 s, so no JIT change was adopted.

In one read-only repeatable-read production snapshot, bounded lookups using the
same protected metadata view returned identical query rows for the selected
issue: subject 1.949/0.032 s and comparison 1.522/0.067 s (existing/candidate).
Row values were not emitted. The comparison covers one issue and one snapshot;
it does not establish general parity or full-page performance. Temporary files
were removed and connections closed.

The user explicitly selected production for a read-only comparison. In one
repeatable-read snapshot, the deployed and isolated candidate review handlers
returned HTTP 200 in 5.349 s and 0.300 s respectively; rendered HTML matched
after CSRF-token normalization. The candidate contained only the scoped-join
change, excluding unrelated uncommitted review changes. Deployed reader hashes
matched release 0.144.43. All four services were healthy; temporary files were
removed and the database connection closed. No serving code was changed.

This is one selected issue and two sequential direct-handler samples; cache,
browser/network performance, other issue types and restricted-record cases are
not certified. Local candidate changes the two joins in source_record_views.py
and finding_review.py, retaining tenant/observation predicates, protected view,
restricted handling and left-join semantics. Existing unrelated uncommitted
changes to finding_review.py must be preserved. No migration. No local tests
per user instruction. Commit and deployment require separate approval.
