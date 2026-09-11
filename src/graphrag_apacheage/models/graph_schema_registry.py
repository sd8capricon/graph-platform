from collections.abc import Iterable
from enum import Enum

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, CheckConstraint, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from graphrag_apacheage.config import settings
from graphrag_apacheage.models.base import Base
from graphrag_apacheage.schemas.model import Model
from graphrag_apacheage.services.embedding_service import EmbeddingService


class SchemaType(str, Enum):
    """Enumeration of valid schema types in the graph registry.

    Attributes:
        NODE: Represents a node/vertex type in the knowledge graph.
        RELATIONSHIP: Represents a relationship/edge type in the knowledge graph.
    """

    NODE = "node"
    RELATIONSHIP = "relationship"


class GraphSchemaRegistry(Base):
    """SQLAlchemy ORM model for storing graph schema definitions in the database.

    Tracks and manages metadata about entity types (nodes) and relationship types
    in Apache Age graphs, including their properties, aliases, and interconnections.

    Attributes:
        id: Primary key, auto-incrementing integer identifier.
        graph_name: Name of the Apache Age graph this schema belongs to (indexed for fast lookup).
        knowledge_base_ids: Ids of every KnowledgeBase that contributed this schema
            type. The same label (e.g. 'Driver') may legitimately be defined by more
            than one knowledge base feeding the same graph, so this row is shared and
            accumulates every contributing knowledge base's id on upsert.
        type: Schema type ('node' or 'relationship'). Enforced by CheckConstraint.
        name: Name/label of the entity or relationship type (e.g., 'Person', 'knows').
        description: Human-readable description of the schema type.
        aliases: List of alternative names/aliases for this schema type.
        properties: List of property names associated with this schema type.
        source_label: For relationship types, the label of the source node type.
        target_label: For relationship types, the label of the target node type.
        embedding: Optional vector embedding of the schema type (e.g. derived from
            name/description/aliases) used for similarity search via `vector_search()`.
    """

    __tablename__ = "graph_registry"
    __table_args__ = (
        CheckConstraint(
            "type IN ('node', 'relationship')", name="ck_graph_registry_type"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    graph_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    knowledge_base_ids: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    type: Mapped[SchemaType] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    properties: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dimension).with_variant(JSON, "sqlite"), nullable=True
    )

    def embedding_text(self) -> str:
        """Build the text embedded for this schema registry record.

        Returns:
            Name, description, and aliases joined into one string.
        """
        parts = [self.name, self.description, *self.aliases]
        return " ".join(part for part in parts if part)

    @classmethod
    async def upsert_records(
        cls,
        session: AsyncSession,
        records: Iterable[GraphSchemaRegistry],
        model: Model | None = None,
    ) -> list[GraphSchemaRegistry]:
        """Upsert (insert or update) schema registry records into the database.

        For each record, checks if it already exists based on (graph_name, type, name).
        - If not found: inserts the new record.
        - If found: merges the data by combining aliases, properties, and
          knowledge_base_ids (each deduped and sorted), and preserving source/target
          labels if not already set.
        Also (re)computes each persisted record's embedding from its post-merge
        name/description/aliases via litellm, provided an embedding `model` is
        passed; otherwise embeddings are left untouched.

        Args:
            session: SQLAlchemy database session for executing queries.
            records: An iterable of GraphSchemaRegistry records to upsert.
            model: The embedding provider configuration to use. If None, embedding
                computation is skipped and existing embeddings are left untouched.

        Returns:
            A list of persisted GraphSchemaRegistry instances (newly inserted or updated).
        """
        persisted: list[GraphSchemaRegistry] = []

        for record in records:
            existing = (
                await session.execute(
                    select(cls).where(
                        cls.graph_name == record.graph_name,
                        cls.type
                        == (
                            record.type.value
                            if isinstance(record.type, SchemaType)
                            else record.type
                        ),
                        cls.name == record.name,
                    )
                )
            ).scalar_one_or_none()

            if existing is None:
                session.add(record)
                persisted.append(record)
                continue

            existing.description = record.description
            existing.aliases = sorted(set(existing.aliases) | set(record.aliases))
            existing.properties = sorted(
                set(existing.properties) | set(record.properties)
            )
            existing.knowledge_base_ids = sorted(
                set(existing.knowledge_base_ids) | set(record.knowledge_base_ids)
            )
            existing.source_label = record.source_label or existing.source_label
            existing.target_label = record.target_label or existing.target_label
            persisted.append(existing)

        embeddings = await EmbeddingService.compute_embeddings(
            model, [record.embedding_text() for record in persisted]
        )
        if embeddings is not None:
            for record, embedding in zip(persisted, embeddings):
                record.embedding = embedding

        await session.flush()
        return persisted

    @classmethod
    async def vector_search(
        cls,
        session: AsyncSession,
        query: str,
        graph_name: str,
        model: Model,
        type: SchemaType | None = None,
        limit: int = 5,
    ) -> list[GraphSchemaRegistry]:
        """Find the schema registry records whose embedding is closest to a text query.

        Embeds the query text via litellm (see `EmbeddingService.compute_embeddings`) and orders stored
        records by pgvector's cosine distance operator, so this requires a PostgreSQL
        database with the pgvector extension installed and records that already
        have an `embedding` set (via upsert or direct assignment).

        Args:
            session: SQLAlchemy database session for executing the query.
            query: Free-text query to embed and compare stored records against.
            graph_name: Restrict the search to records belonging to this graph.
            model: The embedding provider configuration used to embed `query`.
            type: Optional schema type ('node' or 'relationship') to filter by.
            limit: Maximum number of records to return, ordered by similarity.

        Returns:
            A list of GraphSchemaRegistry records ordered from most to least similar.

        Raises:
            ValueError: If `model` is None, since no embedding provider is configured
                to embed the query.
        """
        embeddings = await EmbeddingService.compute_embeddings(model, [query])
        if embeddings is None:
            raise ValueError("model is required to perform vector_search")
        embedding = embeddings[0]

        stmt = (
            select(cls)
            .where(cls.graph_name == graph_name, cls.embedding.is_not(None))
            .order_by(cls.embedding.cosine_distance(embedding))
            .limit(limit)
        )
        if type is not None:
            stmt = stmt.where(cls.type == (type.value if isinstance(type, SchemaType) else type))

        return list((await session.execute(stmt)).scalars().all())

    def __repr__(self) -> str:
        """Return a developer-friendly string representation of the schema registry record.

        Returns:
            A string showing the key identifying fields: id, graph_name, type, and name.
        """
        return (
            f"GraphRegistry(id={self.id!r}, graph_name={self.graph_name!r}, "
            f"type={self.type.value if isinstance(self.type, SchemaType) else self.type!r}, "
            f"name={self.name!r})"
        )


__all__ = ["GraphSchemaRegistry", "SchemaType"]
