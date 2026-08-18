from __future__ import annotations

import contextvars
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.core.config import AppConfig

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")

SENSITIVE_FIELD_MARKERS = (
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
)

STANDARD_LOG_RECORD_FIELDS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}


def get_request_id() -> contextvars.ContextVar[str]:
    return _request_id


class RedactingJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or _request_id.get(),
        }
        for field_name in (
            "project_id",
            "audit_id",
            "stage",
            "unit_id",
            "llm_invocation_id",
            "duration",
            "status",
            "error_code",
        ):
            value = getattr(record, field_name, None)
            if value is not None:
                payload[field_name] = value
        for field_name, value in record.__dict__.items():
            if field_name in STANDARD_LOG_RECORD_FIELDS or field_name in payload:
                continue
            payload[field_name] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(redact_sensitive_values(payload), ensure_ascii=False, default=str)


def configure_logging(config: AppConfig) -> logging.Logger:
    logger = logging.getLogger("architecture_visualizer")
    logger.setLevel(config.log_level)
    logger.propagate = False

    handler = logging.StreamHandler()
    handler.setFormatter(RedactingJsonFormatter())
    handler.setLevel(config.log_level)

    logger.handlers.clear()
    logger.addHandler(handler)
    return logger


def redact_sensitive_values(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: "***" if _is_sensitive_key(str(key)) else redact_sensitive_values(nested_value)
            for key, nested_value in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_values(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive_values(item) for item in value)
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return any(marker in normalized for marker in SENSITIVE_FIELD_MARKERS)
