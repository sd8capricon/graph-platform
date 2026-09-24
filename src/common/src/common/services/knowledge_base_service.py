from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.models.graph_schema_registry import GraphSchemaRegistry
from common.models.node_embedding import NodeEmbedding
from common.models.schema_embedding import SchemaEmbedding
from common.repositories.age_graph_repository import AgeGraphRepository
from common.schemas.graph_schema_registry import GraphSchemaRegistryDTO
from common.schemas.model import Model
from common.schemas.node_embedding import NodeEmbeddingDTO


class KnowledgeBaseService:
    """Lifecycle operations for a knowledge base in an Apache Age graph.

    Owns creating and deleting a graph and a knowledge base's claim on it,
    keeping the `GraphSchemaRegistry` and `NodeEmbedding` side-tables in sync.
    The *write* paths (upserting a knowledge base, its schema registry rows and
    its node embeddings) are ingestion-only and live in the ingestion worker
    (ADR-0004 Decision 4); this service keeps only the shared lifecycle.
    """

    def __init__(self, repository: AgeGraphRepository):
        """Initialize the KnowledgeBaseService.

        Args:
            repository: An AgeGraphRepository instance for database operations.
        """
        self.repository = repository

    async def delete_knowledge_base(
        self,
        session: AsyncSession,
        knowledge_base_id: str,
        graph_name: str,
        organization_id: str,
    ) -> list[str]:
        """Delete a knowledge base from the Apache Age graph and its side-tables.

        The inverse of the worker's ingestion write:

        1. Deletes every node this knowledge base contributed to the graph, via
           `DETACH DELETE`, so the relationships attached to those nodes go with
           them. The node ids are read from the knowledge base's `NodeEmbedding`
           rows, which are the record of what was written to the graph.
        2. Deletes the knowledge base's `NodeEmbedding` rows.
        3. Adjusts `GraphSchemaRegistry`: drops this knowledge base's id from every
           schema row it contributed to, and deletes the rows left with no
           contributing knowledge base. Rows still claimed by another knowledge base
           are kept, since the same label may be defined by several knowledge bases
           feeding one graph. Note that such a surviving row keeps any aliases and
           properties this knowledge base contributed - they were merged in on
           upsert and cannot be attributed back to a single knowledge base. Re-upsert
           the remaining knowledge bases if an exact schema is needed.

        The graph connection is committed but `session` is not - committing it is
        the caller's responsibility.

        Args:
            session: SQLAlchemy async session used to read and delete the side-table rows.
            knowledge_base_id: The id of the KnowledgeBase to delete.
            graph_name: The name of the Apache Age graph to delete it from. Required.
            organization_id: Id of the organization this graph belongs to (see
                ADR-0002, Decision 1). Scopes every side-table read/delete below.

        Returns:
            A list of SQL queries that were executed against the Apache Age graph,
            one per deleted node.

        Raises:
            ValueError: If graph_name or knowledge_base_id is not provided, or if the
                graph does not exist in the database.
        """
        if not graph_name:
            raise ValueError(
                "graph_name is required when deleting a knowledge base from an "
                "Apache Age graph"
            )
        if not knowledge_base_id:
            raise ValueError("knowledge_base_id is required when deleting a knowledge base")

        if not await self.repository.graph_exists(graph_name):
            raise ValueError(
                f"Apache Age graph '{graph_name}' does not exist in the database"
            )

        node_ids = list(
            (
                await session.execute(
                    select(NodeEmbedding.node_id).where(
                        NodeEmbedding.organization_id == organization_id,
                        NodeEmbedding.graph_name == graph_name,
                        NodeEmbedding.knowledge_base_id == knowledge_base_id,
                    )
                )
            )
            .scalars()
            .all()
        )

        queries: list[str] = [
            await self.repository.delete_node(graph_name, node_id)
            for node_id in node_ids
        ]
        await self.repository.commit()

        await session.execute(
            delete(NodeEmbedding).where(
                NodeEmbedding.organization_id == organization_id,
                NodeEmbedding.graph_name == graph_name,
                NodeEmbedding.knowledge_base_id == knowledge_base_id,
            )
        )

        await self.delete_graph_schema_registry(
            session, knowledge_base_id, graph_name, organization_id
        )

        await session.flush()
        return queries

    async def create_graph(self, graph_name: str) -> str | None:
        """Create an Apache Age graph, unless it already exists.

        The counterpart of `delete_graph()`, so the graph lifecycle is driven
        entirely through this service and callers never have to mix service and
        repository calls. Takes no `session`: a brand new graph has no side-table
        rows, so there is nothing to create alongside it. (If a graph name is being
        *reused* after being dropped outside this service, call `delete_graph()`
        first - it tolerates a missing graph and clears any orphaned rows.)

        Args:
            graph_name: The name of the Apache Age graph to create. Required.

        Returns:
            The SQL query that created the graph, or None if the graph already
            existed and nothing was done.

        Raises:
            ValueError: If graph_name is not provided.
        """
        if not graph_name:
            raise ValueError("graph_name is required when creating an Apache Age graph")

        if await self.repository.graph_exists(graph_name):
            return None

        query = await self.repository.create_graph(graph_name)
        await self.repository.commit()
        return query

    async def delete_graph(
        self, session: AsyncSession, graph_name: str, organization_id: str
    ) -> str | None:
        """Drop an Apache Age graph and every side-table row belonging to it.

        The inverse of `create_graph()` and the graph-wide counterpart of
        `delete_knowledge_base()`. Drops the graph
        itself (cascading, so all its nodes and edges go with it), then deletes
        *all* `NodeEmbedding` and `GraphSchemaRegistry` (plus its `SchemaEmbedding`
        children) rows for `graph_name`. Unlike `delete_knowledge_base()`, the
        registry rows are deleted outright rather than adjusted: the graph they
        describe no longer exists, so no contributing knowledge base has a
        remaining claim on them.

        The `SchemaEmbedding` rows must be deleted with their own statement,
        before the `GraphSchemaRegistry` delete: both deletes here are bulk
        `delete()` statements, which bypass the ORM's `cascade="all,
        delete-orphan"` on `GraphSchemaRegistry.embedding_row` entirely (that
        cascade only fires for `session.delete()` on a loaded instance, which
        `delete_graph_schema_registry()` uses but this method does not).

        A missing graph is not an error. Dropping a graph is precisely the case
        that leaves the side-tables orphaned, so the rows are cleaned up either
        way - refusing when the graph is already gone would make that orphaned
        state unfixable through this API.

        As in `delete_knowledge_base()`, the graph connection is committed but
        `session` is not - committing it is the caller's responsibility.

        Args:
            session: SQLAlchemy async session used to delete the side-table rows.
            graph_name: The name of the Apache Age graph to delete. Required.
            organization_id: Id of the organization this graph belongs to (see
                ADR-0002, Decision 1). Scopes every side-table delete below.

        Returns:
            The SQL query that dropped the graph, or None if the graph did not
            exist and only the side-tables were cleaned up.

        Raises:
            ValueError: If graph_name is not provided.
        """
        if not graph_name:
            raise ValueError("graph_name is required when deleting an Apache Age graph")

        query: str | None = None
        if await self.repository.graph_exists(graph_name):
            query = await self.repository.delete_graph(graph_name)
            await self.repository.commit()

        await session.execute(
            delete(NodeEmbedding).where(
                NodeEmbedding.organization_id == organization_id,
                NodeEmbedding.graph_name == graph_name,
            )
        )
        await session.execute(
            delete(SchemaEmbedding).where(
                SchemaEmbedding.graph_registry_id.in_(
                    select(GraphSchemaRegistry.id).where(
                        GraphSchemaRegistry.organization_id == organization_id,
                        GraphSchemaRegistry.graph_name == graph_name,
                    )
                )
            )
        )
        await session.execute(
            delete(GraphSchemaRegistry).where(
                GraphSchemaRegistry.organization_id == organization_id,
                GraphSchemaRegistry.graph_name == graph_name,
            )
        )

        await session.flush()
        return query

    async def delete_graph_schema_registry(
        self,
        session: AsyncSession,
        knowledge_base_id: str,
        graph_name: str,
        organization_id: str,
    ) -> list[GraphSchemaRegistryDTO]:
        """Drop a knowledge base's claim on a graph's schema registry rows.

        Removes `knowledge_base_id` from the `knowledge_base_ids` of every schema
        row in `graph_name` that it contributed to, and deletes the rows that are
        left with no contributing knowledge base. Rows still claimed by another
        knowledge base survive with the id removed.

        Rows are filtered in Python rather than in SQL: `knowledge_base_ids` is a
        plain JSON column, and a graph's schema registry holds only one row per
        label, so the scan is cheap and stays dialect-independent (the jsonb
        containment operators `GraphSchemaRegistry.vector_search()` uses are
        PostgreSQL-only).

        Args:
            session: SQLAlchemy async session used to read and update the rows.
            knowledge_base_id: The id of the KnowledgeBase to remove.
            graph_name: The name of the Apache Age graph whose registry to adjust.
            organization_id: Id of the organization this graph belongs to (see
                ADR-0002, Decision 1). Scopes which rows are read/adjusted.

        Returns:
            A list of the surviving GraphSchemaRegistryDTOs the id was removed from.
            Rows deleted because they had no remaining contributor are not included.
        """
        rows = (
            (
                await session.execute(
                    select(GraphSchemaRegistry).where(
                        GraphSchemaRegistry.organization_id == organization_id,
                        GraphSchemaRegistry.graph_name == graph_name,
                    )
                )
            )
            .scalars()
            .all()
        )

        retained: list[GraphSchemaRegistry] = []
        for row in rows:
            if knowledge_base_id not in row.knowledge_base_ids:
                continue
            remaining = [
                existing_id
                for existing_id in row.knowledge_base_ids
                if existing_id != knowledge_base_id
            ]
            if remaining:
                row.knowledge_base_ids = remaining
                retained.append(row)
            else:
                await session.delete(row)

        await session.flush()
        return [GraphSchemaRegistryDTO.model_validate(row) for row in retained]

    async def search_nodes(
        self,
        session: AsyncSession,
        query: str,
        graph_name: str,
        organization_id: str,
        model: Model,
        labels: list[str] | None = None,
        knowledge_base_id: str | None = None,
        limit: int = 5,
    ) -> list[NodeEmbeddingDTO]:
        """Find knowledge base nodes whose embedding is closest to a text query.

        Args:
            session: SQLAlchemy async session used to execute the search.
            query: Free-text query to embed and compare stored node embeddings against.
            graph_name: Restrict the search to nodes belonging to this graph.
            organization_id: Restrict the search to this organization's rows (see
                ADR-0002, Decision 1).
            model: The embedding provider configuration used to embed `query`. The
                search is confined to rows this model itself produced (see
                `NodeEmbedding.vector_search()`) - there is no separate
                embedding-model filter, since only `model` can say what row it
                should be compared against.
            labels: Optional node labels to filter by.
            knowledge_base_id: Optional KnowledgeBase id to restrict the search to.
            limit: Maximum number of nodes to return, ordered by similarity.

        Returns:
            A list of NodeEmbeddingDTOs ordered from most to least similar.
        """
        return await NodeEmbedding.vector_search(
            session,
            query,
            graph_name,
            organization_id,
            model,
            labels=labels,
            knowledge_base_id=knowledge_base_id,
            limit=limit,
        )


__all__ = ["KnowledgeBaseService"]
