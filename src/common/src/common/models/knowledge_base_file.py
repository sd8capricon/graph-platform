"""Mapping for the management API-owned `knowledge_base_file` table."""

from datetime import datetime
from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from common.models.base import ApiOwnedBase


class KnowledgeBaseFile(ApiOwnedBase):
    """Shared mapping for a file uploaded to a knowledge base through the API.

    The API owns this table's DDL (EF migration `AddKnowledgeBaseFiles`) and is
    its only writer today: it uploads the content through its storage provider
    and records the object key here. Columns are PascalCase to match EF, like
    `knowledge_base`. `storage_key` is an object key for
    `common.storage.base.StorageService` (ADR-0006), never a path or URL.

    This module is a leaf and has no relationship back to `KnowledgeBase`: the
    parent's one-directional `KnowledgeBase.files` is the only navigation. A
    string-form back-reference would fail mapper configuration whenever this
    module is imported without `common.models.knowledge_base`.
    """

    __tablename__ = "knowledge_base_file"

    id: Mapped[str] = mapped_column("Id", String(255), primary_key=True)
    knowledge_base_id: Mapped[str] = mapped_column(
        "KnowledgeBaseId",
        String(255),
        ForeignKey("knowledge_base.Id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
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


__all__ = ["KnowledgeBaseFile"]
