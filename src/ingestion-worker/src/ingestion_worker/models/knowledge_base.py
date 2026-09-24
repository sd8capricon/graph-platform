"""Read-only Core definition of the API-owned `knowledge_base` table.

The worker reads the graph JSON from `Data` by id (and flips the coarse `State`
column on completion). Column names are the EF-default PascalCase names from the
existing migration (`20260924140542_AddKnowledgeBases.cs`), not snake_case.
"""

from sqlalchemy import Column, DateTime, String, Table, Text

from ingestion_worker.models.base import IndexJobMetadata

knowledge_base = Table(
    "knowledge_base",
    IndexJobMetadata,
    Column("Id", String(255), primary_key=True),
    Column("OrganizationId", String(255), nullable=False),
    Column("Name", String(255), nullable=False),
    Column("Data", Text, nullable=False),
    Column("State", String(32), nullable=False),
    Column("CreatedAtUtc", DateTime(timezone=True), nullable=False),
    Column("UpdatedAtUtc", DateTime(timezone=True), nullable=False),
)

__all__ = ["knowledge_base"]