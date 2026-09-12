from pydantic import BaseModel


class NodeRef(BaseModel):
    """A reference to a node that already exists in the graph — one instance, or a label.

    `label` is always required, so a reference always names something. `id`
    narrows it to a single instance; omitting `id` means "the label itself",
    which is exactly the branch `get_node_schema` uses to return the
    label-level schema instead of one instance's.

    Deliberately not `KnowledgeNode`: `KnowledgeNode.ensure_id()` auto-generates
    a random UUID whenever `id` is omitted, which is the right behavior for
    *authoring* a new node but wrong for *looking one up* — a caller (or an
    agent) that omits `id` would silently get a fabricated one that matches no
    node in the graph. `NodeRef.id` is never generated: an omitted `id` stays
    `None` and is a meaningful, explicit choice of mode, not a hole to be
    filled.

    A *present but blank* `id` (`""`, `"   "`) is not the same as an omitted
    one — it is a malformed instance reference (typically an agent filling the
    field with a placeholder), and tools reject it rather than silently
    falling back to label mode, which would answer a broader question than the
    one asked.
    """

    id: str | None = None
    label: str


__all__ = ["NodeRef"]
