from collections.abc import Sequence

from deepagents import create_deep_agent
from langchain.agents.middleware import AgentMiddleware, TodoListMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

from graphrag_apacheage.agent.chat_model import build_chat_model
from graphrag_apacheage.agent.context import AgentContext
from graphrag_apacheage.agent.prompts import GRAPH_AGENT_SYSTEM_PROMPT
from graphrag_apacheage.agent.tools import GRAPH_TOOLS
from graphrag_apacheage.schemas.model import Model


def build_deep_agent(
    chat_model: Model | BaseChatModel,
    *,
    tools: Sequence[BaseTool] = (),
    middleware: Sequence[AgentMiddleware] = (),
    system_prompt: str | None = None,
    name: str | None = None,
) -> CompiledStateGraph:
    """Build the knowledge-graph deep agent.

    Assembles `deepagents.create_deep_agent()` with this repo's graph tools
    (`agent/tools.py`'s `GRAPH_TOOLS`), `AgentContext` as the `context_schema`, and
    deepagents' default middleware stack (filesystem, subagents, summarization,
    tool-call patching) plus an opt-in `TodoListMiddleware`.

    Run-scoped data (graph name, session, repository, embedding model) is not
    supplied here - it is passed per invocation, since one built agent serves many
    runs:

        agent = build_deep_agent(chat_model_config)  # once, at startup
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": "who drives for Mercedes?"}]},
            context=AgentContext(
                graph_name="demo_graph",
                attached_kb_ids=["kb-1"],
                session=session,
                repository=repository,
                model=embedding_model,
            ),
        )

    Args:
        chat_model: Either a configured `Model` (the config-file shape, converted
            via `agent/chat_model.py`'s `build_chat_model()`), or an already-built
            `BaseChatModel`. The `BaseChatModel` branch exists so callers can
            inject a pre-tuned model, and so tests can compile the graph against a
            fake model with no network and no credentials. A model is always
            required: `create_deep_agent(model=None)` falls back to `ChatAnthropic`
            with a deprecation warning, so this never forwards `None`.
        tools: Extra tools, appended to `GRAPH_TOOLS`. Additive - deepagents'
            built-in filesystem and `task` tools are never removed by this
            argument.
        middleware: Extra middleware, appended after `TodoListMiddleware`.
            deepagents splices caller middleware in after its own base stack.
        system_prompt: Overrides `prompts.GRAPH_AGENT_SYSTEM_PROMPT`. `None` (the
            default) means "use that constant", not "no prompt" - deepagents reads
            a `None` prompt as an empty authored prompt.
        name: Graph name, used in traces and when embedding this agent as a
            subgraph.

    Returns:
        The compiled agent graph. Invoke it with
        `await agent.ainvoke({"messages": [...]}, context=AgentContext(...))`.
    """
    model = (
        chat_model
        if isinstance(chat_model, BaseChatModel)
        else build_chat_model(chat_model)
    )
    return create_deep_agent(
        model,
        [*GRAPH_TOOLS, *tools],
        system_prompt=(
            GRAPH_AGENT_SYSTEM_PROMPT if system_prompt is None else system_prompt
        ),
        middleware=[TodoListMiddleware(), *middleware],
        context_schema=AgentContext,
        name=name,
    )


__all__ = ["build_deep_agent"]
