from psycopg2.extensions import connection
from sqlalchemy.ext.asyncio import AsyncSession

from graphrag_apacheage.models.node_embedding import NodeEmbedding
from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository
from graphrag_apacheage.schemas.knowledge_base import KnowledgeBase
from graphrag_apacheage.schemas.model import Model


class KnowledgeBaseService:
    """Service for managing knowledge base operations with Apache Age graph database.

    This service provides high-level operations for upserting knowledge bases
    (nodes and relationships) into an Apache Age graph database.
    """

    def __init__(self, repository: AgeGraphRepository):
        """Initialize the KnowledgeBaseService.

        Args:
            repository: An AgeGraphRepository instance for database operations.
        """
        self.repository = repository

    def upsert_knowledge_base(
        self, knowledge_base: KnowledgeBase, graph_name: str | None = None
    ) -> list[str]:
        """Upsert a knowledge base into the Apache Age graph database.

        Inserts all nodes and relationships from the knowledge base into the
        specified Apache Age graph. The graph must exist in the database.

        Args:
            knowledge_base: The KnowledgeBase instance containing nodes and relationships.
            graph_name: The name of the target Apache Age graph. Required.

        Returns:
            A list of SQL queries that were executed during the upsert operation.

        Raises:
            ValueError: If graph_name is not provided or if the graph does not exist
                in the database.
        """
        if not graph_name:
            raise ValueError(
                "graph_name is required when upserting knowledge base to Apache Age graph"
            )

        if not self.repository.graph_exists(graph_name):
            raise ValueError(
                f"Apache Age graph '{graph_name}' does not exist in the database"
            )

        queries: list[str] = []

        for node in knowledge_base.nodes:
            node_properties = dict(node.properties)
            if node.id is not None:
                node_properties["id"] = node.id
            queries.append(
                self.repository.create_node(graph_name, node.label, node_properties)
            )

        for relationship in knowledge_base.relationships:
            queries.append(
                self.repository.create_relationship(
                    graph_name,
                    relationship.source_id,
                    relationship.target_id,
                    relationship.label,
                    relationship.properties,
                )
            )

        self.repository.commit()
        return queries

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
            raise ValueError(
                "graph_name is required when upserting node embeddings"
            )

        records = knowledge_base.get_node_embedding_records(graph_name)
        return await NodeEmbedding.upsert_records(session, records, model=model)

    async def search_nodes(
        self,
        session: AsyncSession,
        query: str,
        graph_name: str,
        model: Model,
        label: str | None = None,
        knowledge_base_id: str | None = None,
        limit: int = 5,
    ) -> list[NodeEmbedding]:
        """Find knowledge base nodes whose embedding is closest to a text query.

        Args:
            session: SQLAlchemy async session used to execute the search.
            query: Free-text query to embed and compare stored node embeddings against.
            graph_name: Restrict the search to nodes belonging to this graph.
            model: The embedding provider configuration used to embed `query`.
            label: Optional node label to filter by.
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
            label=label,
            knowledge_base_id=knowledge_base_id,
            limit=limit,
        )
