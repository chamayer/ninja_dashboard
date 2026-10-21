# Development reference material

This directory holds durable supporting material used while developing or
maintaining the stack. It is not runtime input and is not archival history.

- `ninja-api/` contains local Ninja RMM API specifications. The large vendor
  JSON exports are intentionally ignored; keep only their small index and
  acquisition guidance in Git.
- `legacy-software-decisions-README.md` explains the retained software
  decision reference data in this directory.
- `authenticated-browser-measurement.md` documents the safe, read-only
  headless-browser method for validating deployed Operations navigation.

Reference material must identify its source, intended use, and whether it is
tracked. Do not use it as evidence of current production behavior without
separate verification.
