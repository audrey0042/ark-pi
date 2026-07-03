from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol


class LlmClientError(Exception):
    """Base class for LLM client failures that CLI may catch."""


class LlmConfigurationError(LlmClientError):
    """Invalid or missing backend configuration."""


class LlmTransportError(LlmClientError):
    """Timeouts, connection errors, or HTTP transport failures."""


class LlmResponseError(LlmClientError):
    """Non-2xx responses, malformed JSON, or missing expected response fields."""


@dataclass(frozen=True)
class LlmRequest:
    prompt: str
    model: str | None = None
    max_tokens: int = 512
    temperature: float = 0.0


@dataclass(frozen=True)
class LlmResponse:
    text: str
    backend: str
    model: str | None = None
    raw: Mapping[str, Any] | None = None


class LlmClient(Protocol):
    def complete(self, request: LlmRequest) -> LlmResponse:
        ...
