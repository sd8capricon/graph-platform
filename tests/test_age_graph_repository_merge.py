"""Tests for AgeGraphRepository's idempotent MERGE write path (ADR-0005)."""

import pytest

from common.repositories.age_graph_repository import AgeGraphRepository


class _RecordingCursor:
    def __init__(self):
        self.queries = []

    async def execute(self, query):
        self.queries.append(query)


class _RecordingConnection:
    def __init__(self):
        self.cursor_obj = _RecordingCursor()

    def cursor(self):
        return self.cursor_obj


async def test_merge_node_emits_merge_on_id_and_set():
    connection = _RecordingConnection()
    repository = AgeGraphRepository(connection)

    query = await repository.merge_node(
        "demo_graph", "Driver", {"id": "driver-1", "name": "Max Verstappen"}
    )

    assert "MERGE (n:Driver {id: 'driver-1'})" in query
    assert "SET n +=" in query
    assert "{id: 'driver-1', name: 'Max Verstappen'}" in query
    assert "CREATE" not in query


async def test_merge_node_requires_an_id_property():
    repository = AgeGraphRepository(_RecordingConnection())

    with pytest.raises(ValueError):
        await repository.merge_node("demo_graph", "Driver", {"name": "no id"})


async def test_merge_node_rejects_unsafe_labels():
    repository = AgeGraphRepository(_RecordingConnection())

    with pytest.raises(ValueError):
        await repository.merge_node(
            "demo_graph", "Driver) DETACH DELETE (a", {"id": "x"}
        )


async def test_merge_relationship_uses_relationship_id_as_identity():
    connection = _RecordingConnection()
    repository = AgeGraphRepository(connection)

    query = await repository.merge_relationship(
        "demo_graph",
        "driver-1",
        "team-1",
        "DRIVES_FOR",
        {"relationship_id": "rel-1", "season": 2024},
    )

    assert "MERGE (a)-[r:DRIVES_FOR {relationship_id: 'rel-1'}]->(b)" in query
    assert "SET r +=" in query
    assert "{relationship_id: 'rel-1', season: 2024}" in query
    assert "CREATE" not in query


async def test_merge_relationship_without_id_collapses_on_type():
    connection = _RecordingConnection()
    repository = AgeGraphRepository(connection)

    query = await repository.merge_relationship(
        "demo_graph", "a", "b", "KNOWS", {"since": 2020}
    )

    assert "MERGE (a)-[r:KNOWS]->(b)" in query


async def test_merge_relationship_rejects_unsafe_labels():
    repository = AgeGraphRepository(_RecordingConnection())

    with pytest.raises(ValueError):
        await repository.merge_relationship("demo_graph", "a", "b", "", {})


async def test_update_node_uses_compound_set_operator():
    connection = _RecordingConnection()
    repository = AgeGraphRepository(connection)

    query = await repository.update_node(
        "demo_graph", "driver-1", {"name": "Max Verstappen"}
    )

    assert "SET n +=" in query
    assert "SET n = n +" not in query
    assert "{name: 'Max Verstappen'}" in query


async def test_update_relationship_uses_compound_set_operator():
    connection = _RecordingConnection()
    repository = AgeGraphRepository(connection)

    query = await repository.update_relationship(
        "demo_graph", "driver-1", "team-1", "DRIVES_FOR", {"season": 2024}
    )

    assert "SET r +=" in query
    assert "SET r = r +" not in query
    assert "{season: 2024}" in query


async def test_merge_node_claims_the_node_for_its_knowledge_base_once():
    repository = AgeGraphRepository(_RecordingConnection())

    query = await repository.merge_node(
        "demo_graph",
        "Driver",
        {"id": "driver-1", "knowledge_base_ids": ["forged"]},
        knowledge_base_id="kb-1",
    )

    # The append is guarded so a replayed merge does not duplicate the id.
    assert (
        "SET n.knowledge_base_ids = CASE WHEN 'kb-1' IN coalesce(n.knowledge_base_ids, []) "
        "THEN n.knowledge_base_ids ELSE coalesce(n.knowledge_base_ids, []) + ['kb-1'] END"
    ) in query
    # The contributor list belongs to the repository; a caller's value is ignored.
    assert "forged" not in query


async def test_merge_node_without_a_knowledge_base_leaves_no_claim():
    repository = AgeGraphRepository(_RecordingConnection())

    query = await repository.merge_node("demo_graph", "Driver", {"id": "driver-1"})

    assert "knowledge_base_ids" not in query


async def test_merge_relationship_claims_the_edge_and_tolerates_no_properties():
    repository = AgeGraphRepository(_RecordingConnection())

    query = await repository.merge_relationship(
        "demo_graph", "a", "b", "KNOWS", {}, knowledge_base_id="kb-1"
    )

    # An empty `SET r +=` is a Cypher syntax error, so it is omitted.
    assert "SET r +=" not in query
    assert "MERGE (a)-[r:KNOWS]->(b) SET r.knowledge_base_ids = CASE" in query


async def test_release_knowledge_base_releases_edges_then_nodes_in_separate_statements():
    connection = _RecordingConnection()
    repository = AgeGraphRepository(connection)

    queries = await repository.release_knowledge_base("demo_graph", "kb-1")

    assert queries == connection.cursor_obj.queries
    assert len(queries) == 4
    release_edges, delete_edges, release_nodes, delete_nodes = queries
    assert (
        "MATCH ()-[r]->() WHERE 'kb-1' IN r.knowledge_base_ids "
        "SET r.knowledge_base_ids = [x IN r.knowledge_base_ids WHERE x <> 'kb-1']"
    ) in release_edges
    assert "WHERE r.knowledge_base_ids = [] DELETE r" in delete_edges
    assert (
        "MATCH (n) WHERE 'kb-1' IN n.knowledge_base_ids "
        "SET n.knowledge_base_ids = [x IN n.knowledge_base_ids WHERE x <> 'kb-1']"
    ) in release_nodes
    assert "WHERE n.knowledge_base_ids = [] DETACH DELETE n" in delete_nodes
    # Apache Age 1.8 silently skips a SET ... WITH ... DELETE chain.
    assert not any("WITH" in query for query in queries)


async def test_release_knowledge_base_requires_an_id():
    repository = AgeGraphRepository(_RecordingConnection())

    with pytest.raises(ValueError):
        await repository.release_knowledge_base("demo_graph", "")


async def test_delete_unclaimed_nodes_only_matches_nodes_without_a_claim():
    connection = _RecordingConnection()
    repository = AgeGraphRepository(connection)

    query = await repository.delete_unclaimed_nodes("demo_graph", ["d1", "it's"])

    assert (
        "MATCH (n) WHERE n.id IN ['d1', 'it\\'s'] AND n.knowledge_base_ids IS NULL "
        "DETACH DELETE n"
    ) in query
    assert await repository.delete_unclaimed_nodes("demo_graph", []) is None
    assert connection.cursor_obj.queries == [query]
