from datetime import UTC, datetime

from common.models.graph_schema_registry import GraphSchemaRegistry
from common.models.knowledge_base import KnowledgeBase
from common.models.node_embedding import NodeEmbedding
from common.models.schema_embedding import SchemaEmbedding
from common.schemas.graph_schema_registry import GraphSchemaRegistryDTO, SchemaType
from common.schemas.knowledge_base import KnowledgeBaseRecordDTO
from common.schemas.model import AuthMode, Model, ModelType
from common.schemas.node_embedding import NodeEmbeddingDTO
from common.schemas.schema_embedding import SchemaEmbeddingDTO
from common.services.embedding_service import EmbeddingService


def _embedding_model() -> Model:
    return Model(
        id="550e8400-e29b-41d4-a716-446655440000",
        display_name="Test embedding model",
        name="test-embedding",
        provider="test",
        auth_mode=AuthMode.MANAGED_IDENTITY,
        type=[ModelType.EMBEDDING],
        embedding_dimension=2,
    )


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _ResultSession:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, _statement):
        return _Rows(self.rows)


def test_knowledge_base_record_dto_reads_the_orm_model():
    now = datetime(2026, 9, 25, tzinfo=UTC)
    row = KnowledgeBase(
        id="kb-1",
        organization_id="org-1",
        name="F1",
        data='{"nodes": []}',
        state="published",
        created_at_utc=now,
        updated_at_utc=now,
    )

    dto = KnowledgeBaseRecordDTO.model_validate(row)

    assert dto.id == "kb-1"
    assert dto.data == '{"nodes": []}'
    assert dto.state == "published"


def test_graph_schema_registry_dto_reads_model_and_embedding_relationship():
    row = GraphSchemaRegistry(
        organization_id="org-1",
        graph_name="f1",
        knowledge_base_ids=["kb-1"],
        type=SchemaType.NODE,
        name="Driver",
        description="",
        aliases=[],
        properties=["name"],
    )
    row.embedding_row = SchemaEmbedding(
        organization_id="org-1",
        embedding_model_id="model-1",
        embedding=[0.1, 0.2],
    )

    dto = GraphSchemaRegistryDTO.model_validate(row)

    assert dto.type is SchemaType.NODE
    assert dto.properties == ["name"]
    assert dto.embedding_row is not None
    assert dto.embedding_row.embedding == [0.1, 0.2]


def test_node_embedding_dto_reads_orm_model():
    row = NodeEmbedding(
        organization_id="org-1",
        graph_name="f1",
        knowledge_base_id="kb-1",
        node_id="driver-1",
        label="Driver",
        properties={"name": "Lewis"},
        embedding_model_id="model-1",
        embedding=[0.1, 0.2],
    )

    dto = NodeEmbeddingDTO.model_validate(row)

    assert dto.node_id == "driver-1"
    assert dto.properties == {"name": "Lewis"}
    assert dto.embedding == [0.1, 0.2]


def test_schema_embedding_dto_reads_orm_model():
    row = SchemaEmbedding(
        graph_registry_id=1,
        organization_id="org-1",
        embedding_model_id="model-1",
        embedding=[0.1, 0.2],
    )

    dto = SchemaEmbeddingDTO.model_validate(row)

    assert dto.graph_registry_id == 1
    assert dto.organization_id == "org-1"
    assert dto.embedding == [0.1, 0.2]


async def test_node_vector_search_returns_dtos(monkeypatch):
    async def fake_compute_embeddings(_model, texts):
        return [[0.1, 0.2] for _ in texts]

    monkeypatch.setattr(EmbeddingService, "compute_embeddings", fake_compute_embeddings)
    row = NodeEmbedding(
        organization_id="org-1",
        graph_name="f1",
        knowledge_base_id="kb-1",
        node_id="driver-1",
        label="Driver",
        properties={"name": "Lewis"},
        embedding=[0.1, 0.2],
    )

    results = await NodeEmbedding.vector_search(
        _ResultSession([row]), "driver", "f1", "org-1", _embedding_model()
    )

    assert len(results) == 1
    assert isinstance(results[0], NodeEmbeddingDTO)
    assert not isinstance(results[0], NodeEmbedding)


async def test_graph_schema_vector_search_returns_dtos(monkeypatch):
    async def fake_compute_embeddings(_model, texts):
        return [[0.1, 0.2] for _ in texts]

    monkeypatch.setattr(EmbeddingService, "compute_embeddings", fake_compute_embeddings)
    row = GraphSchemaRegistry(
        organization_id="org-1",
        graph_name="f1",
        knowledge_base_ids=["kb-1"],
        type=SchemaType.NODE,
        name="Driver",
        description="",
        aliases=[],
        properties=["name"],
    )
    row.embedding_row = SchemaEmbedding(
        organization_id="org-1", embedding_model_id=_embedding_model().id, embedding=[0.1, 0.2]
    )

    results = await GraphSchemaRegistry.vector_search(
        _ResultSession([row]), "driver", "f1", "org-1", _embedding_model()
    )

    assert len(results) == 1
    assert isinstance(results[0], GraphSchemaRegistryDTO)
    assert not isinstance(results[0], GraphSchemaRegistry)
from datetime import UTC, datetime
