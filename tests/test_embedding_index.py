import pytest

from graphrag_apacheage.models.embedding_index import (
    HNSW_MAX_DIMENSIONS,
    drop_embedding_index,
    ensure_embedding_index,
)
from graphrag_apacheage.models.node_embedding import NodeEmbedding
from graphrag_apacheage.models.schema_embedding import SchemaEmbedding
from graphrag_apacheage.schemas.model import AuthMode, Model, ModelType


def _embedding_model(**overrides) -> Model:
    fields = {
        "id": "3f9a1b2c-8d4e-4f1a-9c3b-7e2d5a6f8b91",
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
        'CREATE INDEX IF NOT EXISTS '
        '"ix_node_embedding_emb_3f9a1b2c_8d4e_4f1a_9c3b_7e2d5a6f_768" '
        'ON "node_embedding" '
        "USING hnsw ((embedding::vector(768)) vector_cosine_ops) "
        "WHERE embedding_model_id = '3f9a1b2c-8d4e-4f1a-9c3b-7e2d5a6f8b91'"
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
            id="9a2b3c4d-5e6f-4a1b-8c2d-1e2f3a4b5c6d",
            provider="openai",
            name="text-embedding-3-small",
            embedding_dimension=1536,
        ),
    )

    names = [s.split('"')[1] for s in session.statements]
    assert names == [
        "ix_node_embedding_emb_3f9a1b2c_8d4e_4f1a_9c3b_7e2d5a6f_768",
        "ix_node_embedding_emb_9a2b3c4d_5e6f_4a1b_8c2d_1e2f3a4b_1536",
    ]
    # Re-running is safe: the DDL carries IF NOT EXISTS rather than being guarded
    # by a catalog lookup in Python.
    assert all("IF NOT EXISTS" in s for s in session.statements)


async def test_ensure_embedding_index_quotes_a_hostile_model_id():
    # `Model.id` now requires a UUID (`ensure_id_is_uuid`), so a hostile string
    # can no longer reach here through normal validation. `_index_name()`'s
    # escaping is still defense in depth - e.g. against a row read back from a
    # database written by another version - so this builds the Model via
    # `model_construct()` (bypasses validators) to exercise it directly, the
    # same concern AgeGraphRepository._validate_label exists for.
    session = _RecordingSession()
    fields = {
        "id": "x'; DROP TABLE node_embedding; --",
        "display_name": "Gemini Embedding 2",
        "name": "gemini-embedding-2",
        "provider": "gemini",
        "auth_mode": AuthMode.API_KEY,
        "api_key": "test-key",
        "type": [ModelType.EMBEDDING],
        "embedding_dimension": 768,
    }
    model = Model.model_construct(**fields)

    statement = await ensure_embedding_index(session, "node_embedding", model)

    assert "DROP TABLE" not in statement.split("WHERE")[0]
    assert '"ix_node_embedding_emb_x_drop_table_node_embedding_768"' in statement
    assert (
        "WHERE embedding_model_id = 'x''; DROP TABLE node_embedding; --'" in statement
    )


async def test_ensure_embedding_index_keeps_index_name_within_postgres_identifier_limit():
    # PostgreSQL identifiers are limited to 63 bytes. A UUID id (36 chars) would
    # push "ix_schema_embedding_emb_<slug>_<dim>" past that without the bound in
    # _index_name(), so this pins the truncation rather than relying on
    # inspection - schema_embedding is the longer of the two table names.
    session = _RecordingSession()
    model = _embedding_model(id="123e4567-e89b-12d3-a456-426614174000")

    statement = await ensure_embedding_index(session, "schema_embedding", model)

    name = statement.split('"')[1]
    assert len(name) <= 63


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


