from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from common.schemas.file import FileDTO


class KnowledgeBaseRecordDTO(BaseModel):
    """DTO for the API-owned `common.models.knowledge_base.KnowledgeBase` row.

    This resource record is distinct from the graph-payload `KnowledgeBase`
    defined below. A knowledge base's content is the files uploaded to it, listed
    in `files`, oldest first.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    name: str
    state: str
    created_at_utc: datetime
    updated_at_utc: datetime
    files: list[FileDTO] = Field(default_factory=list)


class KnowledgeNode(BaseModel):
    """Represents a node in a knowledge graph.

    A node is a vertex in the graph with a unique identifier, a semantic label,
    and optional properties for storing metadata.

    Attributes:
        id: Unique identifier for the node. Auto-generated as UUID if not provided.
        label: The semantic label or type of the node (e.g., 'Person', 'Organization').
        properties: A dictionary of key-value pairs storing node metadata.
    """

    id: str | None = None
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def ensure_id(cls, data: Any) -> Any:
        """Ensure that the node has an ID by generating a UUID if not provided.

        Args:
            data: The raw data dictionary before model instantiation.

        Returns:
            The data dictionary with id field populated (generated if necessary).
        """
        if isinstance(data, dict):
            data = dict(data)
            data.setdefault("id", str(uuid4()))
        return data


class KnowledgeRelationship(BaseModel):
    """Represents a directed edge connecting two nodes in a knowledge graph.

    A relationship is a directed connection between two nodes with a semantic label
    and optional properties for storing relationship metadata.

    Attributes:
        source_id: The unique identifier of the source (starting) node.
        target_id: The unique identifier of the target (ending) node.
        label: The semantic label or type of the relationship (e.g., 'knows', 'works_for').
        properties: A dictionary of key-value pairs storing relationship metadata.
    """

    source_id: str | None = None
    target_id: str | None = None
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def ensure_related_ids(cls, data: Any) -> Any:
        """Ensure that source_id and target_id exist by generating UUIDs if not provided.

        Args:
            data: The raw data dictionary before model instantiation.

        Returns:
            The data dictionary with source_id and target_id fields populated
            (generated if necessary).
        """
        if isinstance(data, dict):
            data = dict(data)
            data.setdefault("source_id", str(uuid4()))
            data.setdefault("target_id", str(uuid4()))
        return data


class KnowledgeBase(BaseModel):
    """A container for nodes and relationships that form a knowledge graph.

    Represents a complete knowledge graph with a name, unique identifier, and
    collections of nodes and their relationships.

    Attributes:
        id: Unique identifier for the knowledge base. Auto-generated as UUID if not provided.
        name: The name or identifier of the knowledge base.
        nodes: A list of KnowledgeNode instances in the graph.
        relationships: A list of KnowledgeRelationship instances in the graph.
    """

    id: str | None = None
    name: str
    nodes: list[KnowledgeNode] = Field(default_factory=list)
    relationships: list[KnowledgeRelationship] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def ensure_knowledge_base_id(cls, data: Any) -> Any:
        """Ensure that the knowledge base has an ID by generating a UUID if not provided.

        Args:
            data: The raw data dictionary before model instantiation.

        Returns:
            The data dictionary with id field populated (generated if necessary).
        """
        if isinstance(data, dict):
            data = dict(data)
            data.setdefault("id", str(uuid4()))
        return data

    @classmethod
    def from_json_file(cls, file_path: str | Path) -> "KnowledgeBase":
        """Load a KnowledgeBase from a JSON file.

        Args:
            file_path: Path to the JSON file containing the knowledge base data.

        Returns:
            A KnowledgeBase instance deserialized from the JSON file.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the JSON content is invalid or does not match the schema.
        """
        return cls.model_validate_json(Path(file_path).read_text())


__all__ = [
    "KnowledgeBase",
    "KnowledgeBaseRecordDTO",
    "KnowledgeNode",
    "KnowledgeRelationship",
]
