from collections.abc import Iterable
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, String, UniqueConstraint, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from graphrag_apacheage.config import settings
from graphrag_apacheage.models.base import Base
from graphrag_apacheage.schemas.model import Model
from graphrag_apacheage.services.embedding_service import EmbeddingService


class NodeEmbedding(Base):
    """SQLAlchemy ORM model for storing vector embeddings of knowledge base nodes.

    Tracks one embedding per knowledge graph node (keyed by graph_name + node_id),
    computed from the node's label and properties, so nodes can be found via
    similarity search (see `vector_search()`) independent of Apache Age's own storage.

    Attributes:
        id: Primary key, auto-incrementing integer identifier.
        graph_name: Name of the Apache Age graph this node belongs to (indexed for fast lookup).
        node_id: The node's identifier, matching `KnowledgeNode.id` in the Apache Age graph.
        label: The semantic label/type of the node (e.g., 'Driver').
        properties: Snapshot of the node's properties used to build the embedding text.
        embedding: Vector embedding derived from label/properties, used for similarity
            search via `vector_search()`.
    """

    __tablename__ = "node_embedding"
    __table_args__ = (
        UniqueConstraint("graph_name", "node_id", name="uq_node_embedding_graph_node"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    graph_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    properties: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dimension).with_variant(JSON, "sqlite"), nullable=True
    )

    def embedding_text(self) -> str:
        """Build the text embedded for this node.

        Returns:
            The node's label followed by "key: value" pairs for each property.
        """
        parts = [
            self.label,
            *(f"{key}: {value}" for key, value in self.properties.items()),
        ]
        return " ".join(part for part in parts if part)

    @classmethod
    async def upsert_records(
        cls,
        session: AsyncSession,
        records: Iterable["NodeEmbedding"],
        model: Model | None = None,
    ) -> list["NodeEmbedding"]:
        """Upsert node embedding records into the database.

        For each record, checks if it already exists based on (graph_name, node_id).
        - If not found: inserts the new record.
        - If found: updates its label and properties.
        Also (re)computes each persisted record's embedding from its post-merge
        label/properties via litellm, provided an embedding `model` is passed;
        otherwise embeddings are left untouched.

        Args:
            session: SQLAlchemy database session for executing queries.
            records: An iterable of NodeEmbedding records to upsert.
            model: The embedding provider configuration to use. If None, embedding
                computation is skipped and existing embeddings are left untouched.

        Returns:
            A list of persisted NodeEmbedding instances (newly inserted or updated).
        """
        persisted: list[NodeEmbedding] = []

        for record in records:
            existing = (
                await session.execute(
                    select(cls).where(
                        cls.graph_name == record.graph_name,
                        cls.node_id == record.node_id,
                    )
                )
            ).scalar_one_or_none()

            if existing is None:
                session.add(record)
                persisted.append(record)
                continue

            existing.label = record.label
            existing.properties = record.properties
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
        label: str | None = None,
        limit: int = 5,
    ) -> list["NodeEmbedding"]:
        """Find the node embedding records whose embedding is closest to a text query.

        Embeds the query text via litellm (see `EmbeddingService.compute_embeddings`) and orders stored
        records by pgvector's cosine distance operator, so this requires a PostgreSQL
        database with the pgvector extension installed and records that already
        have an `embedding` set (via upsert or direct assignment).

        Args:
            session: SQLAlchemy database session for executing the query.
            query: Free-text query to embed and compare stored records against.
            graph_name: Restrict the search to nodes belonging to this graph.
            model: The embedding provider configuration used to embed `query`.
            label: Optional node label to filter by.
            limit: Maximum number of records to return, ordered by similarity.

        Returns:
            A list of NodeEmbedding records ordered from most to least similar.

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
        if label is not None:
            stmt = stmt.where(cls.label == label)

        return list((await session.execute(stmt)).scalars().all())

    def __repr__(self) -> str:
        """Return a developer-friendly string representation of the node embedding record.

        Returns:
            A string showing the key identifying fields: id, graph_name, node_id, and label.
        """
        return (
            f"NodeEmbedding(id={self.id!r}, graph_name={self.graph_name!r}, "
            f"node_id={self.node_id!r}, label={self.label!r})"
        )


__all__ = ["NodeEmbedding"]
