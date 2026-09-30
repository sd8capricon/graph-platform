"""Per-service logging configuration loaded from the shared YAML settings file.

Each Python service owns its own `<service>.logging` section in
`configs/local.yaml` (e.g. `ingestion_worker.logging`, `agent_runtime.logging`)
and validates it with `LoggingSettings`; `common.logging_setup.configure_logging`
applies it to the root logger.
"""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
LogOutput = Literal["stdout", "file"]


class LoggingSettings(BaseModel):
    """Logging settings for one service.

    Blank values in YAML mean "use the default", so the template's empty strings
    are valid. Unknown keys and invalid values fail loudly.

    Attributes:
        log_level: Root logger level, case-insensitive. Defaults to `INFO`.
        log_output: `stdout` (default) or `file`.
        log_file_path: Log file path, required when `log_output` is `file`.
            Relative paths resolve against the working directory.
    """

    model_config = ConfigDict(extra="forbid")

    log_level: LogLevel = "INFO"
    log_output: LogOutput = "stdout"
    log_file_path: Path | None = None

    @field_validator("log_level", "log_output", mode="before")
    @classmethod
    def normalize_choice(cls, value: Any, info) -> Any:
        """Treat blank as the field default and match choices case-insensitively."""
        if value is None or (isinstance(value, str) and not value.strip()):
            return cls.model_fields[info.field_name].default
        if isinstance(value, str):
            value = value.strip()
            return value.upper() if info.field_name == "log_level" else value.lower()
        return value

    @field_validator("log_file_path", mode="before")
    @classmethod
    def blank_path_is_none(cls, value: Any) -> Any:
        """Treat a blank file path as unset."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def require_file_path_for_file_output(self) -> "LoggingSettings":
        """File output needs somewhere to write."""
        if self.log_output == "file" and self.log_file_path is None:
            raise ValueError("log_file_path is required when log_output is 'file'")
        return self


__all__ = ["LoggingSettings", "LogLevel", "LogOutput"]
