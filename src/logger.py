"""Centralized logging configuration for Rumor Agent.

Usage:
    from src.logger import get_logger
    logger = get_logger(__name__)
    logger.info("Something happened")
"""

import logging
import sys
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOG_DIR / "rumor_agent.log"

_FMT = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"


def _build_handler(stream) -> logging.StreamHandler:
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter(_FMT, datefmt=_DATE_FMT))
    return handler


def _file_handler() -> logging.FileHandler:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    handler.setFormatter(logging.Formatter(_FMT, datefmt=_DATE_FMT))
    return handler


def configure_logging(level: int | str = logging.INFO) -> None:
    """Configure the root logger. Call once at application startup."""
    root = logging.getLogger()
    if root.handlers:
        return  # already configured
    root.setLevel(level)
    root.addHandler(_build_handler(sys.stderr))
    root.addHandler(_file_handler())


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Call configure_logging() at app startup."""
    return logging.getLogger(name)
