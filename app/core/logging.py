import logging
import sys
from pythonjsonlogger import jsonlogger


def setup_logging(level: str = "info") -> None:
    level_value = getattr(logging, level.upper(), logging.INFO)
    logger = logging.getLogger()
    logger.setLevel(level_value)

    # Remove existing handlers
    for h in list(logger.handlers):
        logger.removeHandler(h)

    log_handler = logging.StreamHandler(sys.stdout)
    fmt = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s %(pathname)s %(lineno)d"
    )
    log_handler.setFormatter(fmt)
    logger.addHandler(log_handler)

    # Silence noisy loggers
    for noisy in ("uvicorn.access", "asyncio", "httpx", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
