"""Log redaction applies to every logger, exception text included."""

from __future__ import annotations

import io
import logging

import pytest

from ingest import logging_utils


@pytest.fixture
def stream(monkeypatch):
    root = logging.getLogger()
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(logging.Formatter(logging_utils.LOG_FORMAT))
    monkeypatch.setattr(root, "handlers", [handler])
    monkeypatch.setattr(root, "filters", [])
    logging_utils.install_log_safety()
    return output


def test_a_module_logger_message_is_redacted(stream):
    # A filter on the root logger never sees records propagated from a module
    # logger; the redaction has to be on the handler.
    logging.getLogger("ingest.connectors.example").warning(
        "calling with Authorization: Bearer abc.def-123 and token=s3cr3t"
    )
    text = stream.getvalue()
    assert "abc.def-123" not in text and "s3cr3t" not in text
    assert "Bearer [REDACTED]" in text and "token=[REDACTED]" in text


def test_exception_text_is_redacted(stream):
    try:
        raise RuntimeError('upstream refused {"access_token": "eyJhbGciOi"}')
    except RuntimeError:
        logging.getLogger("ingest.jobs_child").exception("Job failed")
    text = stream.getvalue()
    assert "Traceback" in text
    assert "eyJhbGciOi" not in text
    assert '"access_token": "[REDACTED]' in text


def test_redact_is_usable_on_plain_text():
    assert logging_utils.redact("client_secret=abc Bearer zzz") == (
        "client_secret=[REDACTED] Bearer [REDACTED]"
    )
