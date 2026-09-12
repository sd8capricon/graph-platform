from typing import Any

from langchain_litellm import ChatLiteLLM

from graphrag_apacheage.schemas.model import AuthMode, Model


def build_chat_model(model: Model, /, **overrides: Any) -> ChatLiteLLM:
    """Build a LangChain chat model from a configured `Model` provider entry.

    Mirrors `EmbeddingService.compute_embeddings()`'s `Model` -> litellm kwarg
    mapping (`services/embedding_service.py`) so chat and embedding calls read the
    same config the same way: `f"{provider}/{name}"` as the litellm model string,
    `connection_string` as `api_base`, and the secret only when `auth_mode` is
    `api_key`. `embedding_dimension` is deliberately not forwarded - it has no
    chat-completion meaning. `reasoning_effort`, when set, is forwarded via
    `model_kwargs` (not as a top-level `ChatLiteLLM` kwarg - `ChatLiteLLM`'s
    pydantic config is `extra="ignore"`, so an unrecognized top-level kwarg is
    silently dropped rather than reaching litellm; `model_kwargs` is the one
    declared field whose contents `ChatLiteLLM` spreads into the completion
    call).

    Args:
        model: The provider configuration to call (provider, name,
            connection_string, and auth). Positional-only, so that `model` stays
            free as an `**overrides` key - it is also `ChatLiteLLM`'s own field
            name for the litellm model string.
        **overrides: Extra `ChatLiteLLM` fields (e.g. `temperature`, `max_tokens`,
            `profile`), applied last so they win. Nothing is set by default, so
            provider defaults apply unless a caller opts in. `profile` is the one
            worth knowing about: without it, deepagents' summarization middleware
            falls back to a fixed token trigger instead of a fraction of the
            model's real context window (see "Deep Agent Assembly Pattern" in
            CLAUDE.md).

    Returns:
        A `ChatLiteLLM` bound to the given provider.
    """
    call_kwargs: dict[str, Any] = {"model": f"{model.provider}/{model.name}"}
    if model.connection_string:
        call_kwargs["api_base"] = model.connection_string
    if model.auth_mode == AuthMode.API_KEY and model.api_key is not None:
        call_kwargs["api_key"] = model.api_key.get_secret_value()
    if model.reasoning_effort:
        call_kwargs["model_kwargs"] = {"reasoning_effort": model.reasoning_effort}
    call_kwargs.update(overrides)
    return ChatLiteLLM(**call_kwargs)


__all__ = ["build_chat_model"]
