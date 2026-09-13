import pytest

from graphrag_apacheage.models.embedding_index import (
    HNSW_MAX_DIMENSIONS,
    ensure_embedding_index,
)
from graphrag_apacheage.models.node_embedding import NodeEmbedding
from graphrag_apacheage.models.schema_embedding import SchemaEmbedding
from graphrag_apacheage.schemas.model import AuthMode, Model, ModelType


def _embedding_model(**overrides) -> Model:
    fields = {
        "display_name": "Gemini Embedding 2",
        "name": "gemini-embedding-2",
        "provider": "gemini",
        "auth_mode": AuthMode.API_KEY,
        "api_key": "test-key",
        "type": [ModelType.EMBEDDING],
        "embedding_dimension": 768,
    }
    fields.update(overrides)
    return Model.model_validate(fields)


class _RecordingSession:
    """Captures the DDL instead of running it - these statements are PostgreSQL-only."""

    def __init__(self):
        self.statements = []

    async def execute(self, statement):
        self.statements.append(str(statement))


async def test_ensure_embedding_index_builds_a_partial_expression_index():
    # pgvector cannot index a dimensionless `vector` column directly; its
    # documented workaround is an expression index casting to a fixed width,
    # made partial so it only covers rows actually of that width.
    session = _RecordingSession()

    statement = await ensure_embedding_index(session, "node_embedding", _embedding_model())

    assert statement == (
        'CREATE INDEX IF NOT EXISTS "ix_node_embedding_emb_gemini_gemini_embedding_2_768" '
        'ON "node_embedding" '
        "USING hnsw ((embedding::vector(768)) vector_cosine_ops) "
        "WHERE embedding_model = 'gemini/gemini-embedding-2'"
    )
    assert session.statements == [statement]


async def test_ensure_embedding_index_is_idempotent_and_scoped_per_model():
    # One index per embedding model, not per organization: the count is bounded
    # by how many providers the deployment supports, not by its tenant count.
    session = _RecordingSession()

    await ensure_embedding_index(session, "node_embedding", _embedding_model())
    await ensure_embedding_index(
        session,
        "node_embedding",
        _embedding_model(
            provider="openai", name="text-embedding-3-small", embedding_dimension=1536
        ),
    )

    names = [s.split('"')[1] for s in session.statements]
    assert names == [
        "ix_node_embedding_emb_gemini_gemini_embedding_2_768",
        "ix_node_embedding_emb_openai_text_embedding_3_small_1536",
    ]
    # Re-running is safe: the DDL carries IF NOT EXISTS rather than being guarded
    # by a catalog lookup in Python.
    assert all("IF NOT EXISTS" in s for s in session.statements)


async def test_ensure_embedding_index_quotes_a_hostile_model_identifier():
    # The identifier reaches both an index name and a WHERE literal. The name is
    # slugified (it is an identifier, so it cannot simply be quoted through) and
    # the literal is escaped, the same concern AgeGraphRepository._validate_label
    # exists for.
    session = _RecordingSession()
    model = _embedding_model(name="x'; DROP TABLE node_embedding; --")

    statement = await ensure_embedding_index(session, "node_embedding", model)

    assert "DROP TABLE" not in statement.split("WHERE")[0]
    assert (
        '"ix_node_embedding_emb_gemini_x_drop_table_node_embedding_768"' in statement
    )
    assert (
        "WHERE embedding_model = 'gemini/x''; DROP TABLE node_embedding; --'"
        in statement
    )


async def test_ensure_embedding_index_rejects_a_model_too_wide_for_hnsw():
    # e.g. OpenAI text-embedding-3-large (3072). Such a model still works - its
    # searches just fall back to a sequential scan - so this must fail loudly at
    # index creation rather than silently emitting DDL PostgreSQL would reject.
    session = _RecordingSession()
    model = _embedding_model(embedding_dimension=HNSW_MAX_DIMENSIONS + 1)

    with pytest.raises(ValueError, match="above pgvector's HNSW limit"):
        await ensure_embedding_index(session, "node_embedding", model)

    assert session.statements == []


async def test_ensure_embedding_index_rejects_a_non_embedding_model():
    session = _RecordingSession()
    model = _embedding_model(type=[ModelType.THINKING], embedding_dimension=None)

    with pytest.raises(ValueError, match="has no embedding_dimension"):
        await ensure_embedding_index(session, "node_embedding", model)

    assert session.statements == []


@pytest.mark.parametrize(
    ("model_class", "table_name"),
    [(NodeEmbedding, "node_embedding"), (SchemaEmbedding, "schema_embedding")],
)
async def test_each_embedding_model_exposes_the_helper_for_its_own_table(
    model_class, table_name
):
    session = _RecordingSession()

    statement = await model_class.ensure_embedding_index(session, _embedding_model())

    assert f'ON "{table_name}"' in statement
