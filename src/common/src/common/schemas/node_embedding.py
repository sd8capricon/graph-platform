"""DTO for the `NodeEmbedding` ORM model."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class NodeEmbeddingDTO(BaseModel):
    """Data transferred for an embedded knowledge graph node."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    organization_id: str
    graph_name: str
    knowledge_base_id: str
    node_id: str
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)
    embedding_model_id: str | None = None
    embedding: list[float] | None = None


__all__ = ["NodeEmbeddingDTO"]
