"""Core definition of the API-owned `index_file` table.

One row per file within an `index_job`. Phase 1 of ADR-0005 treats a whole
knowledge base as one file; the per-file fan-out is Phase 2. Importing this
module registers its foreign key's target (`index_job`) on the shared metadata.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Table, Text

from ingestion_worker.models.base import IndexJobMetadata
from ingestion_worker.models.index_job import index_job  # noqa: F401 - FK target

index_file = Table(
    "index_file",
    IndexJobMetadata,
    Column("id", String(255), primary_key=True),
    Column(
        "index_job_id",
        String(255),
        ForeignKey("index_job.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("file_id", String(255), nullable=False),
    Column("status", String(32), nullable=False),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("error", Text, nullable=True),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
)

__all__ = ["index_file"]