from graphrag_apacheage.agent.serializers import relationship_triplet_to_dict


def test_relationship_triplet_to_dict_extracts_node_id_from_properties():
    source = {"id": 1, "label": "Driver", "properties": {"id": "driver-1", "name": "Lewis"}}
    relationship = {"id": 10, "start_id": 1, "end_id": 2, "label": "DRIVES_FOR", "properties": {"season": 2025}}
    target = {"id": 2, "label": "Team", "properties": {"id": "team-1", "name": "Mercedes"}}

    result = relationship_triplet_to_dict(source, relationship, target)

    assert result == {
        "source": {"node_id": "driver-1", "label": "Driver", "properties": {"name": "Lewis"}},
        "relationship": {
            "source_id": "driver-1",
            "target_id": "team-1",
            "label": "DRIVES_FOR",
            "properties": {"season": 2025},
        },
        "target": {"node_id": "team-1", "label": "Team", "properties": {"name": "Mercedes"}},
    }


def test_relationship_triplet_to_dict_handles_missing_properties():
    source = {"id": 1, "label": "Driver", "properties": {"id": "driver-1"}}
    relationship = {"id": 10, "start_id": 1, "end_id": 2, "label": "DRIVES_FOR"}
    target = {"id": 2, "label": "Team", "properties": {"id": "team-1"}}

    result = relationship_triplet_to_dict(source, relationship, target)

    assert result["relationship"]["properties"] == {}
