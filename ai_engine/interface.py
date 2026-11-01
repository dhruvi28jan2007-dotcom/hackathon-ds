from abc import ABC, abstractmethod
import json
import re
from typing import Any


class AIError(Exception):
    """Base exception for AI engine errors."""
    pass


class AIConfigurationError(AIError):
    """Raised when AI configuration is missing or invalid."""
    pass


class AIServerUnavailableError(AIError):
    """Raised when the open-weight model server is unreachable."""
    pass


class AIProhibitedModelError(AIError):
    """Raised when an attempt is made to use a prohibited closed-model provider."""
    pass


class AIClientInterface(ABC):
    """Provider-independent interface for AI inference."""

    @abstractmethod
    def check_health(self) -> tuple[bool, str]:
        """
        Check connectivity to the AI model endpoint.
        Returns (is_healthy, status_message).
        """
        pass

    @abstractmethod
    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        """
        Generate raw text response from the model.
        """
        pass

    def generate_json(self, prompt: str, system_prompt: str | None = None) -> dict[str, Any] | list[Any]:
        """
        Generate structured JSON output from the model.
        Extracts and parses JSON from the response text.
        """
        raw_output = self.generate(prompt, system_prompt=system_prompt)
        return self._extract_json(raw_output)

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | list[Any]:
        """
        Extract JSON object or array from model response text,
        handling Markdown code fences if present.
        """
        text = text.strip()
        # Look for ```json ... ``` or ``` ... ```
        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        candidate = fence_match.group(1).strip() if fence_match else text

        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # Fallback regex search for JSON object or array
            json_block = re.search(r"(\{|\[)[\s\S]*(\}|\])", text)
            if json_block:
                return json.loads(json_block.group(0))
            raise AIError(f"Failed to parse valid JSON from model response: {text[:200]}...")

