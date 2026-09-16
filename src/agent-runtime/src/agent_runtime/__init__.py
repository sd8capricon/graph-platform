"""Agent runtime: the knowledge-graph agent's tools, prompt and assembly.

Owns the agent-execution workload of ADR-0004: `tools.py`, `prompts.py`,
`deep_agent.py`, `react_agent.py`, `context.py`, `models.py`, `serializers.py`
and `chat_model.py`. Everything it reads from the graph - schemas, ORM models,
the repository, the embedding service - comes from the `common` project.

`main()` is a developer smoke test: it builds the react agent against the
configured chat model, runs one question through it with an `AgentContext` bound
to the demo graph, and prints tool calls, tool results and the final answer.
"""

import asyncio

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from common.config import load_config, settings
from common.database.connection import create_connection, database_url
from common.repositories.age_graph_repository import AgeGraphRepository
from common.schemas.model import Model, ModelType

# Placeholder until the Organization entity (ADR-0002) exists: every write/read
# path now requires an organization_id, and this demo has exactly one org.
DEMO_ORGANIZATION_ID = "demo-org"
DEMO_GRAPH_NAME = "kb_graph"
DEMO_ATTACHED_KB_IDS = ["b7c9e1a4-3f28-4d65-9e07-1a2b3c4d5e6f"]


def chat_model() -> Model | None:
    """Return the configured thinking/chat provider, or `None` when none is set."""
    return next((m for m in settings.models if ModelType.THINKING in m.type), None)


def embedding_model() -> Model | None:
    """Return the configured embedding provider, or `None` when none is set."""
    return next((m for m in settings.models if ModelType.EMBEDDING in m.type), None)


async def check_agent(session: AsyncSession, repository: AgeGraphRepository) -> None:
    """Stream one question through the react agent and print the exchange.

    Builds the agent against the configured chat model, invokes it with an
    `AgentContext` scoped to the demo graph, and prints each streamed chunk:
    tool calls the model requested, tool results, and the model's text.

    Args:
        session: The SQLAlchemy session the agent's tools use for side-tables.
        repository: The Apache Age repository the agent's tools query.
    """
    from langchain.messages import HumanMessage

    from agent_runtime.context import AgentContext
    from agent_runtime.deep_agent import build_deep_agent
    from agent_runtime.react_agent import build_react_agent

    deep_agent = build_deep_agent(chat_model(), name="deep_graph_agent")
    react_agent = build_react_agent(chat_model(), name="react_graph_agent")
    context = AgentContext(
        organization_id=DEMO_ORGANIZATION_ID,
        graph_name=DEMO_GRAPH_NAME,
        attached_kb_ids=DEMO_ATTACHED_KB_IDS,
        session=session,
        repository=repository,
        model=embedding_model(),
    )
    async for chunk in react_agent.astream(
        {
            "messages": [
                HumanMessage(
                    "For which team did Max race, and when? Who else raced for the same team during that time?"
                )
            ]
        },
        stream_mode="messages",
        context=context,
    ):
        message, metadata = chunk

        # Model requested a tool
        if getattr(message, "tool_calls", None):
            for tool_call in message.tool_calls:
                print("\n🔧 TOOL CALL")
                print(f"Name: {tool_call['name']}")
                print(f"Args: {tool_call['args']}")

        # Tool returned something
        if message.type == "tool":
            print("\n📦 TOOL RESULT")
            print(f"Tool: {message.name}")
            print(f"Result: {message.content}")

        # AI response / streamed text
        if message.type == "ai":
            if message.content:
                print("\n🤖 AI RESPONSE")
                print(message.content)


async def run() -> None:
    """Open the demo graph connection and run the agent smoke test."""
    pg_connection = await create_connection()
    repository = AgeGraphRepository(pg_connection)
    engine = create_async_engine(database_url())
    try:
        async with AsyncSession(engine) as session:
            await check_agent(session, repository)
    finally:
        await engine.dispose()
        await pg_connection.close()


def main() -> None:
    """Load environment/config and run the agent smoke test."""
    load_dotenv()
    load_config()
    asyncio.run(run())


__all__ = ["main", "run", "check_agent", "chat_model", "embedding_model"]
