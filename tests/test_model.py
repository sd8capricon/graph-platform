import pytest

from common.schemas.model import AuthMode, Model, ModelType


def _model(**overrides) -> Model:
    fields = {
        "id": "550e8400-e29b-41d4-a716-446655440001",
        "display_name": "Chat GPT-4o",
        "name": "gpt-4o",
        "provider": "openai",
        "auth_mode": AuthMode.API_KEY,
        "api_key": "test-key",
        "type": [ModelType.THINKING],
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


def test_id_is_required_and_not_auto_generated():
    # A stored id must stay stable across restarts (it is stamped as embedding
    # provenance and is what vector_search()/the partial index key off), so an
    # omitted id must fail loudly rather than be silently filled with a fresh
    # UUID each run.
    fields = {
        "display_name": "Chat GPT-4o",
        "name": "gpt-4o",
        "provider": "openai",
        "auth_mode": AuthMode.API_KEY,
        "api_key": "test-key",
        "type": [],
    }

    with pytest.raises(ValueError, match="id"):
        Model.model_validate(fields)


def test_id_must_be_a_valid_uuid():
    # id is the embedding-provenance value and partial-index predicate, so it
    # must be well-formed, not any caller-chosen string.
    with pytest.raises(ValueError, match="UUID"):
        _model(id="chat-gpt-4o")


def test_id_accepts_a_valid_uuid():
    model = _model(id="550e8400-e29b-41d4-a716-446655440000")

    assert model.id == "550e8400-e29b-41d4-a716-446655440000"


def test_type_must_not_be_empty():
    with pytest.raises(ValueError, match="type must not be empty"):
        _model(type=[])


@pytest.mark.parametrize("other", [ModelType.VISION, ModelType.THINKING])
def test_embedding_cannot_be_combined_with_a_chat_capability(other):
    with pytest.raises(ValueError, match="embedding"):
        _model(type=[ModelType.EMBEDDING, other], embedding_dimension=1536)


def test_vision_and_thinking_can_be_combined():
    model = _model(type=[ModelType.VISION, ModelType.THINKING])

    assert model.type == [ModelType.VISION, ModelType.THINKING]
