import os
from ai_engine.interface import (
    AIClientInterface,
    AIConfigurationError,
    AIProhibitedModelError,
)
from ai_engine.open_weight_client import OpenWeightAIClient
from ai_engine.mock_client import MockAIClient


def get_ai_client(provider: str | None = None) -> AIClientInterface:
    """
    Factory function to retrieve the configured AI client.
    Ensures only approved open-weight or mock providers are instantiated.
    """
    selected_provider = (provider or os.getenv("AI_PROVIDER") or "mock").strip().lower()

    # Reject prohibited closed-model provider names immediately
    prohibited_providers = {"openai", "anthropic", "claude", "gemini", "google", "azure"}
    if selected_provider in prohibited_providers:
        raise AIProhibitedModelError(
            f"Prohibited AI provider '{selected_provider}' requested. "
            "ClaimCheck hackathon rules require inference using an approved OPEN-WEIGHT MODEL only."
        )

    if selected_provider == "mock":
        return MockAIClient()

    if selected_provider in ("organizer_server", "local", "open_weight"):
        return OpenWeightAIClient()

    raise AIConfigurationError(
        f"Unsupported AI_PROVIDER '{selected_provider}'. "
        "Valid options are: 'organizer_server', 'local', or 'mock'."
    )

