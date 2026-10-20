# =============================================================================
# ninja-dashboard / postgres
# Just postgres:16-alpine with our first-boot init script baked in.
#
# WHY: Portainer Repository-mode stacks can't bind-mount repo-relative
# paths at runtime — Portainer uses the cloned repo only for the build
# context and the compose YAML, not as a persistent extracted tree on
# disk. So `./sql/init:/docker-entrypoint-initdb.d:ro` resolves to an
# empty host directory and the init script never runs. Baking it into
# a custom image means the file is in the image layer; no bind-mount
# needed. Same pattern dmarc-manager uses for its app code.
# =============================================================================
FROM postgres:16-alpine
COPY sql/init/ /docker-entrypoint-initdb.d/
