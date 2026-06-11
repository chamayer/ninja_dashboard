from __future__ import annotations

import logging
import re


_BEARER_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+")
_TOKEN_RE = re.compile(r'("?(?:access_token|client_secret|token)"?\s*[:=]\s*["\']?)[^"\'\s,}]+')


class _RedactSecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        message = _BEARER_RE.sub(r"\1[REDACTED]", message)
        message = _TOKEN_RE.sub(r"\1[REDACTED]", message)
        record.msg = message
        record.args = ()
        return True


def install_log_safety() -> None:
    root = logging.getLogger()
    root.addFilter(_RedactSecretsFilter())
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
