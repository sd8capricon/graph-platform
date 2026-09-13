from langchain.agents.middleware import AgentMiddleware, TodoListMiddleware
from langchain.tools import tool
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

from graphrag_apacheage.agent import deep_agent
from graphrag_apacheage.agent.context import AgentContext
from graphrag_apacheage.agent.prompts import GRAPH_AGENT_SYSTEM_PROMPT
from graphrag_apacheage.schemas.model import AuthMode, Model

_GRAPH_TOOL_NAMES = [
    "search_schema_registry",
    "search_entities",
    "get_node_schema",
    "get_node_neighbours",
    "get_relationship",
]


def _fake_chat_model() -> GenericFakeChatModel:
    """A BaseChatModel the graph can compile against with no network/credentials."""
    return GenericFakeChatModel(messages=iter([]))


def _chat_model_config() -> Model:
    return Model.model_validate(
        {
            "id": "chat-gpt-4o",
            "display_name": "Chat GPT-4o",
            "name": "gpt-4o",
            "provider": "openai",
            "connection_string": "https://api.openai.com/v1",
            "auth_mode": AuthMode.API_KEY,
            "api_key": "test-key",
        }
    )


def _tool_names(agent) -> set[str]:
    return set(agent.nodes["tools"].bound.tools_by_name)


class _MarkerMiddleware(AgentMiddleware):
    pass


def _capture_create_deep_agent(monkeypatch) -> dict:
    """Patch out create_deep_agent so the wiring contract can be asserted directly."""
    captured: dict = {}

    def fake_create(model, tools=None, **kwargs):
        captured["model"] = model
        captured["tools"] = tools
        captured.update(kwargs)
        return "sentinel-graph"

    monkeypatch.setattr(deep_agent, "create_deep_agent", fake_create)
    return captured


def test_build_deep_agent_exposes_the_graph_tools():
    agent = deep_agent.build_deep_agent(_fake_chat_model())

    assert set(_GRAPH_TOOL_NAMES) <= _tool_names(agent)


def test_build_deep_agent_adds_the_deepagents_and_todo_tools():
    agent = deep_agent.build_deep_agent(_fake_chat_model())

    # Subset assertion on stable names only: deepagents' full built-in tool set
    # can change in a minor release. `write_todos` proves TodoListMiddleware was
    # applied, `task` proves the subagent middleware landed despite `subagents`
    # being left unset.
    assert {"write_todos", "task", "ls", "read_file", "write_file"} <= _tool_names(
        agent
    )


def test_build_deep_agent_appends_extra_tools_to_the_graph_tools():
    @tool(description="Echo the given text back.")
    def echo(text: str) -> str:
        """Test-only tool used to check extra tools reach the graph."""
        return text

    agent = deep_agent.build_deep_agent(_fake_chat_model(), tools=[echo])

    assert set(_GRAPH_TOOL_NAMES) | {"echo"} <= _tool_names(agent)


def test_build_deep_agent_uses_agent_context_as_the_context_schema():
    agent = deep_agent.build_deep_agent(_fake_chat_model())

    assert agent.context_schema is AgentContext


def test_build_deep_agent_passes_the_tools_prompt_middleware_and_context_schema(
    monkeypatch,
):
    captured = _capture_create_deep_agent(monkeypatch)
    model = _fake_chat_model()

    assert deep_agent.build_deep_agent(model) == "sentinel-graph"

    assert captured["model"] is model
    assert [t.name for t in captured["tools"]] == _GRAPH_TOOL_NAMES
    # Identity, not content: swapping the placeholder prompt text for the real one
    # must not turn this test red.
    assert captured["system_prompt"] is GRAPH_AGENT_SYSTEM_PROMPT
    assert [type(m) for m in captured["middleware"]] == [TodoListMiddleware]
    assert captured["context_schema"] is AgentContext


def test_build_deep_agent_overrides_the_default_system_prompt_when_given(monkeypatch):
    captured = _capture_create_deep_agent(monkeypatch)

    deep_agent.build_deep_agent(_fake_chat_model(), system_prompt="custom prompt")

    assert captured["system_prompt"] == "custom prompt"


def test_build_deep_agent_appends_extra_middleware_after_the_todo_middleware(
    monkeypatch,
):
    captured = _capture_create_deep_agent(monkeypatch)

    deep_agent.build_deep_agent(
        _fake_chat_model(), middleware=[_MarkerMiddleware()]
    )

    assert [type(m) for m in captured["middleware"]] == [
        TodoListMiddleware,
        _MarkerMiddleware,
    ]


def test_build_deep_agent_builds_a_litellm_chat_model_from_a_model_config(monkeypatch):
    captured = _capture_create_deep_agent(monkeypatch)
    config = _chat_model_config()
    built = _fake_chat_model()
    calls = []

    def fake_build_chat_model(model, /, **overrides):
        calls.append(model)
        return built

    monkeypatch.setattr(deep_agent, "build_chat_model", fake_build_chat_model)

    deep_agent.build_deep_agent(config)

    assert calls == [config]
    assert captured["model"] is built


def test_build_deep_agent_does_not_rebuild_an_already_built_chat_model(monkeypatch):
    captured = _capture_create_deep_agent(monkeypatch)

    def fail(model, /, **overrides):
        raise AssertionError("build_chat_model must not be called for a BaseChatModel")

    monkeypatch.setattr(deep_agent, "build_chat_model", fail)
    model = _fake_chat_model()

    deep_agent.build_deep_agent(model)

    assert captured["model"] is model
