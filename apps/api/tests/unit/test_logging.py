import json
import logging

from app.core.config import AppConfig
from app.core.logging import RedactingJsonFormatter, configure_logging, get_request_id


def test_redacting_json_formatter_masks_sensitive_fields() -> None:
    formatter = RedactingJsonFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.credentials = "secret"
    record.error_code = "TEST"

    payload = json.loads(formatter.format(record))

    assert payload["message"] == "hello"
    assert payload["error_code"] == "TEST"
    assert payload["credentials"] == "***"
    assert "secret" not in json.dumps(payload)


def test_configure_logging_uses_configured_level_and_request_id() -> None:
    logger = configure_logging(AppConfig(log_level="DEBUG"))
    token = get_request_id().set("request-5")
    try:
        record = logging.LogRecord(
            name=logger.name,
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="message",
            args=(),
            exc_info=None,
        )
        payload = json.loads(logger.handlers[0].formatter.format(record))
    finally:
        get_request_id().reset(token)

    assert logger.level == logging.DEBUG
    assert payload["request_id"] == "request-5"
