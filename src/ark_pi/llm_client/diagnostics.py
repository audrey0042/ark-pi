import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ark_pi.llm_client.factory import create_llm_client
from ark_pi.llm_client.types import LlmClient, LlmRequest

if TYPE_CHECKING:
    from ark_pi.config import ArkSettings

DEFAULT_DIAGNOSTIC_PROMPT = "Reply with: ark-pi-ok"

LlmClientFactory = Callable[..., LlmClient]


@dataclass(frozen=True)
class LlmPassiveStatus:
    backend: str
    model: str
    base_url_configured: bool
    base_url_display: str | None
    timeout_seconds: float
    max_tokens: int
    temperature: float
    network_check_performed: bool
    message: str


@dataclass(frozen=True)
class LlmActiveTestResult:
    backend: str
    model: str
    ok: bool
    output_text: str
    latency_ms: int | None
    error: str | None
    message: str


def _base_url_configured(base_url: str) -> bool:
    return bool(base_url.strip())


def _display_base_url(base_url: str) -> str:
    return base_url.strip().rstrip("/")


def _passive_message(backend: str, base_url_configured: bool, base_url_display: str | None) -> str:
    if backend == "mock":
        return "Mock LLM backend is configured. Passive status does not contact any LLM server."
    if backend == "openai-compatible":
        if base_url_configured and base_url_display is not None:
            return (
                f"OpenAI-compatible backend is configured for {base_url_display}. "
                "Use an explicit LLM test to contact the server."
            )
        return (
            "OpenAI-compatible backend is selected but ARK_LLM_BASE_URL is not configured."
        )
    return f"Configured LLM backend: {backend!r}."


def llm_passive_status(settings: "ArkSettings | None" = None) -> LlmPassiveStatus:
    """Return configured LLM settings without making a network call."""
    if settings is None:
        from ark_pi.config import get_settings

        settings = get_settings()

    backend = settings.llm_backend
    base_url = settings.llm_base_url
    configured = _base_url_configured(base_url)
    display = _display_base_url(base_url) if configured else None

    return LlmPassiveStatus(
        backend=backend,
        model=settings.llm_model,
        base_url_configured=configured,
        base_url_display=display,
        timeout_seconds=settings.llm_timeout_seconds,
        max_tokens=settings.llm_max_tokens,
        temperature=settings.llm_temperature,
        network_check_performed=False,
        message=_passive_message(backend, configured, display),
    )


def run_llm_active_test(
    *,
    prompt: str = DEFAULT_DIAGNOSTIC_PROMPT,
    backend: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    timeout_seconds: float | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    settings: "ArkSettings | None" = None,
    client_factory: LlmClientFactory = create_llm_client,
) -> LlmActiveTestResult:
    """Run an explicit LLM diagnostic test, raising on configuration or transport failures."""
    if settings is None:
        from ark_pi.config import get_settings

        settings = get_settings()

    resolved_backend = backend if backend is not None else settings.llm_backend
    resolved_base_url = settings.llm_base_url if base_url is None else base_url
    resolved_model = settings.llm_model if model is None else model
    resolved_timeout = (
        settings.llm_timeout_seconds if timeout_seconds is None else timeout_seconds
    )
    resolved_max_tokens = settings.llm_max_tokens if max_tokens is None else max_tokens
    resolved_temperature = settings.llm_temperature if temperature is None else temperature

    client = client_factory(
        resolved_backend,
        base_url=resolved_base_url,
        timeout_seconds=resolved_timeout,
    )
    request = LlmRequest(
        prompt=prompt,
        model=resolved_model,
        max_tokens=resolved_max_tokens,
        temperature=resolved_temperature,
    )

    started = time.perf_counter()
    response = client.complete(request)
    latency_ms = int((time.perf_counter() - started) * 1000)
    resolved_model_name = response.model or resolved_model
    return LlmActiveTestResult(
        backend=response.backend,
        model=resolved_model_name,
        ok=True,
        output_text=response.text,
        latency_ms=latency_ms,
        error=None,
        message=f"LLM diagnostic test succeeded for backend {response.backend!r}.",
    )
