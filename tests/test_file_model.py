from datetime import UTC, datetime

from common.models.base import ApiOwnedBase, Base
from common.models.file import File
from common.models.knowledge_base import KnowledgeBase
from common.models.knowledge_base_file import KnowledgeBaseFile
from common.schemas.file import FileDTO, FileStatus
from common.schemas.knowledge_base import KnowledgeBaseRecordDTO


def _file(file_id: str, created_at: datetime) -> File:
    return File(
        id=file_id,
        organization_id="org-1",
        file_name=f"{file_id}.pdf",
        content_type="application/pdf",
        size=42,
        storage_key=f"organizations/org-1/files/{file_id}/content",
        status="uploaded",
        created_at_utc=created_at,
        updated_at_utc=created_at,
    )


def test_file_mapping_matches_api_columns_without_joining_common_metadata():
    table = File.__table__

    assert table.name == "file"
    assert list(table.c.keys()) == [
        "Id",
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
    assert table.c.StorageKey.unique
    # Owner-agnostic: no column ties a file to a knowledge base.
    assert not table.foreign_keys


def test_knowledge_base_file_link_matches_the_api():
    knowledge_base_file = KnowledgeBaseFile.__table__

    assert knowledge_base_file.name == "knowledge_base_file"
    assert list(knowledge_base_file.c.keys()) == ["FileId", "KnowledgeBaseId"]
    assert knowledge_base_file.metadata is ApiOwnedBase.metadata
    assert knowledge_base_file.name not in Base.metadata.tables
    assert [column.name for column in knowledge_base_file.primary_key] == ["FileId"]
    targets = {
        fk.parent.name: (fk.target_fullname, fk.ondelete)
        for fk in knowledge_base_file.foreign_keys
    }
    assert targets == {
        "FileId": ("file.Id", "CASCADE"),
        "KnowledgeBaseId": ("knowledge_base.Id", "CASCADE"),
    }


def test_file_module_imports_and_configures_on_its_own():
    # File and KnowledgeBaseFile are leaves. Configuring mappers must not need KnowledgeBase to
    # have been imported, which is why neither has a relationship to it.
    import subprocess
    import sys

    subprocess.run(
        [
            sys.executable,
            "-c",
            "from common.models.file import File\n"
            "from common.models.knowledge_base_file import KnowledgeBaseFile\n"
            "from sqlalchemy.orm import configure_mappers\n"
            "configure_mappers()",
        ],
        check=True,
    )


def test_file_dto_reads_the_orm_model():
    now = datetime(2026, 9, 25, tzinfo=UTC)

    dto = FileDTO.model_validate(_file("file-1", now))

    assert dto.id == "file-1"
    assert dto.organization_id == "org-1"
    assert dto.storage_key == "organizations/org-1/files/file-1/content"
    assert dto.status is FileStatus.UPLOADED
    assert dto.size == 42


def test_knowledge_base_record_dto_carries_the_knowledge_base_files():
    now = datetime(2026, 9, 25, tzinfo=UTC)
    row = KnowledgeBase(
        id="kb-1",
        organization_id="org-1",
        name="F1",
        state="draft",
        created_at_utc=now,
        updated_at_utc=now,
    )
    row.files.append(_file("file-1", now))

    dto = KnowledgeBaseRecordDTO.model_validate(row)

    assert [file.id for file in dto.files] == ["file-1"]
    assert isinstance(dto.files[0], FileDTO)


def test_knowledge_base_record_dto_defaults_to_no_files():
    now = datetime(2026, 9, 25, tzinfo=UTC)

    dto = KnowledgeBaseRecordDTO(
        id="kb-1",
        organization_id="org-1",
        name="F1",
        state="draft",
        created_at_utc=now,
        updated_at_utc=now,
    )

    assert dto.files == []
