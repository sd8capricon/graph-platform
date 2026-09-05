import json
from typing import Any

from psycopg2.extensions import connection

from graphrag_apacheage.schemas.knowledge_base import KnowledgeBase


class AgeGraphRepository:
    """Repository for Apache Age graph operations.

    Provides a high-level interface for creating, querying, and manipulating
    Apache Age graphs and their nodes/relationships. All operations are executed
    against a PostgreSQL database with the Apache Age extension.

    Attributes:
        pg_connection: An active psycopg2 PostgreSQL database connection.
    """

    def __init__(self, pg_connection: connection):
        """Initialize the repository with a PostgreSQL connection.

        Args:
            pg_connection: A psycopg2 connection object to a PostgreSQL database
                with the Apache Age extension installed.
        """
        self.pg_connection = pg_connection

    @staticmethod
    def _age_literal(value: Any) -> str:
        """Convert a Python value to its Apache Age Cypher literal representation.

        Handles type conversions for strings (with escaping), None, booleans,
        numbers, and complex types via JSON serialization.

        Args:
            value: A Python value to convert.

        Returns:
            A string representation suitable for use in Cypher queries.
        """
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
        """Convert a properties dictionary to Apache Age property literal syntax.

        Transforms a dictionary of key-value pairs into the Cypher property
        syntax (e.g., {name: 'John', age: 30}). Empty dictionaries return
        an empty string.

        Args:
            properties: A dictionary of property names to values.

        Returns:
            A string in Apache Age property literal format, or empty string if
            the properties dictionary is empty.
        """
        if not properties:
            return ""
        entries = [
            f"{json.dumps(key)}: {cls._age_literal(value)}"
            for key, value in properties.items()
        ]
        return " {" + ", ".join(entries) + "}"

    def create_graph(self, graph_name: str) -> str:
        """Create a new Apache Age graph in the database.

        Args:
            graph_name: The name of the graph to create.

        Returns:
            The SQL query string that was executed.

        Raises:
            Exception: If the graph already exists or if the database operation fails.
        """
        query = f"SELECT * FROM ag_catalog.create_graph('{graph_name}');"
        self.pg_connection.cursor().execute(query)
        return query

    def delete_graph(self, graph_name: str) -> str:
        """Drop (delete) an Apache Age graph and all its contents.

        Cascades the deletion, removing all nodes, edges, and associated data
        within the graph.

        Args:
            graph_name: The name of the graph to delete.

        Returns:
            The SQL query string that was executed.

        Raises:
            Exception: If the graph does not exist or if the database operation fails.
        """
        query = f"SELECT * FROM ag_catalog.drop_graph('{graph_name}', true);"
        self.pg_connection.cursor().execute(query)
        return query

    def graph_exists(self, graph_name: str) -> bool:
        """Check if a graph exists in the database.

        Args:
            graph_name: The name of the graph to check.

        Returns:
            True if the graph exists, False otherwise.
        """
        query = f"SELECT 1 FROM ag_catalog.ag_graph WHERE name = '{graph_name}';"
        cursor = self.pg_connection.cursor()
        cursor.execute(query)
        result = cursor.fetchone()
        return result is not None

    def get_nodes(self, graph_name: str, label: str | None = None) -> str:
        """Query nodes in a graph, optionally filtered by label.

        Args:
            graph_name: The name of the graph to query.
            label: Optional label to filter nodes by. If None, returns all nodes.

        Returns:
            The SQL query string that was executed.
        """
        label_filter = f" WHERE n: {label}" if label else ""
        query = (
            f"SELECT * FROM cypher('{graph_name}', $$ MATCH (n{label_filter}) RETURN n $$) "
            "AS (n agtype);"
        )
        self.pg_connection.cursor().execute(query)
        return query

    def create_node(
        self, graph_name: str, label: str, properties: dict[str, Any]
    ) -> str:
        """Create a new node in the graph.

        Args:
            graph_name: The name of the graph.
            label: The label (type) of the node.
            properties: A dictionary of node properties.

        Returns:
            The SQL query string that was executed.
        """
        node_properties = dict(properties)
        properties_literal = self._age_properties_literal(node_properties)
        query = (
            f"SELECT * FROM cypher('{graph_name}', $$ CREATE (n:{label}{properties_literal}) "
            f"RETURN n $$) AS (v agtype);"
        )
        self.pg_connection.cursor().execute(query)
        return query

    def update_node(
        self, graph_name: str, node_id: str, properties: dict[str, Any]
    ) -> str:
        """Update properties on an existing node.

        Merges the provided properties with existing node properties.

        Args:
            graph_name: The name of the graph.
            node_id: The unique identifier of the node to update.
            properties: A dictionary of properties to merge into the node.

        Returns:
            The SQL query string that was executed.
        """
        props = self._age_properties_literal(properties)
        query = (
            f'SELECT * FROM cypher(\'{graph_name}\', $$ MATCH (n {{"id":"{node_id}"}}) '
            f"SET n = n + {props} RETURN n $$) AS (v agtype);"
        )
        self.pg_connection.cursor().execute(query)
        return query

    def delete_node(self, graph_name: str, node_id: str) -> str:
        """Delete a node from the graph.

        Also detaches and deletes all edges connected to this node.

        Args:
            graph_name: The name of the graph.
            node_id: The unique identifier of the node to delete.

        Returns:
            The SQL query string that was executed.
        """
        query = (
            f'SELECT * FROM cypher(\'{graph_name}\', $$ MATCH (n {{"id":"{node_id}"}}) '
            "DETACH DELETE n RETURN count(n) $$) AS (count agtype);"
        )
        self.pg_connection.cursor().execute(query)
        return query

    def get_relationships(self, graph_name: str, label: str | None = None) -> str:
        """Query relationships in a graph, optionally filtered by label.

        Args:
            graph_name: The name of the graph to query.
            label: Optional relationship label to filter by. If None, returns all relationships.

        Returns:
            The SQL query string that was executed.
        """
        label_filter = f" WHERE type(r) = '{label}'" if label else ""
        query = (
            f"SELECT * FROM cypher('{graph_name}', $$ MATCH ()-[r]-() {label_filter} "
            "RETURN r $$) AS (r agtype);"
        )
        self.pg_connection.cursor().execute(query)
        return query

    def create_relationship(
        self,
        graph_name: str,
        source_node_id: str,
        target_node_id: str,
        label: str,
        properties: dict[str, Any] | None = None,
    ) -> str:
        """Create a relationship between two nodes.

        Args:
            graph_name: The name of the graph.
            source_node_id: The unique identifier of the source node.
            target_node_id: The unique identifier of the target node.
            label: The label (type) of the relationship.
            properties: Optional dictionary of relationship properties.

        Returns:
            The SQL query string that was executed.
        """
        properties_literal = self._age_properties_literal(properties or {})
        query = (
            f'SELECT * FROM cypher(\'{graph_name}\', $$ MATCH (a {{"id":"{source_node_id}"}}), '
            f'(b {{"id":"{target_node_id}"}}) CREATE (a)-[:{label}{properties_literal}]->(b) '
            "RETURN a, b $$) AS (v agtype);"
        )
        self.pg_connection.cursor().execute(query)
        return query

    def update_relationship(
        self,
        graph_name: str,
        source_node_id: str,
        target_node_id: str,
        label: str,
        properties: dict[str, Any],
    ) -> str:
        """Update properties on an existing relationship.

        Merges the provided properties with existing relationship properties.

        Args:
            graph_name: The name of the graph.
            source_node_id: The unique identifier of the source node.
            target_node_id: The unique identifier of the target node.
            label: The label (type) of the relationship.
            properties: A dictionary of properties to merge into the relationship.

        Returns:
            The SQL query string that was executed.
        """
        props = self._age_properties_literal(properties)
        query = (
            f'SELECT * FROM cypher(\'{graph_name}\', $$ MATCH (a {{"id":"{source_node_id}"}})-[r:{label}]->'
            f'(b {{"id":"{target_node_id}"}}) SET r = r + {props} RETURN r $$) AS (v agtype);'
        )
        self.pg_connection.cursor().execute(query)
        return query

    def delete_relationship(
        self, graph_name: str, source_node_id: str, target_node_id: str, label: str
    ) -> str:
        """Delete a relationship between two nodes.

        Args:
            graph_name: The name of the graph.
            source_node_id: The unique identifier of the source node.
            target_node_id: The unique identifier of the target node.
            label: The label (type) of the relationship to delete.

        Returns:
            The SQL query string that was executed.
        """
        query = (
            f'SELECT * FROM cypher(\'{graph_name}\', $$ MATCH (a {{"id":"{source_node_id}"}})-[r:{label}]->'
            f'(b {{"id":"{target_node_id}"}}) DELETE r RETURN count(r) $$) AS (count agtype);'
        )
        self.pg_connection.cursor().execute(query)
        return query

    def commit(self) -> None:
        """Commit the current transaction to the database.

        Only commits if the connection supports the commit method.
        """
        if hasattr(self.pg_connection, "commit"):
            self.pg_connection.commit()
