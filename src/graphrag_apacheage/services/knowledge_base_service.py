from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository
from graphrag_apacheage.schemas.knowledge_base import KnowledgeBase


class KnowledgeBaseService:
    def __init__(self, repository: AgeGraphRepository):
        self.repository = repository

    def upsert_knowledge_base(
        self, knowledge_base: KnowledgeBase, graph_name: str | None = None
    ) -> list[str]:
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
    connection, knowledge_base: KnowledgeBase, graph_name: str | None = None
) -> list[str]:
    repository = AgeGraphRepository(connection)
    service = KnowledgeBaseService(repository)
    return service.upsert_knowledge_base(knowledge_base, graph_name=graph_name)
