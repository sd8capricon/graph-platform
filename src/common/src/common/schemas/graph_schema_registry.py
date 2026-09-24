"""DTO and enum for the `GraphSchemaRegistry` ORM model."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from common.schemas.schema_embedding import SchemaEmbeddingDTO


class SchemaType(str, Enum):
    """Supported schema registry record types."""

    NODE = "node"
    RELATIONSHIP = "relationship"


class GraphSchemaRegistryDTO(BaseModel):
    """Data transferred for a graph schema registry record."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    organization_id: str
    graph_name: str
    knowledge_base_ids: list[str] = Field(default_factory=list)
    type: SchemaType
    name: str
    description: str
    aliases: list[str] = Field(default_factory=list)
    properties: list[str] = Field(default_factory=list)
    source_label: str | None = None
    target_label: str | None = None
    embedding_row: SchemaEmbeddingDTO | None = None


__all__ = ["GraphSchemaRegistryDTO", "SchemaType"]
