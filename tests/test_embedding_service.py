import pytest

from graphrag_apacheage.schemas.model import AuthMode, Model, ModelType
from graphrag_apacheage.services.embedding_service import EmbeddingService


def _embedding_model(**overrides) -> Model:
    fields = {
        "id": "text-embedding-3-small",
        "display_name": "Text Embedding 3 Small",
        "name": "text-embedding-3-small",
        "provider": "openai",
        "connection_string": "https://api.openai.com/v1",
        "auth_mode": AuthMode.API_KEY,
        "api_key": "test-key",
        "type": [ModelType.EMBEDDING],
        "embedding_dimension": 3,
    }
    fields.update(overrides)
    return Model.model_validate(fields)


async def test_compute_embeddings_skips_when_model_is_none():
    result = await EmbeddingService.compute_embeddings(None, ["hello world"])

    assert result is None


async def test_compute_embeddings_skips_when_texts_empty():
    result = await EmbeddingService.compute_embeddings(_embedding_model(), [])

    assert result is None


async def test_compute_embeddings_calls_litellm_with_model_details(monkeypatch):
    import graphrag_apacheage.services.embedding_service as embedding_service

    captured = {}

    class FakeResponse:
        data = [{"embedding": [0.1, 0.2, 0.3]}, {"embedding": [0.4, 0.5, 0.6]}]

    async def fake_aembedding(**kwargs):
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(embedding_service.litellm, "aembedding", fake_aembedding)

    result = await EmbeddingService.compute_embeddings(_embedding_model(), ["a", "b"])

    assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert captured["model"] == "openai/text-embedding-3-small"
    assert captured["input"] == ["a", "b"]
    assert captured["api_base"] == "https://api.openai.com/v1"
    assert captured["api_key"] == "test-key"
    assert captured["dimensions"] == 3


async def test_compute_embeddings_omits_api_key_for_managed_identity(monkeypatch):
    import graphrag_apacheage.services.embedding_service as embedding_service

    captured = {}

    class FakeResponse:
        data = [{"embedding": [0.1, 0.2, 0.3]}]

    async def fake_aembedding(**kwargs):
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(embedding_service.litellm, "aembedding", fake_aembedding)

    model = _embedding_model(auth_mode=AuthMode.MANAGED_IDENTITY, api_key=None)
    await EmbeddingService.compute_embeddings(model, ["a"])

    assert "api_key" not in captured


async def test_compute_embeddings_raises_when_provider_returns_wrong_width(monkeypatch):
    """The embedding columns are dimensionless (ADR-0003), so the database no
    longer rejects a mis-sized vector - this check is the only thing that does."""
    import graphrag_apacheage.services.embedding_service as embedding_service

    class FakeResponse:
        # The model below declares embedding_dimension=3.
        data = [{"embedding": [0.1, 0.2, 0.3]}, {"embedding": [0.4, 0.5]}]

    async def fake_aembedding(**kwargs):
        return FakeResponse()

    monkeypatch.setattr(embedding_service.litellm, "aembedding", fake_aembedding)

    with pytest.raises(ValueError, match="returned a 2-dimension vector, expected 3"):
        await EmbeddingService.compute_embeddings(_embedding_model(), ["a", "b"])
