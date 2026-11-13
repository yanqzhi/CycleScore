"""Console and rotating-file logging setup."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


class UTCFormatter(logging.Formatter):
    """Formatter that emits UTC timestamps."""

    converter = __import__("time").gmtime


def configure_logging(level: str, log_directory: Path) -> None:
    """Configure root logging with console and rotating UTF-8 file handlers."""
    log_directory.mkdir(parents=True, exist_ok=True)
    formatter = UTCFormatter(
        "%(asctime)sZ %(levelname)s %(name)s %(message)s", "%Y-%m-%dT%H:%M:%S"
    )
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    file_handler = RotatingFileHandler(
        log_directory / "cyclescope.log",
        maxBytes=5_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(console)
    root.addHandler(file_handler)
