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
    assert "SET n = n +" in query
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
    assert "SET r = r +" in query
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
