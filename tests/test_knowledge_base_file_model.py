from datetime import UTC, datetime

from common.models.base import ApiOwnedBase, Base
from common.models.knowledge_base import KnowledgeBase
from common.models.knowledge_base_file import KnowledgeBaseFile
from common.schemas.knowledge_base import KnowledgeBaseRecordDTO
from common.schemas.knowledge_base_file import (
    KnowledgeBaseFileDTO,
    KnowledgeBaseFileStatus,
)


def _file(file_id: str, created_at: datetime) -> KnowledgeBaseFile:
    return KnowledgeBaseFile(
        id=file_id,
        knowledge_base_id="kb-1",
        organization_id="org-1",
        file_name=f"{file_id}.pdf",
        content_type="application/pdf",
        size=42,
        storage_key=f"organizations/org-1/knowledge-bases/kb-1/files/{file_id}/content",
        status="uploaded",
        created_at_utc=created_at,
        updated_at_utc=created_at,
    )


def test_knowledge_base_file_mapping_matches_api_columns_without_joining_common_metadata():
    table = KnowledgeBaseFile.__table__

    assert table.name == "knowledge_base_file"
    assert list(table.c.keys()) == [
        "Id",
        "KnowledgeBaseId",
        "OrganizationId",
        "FileName",
        "ContentType",
        "Size",
        "StorageKey",
        "Status",
        "CreatedAtUtc",
        "UpdatedAtUtc",
    ]
    assert table.metadata is ApiOwnedBase.metadata
    assert table.name not in Base.metadata.tables

    (foreign_key,) = table.c.KnowledgeBaseId.foreign_keys
    assert foreign_key.target_fullname == "knowledge_base.Id"
    assert foreign_key.ondelete == "CASCADE"
    assert table.c.StorageKey.unique


def test_knowledge_base_file_dto_reads_the_orm_model():
    now = datetime(2026, 9, 25, tzinfo=UTC)

    dto = KnowledgeBaseFileDTO.model_validate(_file("file-1", now))

    assert dto.id == "file-1"
    assert dto.knowledge_base_id == "kb-1"
    assert dto.storage_key.endswith("/files/file-1/content")
    assert dto.status is KnowledgeBaseFileStatus.UPLOADED
    assert dto.size == 42


def test_knowledge_base_record_dto_carries_the_knowledge_base_files():
    now = datetime(2026, 9, 25, tzinfo=UTC)
    row = KnowledgeBase(
        id="kb-1",
        organization_id="org-1",
        name="F1",
        data='{"nodes": []}',
        state="draft",
        created_at_utc=now,
        updated_at_utc=now,
    )
    row.files.append(_file("file-1", now))

    dto = KnowledgeBaseRecordDTO.model_validate(row)

    assert [file.id for file in dto.files] == ["file-1"]
    assert isinstance(dto.files[0], KnowledgeBaseFileDTO)


def test_knowledge_base_record_dto_defaults_to_no_files():
    now = datetime(2026, 9, 25, tzinfo=UTC)

    dto = KnowledgeBaseRecordDTO(
        id="kb-1",
        organization_id="org-1",
        name="F1",
        data="{}",
        state="draft",
        created_at_utc=now,
        updated_at_utc=now,
    )

    assert dto.files == []
