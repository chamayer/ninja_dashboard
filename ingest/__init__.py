"""ninja-dashboard ingest package.

Pulls data from the NinjaRMM v2 API on a schedule and writes it to
Postgres. See REQUIREMENTS.md and CONTEXT.md for design and scope.
"""

from pathlib import Path

VERSION = (Path(__file__).parent.parent / "VERSION").read_text().strip()
