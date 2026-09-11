import json
from typing import Any

from psycopg import AsyncConnection


class AgeGraphRepository:
    """Repository for Apache Age graph operations.

    Provides a high-level interface for creating, querying, and manipulating
    Apache Age graphs and their nodes/relationships. All operations are executed
    against a PostgreSQL database with the Apache Age extension, via an async
    psycopg connection.

    Attributes:
        pg_connection: An active psycopg async PostgreSQL database connection.
    """

    def __init__(self, pg_connection: AsyncConnection):
        """Initialize the repository with a PostgreSQL connection.

        Args:
            pg_connection: A psycopg async connection object to a PostgreSQL
                database with the Apache Age extension installed.
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
            f"{key}: {cls._age_literal(value)}" for key, value in properties.items()
        ]
        return " {" + ", ".join(entries) + "}"

    @staticmethod
    def _parse_agtype(value: str) -> Any:
        """Parse a raw `agtype` column value into a plain Python value.

        Apache Age returns vertex/edge columns as a JSON object literal suffixed
        with its Cypher type, e.g. `{"id": ..., "label": ..., "properties": {...}}::vertex`
        or `{"id": ..., "start_id": ..., "end_id": ..., "label": ..., "properties": {...}}::edge`.
        Strips a trailing `::vertex`/`::edge` suffix (if present) before parsing
        the remainder as JSON. Scalar columns (e.g. `type(r)`, `label(b)`, `count(*)`)
        carry no such suffix and parse directly into a str/int.

        Args:
            value: The raw string returned by psycopg for an `agtype` column.

        Returns:
            The parsed value: a dict for a vertex/edge, or a scalar for a scalar column.
        """
        text = value
        for suffix in ("::vertex", "::edge"):
            if text.endswith(suffix):
                text = text[: -len(suffix)]
                break
        return json.loads(text)

    async def create_graph(self, graph_name: str) -> str:
        """Create a new Apache Age graph in the database.

        Args:
            graph_name: The name of the graph to create.

        Returns:
            The SQL query string that was executed.

        Raises:
            Exception: If the graph already exists or if the database operation fails.
        """
        query = f"SELECT * FROM ag_catalog.create_graph('{graph_name}');"
        cursor = self.pg_connection.cursor()
        await cursor.execute(query)
        return query

    async def delete_graph(self, graph_name: str) -> str:
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
        cursor = self.pg_connection.cursor()
        await cursor.execute(query)
        return query

    async def graph_exists(self, graph_name: str) -> bool:
        """Check if a graph exists in the database.

        Args:
            graph_name: The name of the graph to check.

        Returns:
            True if the graph exists, False otherwise.
        """
        query = f"SELECT 1 FROM ag_catalog.ag_graph WHERE name = '{graph_name}';"
        cursor = self.pg_connection.cursor()
        await cursor.execute(query)
        result = await cursor.fetchone()
        return result is not None

    async def get_nodes(self, graph_name: str, label: str | None = None) -> str:
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
        cursor = self.pg_connection.cursor()
        await cursor.execute(query)
        return query

    async def create_node(
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
        cursor = self.pg_connection.cursor()
        await cursor.execute(query)
        return query

    async def update_node(
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
            f'SELECT * FROM cypher(\'{graph_name}\', $$ MATCH (n {{id:"{node_id}"}}) '
            f"SET n = n + {props} RETURN n $$) AS (v agtype);"
        )
        cursor = self.pg_connection.cursor()
        await cursor.execute(query)
        return query

    async def delete_node(self, graph_name: str, node_id: str) -> str:
        """Delete a node from the graph.

        Also detaches and deletes all edges connected to this node.

        Args:
            graph_name: The name of the graph.
            node_id: The unique identifier of the node to delete.

        Returns:
            The SQL query string that was executed.
        """
        query = (
            f'SELECT * FROM cypher(\'{graph_name}\', $$ MATCH (n {{id:"{node_id}"}}) '
            "DETACH DELETE n RETURN count(n) $$) AS (count agtype);"
        )
        cursor = self.pg_connection.cursor()
        await cursor.execute(query)
        return query

    async def get_relationships(self, graph_name: str, label: str | None = None) -> str:
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
        cursor = self.pg_connection.cursor()
        await cursor.execute(query)
        return query

    async def get_node_neighbours(
        self,
        graph_name: str,
        node_id: str,
        relationship_labels: list[str] | None = None,
    ) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
        """Fetch a node's neighbours, as (source, relationship, target) triplets.

        Matches the node by its `id` property (the app-level identifier stamped onto
        every vertex by `create_node`), not Apache Age's own internal vertex id.
        Traverses relationships in both directions and, for each one, orients
        source/target using the edge's own `start_id`/`end_id` rather than assuming
        the queried node is always the source. De-duplicates so a single physical
        relationship is never returned twice (Apache Age can surface an undirected
        match twice, once per traversal direction).

        Args:
            graph_name: The name of the graph to query.
            node_id: The `id` property value of the node whose relationships to fetch.
            relationship_labels: Optional relationship labels to filter by. If None
                or empty, all relationship labels are included.

        Returns:
            A list of `(source, relationship, target)` tuples, each a plain dict
            parsed from the vertex/edge `agtype` payload, with no relationship
            repeated.
        """
        id_filter = self._age_properties_literal({"id": node_id})
        label_filter = ""
        if relationship_labels:
            literal_labels = ", ".join(
                self._age_literal(label) for label in relationship_labels
            )
            label_filter = f" WHERE type(r) IN [{literal_labels}]"

        query = (
            f"SELECT * FROM cypher('{graph_name}', $$ "
            f"MATCH (a{id_filter})-[r]-(b){label_filter} "
            "RETURN a, r, b $$) AS (a agtype, r agtype, b agtype);"
        )
        cursor = self.pg_connection.cursor()
        await cursor.execute(query)
        rows = await cursor.fetchall()

        seen_edge_ids: set[Any] = set()
        triplets: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
        for a_raw, r_raw, b_raw in rows:
            a_vertex = self._parse_agtype(a_raw)
            edge = self._parse_agtype(r_raw)
            b_vertex = self._parse_agtype(b_raw)

            edge_id = edge["id"]
            if edge_id in seen_edge_ids:
                continue
            seen_edge_ids.add(edge_id)

            if edge["start_id"] == a_vertex["id"]:
                source, target = a_vertex, b_vertex
            else:
                source, target = b_vertex, a_vertex

            triplets.append((source, edge, target))

        return triplets

    async def get_node_schema(
        self, graph_name: str, node_id: str
    ) -> list[tuple[str, str, str, int]]:
        """Summarize the shape of a node's neighborhood, aggregated by the database.

        Unlike `get_node_neighbours()`, which returns every relationship
        instance along with its neighbor's full properties, this returns only the
        distinct relationship label / neighbor label combinations and how many
        relationships match each. The counting is done by the database, so a
        high-degree node costs a handful of rows rather than one per relationship.

        Runs one query per direction (outgoing, then incoming) rather than a single
        undirected match, so each row's direction is known from the query that
        produced it and no `start_id`/`end_id` comparison is needed. A self-loop
        legitimately appears in both directions.

        Args:
            graph_name: The name of the graph to query.
            node_id: The `id` property value of the node to summarize.

        Returns:
            A list of `(relationship_label, direction, neighbor_label, count)`
            tuples, outgoing entries first then incoming, each group sorted by
            `(relationship_label, neighbor_label)` since the database does not
            guarantee row order.
        """
        id_filter = self._age_properties_literal({"id": node_id})
        cursor = self.pg_connection.cursor()

        entries: list[tuple[str, str, str, int]] = []
        for direction, pattern in (
            ("outgoing", f"MATCH (a{id_filter})-[r]->(b)"),
            ("incoming", f"MATCH (a{id_filter})<-[r]-(b)"),
        ):
            query = (
                f"SELECT * FROM cypher('{graph_name}', $$ "
                f"{pattern} "
                "RETURN type(r), label(b), count(*) $$) "
                "AS (relationship agtype, neighbor_label agtype, count agtype);"
            )
            await cursor.execute(query)
            rows = await cursor.fetchall()
            parsed = [
                (
                    self._parse_agtype(relationship),
                    self._parse_agtype(neighbor_label),
                    self._parse_agtype(count),
                )
                for relationship, neighbor_label, count in rows
            ]
            entries.extend(
                (relationship, direction, neighbor_label, count)
                for relationship, neighbor_label, count in sorted(parsed)
            )

        return entries

    async def search_relationships(
        self,
        graph_name: str,
        label: str,
        source_label: str | None = None,
        target_label: str | None = None,
        source_id: str | None = None,
        target_id: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
        """Search relationships by type, optional endpoint constraints, and property filters.

        Unlike `get_node_neighbours()`, which traverses from one known node in
        both directions, this searches the whole graph by relationship type, so
        `source_id`/`target_id` are optional constraints rather than the anchor
        of the match. Matches the directed pattern relationships are created
        with (`(a)-[r:label]->(b)`, the same orientation `create_relationship()`
        writes), so `source_label`/`source_id` constrain the relationship's
        actual source and `target_label`/`target_id` its actual target — never
        either endpoint interchangeably.

        Args:
            graph_name: The name of the graph to query.
            label: The relationship type to match.
            source_label: Optional label to restrict the source node to.
            target_label: Optional label to restrict the target node to.
            source_id: Optional `id` property value to restrict the source node to.
            target_id: Optional `id` property value to restrict the target node to.
            properties: Optional relationship property filters (exact match on
                each key).

        Returns:
            A list of `(source, relationship, target)` tuples, each a plain
            dict parsed from the vertex/edge `agtype` payload.
        """
        source_label_filter = f":{source_label}" if source_label else ""
        target_label_filter = f":{target_label}" if target_label else ""
        source_id_filter = (
            self._age_properties_literal({"id": source_id}) if source_id else ""
        )
        target_id_filter = (
            self._age_properties_literal({"id": target_id}) if target_id else ""
        )
        properties_filter = self._age_properties_literal(properties or {})

        query = (
            f"SELECT * FROM cypher('{graph_name}', $$ "
            f"MATCH (a{source_label_filter}{source_id_filter})"
            f"-[r:{label}{properties_filter}]->"
            f"(b{target_label_filter}{target_id_filter}) "
            "RETURN a, r, b $$) AS (a agtype, r agtype, b agtype);"
        )
        cursor = self.pg_connection.cursor()
        await cursor.execute(query)
        rows = await cursor.fetchall()

        return [
            (
                self._parse_agtype(a_raw),
                self._parse_agtype(r_raw),
                self._parse_agtype(b_raw),
            )
            for a_raw, r_raw, b_raw in rows
        ]

    async def create_relationship(
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
            f'SELECT * FROM cypher(\'{graph_name}\', $$ MATCH (a {{id:"{source_node_id}"}}), '
            f'(b {{id:"{target_node_id}"}}) CREATE (a)-[:{label}{properties_literal}]->(b) '
            "RETURN a, b $$) AS (a agtype, b agtype);"
        )
        cursor = self.pg_connection.cursor()
        await cursor.execute(query)
        return query

    async def update_relationship(
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
            f'SELECT * FROM cypher(\'{graph_name}\', $$ MATCH (a {{id:"{source_node_id}"}})-[r:{label}]->'
            f'(b {{id:"{target_node_id}"}}) SET r = r + {props} RETURN r $$) AS (v agtype);'
        )
        cursor = self.pg_connection.cursor()
        await cursor.execute(query)
        return query

    async def delete_relationship(
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
            f'SELECT * FROM cypher(\'{graph_name}\', $$ MATCH (a {{id:"{source_node_id}"}})-[r:{label}]->'
            f'(b {{id:"{target_node_id}"}}) DELETE r RETURN count(r) $$) AS (count agtype);'
        )
        cursor = self.pg_connection.cursor()
        await cursor.execute(query)
        return query

    async def commit(self) -> None:
        """Commit the current transaction to the database.

        Only commits if the connection supports the commit method.
        """
        if hasattr(self.pg_connection, "commit"):
            await self.pg_connection.commit()
