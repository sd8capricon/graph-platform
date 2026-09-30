"""Apply a service's `LoggingSettings` to the process's root logger."""

import logging.config
from typing import Any

from common.schemas.logging import LoggingSettings

LOG_FORMAT = "%(asctime)s %(levelname)s [%(processName)s] %(name)s: %(message)s"


def configure_logging(settings: LoggingSettings) -> None:
    """Configure the root logger from `settings`.

    Uses `dictConfig`, which replaces the root logger's handlers, so calling this
    more than once does not duplicate output. Existing module-level loggers stay
    enabled (`disable_existing_loggers=False`) and propagate to the root.

    Args:
        settings: The service's validated logging section.
    """
    handler: dict[str, Any]
    if settings.log_output == "file":
        assert settings.log_file_path is not None  # enforced by LoggingSettings
        settings.log_file_path.parent.mkdir(parents=True, exist_ok=True)
        handler = {
            "class": "logging.FileHandler",
            "filename": str(settings.log_file_path),
            "encoding": "utf-8",
        }
    else:
        handler = {"class": "logging.StreamHandler", "stream": "ext://sys.stdout"}

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"default": {"format": LOG_FORMAT}},
            "handlers": {"default": {**handler, "formatter": "default"}},
            "root": {"level": settings.log_level, "handlers": ["default"]},
        }
    )


__all__ = ["configure_logging", "LOG_FORMAT"]
