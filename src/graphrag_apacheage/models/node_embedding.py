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

    Tracks one embedding per knowledge graph node (keyed by organization_id +
    graph_name + knowledge_base_id + node_id), computed from the node's label and
    properties, so nodes can be found via similarity search (see `vector_search()`)
    independent of Apache Age's own storage. The same node_id may appear once per
    knowledge base feeding the graph.

    Attributes:
        id: Primary key, auto-incrementing integer identifier.
        organization_id: Id of the organization that owns this node (see ADR-0002,
            Decision 1: every graph belongs to exactly one organization).
            Denormalized directly onto this row - not derived via a join through
            graph_name - the same way graph_name is already stored directly
            rather than looked up, so `vector_search()`'s isolation filter doesn't
            depend on a separate graph-to-organization mapping being correct.
            Part of the row's identity alongside graph_name/knowledge_base_id/
            node_id.
        graph_name: Name of the Apache Age graph this node belongs to (indexed for fast lookup).
        knowledge_base_id: Identifier of the KnowledgeBase this node came from, part of
            the row's identity.
        node_id: The node's identifier, matching `KnowledgeNode.id` in the Apache Age graph.
        label: The semantic label/type of the node (e.g., 'Driver').
        properties: Snapshot of the node's properties used to build the embedding text.
        embedding_model: The `f"{provider}/{name}"` identifier (see
            `Model.identifier`) of the embedding model that produced `embedding`,
            or None if no embedding has been computed yet. Row-level provenance
            per ADR-0001 option (1), rescoped by ADR-0002: during the window
            between an organization admin changing the active embedding model and
            recalculation finishing, this lets a caller filter to rows already
            migrated to the new model instead of ranking old- and new-model
            embeddings together.
        embedding: Vector embedding derived from label/properties, used for similarity
            search via `vector_search()`.
    """

    __tablename__ = "node_embedding"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "graph_name",
            "knowledge_base_id",
            "node_id",
            name="uq_node_embedding_org_graph_kb_node",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    organization_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    graph_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    knowledge_base_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    node_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    properties: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    embedding_model: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
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

        For each record, checks if it already exists based on
        (organization_id, graph_name, knowledge_base_id, node_id).
        - If not found: inserts the new record.
        - If found: updates its label and properties.
        Also (re)computes each persisted record's embedding from its post-merge
        label/properties via litellm, provided an embedding `model` is passed,
        stamping `embedding_model` (see `Model.identifier`) alongside it;
        otherwise embeddings are left untouched.

        Args:
            session: SQLAlchemy database session for executing queries.
            records: An iterable of NodeEmbedding records to upsert. Each record's
                `organization_id` must already be set.
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
                        cls.organization_id == record.organization_id,
                        cls.graph_name == record.graph_name,
                        cls.knowledge_base_id == record.knowledge_base_id,
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
            embedding_model = model.identifier if model is not None else None
            for record, embedding in zip(persisted, embeddings):
                record.embedding = embedding
                record.embedding_model = embedding_model

        await session.flush()
        return persisted

    @classmethod
    async def vector_search(
        cls,
        session: AsyncSession,
        query: str,
        graph_name: str,
        organization_id: str,
        model: Model,
        labels: list[str] | None = None,
        knowledge_base_id: str | None = None,
        embedding_model: str | None = None,
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
            organization_id: Restrict the search to this organization's rows.
                Always applied, unlike `labels`/`knowledge_base_id` - a row
                outside the caller's organization is never a valid match.
            model: The embedding provider configuration used to embed `query`.
            labels: Optional node labels to filter by. A record matches if its
                label is any of these.
            knowledge_base_id: Optional KnowledgeBase id to restrict the search to, so a
                graph fed by several knowledge bases can be searched one base at a time.
            embedding_model: Optional `Model.identifier` to restrict the search to
                rows whose embedding was computed by that model (see
                `embedding_model` on this class) - useful during an ADR-0002
                recalculation window to exclude not-yet-migrated rows.
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
            .where(
                cls.organization_id == organization_id,
                cls.graph_name == graph_name,
                cls.embedding.is_not(None),
            )
            .order_by(cls.embedding.cosine_distance(embedding))
            .limit(limit)
        )
        if labels:
            stmt = stmt.where(cls.label.in_(labels))
        if knowledge_base_id is not None:
            stmt = stmt.where(cls.knowledge_base_id == knowledge_base_id)
        if embedding_model is not None:
            stmt = stmt.where(cls.embedding_model == embedding_model)

        return list((await session.execute(stmt)).scalars().all())

    def __repr__(self) -> str:
        """Return a developer-friendly string representation of the node embedding record.

        Returns:
            A string showing the key identifying fields: id, organization_id,
            graph_name, knowledge_base_id, node_id, and label.
        """
        return (
            f"NodeEmbedding(id={self.id!r}, organization_id={self.organization_id!r}, "
            f"graph_name={self.graph_name!r}, "
            f"knowledge_base_id={self.knowledge_base_id!r}, "
            f"node_id={self.node_id!r}, label={self.label!r})"
        )


__all__ = ["NodeEmbedding"]
