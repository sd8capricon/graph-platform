"""Mapping for the management API-owned `knowledge_base_file` link table."""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from common.models.base import ApiOwnedBase


class KnowledgeBaseFile(ApiOwnedBase):
    """Links a `common.models.file.File` to the knowledge base that owns it.

    The API owns this table's DDL (EF migration `AddFiles`). Its PascalCase
    column names match EF. `file_id` is the primary key, as in the API, so a
    file belongs to at most one knowledge base. Both foreign keys cascade.

    `KnowledgeBase.files` reads through this table as its `secondary`. This
    class has no relationships of its own, so it stays a leaf that configures
    without `KnowledgeBase` or `File` having been imported.
    """

    __tablename__ = "knowledge_base_file"

    file_id: Mapped[str] = mapped_column(
        "FileId",
        String(255),
        ForeignKey("file.Id", ondelete="CASCADE"),
        primary_key=True,
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        "KnowledgeBaseId",
        String(255),
        ForeignKey("knowledge_base.Id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


__all__ = ["KnowledgeBaseFile"]
