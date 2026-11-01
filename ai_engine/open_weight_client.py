import os
import requests
from typing import Any
from urllib.parse import urlparse
from ai_engine.interface import (
    AIClientInterface,
    AIConfigurationError,
    AIServerUnavailableError,
    AIProhibitedModelError,
    AIError,
)

# Explicitly prohibited closed-model hosts to enforce hackathon open-weight rules
PROHIBITED_HOSTS = {
    "api.openai.com",
    "api.anthropic.com",
    "generativelanguage.googleapis.com",
    "aiplatform.googleapis.com",
    "bedrock.amazonaws.com",
    "api.cohere.ai",
}


class OpenWeightAIClient(AIClientInterface):
    """
    Client for interacting with approved open-weight model servers
    (e.g., local Ollama, vLLM, SGLang, or an organizer-provided server).
    Uses the standard OpenAI-compatible HTTP protocol without proprietary SDKs.
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout: int = 45,
    ):
        self.base_url = (base_url or os.getenv("AI_BASE_URL") or "").rstrip("/")
        self.model = model or os.getenv("AI_MODEL") or ""
        self.api_key = api_key or os.getenv("AI_API_KEY") or ""
        self.timeout = timeout

        self._validate_configuration()

    def _validate_configuration(self) -> None:
        """Validate that endpoint URL is provided and not pointing to a prohibited closed model."""
        if not self.base_url:
            raise AIConfigurationError(
                "AI_BASE_URL is not configured. Please set AI_BASE_URL in your environment or .env file "
                "to point to your approved open-weight model server (e.g., http://localhost:11434/v1)."
            )

        if not self.model:
            raise AIConfigurationError(
                "AI_MODEL is not configured. Please set AI_MODEL in your environment or .env file "
                "to an approved open-weight model name (e.g., qwen2.5:7b)."
            )

        parsed = urlparse(self.base_url)
        hostname = (parsed.hostname or "").lower()

        for prohibited in PROHIBITED_HOSTS:
            if prohibited in hostname:
                raise AIProhibitedModelError(
                    f"Violation of hackathon rules: Prohibited closed-model host '{hostname}' detected. "
                    f"ClaimCheck inference must run ONLY on approved open-weight models."
                )

    def _get_chat_endpoint(self) -> str:
        """Construct the OpenAI-compatible chat completions endpoint."""
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"

    def _get_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def check_health(self) -> tuple[bool, str]:
        """
        Check connectivity to the open-weight model server.
        """
        try:
            # First attempt a quick models or base endpoint check
            parsed = urlparse(self.base_url)
            base_root = f"{parsed.scheme}://{parsed.netloc}"
            
            # Try /v1/models or root endpoint
            try:
                resp = requests.get(f"{self.base_url}/models", headers=self._get_headers(), timeout=5)
                if resp.status_code == 200:
                    return True, f"Connected to open-weight server at {self.base_url} (model: {self.model})"
            except requests.RequestException:
                pass

            # Fallback probe to base server
            resp = requests.get(base_root, timeout=5)
            if resp.status_code in (200, 404, 405):
                return True, f"Server reachable at {base_root}. Target model: {self.model}"
            
            return False, f"Server responded with status code {resp.status_code}"
        except requests.exceptions.ConnectionError:
            return False, (
                f"Cannot connect to open-weight server at {self.base_url}. "
                "Please verify that your open-weight model server (Ollama, vLLM, organizer server) is running."
            )
        except requests.exceptions.Timeout:
            return False, f"Connection to open-weight server at {self.base_url} timed out."
        except Exception as e:
            return False, f"Health check failed: {str(e)}"

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        """
        Send a chat completion request to the approved open-weight model server.
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,  # Low temperature for deterministic analysis
        }

        endpoint = self._get_chat_endpoint()
        headers = self._get_headers()

        try:
            response = requests.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.exceptions.ConnectionError as exc:
            raise AIServerUnavailableError(
                f"Approved open-weight model server at '{self.base_url}' is unavailable. "
                "Ensure your local model runner (e.g. Ollama, vLLM) or organizer endpoint is running and reachable."
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise AIServerUnavailableError(
                f"Request to open-weight model server at '{self.base_url}' timed out after {self.timeout}s."
            ) from exc
        except requests.RequestException as exc:
            raise AIError(f"Network error while contacting AI server: {str(exc)}") from exc

        if response.status_code != 200:
            raise AIError(
                f"AI server returned HTTP {response.status_code}: {response.text[:300]}"
            )

        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
            return content.strip()
        except (KeyError, IndexError) as exc:
            raise AIError(f"Unexpected response format from AI server: {data}") from exc

