import os
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from pydantic import BaseModel, Field, SecretStr, model_validator


class AuthMode(str, Enum):
    """Enumeration of supported authentication modes for connecting to a model provider.

    Attributes:
        API_KEY: Authenticate using a static API key.
        MANAGED_IDENTITY: Authenticate using a cloud-managed identity (no API key needed).
    """

    API_KEY = "api_key"
    MANAGED_IDENTITY = "managed_identity"


class ModelType(str, Enum):
    """Enumeration of capabilities a model can be used for.

    Attributes:
        EMBEDDING: The model can compute text embeddings.
        VISION: The model can process image inputs.
        THINKING: The model supports extended/step-by-step reasoning.
    """

    EMBEDDING = "embedding"
    VISION = "vision"
    THINKING = "thinking"


class Model(BaseModel):
    """Represents a configured LLM/embedding model provider connection.

    Attributes:
        id: Unique identifier for the model. Auto-generated as UUID if not provided.
        display_name: A human-friendly name for this configured model (e.g., 'Chat GPT-4o').
        name: The name of the model (e.g., 'gpt-4o', 'text-embedding-3-small').
        provider: The provider serving the model (e.g., 'openai', 'azure').
        connection_string: The connection string/endpoint used to reach the provider.
        auth_mode: How to authenticate with the provider: 'api_key' or 'managed_identity'.
        type: The capabilities this model supports (e.g., embedding, vision, thinking).
        api_key: The API key used to authenticate, required when auth_mode is 'api_key'.
            Stored as a SecretStr so it is masked in reprs/logs.
        embedding_dimension: The output vector size, required when 'embedding' is in type.
    """

    id: str | None = None
    display_name: str
    name: str
    provider: str
    connection_string: str
    auth_mode: AuthMode
    type: list[ModelType] = Field(default_factory=list)
    api_key: SecretStr | None = None
    embedding_dimension: int | None = None

    @model_validator(mode="before")
    @classmethod
    def ensure_id(cls, data: Any) -> Any:
        """Ensure that the model has an ID by generating a UUID if not provided.

        Args:
            data: The raw data dictionary before model instantiation.

        Returns:
            The data dictionary with id field populated (generated if necessary).
        """
        if isinstance(data, dict):
            data = dict(data)
            data.setdefault("id", str(uuid4()))
        return data

    @model_validator(mode="after")
    def ensure_api_key_matches_auth_mode(self) -> "Model":
        """Ensure api_key is provided only when it's required by auth_mode.

        Returns:
            The validated Model instance.

        Raises:
            ValueError: If auth_mode is 'api_key' but no api_key was provided.
        """
        if self.auth_mode == AuthMode.API_KEY and self.api_key is None:
            raise ValueError("api_key is required when auth_mode is 'api_key'")
        return self

    @model_validator(mode="after")
    def ensure_embedding_dimension_matches_type(self) -> "Model":
        """Ensure embedding_dimension is provided only when it's required by type.

        Returns:
            The validated Model instance.

        Raises:
            ValueError: If 'embedding' is in type but no embedding_dimension was provided.
        """
        if ModelType.EMBEDDING in self.type and self.embedding_dimension is None:
            raise ValueError(
                "embedding_dimension is required when 'embedding' is in type"
            )
        return self

    @classmethod
    def from_config(cls, path: str | Path) -> list["Model"]:
        """Load Models from a YAML config file (see `configs/local.yaml`).

        The file has a top-level `models` list; each entry matches Model's fields
        except `api_key_env` replaces `api_key` — it names the environment variable
        to read the actual API key value from at load time.

        Args:
            path: Path to the YAML config file.

        Returns:
            A list of Model instances, one per entry in the config's `models` list.

        Raises:
            pydantic.ValidationError: If an entry is missing required fields or invalid.
        """
        data = yaml.safe_load(Path(path).read_text())

        models = []
        for entry in data.get("models", []):
            entry = dict(entry)
            api_key_env = entry.pop("api_key_env", None)
            if api_key_env:
                entry["api_key"] = os.environ.get(api_key_env)
            models.append(cls(**entry))
        return models


__all__ = ["Model", "AuthMode", "ModelType"]
