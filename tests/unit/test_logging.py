"""Logging behavior tests."""

import logging

from cyclescope.infrastructure.logging import configure_logging


def test_logging_configures_console_and_file(tmp_path: object) -> None:
    configure_logging("DEBUG", tmp_path)  # type: ignore[arg-type]
    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert len(root.handlers) == 2
    for handler in root.handlers:
        handler.close()
    root.handlers.clear()
