from common.models.base import ApiOwnedBase, Base
from common.models.knowledge_base import KnowledgeBase
from common.schemas.knowledge_base import KnowledgeBaseRecordDTO


def test_knowledge_base_mapping_matches_api_columns_without_joining_common_metadata():
    table = KnowledgeBase.__table__

    assert table.name == "knowledge_base"
    assert list(table.c.keys()) == [
        "Id",
        "OrganizationId",
        "Name",
        "Data",
        "State",
        "CreatedAtUtc",
        "UpdatedAtUtc",
    ]
    assert table.metadata is ApiOwnedBase.metadata
    assert table.name not in Base.metadata.tables


def test_knowledge_base_record_dto_is_separate_from_the_graph_payload_schema():
    assert "data" in KnowledgeBaseRecordDTO.model_fields
    assert "nodes" not in KnowledgeBaseRecordDTO.model_fields
