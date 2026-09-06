import os

import litellm

EMBEDDING_DIM = 1536
EMBEDDING_MODEL_ENV_VAR = "EMBEDDING_MODEL"


class EmbeddingService:
    """Computes text embeddings via litellm for ORM models with a vector embedding column.

    Centralizes the EMBEDDING_MODEL env var lookup and litellm calls shared by
    models such as GraphSchemaRegistry and NodeEmbedding, so they stay agnostic
    of which embedding provider is configured.
    """

    @staticmethod
    async def compute_embeddings(texts: list[str]) -> list[list[float]] | None:
        """Compute embeddings for a batch of texts via litellm.

        Reads the model name from the EMBEDDING_MODEL env var (e.g. "openai/text-embedding-3-small",
        "azure/...", "huggingface/..."). If unset, embedding is skipped so callers without an
        embedding provider configured are unaffected.

        Args:
            texts: Batch of texts to embed, one per record.

        Returns:
            One embedding vector per input text, or None if EMBEDDING_MODEL is not set.
        """
        model = os.getenv(EMBEDDING_MODEL_ENV_VAR)
        if not model or not texts:
            return None

        response = await litellm.aembedding(model=model, input=texts)
        return [item["embedding"] for item in response.data]


__all__ = ["EmbeddingService", "EMBEDDING_DIM", "EMBEDDING_MODEL_ENV_VAR"]
