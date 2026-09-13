from collections.abc import Iterable
from enum import Enum

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, CheckConstraint, String, Text, cast, select
from sqlalchemy.dialects.postgresql import JSONB, array
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, contains_eager, mapped_column, relationship

from graphrag_apacheage.models.base import Base
from graphrag_apacheage.models.schema_embedding import SchemaEmbedding
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
        records: Iterable["GraphSchemaRegistry"],
        model: Model | None = None,
    ) -> list["GraphSchemaRegistry"]:
        """Upsert (insert or update) schema registry records into the database.

        For each record, checks if it already exists based on
        (organization_id, graph_name, type, name).
        - If not found: inserts the new record.
        - If found: merges the data by combining aliases, properties, and
          knowledge_base_ids (each deduped and sorted), and preserving source/target
          labels if not already set.
        Also (re)computes each persisted record's embedding from its post-merge
        name/description/aliases via litellm, provided an embedding `model` is
        passed, storing it on the record's `embedding_row` (see `SchemaEmbedding`)
        rather than on the record itself; otherwise embeddings are left untouched.

        Args:
            session: SQLAlchemy database session for executing queries.
            records: An iterable of GraphSchemaRegistry records to upsert. Each
                record's `organization_id` must already be set.
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
                        cls.organization_id == record.organization_id,
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
                # Load-bearing: marks `embedding_row` as loaded (== None) before
                # this record becomes persistent. Without this, the next
                # iteration's `select()` above autoflushes it, and reading
                # `record.embedding_row` after that (below) raises
                # MissingGreenlet - `lazy="selectin"` only helps on rows loaded
                # by a query, not on a row that became persistent via autoflush.
                record.embedding_row = None
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
            embedding_model_id = model.id if model is not None else None
            for record, embedding in zip(persisted, embeddings):
                child = record.embedding_row
                if child is None:
                    record.embedding_row = SchemaEmbedding(
                        organization_id=record.organization_id,
                        embedding_model_id=embedding_model_id,
                        embedding=embedding,
                    )
                else:
                    # Mutate in place - never replace: the unit of work orders
                    # INSERTs before DELETEs within a table, so assigning a new
                    # SchemaEmbedding to a row that already has one races the
                    # pending delete-orphan of the old child and raises
                    # IntegrityError on the unique graph_registry_id.
                    child.organization_id = record.organization_id
                    child.embedding_model_id = embedding_model_id
                    child.embedding = embedding

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
        type: SchemaType | None = None,
        knowledge_base_ids: list[str] | None = None,
        top_k: int = 5,
    ) -> list["GraphSchemaRegistry"]:
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
        see `models/embedding_index.py`.

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
            A list of GraphSchemaRegistry records ordered from most to least similar.

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

        return list((await session.execute(stmt)).scalars().all())

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
