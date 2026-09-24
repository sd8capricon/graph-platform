"""ORM model for the API-owned `index_file` table.

One row per file within an `index_job`. Phase 1 of ADR-0005 treats a whole
knowledge base as one file; the per-file fan-out is Phase 2.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ingestion_worker.models.base import IndexJobBase
from ingestion_worker.models.index_job import IndexJob  # noqa: F401 - FK target


class IndexFile(IndexJobBase):
    """One API-created source file within an ingestion job."""

    __tablename__ = "index_file"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    index_job_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("index_job.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


__all__ = ["IndexFile"]
