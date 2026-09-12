from pydantic import BaseModel


class NodeRef(BaseModel):
    """A reference to a node that already exists in the graph, by its `id`.

    Deliberately not `KnowledgeNode`: `KnowledgeNode.ensure_id()` auto-generates
    a random UUID whenever `id` is omitted, which is the right behavior for
    *authoring* a new node but wrong for *looking one up* — a caller (or an
    agent) that forgets `id` would silently get a fabricated one that matches
    no node in the graph, instead of a validation error at the tool boundary.
    Making `id` a required, non-generated field here means an omitted `id`
    fails schema validation before a tool like `get_node_schema` ever runs.
    """

    id: str
    label: str


__all__ = ["NodeRef"]
