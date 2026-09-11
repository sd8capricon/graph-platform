from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from graphrag_apacheage.schemas.model import Model

DEFAULT_CONFIG_PATH = Path("configs/local.yaml")


class AppSettings(BaseModel):
    """Application configuration loaded from a YAML file (see `configs/local.yaml`).

    Attributes:
        embedding_dimension: Vector size for the `embedding` column on ORM models
            with a pgvector column (see `models/node_embedding.py`,
            `models/graph_schema_registry.py`).
        models: The configured LLM/embedding provider connections.
    """

    embedding_dimension: int = 1536
    models: list[Model] = Field(default_factory=list)

    def __init__(self, path: str | Path | None = None, **data: Any):
        """Build AppSettings, optionally loading fields from a YAML config file.

        Args:
            path: Path to a YAML config file (see `configs/local.yaml`). Its
                `embedding_dimensions` key populates `embedding_dimension` and its
                `models` list populates `models`. If omitted, only `**data` (and
                field defaults) apply, so no file is read.
            **data: Field overrides, take precedence over values loaded from `path`.

        Raises:
            pydantic.ValidationError: If the resulting fields are invalid.
        """
        if path is not None:
            loaded = yaml.safe_load(Path(path).read_text())
            data.setdefault("embedding_dimension", loaded["embedding_dimensions"])
            data.setdefault("models", loaded.get("models") or [])
        super().__init__(**data)


settings = AppSettings()
"""Module-level settings singleton. ORM models with a pgvector `embedding` column
(see `models/node_embedding.py`, `models/graph_schema_registry.py`) read
`settings.embedding_dimension` at class-definition time, so `load_config()` must
run before those modules are first imported anywhere.
"""


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> AppSettings:
    """Load app config once on startup and apply it to the active settings.

    Updates the `settings` singleton's fields in place (rather than rebinding
    the module-level name) so modules that already did
    `from graphrag_apacheage.config import settings` see the loaded values too.

    Args:
        path: Path to the YAML config file, defaulting to `DEFAULT_CONFIG_PATH`.

    Returns:
        The `settings` singleton, now updated with values loaded from `path`.
    """
    loaded = AppSettings(path)
    for name in AppSettings.model_fields:
        setattr(settings, name, getattr(loaded, name))
    return settings


__all__ = ["AppSettings", "DEFAULT_CONFIG_PATH", "settings", "load_config"]
