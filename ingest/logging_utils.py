from __future__ import annotations

import logging
import re


_BEARER_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+")
_TOKEN_RE = re.compile(
    r'("?(?:access_token|client_secret|token)"?\s*[:=]\s*["\']?)[^"\'\s,}]+'
)

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def redact(text: str) -> str:
    """Remove bearer tokens and token-like values from any text."""
    text = _BEARER_RE.sub(r"\1[REDACTED]", text)
    return _TOKEN_RE.sub(r"\1[REDACTED]", text)


class _RedactingFormatter(logging.Formatter):
    """Redacts the whole formatted record, exception and stack text included.

    Redaction has to live on handlers: Python runs a logger's filters only for
    records logged on that logger itself, never for records propagated from a
    child logger, so a filter on the root logger does not see module loggers.
    """

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def install_log_safety() -> None:
    """Redact every root handler's output and quiet noisy HTTP client loggers."""
    for handler in logging.getLogger().handlers:
        current = handler.formatter
        handler.setFormatter(
            _RedactingFormatter(
                current._fmt if current is not None else LOG_FORMAT,
                current.datefmt if current is not None else None,
            )
        )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