async def test_drop_embedding_index_matches_the_index_ensure_would_create():
    # The inverse must reference the exact index ensure_embedding_index() creates,
    # or paired ensure/drop calls would silently operate on different names.
    session = _RecordingSession()
    model = _embedding_model()

    drop = await drop_embedding_index(session, "node_embedding", model)

    names = [s.split('"')[1] for s in session.statements]
    assert names == ["ix_node_embedding_emb_3f9a1b2c_8d4e_4f1a_9c3b_7e2d5a6f_768"]
    assert drop == 'DROP INDEX IF EXISTS "ix_node_embedding_emb_3f9a1b2c_8d4e_4f1a_9c3b_7e2d5a6f_768"'
    # The name matches a fresh ensure_embedding_index() for the same model, so a
    # round-trip hits the same physical index.
    ensure_names = []

    async def _capture_ensure(s, table, m):
        stmt = await ensure_embedding_index(s, table, m)
        ensure_names.append(stmt.split('"')[1])
        return stmt

    session2 = _RecordingSession()
    await _capture_ensure(session2, "node_embedding", model)
    assert ensure_names == names


async def test_drop_embedding_index_is_safe_to_repeat_and_scoped_per_model():
    # DROP INDEX IF EXISTS makes the "drop what we may not have created" case a
    # cheap no-op, and the name is scoped per model so one model's drop never
    # touches another's index.
    session = _RecordingSession()
    model_a = _embedding_model()
    model_b = _embedding_model(
        id="9a2b3c4d-5e6f-4a1b-8c2d-1e2f3a4b5c6d",
        provider="openai",
        name="text-embedding-3-small",
        embedding_dimension=1536,
    )

    await drop_embedding_index(session, "node_embedding", model_a)
    await drop_embedding_index(session, "node_embedding", model_a)
    await drop_embedding_index(session, "node_embedding", model_b)

    names = [s.split('"')[1] for s in session.statements]
    assert names == [
        "ix_node_embedding_emb_3f9a1b2c_8d4e_4f1a_9c3b_7e2d5a6f_768",
        "ix_node_embedding_emb_3f9a1b2c_8d4e_4f1a_9c3b_7e2d5a6f_768",
        "ix_node_embedding_emb_9a2b3c4d_5e6f_4a1b_8c2d_1e2f3a4b_1536",
    ]
    assert all("DROP INDEX IF EXISTS" in s for s in session.statements)


async def test_drop_embedding_index_keeps_index_name_within_postgres_identifier_limit():
    # Same constraint as the create side: the dropped name must be a valid,
    # bounded PostgreSQL identifier (schema_embedding is the longer table name).
    session = _RecordingSession()

    statement = await drop_embedding_index(
        session, "schema_embedding", _embedding_model(id="123e4567-e89b-12d3-a456-426614174000")
    )

    name = statement.split('"')[1]
    assert len(name) <= 63


async def test_drop_embedding_index_rejects_a_model_too_wide_for_hnsw():
    # A model ensure_embedding_index() would refuse to index was never indexed,
    # so there is nothing to drop; the pair must agree on the same boundary.
    session = _RecordingSession()
    model = _embedding_model(embedding_dimension=HNSW_MAX_DIMENSIONS + 1)

    with pytest.raises(ValueError, match="there is nothing to drop"):
        await drop_embedding_index(session, "node_embedding", model)

    assert session.statements == []


async def test_drop_embedding_index_rejects_a_non_embedding_model():
    session = _RecordingSession()
    model = _embedding_model(type=[ModelType.THINKING], embedding_dimension=None)

    with pytest.raises(ValueError, match="has no embedding_dimension"):
        await drop_embedding_index(session, "node_embedding", model)

    assert session.statements == []


@pytest.mark.parametrize(
    ("model_class", "table_name"),
    [(NodeEmbedding, "node_embedding"), (SchemaEmbedding, "schema_embedding")],
)
async def test_each_embedding_model_exposes_the_drop_helper_for_its_own_table(
    model_class, table_name
):
    session = _RecordingSession()

    statement = await model_class.drop_embedding_index(session, _embedding_model())

    name = statement.split('"')[1]
    assert name.startswith(f"ix_{table_name}_emb_")
