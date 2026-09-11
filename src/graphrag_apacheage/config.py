from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


class AppSettings(BaseModel):
    """Application configuration loaded from a YAML file (see `configs/local.yaml`).

    Attributes:
        embedding_dimension: Vector size for the `embedding` column on ORM models
            with a pgvector column (see `models/node_embedding.py`,
            `models/graph_schema_registry.py`).
    """

    embedding_dimension: int = 1536

    def __init__(self, path: str | Path | None = None, **data: Any):
        """Build AppSettings, optionally loading fields from a YAML config file.

        Args:
            path: Path to a YAML config file (see `configs/local.yaml`). Its
                `embedding_dimensions` key is used to populate `embedding_dimension`.
                If omitted, only `**data` (and field defaults) apply.
            **data: Field overrides, take precedence over values loaded from `path`.

        Raises:
            pydantic.ValidationError: If the resulting fields are invalid.
        """
        if path is not None:
            loaded = yaml.safe_load(Path(path).read_text())
            data.setdefault("embedding_dimension", loaded["embedding_dimensions"])
        super().__init__(**data)


settings = AppSettings()
"""Module-level settings singleton. ORM models with a pgvector `embedding` column
(see `models/node_embedding.py`, `models/graph_schema_registry.py`) read
`settings.embedding_dimension` at class-definition time, so `load_config()` must
run before those modules are first imported anywhere.
"""


def load_config(path: str | Path) -> AppSettings:
    """Load app config on startup and apply it as the active settings.

    Args:
        path: Path to the YAML config file.

    Returns:
        The loaded AppSettings, now also stored as the module's `settings` singleton.
    """
    global settings
    settings = AppSettings(path)
    return settings


__all__ = ["AppSettings", "settings", "load_config"]
