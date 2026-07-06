# ninja-dashboard Project Overrides

This file supplements `C:\Users\chamayer\Documents\Development\DEVELOPMENT.md`.

## Module Documentation

`ninja-dashboard` is a multi-service repo. Root state files stay as the
project index. Module-level work may keep detailed state inside the module.

For Operations work:

- Root `BLUEPRINT.md` is a checkpoint/router only.
- Detailed active plan lives at `operations/BUILD_BLUEPRINT.md`.
- Detailed session log lives at `operations/SESSIONS.md`.
- Detailed backlog lives at `operations/TODO.md`.
- Root `SESSIONS.md` and `TODO.md` get short pointer entries only when
  Operations work affects repo-level status.
- `operations/BLUEPRINT.md` is the product architecture/specification
  document, not the per-session scratchpad.

Before editing Operations code, report the active doc paths and wait for
approval for the specific M0 slice being changed.
