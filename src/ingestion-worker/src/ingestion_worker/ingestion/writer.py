"""Idempotent side-table writers for the ingestion pipeline.

Moved out of `common` (ADR-0004 Decision 4): only ingestion writes these rows,
so the upsert logic lives in the worker. Read/vector-search queries stay on the
ORM models in `common` and transfer results as DTOs. The logic itself - including
the two `GraphSchemaRegistry`/`SchemaEmbedding` traps - is preserved from the
previous `GraphSchemaRegistry.upsert_records()` / `NodeEmbedding.upsert_records()`.
"""

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.models.graph_schema_registry import GraphSchemaRegistry
from common.models.node_embedding import NodeEmbedding
from common.models.schema_embedding import SchemaEmbedding
from common.schemas.graph_schema_registry import GraphSchemaRegistryDTO, SchemaType
from common.schemas.model import Model
from common.schemas.node_embedding import NodeEmbeddingDTO
from common.schemas.schema_embedding import SchemaEmbeddingDTO
from common.services.embedding_service import EmbeddingService


def schema_embedding_text(record: GraphSchemaRegistryDTO) -> str:
    """Text embedded for a schema registry record (name/description/aliases)."""
    parts = [record.name, record.description, *record.aliases]
    return " ".join(part for part in parts if part)


def node_embedding_text(record: NodeEmbeddingDTO) -> str:
    """Text embedded for a node (label plus `key: value` property pairs)."""
    parts = [
        record.label,
        *(f"{key}: {value}" for key, value in record.properties.items()),
    ]
    return " ".join(part for part in parts if part)


async def upsert_schema_registry(
    session: AsyncSession,
    records: Iterable[GraphSchemaRegistryDTO],
    model: Model | None = None,
) -> list[GraphSchemaRegistryDTO]:
    """Upsert schema registry records, merging by (org, graph, type, name).

    Newly-seen labels insert; an existing label merges aliases, properties and
    contributing knowledge-base ids. When `model` is passed, each persisted
    record's embedding is (re)computed and stored on its `embedding_row`.
    """
    persisted: list[GraphSchemaRegistry] = []

    for record in records:
        existing = (
            await session.execute(
                select(GraphSchemaRegistry).where(
                    GraphSchemaRegistry.organization_id == record.organization_id,
                    GraphSchemaRegistry.graph_name == record.graph_name,
                    GraphSchemaRegistry.type
                    == (
                        record.type.value
                        if isinstance(record.type, SchemaType)
                        else record.type
                    ),
                    GraphSchemaRegistry.name == record.name,
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            # Load-bearing: marks `embedding_row` as loaded (== None) before
            # the ORM row becomes persistent. Without this, the next
            # iteration's `select()` autoflushes it, and reading the unloaded
            # relationship afterward raises MissingGreenlet.
            row = GraphSchemaRegistry(
                **record.model_dump(exclude={"id", "embedding_row"})
            )
            row.embedding_row = None
            session.add(row)
            persisted.append(row)
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
        model,
        [
            schema_embedding_text(GraphSchemaRegistryDTO.model_validate(record))
            for record in persisted
        ],
    )
    if embeddings is not None:
        embedding_model_id = model.id if model is not None else None
        for record, embedding in zip(persisted, embeddings):
            child = record.embedding_row
            if child is None:
                child_dto = SchemaEmbeddingDTO(
                    organization_id=record.organization_id,
                    embedding_model_id=embedding_model_id,
                    embedding=embedding,
                )
                record.embedding_row = SchemaEmbedding(
                    **child_dto.model_dump(exclude={"id", "graph_registry_id"})
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
    return [GraphSchemaRegistryDTO.model_validate(record) for record in persisted]


async def upsert_node_embeddings(
    session: AsyncSession,
    records: Iterable[NodeEmbeddingDTO],
    model: Model | None = None,
) -> list[NodeEmbeddingDTO]:
    """Upsert node embedding rows, keyed by (org, graph, kb, node).

    A new key inserts; an existing one updates label/properties. When `model` is
    passed, each persisted record's embedding is (re)computed and its
    `embedding_model_id` provenance stamped.
    """
    persisted: list[NodeEmbedding] = []

    for record in records:
        existing = (
            await session.execute(
                select(NodeEmbedding).where(
                    NodeEmbedding.organization_id == record.organization_id,
                    NodeEmbedding.graph_name == record.graph_name,
                    NodeEmbedding.knowledge_base_id == record.knowledge_base_id,
                    NodeEmbedding.node_id == record.node_id,
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            row = NodeEmbedding(
                **record.model_dump(exclude={"id"})
            )
            session.add(row)
            persisted.append(row)
            continue

        existing.label = record.label
        existing.properties = record.properties
        persisted.append(existing)

    embeddings = await EmbeddingService.compute_embeddings(
        model,
        [
            node_embedding_text(NodeEmbeddingDTO.model_validate(record))
            for record in persisted
        ],
    )
    if embeddings is not None:
        embedding_model_id = model.id if model is not None else None
        for record, embedding in zip(persisted, embeddings):
            record.embedding = embedding
            record.embedding_model_id = embedding_model_id

    await session.flush()
    return [NodeEmbeddingDTO.model_validate(record) for record in persisted]


__all__ = [
    "schema_embedding_text",
    "node_embedding_text",
    "upsert_schema_registry",
    "upsert_node_embeddings",
]
