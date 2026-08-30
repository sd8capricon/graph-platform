from psycopg2.extensions import connection

from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository
from graphrag_apacheage.schemas.knowledge_base import KnowledgeBase


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


def upsert_knowledge_base_to_age_graph(
    pg_connection: connection,
    knowledge_base: KnowledgeBase,
    graph_name: str | None = None,
) -> list[str]:
    """Upsert a knowledge base to an Apache Age graph using a PostgreSQL connection.

    Convenience function that creates a KnowledgeBaseService instance and
    performs an upsert operation in a single call.

    Args:
        pg_connection: A psycopg2 PostgreSQL database connection.
        knowledge_base: The KnowledgeBase instance containing nodes and relationships.
        graph_name: The name of the target Apache Age graph. Required.

    Returns:
        A list of SQL queries that were executed during the upsert operation.

    Raises:
        ValueError: If graph_name is not provided or if the graph does not exist
            in the database.
    """
    repository = AgeGraphRepository(pg_connection)
    service = KnowledgeBaseService(repository)
    return service.upsert_knowledge_base(knowledge_base, graph_name=graph_name)
