"""Mapping for the management API-owned `knowledge_base` table."""

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from common.models.base import ApiOwnedBase


class KnowledgeBase(ApiOwnedBase):
    """Shared mapping for a knowledge base resource stored by the API.

    The API owns this table's DDL. Its PascalCase column names match the EF
    migration; the separate `ApiOwnedBase` metadata keeps it out of the Python
    services' normal `Base.metadata.create_all()` calls. The ingestion worker
    uses this mapping for persistence and transfers resource data as
    `KnowledgeBaseRecordDTO`.
    """

    __tablename__ = "knowledge_base"

    id: Mapped[str] = mapped_column("Id", String(255), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        "OrganizationId", String(255), nullable=False
    )
    name: Mapped[str] = mapped_column("Name", String(255), nullable=False)
    data: Mapped[str] = mapped_column("Data", Text, nullable=False)
    state: Mapped[str] = mapped_column("State", String(32), nullable=False)
    created_at_utc: Mapped[datetime] = mapped_column(
        "CreatedAtUtc", DateTime(timezone=True), nullable=False
    )
    updated_at_utc: Mapped[datetime] = mapped_column(
        "UpdatedAtUtc", DateTime(timezone=True), nullable=False
    )


__all__ = ["KnowledgeBase"]
