"""Mapping for the management API-owned `file` table."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from common.models.base import ApiOwnedBase


class File(ApiOwnedBase):
    """Shared mapping for a stored file, independent of what owns it.

    The API owns this table's DDL (EF migration `AddFiles`) and is its only
    writer today: it uploads the content through its storage provider and
    records the object key here. Columns are PascalCase to match EF, like
    `knowledge_base`. `storage_key` is an object key for
    `common.storage.base.StorageService` (ADR-0006), never a path or URL.

    A file belongs to an organization, not to a particular resource. Owners
    link to their files through their own tables (today only
    `common.models.knowledge_base_file.KnowledgeBaseFile`), so this module is
    a leaf with no relationships. The API's FK from `OrganizationId` to
    `organization` is not mapped here, because Python does not map `organization`.
    """

    __tablename__ = "file"

    id: Mapped[str] = mapped_column("Id", String(255), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        "OrganizationId", String(255), nullable=False, index=True
    )
    file_name: Mapped[str] = mapped_column("FileName", String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(
        "ContentType", String(255), nullable=False
    )
    size: Mapped[int] = mapped_column("Size", BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(
        "StorageKey", String(1024), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column("Status", String(32), nullable=False)
    created_at_utc: Mapped[datetime] = mapped_column(
        "CreatedAtUtc", DateTime(timezone=True), nullable=False
    )
    updated_at_utc: Mapped[datetime] = mapped_column(
        "UpdatedAtUtc", DateTime(timezone=True), nullable=False
    )


__all__ = ["File"]
