"""Application entry point."""

import logging

from cyclescope.infrastructure.config import get_settings
from cyclescope.infrastructure.logging import configure_logging


def main() -> None:
    """Initialize application logging and report readiness."""
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_directory)
    logging.getLogger(__name__).info(
        "%s %s ready", settings.app_name, settings.app_version
    )


if __name__ == "__main__":
    main()
