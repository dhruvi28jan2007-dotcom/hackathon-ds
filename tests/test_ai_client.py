import pytest
from ai_engine.interface import (
    AIConfigurationError,
    AIProhibitedModelError,
    AIServerUnavailableError,
)
from ai_engine.mock_client import MockAIClient
from ai_engine.open_weight_client import OpenWeightAIClient
from ai_engine.client import get_ai_client


def test_mock_client_generation():
    client = MockAIClient()
    healthy, msg = client.check_health()
    assert healthy is True

    claims = client.generate_json("Please extract claims from this PR")
    assert isinstance(claims, list)
    assert len(claims) > 0
    assert claims[0]["id"] == "claim-1"


def test_open_weight_client_configuration_validation():
    # Missing base url should raise AIConfigurationError
    with pytest.raises(AIConfigurationError):
        OpenWeightAIClient(base_url="", model="qwen2.5:7b")

    # Missing model should raise AIConfigurationError
    with pytest.raises(AIConfigurationError):
        OpenWeightAIClient(base_url="http://localhost:11434/v1", model="")


def test_open_weight_client_prohibits_closed_models():
    # Prohibited closed-model URLs must be blocked
    with pytest.raises(AIProhibitedModelError):
        OpenWeightAIClient(base_url="https://api.openai.com/v1", model="gpt-4o")

    with pytest.raises(AIProhibitedModelError):
        OpenWeightAIClient(base_url="https://api.anthropic.com/v1", model="claude-3-5")


def test_factory_get_ai_client():
    mock_client = get_ai_client(provider="mock")
    assert isinstance(mock_client, MockAIClient)

    # Closed-model provider name must raise AIProhibitedModelError
    with pytest.raises(AIProhibitedModelError):
        get_ai_client(provider="openai")

    with pytest.raises(AIProhibitedModelError):
        get_ai_client(provider="gemini")


def test_open_weight_server_unavailable():
    # Connecting to non-existent local port should raise AIServerUnavailableError
    client = OpenWeightAIClient(
        base_url="http://127.0.0.1:59999/v1",
        model="qwen2.5:7b",
        timeout=1,
    )
    with pytest.raises(AIServerUnavailableError):
        client.generate("Test prompt")

