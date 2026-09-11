from graphrag_apacheage.agent.chat_model import build_chat_model
from graphrag_apacheage.schemas.model import AuthMode, Model, ModelType


def _chat_model_config(**overrides) -> Model:
    fields = {
        "display_name": "Chat GPT-4o",
        "name": "gpt-4o",
        "provider": "openai",
        "connection_string": "https://api.openai.com/v1",
        "auth_mode": AuthMode.API_KEY,
        "api_key": "test-key",
        "type": [],
    }
    fields.update(overrides)
    return Model.model_validate(fields)


def test_build_chat_model_maps_provider_and_name_into_the_litellm_model_string():
    chat = build_chat_model(_chat_model_config())

    assert chat.model == "openai/gpt-4o"


def test_build_chat_model_passes_connection_string_as_api_base():
    chat = build_chat_model(_chat_model_config())

    assert chat.api_base == "https://api.openai.com/v1"


def test_build_chat_model_passes_api_key_when_auth_mode_is_api_key():
    chat = build_chat_model(_chat_model_config(api_key="secret-key"))

    assert chat.api_key == "secret-key"


def test_build_chat_model_omits_api_key_for_managed_identity():
    chat = build_chat_model(
        _chat_model_config(auth_mode=AuthMode.MANAGED_IDENTITY, api_key=None)
    )

    assert chat.api_key is None


def test_build_chat_model_omits_api_base_when_connection_string_is_empty():
    chat = build_chat_model(_chat_model_config(connection_string=""))

    assert chat.api_base is None


def test_build_chat_model_ignores_embedding_dimension():
    chat = build_chat_model(
        _chat_model_config(type=[ModelType.EMBEDDING], embedding_dimension=1536)
    )

    assert "dimensions" not in chat.model_kwargs
    assert chat.max_tokens is None


def test_build_chat_model_applies_overrides_last():
    chat = build_chat_model(
        _chat_model_config(), model="openai/gpt-5", temperature=0.0
    )

    assert chat.model == "openai/gpt-5"
    assert chat.temperature == 0.0
