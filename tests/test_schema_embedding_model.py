from sqlalchemy import create_engine, inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from common.models.base import Base
from common.models.graph_schema_registry import GraphSchemaRegistry, SchemaType
from common.models.schema_embedding import SchemaEmbedding


def test_schema_embedding_column_is_dimensionless():
    """Per ADR-0003 the column is `vector`, not `vector(n)`, so organizations on
    embedding models of different widths can share the table. Asserted on the
    compiled PostgreSQL DDL because SQLite never uses the pgvector type at all
    (it falls back to JSON via with_variant), so the width is invisible there."""
    ddl = str(
        CreateTable(SchemaEmbedding.__table__).compile(dialect=postgresql.dialect())
    )

    assert "embedding VECTOR," in ddl or ddl.rstrip().endswith("embedding VECTOR")
    assert "VECTOR(" not in ddl


def test_schema_embedding_table_exists_and_tracks_the_registry_row():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    assert "schema_embedding" in inspector.get_table_names()

    columns = {column["name"] for column in inspector.get_columns("schema_embedding")}
    expected = {
        "id",
        "graph_registry_id",
        "organization_id",
        "embedding_model_id",
        "embedding",
    }
    assert expected.issubset(columns)


def test_schema_embedding_round_trips_on_sqlite():
    # The embedding column uses a JSON fallback on SQLite (via with_variant),
    # since pgvector's Vector type only compiles on PostgreSQL.
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    registry_row = GraphSchemaRegistry(
        organization_id="org-1",
        graph_name="demo",
        knowledge_base_ids=["kb-1"],
        type=SchemaType.NODE,
        name="Driver",
        description="A racer",
        aliases=[],
        properties=[],
    )
    registry_row.embedding_row = SchemaEmbedding(
        organization_id="org-1",
        embedding_model_id="text-embedding-3-small",
        embedding=[0.1, 0.2, 0.3],
    )

    with Session(engine) as session:
        session.add(registry_row)
        session.commit()

        stored = session.execute(
            select(GraphSchemaRegistry).where(GraphSchemaRegistry.name == "Driver")
        ).scalar_one()

    assert stored.embedding_row.embedding == [0.1, 0.2, 0.3]
    assert stored.embedding_row.embedding_model_id == "text-embedding-3-small"
    assert stored.embedding_row.organization_id == "org-1"


async def test_deleting_the_registry_row_cascades_to_its_embedding_row():
    # GraphSchemaRegistry.embedding_row has cascade="all, delete-orphan": deleting
    # the parent through the ORM (session.delete) must delete the child too,
    # without relying on a database-level ON DELETE CASCADE (SQLite in tests has
    # foreign key enforcement off by default).
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def fake_compute(model, texts):
        return [[0.1, 0.2, 0.3] for _ in texts] if texts else None

    import common.models.graph_schema_registry as gsr_mod

    class FakeModel:
        id = "text-embedding-3-small"
        identifier = "openai/text-embedding-3-small"

    gsr_mod.EmbeddingService.compute_embeddings = staticmethod(fake_compute)

    async with AsyncSession(engine) as session:
        record = GraphSchemaRegistry(
            organization_id="org-1",
            graph_name="demo",
            knowledge_base_ids=["kb-1"],
            type=SchemaType.NODE,
            name="Driver",
            description="A racer",
            aliases=[],
            properties=[],
        )
        await GraphSchemaRegistry.upsert_records(session, [record], model=FakeModel())
        await session.commit()

    async with AsyncSession(engine) as session:
        row = (
            await session.execute(
                select(GraphSchemaRegistry).where(GraphSchemaRegistry.name == "Driver")
            )
        ).scalar_one()
        await session.delete(row)
        await session.flush()
        await session.commit()

    async with AsyncSession(engine) as session:
        remaining = (await session.execute(select(SchemaEmbedding))).scalars().all()
        assert remaining == []


async def test_upsert_records_keeps_separate_embedding_rows_per_organization():
    # Mirrors NodeEmbedding's equivalent test: two organizations sharing a
    # graph_name/type/name must not collide into one shared SchemaEmbedding row.
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def fake_compute(model, texts):
        return [[0.1, 0.2, 0.3] for _ in texts] if texts else None

    import common.models.graph_schema_registry as gsr_mod

    class FakeModel:
        id = "text-embedding-3-small"
        identifier = "openai/text-embedding-3-small"

    gsr_mod.EmbeddingService.compute_embeddings = staticmethod(fake_compute)

    def _driver(organization_id: str) -> GraphSchemaRegistry:
        return GraphSchemaRegistry(
            organization_id=organization_id,
            graph_name="demo",
            knowledge_base_ids=["kb-1"],
            type=SchemaType.NODE,
            name="Driver",
            description="A racer",
            aliases=[],
            properties=[],
        )

    async with AsyncSession(engine) as session:
        await GraphSchemaRegistry.upsert_records(
            session, [_driver("org-1")], model=FakeModel()
        )
        await session.commit()

        await GraphSchemaRegistry.upsert_records(
            session, [_driver("org-2")], model=FakeModel()
        )
        await session.commit()

        registry_rows = (
            (await session.execute(select(GraphSchemaRegistry))).scalars().all()
        )
        embedding_rows = (await session.execute(select(SchemaEmbedding))).scalars().all()

    assert len(registry_rows) == 2
    assert {row.organization_id for row in registry_rows} == {"org-1", "org-2"}
    assert len(embedding_rows) == 2
    assert {row.organization_id for row in embedding_rows} == {"org-1", "org-2"}
