"""DTO for the `SchemaEmbedding` ORM model."""

from pydantic import BaseModel, ConfigDict


class SchemaEmbeddingDTO(BaseModel):
    """Data transferred for a schema registry row's embedding side-table."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    graph_registry_id: int | None = None
    organization_id: str
    embedding_model_id: str | None = None
    embedding: list[float] | None = None


__all__ = ["SchemaEmbeddingDTO"]
