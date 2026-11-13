# PLAN-056 — Software emergency recovery

User authorized immediate Software recovery within five minutes, retaining the
existing contract. This follows release ee98be1d / 0.144.17.

Confirmed evidence: latest overview failures report `Software overview preparation
inputs are pending or failed`. There are 310 unconsumed classification targets.
The latest ownership sweep was stalled with worker_interrupted during deployment.
The stored summary dates from November 12 and its window expiration is past;
showing it as current would violate the existing contract.

Recovery uses existing governed Job admission: ownership sweep 167ccfa6 and
classification-only 67944e89 began at 16:00:49 UTC. Both are executing. An overview
is already queued waiting for protected work. No direct summary edits, validity
bypass, test changes, runtime replacement, or deployment performed for recovery.

Both input recovery runs completed: classifier at 16:02:09 UTC, sweep at 16:04:35.
The next overview failed because a second request changed its captured inputs.
Further automatic admission also changed the publication fence. No material input
change is necessary to trigger this failure: queued overview request metadata is
part of the captured input token.

The scoped scheduler correction now recovers pending classification before
overview admission, avoids duplicate classification requests, and defers duplicate
overview requests while a run is queued/running. Existing validity fences remain.
Syntax and focused Ruff passed. Release 0.144.18 is being prepared with no
migrations. Deployment waits for the current publication to finish.

A reviewed helper briefly holds the existing scheduler leader lease for 85 seconds
to allow the current publisher to finish without duplicate scheduled requests.
The lease releases in finally or on connection termination. No job results or
publication values are altered by this helper.

Next: wait for actual input completion, existing publication, then verify the
protected result and authenticated populated Software HTML. No success claimed.
