from unittest.mock import MagicMock

import pytest
from langchain.tools import ToolRuntime
from sqlalchemy.ext.asyncio import AsyncSession

from graphrag_apacheage.agent.context import AgentContext
from graphrag_apacheage.agent.tools import get_node_relationships, get_node_schema
from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository
from graphrag_apacheage.schemas.knowledge_base import KnowledgeNode


def _context(repository) -> AgentContext:
    return AgentContext(
        graph_name="demo_graph",
        session=MagicMock(spec=AsyncSession),
        repository=repository,
    )


def _runtime(context: AgentContext) -> ToolRuntime:
    return ToolRuntime(
        state=None,
        context=context,
        config={},
        stream_writer=None,
        tool_call_id=None,
        store=None,
    )


async def test_get_node_relationships_groups_relationships_under_the_node_once():
    repository = MagicMock(spec=AgeGraphRepository)
    repository.get_node_relationships.return_value = [
        (
            {"id": 1, "label": "Driver", "properties": {"id": "driver-1", "name": "Lewis"}},
            {"id": 10, "start_id": 1, "end_id": 2, "label": "DRIVES_FOR", "properties": {}},
            {"id": 2, "label": "Team", "properties": {"id": "team-1", "name": "Mercedes"}},
        ),
        (
            {"id": 3, "label": "Team", "properties": {"id": "team-2", "name": "Ferrari"}},
            {"id": 11, "start_id": 3, "end_id": 1, "label": "SPONSORS", "properties": {}},
            {"id": 1, "label": "Driver", "properties": {"id": "driver-1", "name": "Lewis"}},
        ),
    ]
    node = KnowledgeNode(id="driver-1", label="Driver", properties={"name": "Lewis"})

    result = await get_node_relationships.coroutine(
        node=node, runtime=_runtime(_context(repository)), relationships=None
    )

    repository.get_node_relationships.assert_called_once_with("demo_graph", "driver-1", None)
    assert result == {
        "node": {"node_id": "driver-1", "label": "Driver", "properties": {"name": "Lewis"}},
        "relationships": [
            {
                "label": "DRIVES_FOR",
                "properties": {},
                "direction": "outgoing",
                "neighbor": {"node_id": "team-1", "label": "Team", "properties": {"name": "Mercedes"}},
            },
            {
                "label": "SPONSORS",
                "properties": {},
                "direction": "incoming",
                "neighbor": {"node_id": "team-2", "label": "Team", "properties": {"name": "Ferrari"}},
            },
        ],
    }


async def test_get_node_relationships_passes_relationship_label_filter_through():
    repository = MagicMock(spec=AgeGraphRepository)
    repository.get_node_relationships.return_value = []
    node = KnowledgeNode(id="driver-1", label="Driver")

    await get_node_relationships.coroutine(
        node=node, runtime=_runtime(_context(repository)), relationships=["DRIVES_FOR"]
    )

    repository.get_node_relationships.assert_called_once_with(
        "demo_graph", "driver-1", ["DRIVES_FOR"]
    )


async def test_get_node_relationships_raises_when_node_has_no_id():
    node = KnowledgeNode.model_construct(id=None, label="Driver", properties={})

    with pytest.raises(ValueError, match="node.id is required"):
        await get_node_relationships.coroutine(
            node=node,
            runtime=_runtime(_context(MagicMock(spec=AgeGraphRepository))),
            relationships=None,
        )


async def test_get_node_schema_returns_neighborhood_shape_grouped_under_the_node():
    repository = MagicMock(spec=AgeGraphRepository)
    repository.get_node_schema.return_value = [
        ("RACED_FOR", "outgoing", "Team", 3),
        ("SPONSORS", "incoming", "Sponsor", 1),
    ]
    node = KnowledgeNode(id="driver-1", label="Driver", properties={"name": "Lewis"})

    result = await get_node_schema.coroutine(
        node=node, runtime=_runtime(_context(repository))
    )

    repository.get_node_schema.assert_called_once_with("demo_graph", "driver-1")
    assert result == {
        "node": {"node_id": "driver-1", "label": "Driver"},
        "relationships": [
            {
                "label": "RACED_FOR",
                "direction": "outgoing",
                "neighbor_label": "Team",
                "count": 3,
            },
            {
                "label": "SPONSORS",
                "direction": "incoming",
                "neighbor_label": "Sponsor",
                "count": 1,
            },
        ],
    }


async def test_get_node_schema_raises_when_node_has_no_id():
    node = KnowledgeNode.model_construct(id=None, label="Driver", properties={})

    with pytest.raises(ValueError, match="node.id is required"):
        await get_node_schema.coroutine(
            node=node, runtime=_runtime(_context(MagicMock(spec=AgeGraphRepository)))
        )
