from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def redact_url(url: str) -> str:
    """Return a log-safe version of a URL.

    Keeps scheme, host, port, and path. Drops username, password,
    query string, and fragment so secrets never leak into logs.
    """
    parts = urlsplit(url)
    netloc = parts.hostname or ""
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    path = parts.path or ""
    return urlunsplit((parts.scheme, netloc, path, "", ""))
