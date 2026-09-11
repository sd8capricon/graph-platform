from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from graphrag_apacheage.models.graph_schema_registry import GraphSchemaRegistry
from graphrag_apacheage.models.node_embedding import NodeEmbedding
from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository
from graphrag_apacheage.schemas.knowledge_base import KnowledgeBase
from graphrag_apacheage.schemas.model import Model


class KnowledgeBaseService:
    """Service for managing knowledge base operations with Apache Age graph database.

    This service provides high-level operations for upserting and deleting knowledge
    bases (nodes and relationships) in an Apache Age graph database, keeping the
    `GraphSchemaRegistry` and `NodeEmbedding` side-tables in sync with the graph.
    """

    def __init__(self, repository: AgeGraphRepository):
        """Initialize the KnowledgeBaseService.

        Args:
            repository: An AgeGraphRepository instance for database operations.
        """
        self.repository = repository

    async def upsert_knowledge_base(
        self,
        session: AsyncSession,
        knowledge_base: KnowledgeBase,
        graph_name: str,
        model: Model | None = None,
    ) -> list[str]:
        """Upsert a knowledge base into the Apache Age graph and its side-tables.

        Performs the full ingestion of one knowledge base into one graph:

        1. Inserts all nodes and relationships into the Apache Age graph (which
           must already exist) and commits the graph connection.
        2. Upserts the knowledge base's schema definitions into
           `GraphSchemaRegistry`, merging with any definitions already contributed
           by other knowledge bases feeding the same graph.
        3. Upserts one `NodeEmbedding` row per node.

        Steps 2 and 3 are flushed but not committed — committing `session` is the
        caller's responsibility, so graph writes and side-table writes can be
        reconciled by the caller.

        Args:
            session: SQLAlchemy async session used to persist the schema registry
                records and node embeddings.
            knowledge_base: The KnowledgeBase instance containing nodes and relationships.
            graph_name: The name of the target Apache Age graph. Required.
            model: The embedding provider configuration used to embed the schema
                registry records and node embeddings. If None, embedding computation
                is skipped and rows are stored without an embedding.

        Returns:
            A list of SQL queries that were executed against the Apache Age graph.

        Raises:
            ValueError: If graph_name is not provided, if the graph does not exist
                in the database, or if the knowledge base has no id.
        """
        if not graph_name:
            raise ValueError(
                "graph_name is required when upserting knowledge base to Apache Age graph"
            )

        if not await self.repository.graph_exists(graph_name):
            raise ValueError(
                f"Apache Age graph '{graph_name}' does not exist in the database"
            )

        queries: list[str] = []

        for node in knowledge_base.nodes:
            node_properties = dict(node.properties)
            if node.id is not None:
                node_properties["id"] = node.id
            queries.append(
                await self.repository.create_node(
                    graph_name, node.label, node_properties
                )
            )

        for relationship in knowledge_base.relationships:
            queries.append(
                await self.repository.create_relationship(
                    graph_name,
                    relationship.source_id,
                    relationship.target_id,
                    relationship.label,
                    relationship.properties,
                )
            )

        await self.repository.commit()

        await self.upsert_graph_schema_registry(
            session, knowledge_base, graph_name, model=model
        )
        await self.upsert_node_embeddings(
            session, knowledge_base, graph_name, model=model
        )

        return queries

    async def delete_knowledge_base(
        self, session: AsyncSession, knowledge_base_id: str, graph_name: str
    ) -> list[str]:
        """Delete a knowledge base from the Apache Age graph and its side-tables.

        The inverse of `upsert_knowledge_base()`:

        1. Deletes every node this knowledge base contributed to the graph, via
           `DETACH DELETE`, so the relationships attached to those nodes go with
           them. The node ids are read from the knowledge base's `NodeEmbedding`
           rows, which are this service's record of what it wrote to the graph.
        2. Deletes the knowledge base's `NodeEmbedding` rows.
        3. Adjusts `GraphSchemaRegistry`: drops this knowledge base's id from every
           schema row it contributed to, and deletes the rows left with no
           contributing knowledge base. Rows still claimed by another knowledge base
           are kept, since the same label may be defined by several knowledge bases
           feeding one graph. Note that such a surviving row keeps any aliases and
           properties this knowledge base contributed — they were merged in on
           upsert and cannot be attributed back to a single knowledge base. Re-upsert
           the remaining knowledge bases if an exact schema is needed.

        As in `upsert_knowledge_base()`, the graph connection is committed but
        `session` is not — committing it is the caller's responsibility.

        Args:
            session: SQLAlchemy async session used to read and delete the side-table rows.
            knowledge_base_id: The id of the KnowledgeBase to delete.
            graph_name: The name of the Apache Age graph to delete it from. Required.

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
                NodeEmbedding.graph_name == graph_name,
                NodeEmbedding.knowledge_base_id == knowledge_base_id,
            )
        )

        await self.delete_graph_schema_registry(session, knowledge_base_id, graph_name)

        await session.flush()
        return queries

    async def upsert_graph_schema_registry(
        self,
        session: AsyncSession,
        knowledge_base: KnowledgeBase,
        graph_name: str,
        model: Model | None = None,
    ) -> list[GraphSchemaRegistry]:
        """Extract and store a knowledge base's node/relationship type definitions.

        Args:
            session: SQLAlchemy async session used to persist the schema records.
            knowledge_base: The KnowledgeBase whose schema should be registered.
            graph_name: The name of the Apache Age graph these schemas belong to. Required.
            model: The embedding provider configuration to use. If None, embedding
                computation is skipped and records are stored without an embedding.

        Returns:
            A list of persisted GraphSchemaRegistry records (newly inserted or updated).

        Raises:
            ValueError: If graph_name is not provided, or if the knowledge base has
                no id.
        """
        if not graph_name:
            raise ValueError(
                "graph_name is required when upserting graph schema registry records"
            )

        records = knowledge_base.get_graph_schema_registry_records(graph_name)
        return await GraphSchemaRegistry.upsert_records(session, records, model=model)

    async def delete_graph_schema_registry(
        self, session: AsyncSession, knowledge_base_id: str, graph_name: str
    ) -> list[GraphSchemaRegistry]:
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

        Returns:
            A list of the surviving GraphSchemaRegistry rows the id was removed from.
            Rows deleted because they had no remaining contributor are not included.
        """
        rows = (
            (
                await session.execute(
                    select(GraphSchemaRegistry).where(
                        GraphSchemaRegistry.graph_name == graph_name
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
        return retained

    async def upsert_node_embeddings(
        self,
        session: AsyncSession,
        knowledge_base: KnowledgeBase,
        graph_name: str,
        model: Model | None = None,
    ) -> list[NodeEmbedding]:
        """Compute and store vector embeddings for a knowledge base's nodes.

        Args:
            session: SQLAlchemy async session used to persist node embeddings.
            knowledge_base: The KnowledgeBase whose nodes should be embedded.
            graph_name: The name of the Apache Age graph these nodes belong to. Required.
            model: The embedding provider configuration to use. If None, embedding
                computation is skipped and nodes are stored without an embedding.

        Returns:
            A list of persisted NodeEmbedding records (newly inserted or updated).

        Raises:
            ValueError: If graph_name is not provided, or if the knowledge base has
                no id.
        """
        if not graph_name:
            raise ValueError("graph_name is required when upserting node embeddings")

        records = knowledge_base.get_node_embedding_records(graph_name)
        return await NodeEmbedding.upsert_records(session, records, model=model)

    async def search_nodes(
        self,
        session: AsyncSession,
        query: str,
        graph_name: str,
        model: Model,
        labels: list[str] | None = None,
        knowledge_base_id: str | None = None,
        limit: int = 5,
    ) -> list[NodeEmbedding]:
        """Find knowledge base nodes whose embedding is closest to a text query.

        Args:
            session: SQLAlchemy async session used to execute the search.
            query: Free-text query to embed and compare stored node embeddings against.
            graph_name: Restrict the search to nodes belonging to this graph.
            model: The embedding provider configuration used to embed `query`.
            labels: Optional node labels to filter by.
            knowledge_base_id: Optional KnowledgeBase id to restrict the search to.
            limit: Maximum number of nodes to return, ordered by similarity.

        Returns:
            A list of NodeEmbedding records ordered from most to least similar.
        """
        return await NodeEmbedding.vector_search(
            session,
            query,
            graph_name,
            model,
            labels=labels,
            knowledge_base_id=knowledge_base_id,
            limit=limit,
        )
