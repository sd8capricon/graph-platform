from graphrag_apacheage.agent.serializers import AgentSerializer


def test_node_neighbours_to_dict_groups_node_once_with_direction_per_relationship():
    triplets = [
        (
            {"id": 1, "label": "Driver", "properties": {"id": "driver-1", "name": "Lewis"}},
            {"id": 10, "start_id": 1, "end_id": 2, "label": "DRIVES_FOR", "properties": {"season": 2025}},
            {"id": 2, "label": "Team", "properties": {"id": "team-1", "name": "Mercedes"}},
        ),
        (
            {"id": 3, "label": "Team", "properties": {"id": "team-2", "name": "Ferrari"}},
            {"id": 11, "start_id": 3, "end_id": 1, "label": "SPONSORS", "properties": {}},
            {"id": 1, "label": "Driver", "properties": {"id": "driver-1", "name": "Lewis"}},
        ),
    ]

    result = AgentSerializer.node_neighbours_to_dict("driver-1", "Driver", {"name": "Lewis"}, triplets)

    assert result == {
        "node": {"node_id": "driver-1", "label": "Driver", "properties": {"name": "Lewis"}},
        "relationships": [
            {
                "label": "DRIVES_FOR",
                "properties": {"season": 2025},
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


def test_node_neighbours_to_dict_handles_missing_properties():
    triplets = [
        (
            {"id": 1, "label": "Driver", "properties": {"id": "driver-1"}},
            {"id": 10, "start_id": 1, "end_id": 2, "label": "DRIVES_FOR"},
            {"id": 2, "label": "Team", "properties": {"id": "team-1"}},
        )
    ]

    result = AgentSerializer.node_neighbours_to_dict("driver-1", "Driver", {}, triplets)

    assert result["relationships"][0]["properties"] == {}


def test_node_neighbours_to_dict_returns_empty_relationships_list_when_no_triplets():
    result = AgentSerializer.node_neighbours_to_dict("driver-1", "Driver", {}, [])

    assert result == {
        "node": {"node_id": "driver-1", "label": "Driver", "properties": {}},
        "relationships": [],
    }


def test_node_schema_to_dict_groups_entries_under_the_node_once():
    entries = [
        ("RACED_FOR", "outgoing", "Team", 3),
        ("SPONSORS", "incoming", "Sponsor", 1),
    ]

    result = AgentSerializer.node_schema_to_dict(
        "driver-1",
        "Driver",
        entries,
        node_properties=["name", "number"],
        relationship_properties={"RACED_FOR": ["season"]},
        neighbor_properties={"Team": ["name"], "Sponsor": ["name", "tier"]},
    )

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


def test_node_schema_to_dict_defaults_properties_to_empty_when_not_provided():
    entries = [("RACED_FOR", "outgoing", "Team", 3)]

    result = AgentSerializer.node_schema_to_dict("driver-1", "Driver", entries)

    assert result == {
        "node": {"node_id": "driver-1", "label": "Driver", "properties": []},
        "relationships": [
            {
                "label": "RACED_FOR",
                "properties": [],
                "direction": "outgoing",
                "neighbor_label": "Team",
                "neighbor_properties": [],
                "count": 3,
            },
        ],
    }


def test_node_schema_to_dict_returns_empty_relationships_list_when_no_entries():
    result = AgentSerializer.node_schema_to_dict("driver-1", "Driver", [])

    assert result == {
        "node": {"node_id": "driver-1", "label": "Driver", "properties": []},
        "relationships": [],
    }
