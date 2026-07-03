from typing import Any

import httpx

from ark_pi.llm_client.types import (
    LlmConfigurationError,
    LlmRequest,
    LlmResponse,
    LlmResponseError,
    LlmTransportError,
)

DEFAULT_MODEL = "local"


class OpenAiCompatibleClient:
    """Minimal OpenAI-compatible HTTP client for future llama.cpp server use."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        normalized = base_url.strip()
        if not normalized:
            msg = "openai-compatible backend requires a non-empty base_url"
            raise LlmConfigurationError(msg)
        self._base_url = normalized.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def complete(self, request: LlmRequest) -> LlmResponse:
        url = f"{self._base_url}/v1/chat/completions"
        payload: dict[str, Any] = {
            "model": request.model or DEFAULT_MODEL,
            "messages": [{"role": "user", "content": request.prompt}],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }

        try:
            response = httpx.post(
                url,
                json=payload,
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            msg = f"LLM request timed out after {self._timeout_seconds}s"
            raise LlmTransportError(msg) from exc
        except httpx.RequestError as exc:
            msg = f"LLM request failed: {exc}"
            raise LlmTransportError(msg) from exc

        if response.status_code < 200 or response.status_code >= 300:
            msg = f"LLM request failed with HTTP {response.status_code}: {response.text}"
            raise LlmResponseError(msg)

        try:
            data = response.json()
        except ValueError as exc:
            msg = "LLM response was not valid JSON"
            raise LlmResponseError(msg) from exc

        try:
            choices = data["choices"]
            message = choices[0]["message"]
            content = message["content"]
        except (KeyError, IndexError, TypeError) as exc:
            msg = "LLM response missing expected choices[0].message.content"
            raise LlmResponseError(msg) from exc

        if not isinstance(content, str):
            msg = "LLM response content was not a string"
            raise LlmResponseError(msg)

        return LlmResponse(
            text=content,
            backend="openai-compatible",
            model=request.model,
            raw=data,
        )
