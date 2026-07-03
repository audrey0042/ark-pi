from ark_pi.llm_client.mock import MockLlmClient
from ark_pi.llm_client.openai_compat import OpenAiCompatibleClient
from ark_pi.llm_client.types import LlmClient, LlmConfigurationError

SUPPORTED_BACKENDS = frozenset({"mock", "openai-compatible"})


def create_llm_client(
    backend: str,
    *,
    base_url: str | None = None,
    timeout_seconds: float = 30.0,
) -> LlmClient:
    if backend not in SUPPORTED_BACKENDS:
        supported = ", ".join(sorted(SUPPORTED_BACKENDS))
        msg = f"Unknown LLM backend {backend!r}. Supported backends: {supported}"
        raise LlmConfigurationError(msg)

    if backend == "mock":
        return MockLlmClient()

    if not base_url or not base_url.strip():
        msg = "openai-compatible backend requires a non-empty base_url"
        raise LlmConfigurationError(msg)

    return OpenAiCompatibleClient(
        base_url=base_url,
        timeout_seconds=timeout_seconds,
    )
