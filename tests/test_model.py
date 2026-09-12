import pytest

from graphrag_apacheage.schemas.model import AuthMode, Model, ModelType


def _model(**overrides) -> Model:
    fields = {
        "display_name": "Chat GPT-4o",
        "name": "gpt-4o",
        "provider": "openai",
        "auth_mode": AuthMode.API_KEY,
        "api_key": "test-key",
        "type": [],
    }
    fields.update(overrides)
    return Model.model_validate(fields)


def test_reasoning_effort_is_optional_and_allowed_on_a_chat_model():
    model = _model(reasoning_effort="low")

    assert model.reasoning_effort == "low"


def test_reasoning_effort_defaults_to_none():
    model = _model()

    assert model.reasoning_effort is None


def test_reasoning_effort_raises_when_embedding_is_in_type():
    with pytest.raises(ValueError, match="reasoning_effort"):
        _model(
            type=[ModelType.EMBEDDING],
            embedding_dimension=1536,
            reasoning_effort="low",
        )
