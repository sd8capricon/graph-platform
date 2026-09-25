"""DTOs for the API-owned `common.models.knowledge_base_file.KnowledgeBaseFile` row."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class KnowledgeBaseFileStatus(StrEnum):
    """Processing status of a knowledge base file.

    The values are the snake_case strings the API's `KnowledgeBaseFileStatus`
    enum persists. The API sets `uploaded`; the others are reserved for per-file
    ingestion (ADR-0005 Phase 2).
    """

    UPLOADED = "uploaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class KnowledgeBaseFileDTO(BaseModel):
    """File metadata plus the storage key the worker reads the content from."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    knowledge_base_id: str
    organization_id: str
    file_name: str
    content_type: str
    size: int
    storage_key: str
    status: KnowledgeBaseFileStatus
    created_at_utc: datetime
    updated_at_utc: datetime


__all__ = ["KnowledgeBaseFileDTO", "KnowledgeBaseFileStatus"]
