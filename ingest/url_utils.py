from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def redact_url(url: str) -> str:
    """Return a log-safe version of a URL.

    Keeps scheme, host, and port. Drops username, password, path,
    query string, and fragment so secrets never leak into logs.
    """
    parts = urlsplit(url)
    netloc = parts.hostname or ""
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, "", "", ""))
