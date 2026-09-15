from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from common.database.indexes import (
    drop_embedding_index,
    ensure_embedding_index,
)
from common.models.base import Base
from common.schemas.model import Model


class SchemaEmbedding(Base):
    """SQLAlchemy ORM model storing one vector embedding per GraphSchemaRegistry row.

    The embedding side-table for `GraphSchemaRegistry` (`models/graph_schema_registry.py`),
    mirroring the split `NodeEmbedding` already has from the Apache Age graph itself
    (see ADR-0002, Decision 5): `graph_registry` keeps describing schema metadata
    (types, names, properties, aliases, source/target labels), and the embedding
    used for `GraphSchemaRegistry.vector_search()` similarity lives here instead,
    keyed back to the registry row via a 1:1 foreign key. This keeps an org-wide
    re-embed (ADR-0002, Decision 4) a targeted rewrite of a table that holds
    nothing but derived vectors, instead of a bulk UPDATE across the table that
    also holds the schema's source of truth.

    Attributes:
        id: Primary key, auto-incrementing integer identifier.
        graph_registry_id: The GraphSchemaRegistry row this embedding belongs to.
            One-to-one: unique, so each registry row has at most one embedding row.
        organization_id: Id of the organization that owns this embedding (see
            ADR-0002, Decision 1: every graph, and therefore every schema it
            defines, belongs to exactly one organization). Denormalized directly
            onto this row - not derived via a join through `graph_registry_id` -
            so `vector_search()`'s isolation filter doesn't depend on a join
            staying correct, the same rationale ADR-0002 gives for denormalizing
            it onto `NodeEmbedding` too.
        embedding_model_id: The configured `Model.id` of the embedding model that
            produced `embedding`, or None if no embedding has been computed yet.
            Row-level provenance per ADR-0001 option (1), rescoped by ADR-0002.
            Deliberately `Model.id`, not `Model.identifier` (the
            `f"{provider}/{name}"` litellm string) - two config entries can share
            a provider/name while differing in endpoint, auth mode, or dimension,
            so only the caller-assigned `id` is a stable identity across
            restarts. Load-bearing for two things beyond provenance (ADR-0003):
            it is what `GraphSchemaRegistry.vector_search()` filters on so a
            query never compares vectors from two different models' spaces, and
            it is the predicate of this table's partial indexes, so it is also
            what makes those indexes usable at all.
        embedding: Vector embedding derived from the owning GraphSchemaRegistry
            row's name/description/aliases, used for similarity search via
            `GraphSchemaRegistry.vector_search()`. The column is deliberately
            **dimensionless** (`vector`, no width) per ADR-0003, so organizations
            using embedding models of different widths can share this table. The
            cost is that the width is no longer enforced by the database - see
            `EmbeddingService.compute_embeddings()`'s fail-fast check - and that
            an ANN index needs an expression+partial form, see
            `ensure_embedding_index()` below.
    """

    __tablename__ = "schema_embedding"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    graph_registry_id: Mapped[int] = mapped_column(
        ForeignKey("graph_registry.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    organization_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    embedding_model_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector().with_variant(JSON, "sqlite"),
        nullable=True,
    )

    graph_registry: Mapped["GraphSchemaRegistry"] = relationship(  # noqa: F821
        back_populates="embedding_row"
    )

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
        """Return a developer-friendly string representation of the embedding row.

        Returns:
            A string showing the key identifying fields: id, graph_registry_id,
            and organization_id.
        """
        return (
            f"SchemaEmbedding(id={self.id!r}, "
            f"graph_registry_id={self.graph_registry_id!r}, "
            f"organization_id={self.organization_id!r})"
        )


__all__ = ["SchemaEmbedding"]
