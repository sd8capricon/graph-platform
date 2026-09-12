from unittest.mock import MagicMock

import pytest
from langchain.tools import ToolRuntime
from sqlalchemy.ext.asyncio import AsyncSession

from graphrag_apacheage.agent.context import AgentContext
from graphrag_apacheage.agent.models import NodeRef
from graphrag_apacheage.agent.tools import (
    get_node_neighbours,
    get_node_schema,
    get_relationship,
    search_entities,
    search_schema_registry,
)
from graphrag_apacheage.models.graph_schema_registry import (
    GraphSchemaRegistry,
    SchemaType,
)
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


async def test_get_node_neighbours_groups_relationships_under_the_node_once():
    repository = MagicMock(spec=AgeGraphRepository)
    repository.get_node_neighbours.return_value = [
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

    result = await get_node_neighbours.coroutine(
        node=node, runtime=_runtime(_context(repository)), relationships=None
    )

    repository.get_node_neighbours.assert_called_once_with("demo_graph", "driver-1", None)
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


async def test_get_node_neighbours_passes_relationship_label_filter_through():
    repository = MagicMock(spec=AgeGraphRepository)
    repository.get_node_neighbours.return_value = []
    node = KnowledgeNode(id="driver-1", label="Driver")

    await get_node_neighbours.coroutine(
        node=node, runtime=_runtime(_context(repository)), relationships=["DRIVES_FOR"]
    )

    repository.get_node_neighbours.assert_called_once_with(
        "demo_graph", "driver-1", ["DRIVES_FOR"]
    )


async def test_get_node_neighbours_raises_when_node_has_no_id():
    node = KnowledgeNode.model_construct(id=None, label="Driver", properties={})

    with pytest.raises(ValueError, match="node.id is required"):
        await get_node_neighbours.coroutine(
            node=node,
            runtime=_runtime(_context(MagicMock(spec=AgeGraphRepository))),
            relationships=None,
        )


async def test_get_node_schema_returns_neighborhood_shape_grouped_under_the_node(
    monkeypatch,
):
    repository = MagicMock(spec=AgeGraphRepository)
    repository.get_node_schema.return_value = [
        ("RACED_FOR", "outgoing", "Team", 3),
        ("SPONSORS", "incoming", "Sponsor", 1),
    ]
    node = NodeRef(id="driver-1", label="Driver")

    properties_by_type = {
        SchemaType.NODE: {
            "Driver": ["name", "number"],
            "Team": ["name"],
            "Sponsor": ["name", "tier"],
        },
        SchemaType.RELATIONSHIP: {"RACED_FOR": ["season"], "SPONSORS": []},
    }

    async def fake_get_properties_by_name(session, graph_name, names, type=None):
        available = properties_by_type[type]
        return {name: available[name] for name in names if name in available}

    monkeypatch.setattr(
        GraphSchemaRegistry, "get_properties_by_name", fake_get_properties_by_name
    )

    result = await get_node_schema.coroutine(
        node=node, runtime=_runtime(_context(repository))
    )

    repository.get_node_schema.assert_called_once_with("demo_graph", "driver-1")
    assert result == {
        "node": {
            "node_id": "driver-1",
            "label": "Driver",
            "properties": ["name", "number"],
        },
        "relationships": [
            {
                "label": "RACED_FOR",
                "properties": ["season"],
                "direction": "outgoing",
                "neighbor_label": "Team",
                "neighbor_properties": ["name"],
                "count": 3,
            },
            {
                "label": "SPONSORS",
                "properties": [],
                "direction": "incoming",
                "neighbor_label": "Sponsor",
                "neighbor_properties": ["name", "tier"],
                "count": 1,
            },
        ],
    }


async def test_get_node_schema_returns_label_schema_when_id_is_omitted(monkeypatch):
    repository = MagicMock(spec=AgeGraphRepository)
    repository.get_label_schema.return_value = [
        ("RACED_FOR", "outgoing", "Team", 20),
        ("RACED_FOR", "outgoing", "Academy", 4),
    ]
    node = NodeRef(label="Driver")

    properties_by_type = {
        SchemaType.NODE: {
            "Driver": ["name", "number"],
            "Team": ["name"],
            "Academy": ["name"],
        },
        SchemaType.RELATIONSHIP: {"RACED_FOR": ["season"]},
    }

    async def fake_get_properties_by_name(session, graph_name, names, type=None):
        available = properties_by_type[type]
        return {name: available[name] for name in names if name in available}

    monkeypatch.setattr(
        GraphSchemaRegistry, "get_properties_by_name", fake_get_properties_by_name
    )

    result = await get_node_schema.coroutine(
        node=node, runtime=_runtime(_context(repository))
    )

    repository.get_label_schema.assert_called_once_with("demo_graph", "Driver")
    repository.get_node_schema.assert_not_called()
    # No `node_id` key at all in label mode, not `node_id: None`.
    assert result["node"] == {"label": "Driver", "properties": ["name", "number"]}
    assert [entry["neighbor_label"] for entry in result["relationships"]] == [
        "Team",
        "Academy",
    ]
    assert result["relationships"][0]["neighbor_properties"] == ["name"]


@pytest.mark.parametrize("label", ["", "   "])
async def test_get_node_schema_raises_on_empty_label(label):
    repository = MagicMock(spec=AgeGraphRepository)

    with pytest.raises(ValueError, match="node.label is required"):
        await get_node_schema.coroutine(
            node=NodeRef(label=label), runtime=_runtime(_context(repository))
        )
    repository.get_label_schema.assert_not_called()


@pytest.mark.parametrize("node_id", ["", "   "])
async def test_get_node_schema_raises_on_blank_id(node_id):
    """A blank `id` is a malformed instance reference, not a request for the
    label schema — omitting the field entirely is how you ask for that."""
    repository = MagicMock(spec=AgeGraphRepository)
    node = NodeRef(id=node_id, label="Driver")

    with pytest.raises(ValueError, match="node.id must not be blank"):
        await get_node_schema.coroutine(
            node=node, runtime=_runtime(_context(repository))
        )
    repository.get_node_schema.assert_not_called()
    repository.get_label_schema.assert_not_called()


def test_node_ref_id_is_optional_but_never_generated():
    """`NodeRef.id` is optional (omitting it selects `get_node_schema`'s label
    mode) but, unlike `KnowledgeNode.id`, is never auto-generated — an omitted
    `id` stays `None` rather than becoming a UUID that matches nothing in the
    graph."""
    assert NodeRef(label="Driver").id is None
    assert KnowledgeNode(label="Driver").id is not None


async def test_get_relationship_reshapes_matches_via_serializer():
    repository = MagicMock(spec=AgeGraphRepository)
    repository.search_relationships.return_value = [
        (
            {"id": 1, "label": "Driver", "properties": {"id": "driver-1", "name": "Lewis"}},
            {"id": 10, "start_id": 1, "end_id": 2, "label": "DRIVES_FOR", "properties": {"season": 2025}},
            {"id": 2, "label": "Team", "properties": {"id": "team-1", "name": "Mercedes"}},
        ),
    ]

    result = await get_relationship.coroutine(
        relationship="DRIVES_FOR",
        runtime=_runtime(_context(repository)),
        source_label="Driver",
        target_label="Team",
        source_id="driver-1",
        target_id="team-1",
        properties={"season": 2025},
    )

    repository.search_relationships.assert_called_once_with(
        "demo_graph",
        "DRIVES_FOR",
        source_label="Driver",
        target_label="Team",
        source_id="driver-1",
        target_id="team-1",
        properties={"season": 2025},
    )
    assert result == [
        {
            "source": {"node_id": "driver-1", "label": "Driver", "properties": {"name": "Lewis"}},
            "relationship": {"label": "DRIVES_FOR", "properties": {"season": 2025}},
            "target": {"node_id": "team-1", "label": "Team", "properties": {"name": "Mercedes"}},
        },
    ]


@pytest.mark.parametrize("relationship", ["", "   "])
async def test_get_relationship_raises_on_empty_relationship_label(relationship):
    with pytest.raises(ValueError, match="relationship must not be empty"):
        await get_relationship.coroutine(
            relationship=relationship,
            runtime=_runtime(_context(MagicMock(spec=AgeGraphRepository))),
        )


@pytest.mark.parametrize("query", ["", "   "])
async def test_search_schema_registry_raises_on_empty_query(query):
    with pytest.raises(ValueError, match="query must not be empty"):
        await search_schema_registry.coroutine(
            query=query,
            runtime=_runtime(_context(MagicMock(spec=AgeGraphRepository))),
        )


@pytest.mark.parametrize("query", ["", "   "])
async def test_search_entities_raises_on_empty_query(query):
    with pytest.raises(ValueError, match="query must not be empty"):
        await search_entities.coroutine(
            query=query,
            runtime=_runtime(_context(MagicMock(spec=AgeGraphRepository))),
            labels=None,
        )
