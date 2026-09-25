"""DTOs for the API-owned `common.models.file.File` row."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class FileStatus(StrEnum):
    """Processing status of a stored file.

    The values are the snake_case strings the API's `FileStatus` enum persists.
    The API sets `uploaded`. The others are reserved for processing, which for
    knowledge base files is per-file ingestion (ADR-0005 Phase 2).
    """

    UPLOADED = "uploaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class FileDTO(BaseModel):
    """File metadata plus the storage key the content can be read from."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    file_name: str
    content_type: str
    size: int
    storage_key: str
    status: FileStatus
    created_at_utc: datetime
    updated_at_utc: datetime


__all__ = ["FileDTO", "FileStatus"]
