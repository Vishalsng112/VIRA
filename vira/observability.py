"""Logging and request observability helpers."""
import os
import sys

from loguru import logger


def configure_logging() -> None:
    """Enable JSON logs when VIRA_LOG_JSON=1 (production-friendly)."""
    if os.environ.get("VIRA_LOG_JSON", "").lower() not in ("1", "true", "yes"):
        return
    logger.remove()
    logger.add(sys.stderr, serialize=True, level=os.environ.get("VIRA_LOG_LEVEL", "INFO"))
