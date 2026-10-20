# Goal

- Move service-owned build files out of the repository root without changing
  Docker build contexts or runtime behavior.

# Scope

- Move ingest dependencies and Dockerfile into `ingest/`.
- Move the Operations Dockerfile into `operations/`.
- Group the shared Postgres Dockerfile under `docker/`.
- Update Compose, tests, and current task references.

# Status

- Done.

# Checkpoint

- Compose retains the repository-root build context. Service Dockerfiles now
  live with their owners (`ingest/`, `operations/`), while the shared Postgres
  image definition lives in `docker/`. The ingest dependency manifest moved to
  `ingest/requirements.txt`; its Dockerfile copy path, Compose paths, test,
  and current TODO references were updated. `docker compose config --quiet`,
  whitespace checks, and governance validation passed; the focused Operations
  test has an unrelated stale catalog-count expectation (53 versus 61 current
  definitions). No runtime behavior changed.

# Next action

- Replace this blueprint with the next approved root or cross-service task.
