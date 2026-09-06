from graphrag_apacheage.services.embedding_service import EmbeddingService


async def test_compute_embeddings_skips_when_env_var_unset(monkeypatch):
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)

    result = await EmbeddingService.compute_embeddings(["hello world"])

    assert result is None


async def test_compute_embeddings_skips_when_texts_empty(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "openai/text-embedding-3-small")

    result = await EmbeddingService.compute_embeddings([])

    assert result is None


async def test_compute_embeddings_calls_litellm_when_configured(monkeypatch):
    import graphrag_apacheage.services.embedding_service as embedding_service

    monkeypatch.setenv("EMBEDDING_MODEL", "openai/text-embedding-3-small")

    captured = {}

    class FakeResponse:
        data = [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]

    async def fake_aembedding(model, input):
        captured["model"] = model
        captured["input"] = input
        return FakeResponse()

    monkeypatch.setattr(embedding_service.litellm, "aembedding", fake_aembedding)

    result = await EmbeddingService.compute_embeddings(["a", "b"])

    assert result == [[0.1, 0.2], [0.3, 0.4]]
    assert captured["model"] == "openai/text-embedding-3-small"
    assert captured["input"] == ["a", "b"]
