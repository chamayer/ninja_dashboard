# PLAN-031 — Source record and reported states

Completed 2026-10-28. Source Records distinguishes Present/Withdrawn record
state from the individual source record's Online/Offline/unknown state in HTML
and CSV. Migration 0360 exposes the reported value through the tenant-scoped,
restricted-layout-aware metadata view.

Commit `b393c57` was pushed to origin and the mirror. Production applied
migrations 0358–0360 on 2026-10-28; Operations was healthy and its Django
system check passed. A production read under `operations_app` confirmed the
two ScreenConnect records used in the investigation reported offline and
online respectively. The deployed template contains the new column. Python
compilation, migration Ruff, whitespace, and a rolled-back local view migration
also passed. An authenticated browser check was not performed. Registry
validation in the worktree reported the separate PLAN-028 blueprint mismatch.
