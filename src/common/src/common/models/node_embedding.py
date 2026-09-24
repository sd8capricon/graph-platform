from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, String, UniqueConstraint, cast, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from common.database.indexes import (
    drop_embedding_index,
    ensure_embedding_index,
)
from common.models.base import Base
from common.schemas.model import Model
from common.services.embedding_service import EmbeddingService


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
        embedding_model_id: The configured `Model.id` of the embedding model that
            produced `embedding`, or None if no embedding has been computed yet.
            Row-level provenance per ADR-0001 option (1), rescoped by ADR-0002.
            Deliberately `Model.id`, not `Model.identifier` (the
            `f"{provider}/{name}"` litellm string) - two config entries can share
            a provider/name while differing in endpoint, auth mode, or dimension,
            so only the caller-assigned `id` is a stable identity across
            restarts. Load-bearing for two things beyond provenance (ADR-0003):
            it is what `vector_search()` filters on so a query never compares
            vectors from two different models' spaces, and it is the predicate
            of this table's partial indexes, so it is also what makes those
            indexes usable at all.
        embedding: Vector embedding derived from label/properties, used for similarity
            search via `vector_search()`. The column is deliberately
            **dimensionless** (`vector`, no width) per ADR-0003, so organizations
            using embedding models of different widths can share this table. The
            cost is that the width is no longer enforced by the database - see
            `EmbeddingService.compute_embeddings()`'s fail-fast check - and that
            an ANN index needs an expression+partial form, see
            `ensure_embedding_index()` below.
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
    embedding_model_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector().with_variant(JSON, "sqlite"), nullable=True
    )

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
        limit: int = 5,
    ) -> list["NodeEmbedding"]:
        """Find the node embedding records whose embedding is closest to a text query.

        Embeds the query text via litellm (see `EmbeddingService.compute_embeddings`) and orders stored
        records by pgvector's cosine distance operator, so this requires a PostgreSQL
        database with the pgvector extension installed and records that already
        have an `embedding` set (via upsert or direct assignment).

        The search is confined to rows `model` itself produced: `embedding_model_id`
        is filtered on `model.id`, and the distance is taken over
        `embedding` cast to `model.embedding_dimension`. Both are derived from
        `model` rather than taken as separate arguments, because both must agree
        with it to be meaningful - a cosine distance between two different models'
        vectors is a number without meaning (ADR-0001), and between two different
        *widths* it is an error. This pairing is also exactly what makes the
        partial expression indexes usable; see `database/indexes.py`.

        Args:
            session: SQLAlchemy database session for executing the query.
            query: Free-text query to embed and compare stored records against.
            graph_name: Restrict the search to nodes belonging to this graph.
            organization_id: Restrict the search to this organization's rows.
                Always applied, unlike `labels`/`knowledge_base_id` - a row
                outside the caller's organization is never a valid match.
            model: The embedding provider configuration used to embed `query`, and
                the one whose rows are searched. Rows embedded by any other model
                are excluded, so during an ADR-0002 recalculation window this
                naturally sees only the rows already migrated to `model`.
            labels: Optional node labels to filter by. A record matches if its
                label is any of these.
            knowledge_base_id: Optional KnowledgeBase id to restrict the search to, so a
                graph fed by several knowledge bases can be searched one base at a time.
            limit: Maximum number of records to return, ordered by similarity.

        Returns:
            A list of NodeEmbedding records ordered from most to least similar.

        Raises:
            ValueError: If `model` is None, since no embedding provider is configured
                to embed the query, or if it has no `embedding_dimension` and so
                is not an embedding model at all.
        """
        # Validate before embedding, not after: `compute_embeddings()` is a real
        # (billed) provider call, and a model we cannot search against should
        # never get that far.
        if model is None:
            raise ValueError("model is required to perform vector_search")
        if model.embedding_dimension is None:
            raise ValueError(
                f"{model.identifier} has no embedding_dimension; it is not an "
                "embedding model and cannot be searched against"
            )

        embeddings = await EmbeddingService.compute_embeddings(model, [query])
        if embeddings is None:
            raise ValueError("model is required to perform vector_search")
        embedding = embeddings[0]

        stmt = (
            select(cls)
            .where(
                cls.organization_id == organization_id,
                cls.graph_name == graph_name,
                cls.embedding_model_id == model.id,
                cls.embedding.is_not(None),
            )
            .order_by(
                cast(cls.embedding, Vector(model.embedding_dimension)).cosine_distance(
                    embedding
                )
            )
            .limit(limit)
        )
        if labels:
            stmt = stmt.where(cls.label.in_(labels))
        if knowledge_base_id is not None:
            stmt = stmt.where(cls.knowledge_base_id == knowledge_base_id)

        return list((await session.execute(stmt)).scalars().all())

    @classmethod
    async def ensure_embedding_index(cls, session: AsyncSession, model: Model) -> str:
        """Create this table's per-model partial HNSW index, if it does not exist.

        See `database/indexes.py` for what the index looks like and why one
        is needed per embedding model rather than one for the whole table.

        Args:
            session: SQLAlchemy async session used to execute the DDL. Must be
                bound to PostgreSQL.
            model: The embedding provider configuration whose rows to index.

        Returns:
            The executed `CREATE INDEX` statement.

        Raises:
            ValueError: If `model` has no `embedding_dimension`, or that dimension
                exceeds what pgvector's HNSW index supports for the `vector` type.
        """
        return await ensure_embedding_index(session, cls.__tablename__, model)

    @classmethod
    async def drop_embedding_index(
        cls, session: AsyncSession, model: Model
    ) -> str:
        """Drop this table's per-model partial HNSW index, if present.

        The inverse of :meth:`ensure_embedding_index`: removes the index for
        `model` from this table. See `database/indexes.py` for what the
        index looks like and why one exists per embedding model.

        Args:
            session: SQLAlchemy async session used to execute the DDL. Must be
                bound to PostgreSQL.
            model: The embedding provider configuration whose index to drop.

        Returns:
            The executed `DROP INDEX` statement.

        Raises:
            ValueError: If `model` has no `embedding_dimension`, or that
                dimension exceeds what pgvector's HNSW index supports for the
                `vector` type.
        """
        return await drop_embedding_index(session, cls.__tablename__, model)

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
