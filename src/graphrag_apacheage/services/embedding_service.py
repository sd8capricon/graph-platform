from typing import Any

import litellm

from graphrag_apacheage.schemas.model import AuthMode, Model

EMBEDDING_DIM = 1536


class EmbeddingService:
    """Computes text embeddings via litellm for ORM models with a vector embedding column.

    Centralizes litellm calls shared by models such as GraphSchemaRegistry and
    NodeEmbedding, so they stay agnostic of which embedding provider is configured.
    Callers pass a `Model` (see `schemas/model.py`) describing the embedding
    provider/connection/credentials to use for a given call.
    """

    @staticmethod
    async def compute_embeddings(
        model: Model | None, texts: list[str]
    ) -> list[list[float]] | None:
        """Compute embeddings for a batch of texts via litellm.

        Args:
            model: The embedding provider configuration to use (provider, name,
                connection_string, and auth). If None, embedding is skipped so
                callers without a configured embedding model are unaffected.
            texts: Batch of texts to embed, one per record.

        Returns:
            One embedding vector per input text, or None if no model was provided.
        """
        if model is None or not texts:
            return None

        call_kwargs: dict[str, Any] = {
            "model": f"{model.provider}/{model.name}",
            "input": texts,
        }
        if model.connection_string:
            call_kwargs["api_base"] = model.connection_string
        if model.auth_mode == AuthMode.API_KEY and model.api_key is not None:
            call_kwargs["api_key"] = model.api_key.get_secret_value()
        if model.embedding_dimension is not None:
            call_kwargs["dimensions"] = model.embedding_dimension

        response = await litellm.aembedding(**call_kwargs)
        return [item["embedding"] for item in response.data]


__all__ = ["EmbeddingService", "EMBEDDING_DIM"]
