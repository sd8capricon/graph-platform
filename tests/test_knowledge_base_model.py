from common.models.base import ApiOwnedBase, Base
from common.models.knowledge_base import KnowledgeBase


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
