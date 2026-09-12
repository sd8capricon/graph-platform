from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from graphrag_apacheage.config import settings
from graphrag_apacheage.models.base import Base


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
        embedding_model: The `f"{provider}/{name}"` identifier (see
            `Model.identifier`) of the embedding model that produced `embedding`,
            or None if no embedding has been computed yet. Row-level provenance
            per ADR-0001 option (1), rescoped by ADR-0002: during the window
            between an organization admin changing the active embedding model and
            recalculation finishing, this lets a caller filter to rows already
            migrated to the new model instead of ranking old- and new-model
            embeddings together.
        embedding: Vector embedding derived from the owning GraphSchemaRegistry
            row's name/description/aliases, used for similarity search via
            `GraphSchemaRegistry.vector_search()`.
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
    embedding_model: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dimension).with_variant(JSON, "sqlite"),
        nullable=True,
    )

    graph_registry: Mapped["GraphSchemaRegistry"] = relationship(  # noqa: F821
        back_populates="embedding_row"
    )

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
