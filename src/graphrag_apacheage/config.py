from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from graphrag_apacheage.schemas.model import Model

DEFAULT_CONFIG_PATH = Path("configs/local.yaml")


class AppSettings(BaseModel):
    """Application configuration loaded from a YAML file (see `configs/local.yaml`).

    Attributes:
        models: The configured LLM/embedding provider connections.
    """

    models: list[Model] = Field(default_factory=list)

    def __init__(self, path: str | Path | None = None, **data: Any):
        """Build AppSettings, optionally loading fields from a YAML config file.

        Args:
            path: Path to a YAML config file (see `configs/local.yaml`). Its
                `models` list populates `models`. If omitted, only `**data` (and
                field defaults) apply, so no file is read.
            **data: Field overrides, take precedence over values loaded from `path`.

        Raises:
            pydantic.ValidationError: If the resulting fields are invalid.
        """
        if path is not None:
            loaded = yaml.safe_load(Path(path).read_text())
            data.setdefault("models", loaded.get("models") or [])
        super().__init__(**data)


settings = AppSettings()
"""Module-level settings singleton.

There is deliberately no process-wide `embedding_dimension` here. It used to size
the pgvector `embedding` columns, which forced every organization onto one vector
width and made `load_config()` ordering load-bearing (the column size was fixed at
class-definition time, so importing a model module too early silently baked in the
default). ADR-0003 made those columns dimensionless, which removed both problems:
the only dimension knob left is `Model.embedding_dimension`, per provider entry.
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
