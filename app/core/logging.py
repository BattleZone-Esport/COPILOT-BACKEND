
import logging
import sys
import contextvars
from typing import Any, List

from pythonjsonlogger import jsonlogger

# Context variable for request ID
request_id_var = contextvars.ContextVar("request_id", default="unassigned")

# List of keys to redact from logs
SENSITIVE_KEYS = [
    "prompt",
    "input",
    "output",
    "final_output",
    "intermediate_output",
    "content",
    "code",
    "diff",
    # From settings
    "AUTH_SECRET_KEY",
    "AUTH_GOOGLE_CLIENT_ID",
    "AUTH_GOOGLE_CLIENT_SECRET",
    "OPENAI_API_KEY",
    "MONGODB_URI",
    "MONGO_URI",
    "QSTASH_TOKEN",
    "REDIS_URL",
]


def _redact(obj: Any) -> Any:
    """Recursively redact sensitive keys from a dictionary or list."""
    if isinstance(obj, dict):
        return {
            k: "[REDACTED]" if k in SENSITIVE_KEYS and v is not None else _redact(v)
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [_redact(item) for item in obj]
    return obj


class RedactingFilter(logging.Filter):
    """A logging filter that redacts sensitive information."""

    def filter(self, record):
        # Redact the top-level message if it's a dict
        if isinstance(record.msg, dict):
            record.msg = _redact(record.msg)

        # Redact the `args` tuple
        if record.args:
            record.args = _redact(list(record.args))

        return True


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """
    A custom JSON formatter that adds the request_id from context
    and redacts sensitive data.
    """

    def add_fields(self, log_record, record, message_dict):
        super(CustomJsonFormatter, self).add_fields(log_record, record, message_dict)
        if "request_id" not in log_record:
            log_record["request_id"] = request_id_var.get()

        # The filter runs before the formatter, but we can do a final pass
        # on the fully formed log_record just in case.
        for key, value in log_record.items():
            if key in SENSITIVE_KEYS and value is not None:
                log_record[key] = "[REDACTED]"


def setup_logging(level: str = "info") -> None:
    """
    Configures logging with a JSON formatter, a request ID, and redaction.
    """
    level_value = getattr(logging, level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(level_value)

    # Remove any existing handlers to avoid duplicate logs
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)

    log_handler = logging.StreamHandler(sys.stdout)

    # Add the redacting filter to the handler
    log_handler.addFilter(RedactingFilter())

    # Define the format for the logs
    # The formatter will automatically pick up extra fields
    formatter = CustomJsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )

    log_handler.setFormatter(formatter)
    root_logger.addHandler(log_handler)

    # Silence overly verbose third-party loggers
    for noisy_logger in ("uvicorn.access", "asyncio", "httpx", "openai", "websockets"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

