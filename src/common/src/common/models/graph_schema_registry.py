from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, CheckConstraint, String, Text, cast, select
from sqlalchemy.dialects.postgresql import JSONB, array
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, contains_eager, mapped_column, relationship

from common.models.base import Base
from common.models.schema_embedding import SchemaEmbedding
from common.schemas.graph_schema_registry import GraphSchemaRegistryDTO, SchemaType
from common.schemas.model import Model
from common.services.embedding_service import EmbeddingService


class GraphSchemaRegistry(Base):
    """SQLAlchemy ORM model for storing graph schema definitions in the database.

    Tracks and manages metadata about entity types (nodes) and relationship types
    in Apache Age graphs, including their properties, aliases, and interconnections.
    The embedding used for `vector_search()` similarity is not stored here - see
    `SchemaEmbedding` (`models/schema_embedding.py`) - so this table describes only
    schema, per ADR-0002 Decision 5.

    Attributes:
        id: Primary key, auto-incrementing integer identifier.
        organization_id: Id of the organization this schema row belongs to (see
            ADR-0002, Decision 1: every graph belongs to exactly one
            organization). Part of the row's identity alongside graph_name/type/
            name, so two organizations can define a schema under the same
            graph_name without colliding.
        graph_name: Name of the Apache Age graph this schema belongs to (indexed for fast lookup).
        knowledge_base_ids: Ids of every KnowledgeBase that contributed this schema
            type. The same label (e.g. 'Driver') may legitimately be defined by
            more than one knowledge base feeding the same graph, so this row is
            shared and accumulates every contributing knowledge base's id on
            upsert.
        type: Schema type ('node' or 'relationship'). Enforced by CheckConstraint.
        name: Name/label of the entity or relationship type (e.g., 'Person', 'knows').
        description: Human-readable description of the schema type.
        aliases: List of alternative names/aliases for this schema type.
        properties: List of property names associated with this schema type.
        source_label: For relationship types, the label of the source node type.
        target_label: For relationship types, the label of the target node type.
        embedding_row: The SchemaEmbedding row holding this schema's vector
            embedding (derived from name/description/aliases), used for
            similarity search via `vector_search()`. One-to-one; None until an
            embedding has been computed for this row.
    """

    __tablename__ = "graph_registry"
    __table_args__ = (
        CheckConstraint(
            "type IN ('node', 'relationship')", name="ck_graph_registry_type"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    organization_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
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
    embedding_row: Mapped[SchemaEmbedding | None] = relationship(
        back_populates="graph_registry",
        cascade="all, delete-orphan",
        lazy="selectin",
        uselist=False,
    )

    @classmethod
    async def vector_search(
        cls,
        session: AsyncSession,
        query: str,
        graph_name: str,
        organization_id: str,
        model: Model,
        type: SchemaType | None = None,
        knowledge_base_ids: list[str] | None = None,
        top_k: int = 5,
    ) -> list[GraphSchemaRegistryDTO]:
        """Find the schema registry records whose embedding is closest to a text query.

        Embeds the query text via litellm (see `EmbeddingService.compute_embeddings`) and orders stored
        records by pgvector's cosine distance operator, so this requires a PostgreSQL
        database with the pgvector extension installed and records that already
        have an embedding (via `SchemaEmbedding`, upserted or assigned directly).

        The search is confined to rows `model` itself produced:
        `SchemaEmbedding.embedding_model_id` is filtered on `model.id`, and
        the distance is taken over `embedding` cast to `model.embedding_dimension`.
        Both are derived from `model` rather than taken as separate arguments,
        because both must agree with it to be meaningful - a cosine distance
        between two different models' vectors is a number without meaning
        (ADR-0001), and between two different *widths* it is an error. This
        pairing is also exactly what makes the partial expression indexes usable;
        see `database/indexes.py`.

        Args:
            session: SQLAlchemy database session for executing the query.
            query: Free-text query to embed and compare stored records against.
            graph_name: Restrict the search to records belonging to this graph.
            organization_id: Restrict the search to this organization's rows.
                Applied on both `GraphSchemaRegistry.organization_id` (the
                authoritative scope of the schema row) and
                `SchemaEmbedding.organization_id` (the ADR-0002 denormalized
                isolation filter on the embedding row) - a mismatch between the
                two (a bug) returns nothing rather than leaking across
                organizations.
            model: The embedding provider configuration used to embed `query`, and
                the one whose rows are searched. Rows embedded by any other model
                are excluded, so during an ADR-0002 recalculation window this
                naturally sees only the rows already migrated to `model`.
            type: Optional schema type ('node' or 'relationship') to filter by.
            knowledge_base_ids: Optional knowledge base ids to restrict the search to.
                A record matches if its `knowledge_base_ids` overlaps with any of these
                (via PostgreSQL's jsonb `?|` operator), since a schema row may be shared
                by several contributing knowledge bases.
            top_k: Maximum number of records to return, ordered by similarity.

        Returns:
            A list of GraphSchemaRegistryDTOs ordered from most to least similar.

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
            .join(SchemaEmbedding, SchemaEmbedding.graph_registry_id == cls.id)
            .options(contains_eager(cls.embedding_row))
            .where(
                cls.organization_id == organization_id,
                SchemaEmbedding.organization_id == organization_id,
                cls.graph_name == graph_name,
                SchemaEmbedding.embedding_model_id == model.id,
                SchemaEmbedding.embedding.is_not(None),
            )
            .order_by(
                cast(
                    SchemaEmbedding.embedding, Vector(model.embedding_dimension)
                ).cosine_distance(embedding)
            )
            .limit(top_k)
        )
        if type is not None:
            stmt = stmt.where(
                cls.type == (type.value if isinstance(type, SchemaType) else type)
            )
        if knowledge_base_ids:
            stmt = stmt.where(
                cast(cls.knowledge_base_ids, JSONB).op("?|")(array(knowledge_base_ids))
            )

        rows = (await session.execute(stmt)).scalars().all()
        return [GraphSchemaRegistryDTO.model_validate(row) for row in rows]

    @classmethod
    async def get_properties_by_name(
        cls,
        session: AsyncSession,
        graph_name: str,
        organization_id: str,
        names: Iterable[str],
        type: SchemaType | None = None,
    ) -> dict[str, list[str]]:
        """Look up the stored property-name list for each given schema name.

        Args:
            session: SQLAlchemy database session for executing the query.
            graph_name: Restrict the lookup to records belonging to this graph.
            organization_id: Restrict the lookup to this organization's rows.
            names: Schema names (node or relationship labels) to look up.
            type: Optional schema type ('node' or 'relationship') to filter by.

        Returns:
            A mapping of name -> properties for matching registry rows. Names
            with no matching row (e.g. a label not yet in the registry) are
            omitted rather than mapped to an empty list.
        """
        names = set(names)
        if not names:
            return {}

        stmt = select(cls).where(
            cls.organization_id == organization_id,
            cls.graph_name == graph_name,
            cls.name.in_(names),
        )
        if type is not None:
            stmt = stmt.where(
                cls.type == (type.value if isinstance(type, SchemaType) else type)
            )
        rows = (await session.execute(stmt)).scalars().all()
        return {row.name: row.properties for row in rows}

    def __repr__(self) -> str:
        """Return a developer-friendly string representation of the schema registry record.

        Returns:
            A string showing the key identifying fields: id, organization_id,
            graph_name, type, and name.
        """
        return (
            f"GraphRegistry(id={self.id!r}, organization_id={self.organization_id!r}, "
            f"graph_name={self.graph_name!r}, "
            f"type={self.type.value if isinstance(self.type, SchemaType) else self.type!r}, "
            f"name={self.name!r})"
        )


__all__ = ["GraphSchemaRegistry", "SchemaType"]
