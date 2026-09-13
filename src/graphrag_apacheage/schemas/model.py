import os
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator


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
        id: Stable, caller-assigned UUID identifying this configured model entry.
            Required, not auto-generated - it must stay the same across process
            restarts, since it is stamped as the embedding-provenance value on
            `NodeEmbedding`/`SchemaEmbedding` rows (`embedding_model_id`) and is
            what `vector_search()` filters on and the partial ANN index is
            predicated on (see `Model.identifier` for the distinct litellm-model
            string, which is not used for provenance). Must parse as a UUID
            (any version/format `uuid.UUID` accepts); stored as `str`, not
            `UUID`, since every consumer (column value, SQL literal, dict key)
            treats it as a plain string.
        display_name: A human-friendly name for this configured model (e.g., 'Chat GPT-4o').
        name: The name of the model (e.g., 'gpt-4o', 'text-embedding-3-small').
        provider: The provider serving the model (e.g., 'openai', 'azure').
        connection_string: The connection string/endpoint used to reach the provider.
            Optional — omit to use the provider's default endpoint (e.g. litellm's
            built-in routing for a known provider name).
        auth_mode: How to authenticate with the provider: 'api_key' or 'managed_identity'.
        type: The capabilities this model supports (e.g., embedding, vision, thinking).
        api_key: The API key used to authenticate, required when auth_mode is 'api_key'.
            Stored as a SecretStr so it is masked in reprs/logs.
        embedding_dimension: The output vector size, required when 'embedding' is in type.
        reasoning_effort: Optional reasoning effort level (e.g. 'low', 'medium', 'high')
            for a non-embedding (chat) model. Invalid when 'embedding' is in type.
    """

    id: str
    display_name: str
    name: str
    provider: str
    connection_string: str | None = None
    auth_mode: AuthMode
    type: list[ModelType] = Field(default_factory=list)
    api_key: SecretStr | None = None
    embedding_dimension: int | None = None
    reasoning_effort: str | None = None

    @field_validator("id")
    @classmethod
    def ensure_id_is_uuid(cls, value: str) -> str:
        """Ensure `id` is a valid UUID string.

        `id` is stamped as embedding provenance and is the partial-index
        predicate (see `models/embedding_index.py`), so it must be a
        well-formed identifier, not any caller-chosen string.

        Args:
            value: The raw `id` value before validation.

        Returns:
            The validated id string, unchanged.

        Raises:
            ValueError: If `value` does not parse as a UUID.
        """
        try:
            UUID(value)
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError(f"id must be a valid UUID, got {value!r}") from exc
        return value

    @model_validator(mode="before")
    @classmethod
    def resolve_api_key_env(cls, data: Any) -> Any:
        """Resolve the `api_key_env` config indirection into an actual `api_key` value.

        Config files name an environment variable rather than inlining the secret
        (see `configs/local.yaml`), so entries can validate straight into a Model.

        Args:
            data: The raw data dictionary before model instantiation.

        Returns:
            The data dictionary with `api_key_env` replaced by `api_key`.
        """
        if isinstance(data, dict) and "api_key_env" in data:
            data = dict(data)
            env_name = data.pop("api_key_env")
            if env_name:
                data.setdefault("api_key", os.environ.get(env_name))
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

    @model_validator(mode="after")
    def ensure_reasoning_effort_not_for_embedding(self) -> "Model":
        """Ensure reasoning_effort is only set on non-embedding (chat) models.

        Returns:
            The validated Model instance.

        Raises:
            ValueError: If 'embedding' is in type but reasoning_effort was provided.
        """
        if ModelType.EMBEDDING in self.type and self.reasoning_effort is not None:
            raise ValueError(
                "reasoning_effort is invalid when 'embedding' is in type"
            )
        return self

    @property
    def identifier(self) -> str:
        """The litellm-style `f"{provider}/{name}"` string identifying this model.

        This is the model string litellm itself needs -
        `EmbeddingService.compute_embeddings()` and `agent/chat_model.py`'s
        `build_chat_model()` both pass it as the provider/model to call. It is
        *not* used for embedding provenance: `NodeEmbedding`/`SchemaEmbedding`
        stamp and filter on `Model.id` instead (`embedding_model_id`), since a
        `provider/name` pair is not a stable identity for a configured model
        entry - two entries can share one while differing in endpoint, auth, or
        dimension - whereas `id` is required and caller-assigned.

        Returns:
            `f"{self.provider}/{self.name}"`.
        """
        return f"{self.provider}/{self.name}"


__all__ = ["Model", "AuthMode", "ModelType"]
