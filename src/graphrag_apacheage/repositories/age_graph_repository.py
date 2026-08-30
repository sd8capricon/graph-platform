import json
from typing import Any

from graphrag_apacheage.schemas.knowledge_base import KnowledgeBase


class AgeGraphRepository:
    def __init__(self, connection):
        self.connection = connection

    @staticmethod
    def _age_literal(value: Any) -> str:
        if isinstance(value, str):
            escaped = value.replace("\\", "\\\\").replace("'", "\\'")
            return f"'{escaped}'"
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def _age_properties_literal(cls, properties: dict[str, Any]) -> str:
        if not properties:
            return ""
        entries = [
            f"{json.dumps(key)}: {cls._age_literal(value)}"
            for key, value in properties.items()
        ]
        return " {" + ", ".join(entries) + "}"

    def create_graph(self, graph_name: str) -> str:
        query = f"SELECT * FROM ag_catalog.create_graph('{graph_name}');"
        self.connection.cursor().execute(query)
        return query

    def graph_exists(self, graph_name: str) -> bool:
        query = f"SELECT 1 FROM ag_catalog.ag_graph WHERE name = '{graph_name}';"
        cursor = self.connection.cursor()
        cursor.execute(query)
        result = cursor.fetchone()
        return result is not None

    def get_nodes(self, graph_name: str, label: str | None = None) -> str:
        label_filter = f" WHERE n: {label}" if label else ""
        query = (
            f"SELECT * FROM cypher('{graph_name}', $$ MATCH (n{label_filter}) RETURN n $$) "
            "AS (n agtype);"
        )
        self.connection.cursor().execute(query)
        return query

    def create_node(
        self, graph_name: str, label: str, properties: dict[str, Any]
    ) -> str:
        node_properties = dict(properties)
        properties_literal = self._age_properties_literal(node_properties)
        query = (
            f"SELECT * FROM cypher('{graph_name}', $$ CREATE (n:{label}{properties_literal}) "
            f"RETURN n $$) AS (v agtype);"
        )
        self.connection.cursor().execute(query)
        return query

    def update_node(
        self, graph_name: str, node_id: str, properties: dict[str, Any]
    ) -> str:
        props = self._age_properties_literal(properties)
        query = (
            f'SELECT * FROM cypher(\'{graph_name}\', $$ MATCH (n {{"id":"{node_id}"}}) '
            f"SET n = n + {props} RETURN n $$) AS (v agtype);"
        )
        self.connection.cursor().execute(query)
        return query

    def delete_node(self, graph_name: str, node_id: str) -> str:
        query = (
            f'SELECT * FROM cypher(\'{graph_name}\', $$ MATCH (n {{"id":"{node_id}"}}) '
            "DETACH DELETE n RETURN count(n) $$) AS (count agtype);"
        )
        self.connection.cursor().execute(query)
        return query

    def get_relationships(self, graph_name: str, label: str | None = None) -> str:
        label_filter = f" WHERE type(r) = '{label}'" if label else ""
        query = (
            f"SELECT * FROM cypher('{graph_name}', $$ MATCH ()-[r]-() {label_filter} "
            "RETURN r $$) AS (r agtype);"
        )
        self.connection.cursor().execute(query)
        return query

    def create_relationship(
        self,
        graph_name: str,
        source_node_id: str,
        target_node_id: str,
        label: str,
        properties: dict[str, Any] | None = None,
    ) -> str:
        properties_literal = self._age_properties_literal(properties or {})
        query = (
            f'SELECT * FROM cypher(\'{graph_name}\', $$ MATCH (a {{"id":"{source_node_id}"}}), '
            f'(b {{"id":"{target_node_id}"}}) CREATE (a)-[:{label}{properties_literal}]->(b) '
            "RETURN a, b $$) AS (v agtype);"
        )
        self.connection.cursor().execute(query)
        return query

    def update_relationship(
        self,
        graph_name: str,
        source_node_id: str,
        target_node_id: str,
        label: str,
        properties: dict[str, Any],
    ) -> str:
        props = self._age_properties_literal(properties)
        query = (
            f'SELECT * FROM cypher(\'{graph_name}\', $$ MATCH (a {{"id":"{source_node_id}"}})-[r:{label}]->'
            f'(b {{"id":"{target_node_id}"}}) SET r = r + {props} RETURN r $$) AS (v agtype);'
        )
        self.connection.cursor().execute(query)
        return query

    def delete_relationship(
        self, graph_name: str, source_node_id: str, target_node_id: str, label: str
    ) -> str:
        query = (
            f'SELECT * FROM cypher(\'{graph_name}\', $$ MATCH (a {{"id":"{source_node_id}"}})-[r:{label}]->'
            f'(b {{"id":"{target_node_id}"}}) DELETE r RETURN count(r) $$) AS (count agtype);'
        )
        self.connection.cursor().execute(query)
        return query

    def commit(self) -> None:
        if hasattr(self.connection, "commit"):
            self.connection.commit()


def upsert_knowledge_base_to_age_graph(
    connection, knowledge_base: KnowledgeBase, graph_name: str | None = None
) -> list[str]:
    if not graph_name:
        raise ValueError(
            "graph_name is required when upserting knowledge base to Apache Age graph"
        )
    repository = AgeGraphRepository(connection)
    target_graph = graph_name
    queries: list[str] = []
    try:
        queries.append(repository.create_graph(target_graph))
    except Exception:
        pass
    for node in knowledge_base.nodes:
        queries.append(
            repository.create_node(
                target_graph,
                node.label,
                (
                    {**node.properties, "id": node.id}
                    if node.id is not None
                    else node.properties
                ),
            )
        )
    for relationship in knowledge_base.relationships:
        queries.append(
            repository.create_relationship(
                target_graph,
                relationship.source_id,
                relationship.target_id,
                relationship.label,
                relationship.properties,
            )
        )
    repository.commit()
    return queries
