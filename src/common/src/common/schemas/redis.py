"""Redis cache configuration loaded from the shared YAML settings file."""

import os
from typing import Any

from pydantic import BaseModel, ConfigDict, SecretStr, model_validator


class RedisSettings(BaseModel):
    """Redis connection settings.

    The complete connection string is secret because it may contain credentials.
    YAML names the environment variable that supplies it; the value is never
    stored in the YAML file or exposed by the settings model's representation.
    """

    model_config = ConfigDict(hide_input_in_errors=True)

    connection_string: SecretStr | None = None

    @model_validator(mode="before")
    @classmethod
    def resolve_connection_string_env(cls, data: Any) -> Any:
        """Resolve `connection_string_env` into a masked secret value."""
        if isinstance(data, dict) and "connection_string_env" in data:
            data = dict(data)
            env_name = data.pop("connection_string_env")
            if env_name:
                data.setdefault("connection_string", os.environ.get(env_name))
        return data

    @property
    def is_configured(self) -> bool:
        """Whether a non-empty connection string was supplied."""
        return bool(self.connection_string and self.connection_string.get_secret_value())


__all__ = ["RedisSettings"]
