from collections.abc import Sequence

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

from common.agent.chat_model import build_chat_model
from common.agent.context import AgentContext
from common.agent.prompts import GRAPH_AGENT_SYSTEM_PROMPT
from common.agent.tools import GRAPH_TOOLS
from common.schemas.model import Model


def build_react_agent(
    chat_model: Model | BaseChatModel,
    *,
    tools: Sequence[BaseTool] = (),
    middleware: Sequence[AgentMiddleware] = (),
    system_prompt: str | None = None,
    name: str | None = None,
) -> CompiledStateGraph:
    """Build the knowledge-graph react agent.

    The plain-`langchain` counterpart to `agent/deep_agent.py`'s
    `build_deep_agent()`: same tools (`agent/tools.py`'s `GRAPH_TOOLS`), same
    `AgentContext` as `context_schema`, same system prompt, but assembled with
    `langchain.agents.create_agent()` instead of `deepagents.create_deep_agent()` -
    no filesystem/subagent/summarization middleware stack, no `TodoListMiddleware`,
    no deepagents dependency.

    Run-scoped data (graph name, session, repository, embedding model) is not
    supplied here - it is passed per invocation, since one built agent serves many
    runs:

        agent = build_react_agent(chat_model_config)  # once, at startup
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
            fake model with no network and no credentials.
        tools: Extra tools, appended to `GRAPH_TOOLS`.
        middleware: Extra middleware, passed straight through to `create_agent()`.
        system_prompt: Overrides `prompts.GRAPH_AGENT_SYSTEM_PROMPT`. `None` (the
            default) means "use that constant", not "no prompt".
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
    return create_agent(
        model,
        [*GRAPH_TOOLS, *tools],
        system_prompt=(
            GRAPH_AGENT_SYSTEM_PROMPT if system_prompt is None else system_prompt
        ),
        middleware=middleware,
        context_schema=AgentContext,
        name=name,
    )


__all__ = ["build_react_agent"]
