from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ark_pi.config import ArkSettings, get_settings, load_settings_from_env_file
from ark_pi.llm_client.diagnostics import (
    DEFAULT_DIAGNOSTIC_PROMPT,
    llm_passive_status,
    run_llm_active_test,
)

EXPECTED_DIAGNOSTIC_OUTPUT = "ark-pi-ok"


@dataclass(frozen=True)
class ApplianceSmokeResult:
    role: str
    backend: str
    model: str
    base_url: str | None
    timeout_seconds: float
    ok: bool
    output_text: str
    latency_ms: int | None
    message: str
    network_check_performed: bool = True


def _output_matches_expected(text: str) -> bool:
    return EXPECTED_DIAGNOSTIC_OUTPUT in text


def _resolve_settings(env_file: Path | None) -> ArkSettings:
    if env_file is not None:
        return load_settings_from_env_file(env_file)
    return get_settings()


def run_appliance_smoke(
    *,
    env_file: Path | None = None,
    llm_base_url: str | None = None,
    timeout_seconds: float | None = None,
) -> ApplianceSmokeResult:
    """Run an explicit RAG-to-LLM smoke test using the configured backend."""
    settings = _resolve_settings(env_file)
    passive = llm_passive_status(settings)

    test_result = run_llm_active_test(
        prompt=DEFAULT_DIAGNOSTIC_PROMPT,
        settings=settings,
        base_url=llm_base_url,
        timeout_seconds=timeout_seconds,
    )

    output_ok = _output_matches_expected(test_result.output_text)
    if output_ok:
        message = (
            f"Appliance smoke succeeded: LLM returned expected output "
            f"{EXPECTED_DIAGNOSTIC_OUTPUT!r}."
        )
    else:
        message = (
            f"Appliance smoke failed: expected output to contain "
            f"{EXPECTED_DIAGNOSTIC_OUTPUT!r}, got {test_result.output_text!r}."
        )

    return ApplianceSmokeResult(
        role=settings.role,
        backend=passive.backend,
        model=passive.model,
        base_url=passive.base_url_display,
        timeout_seconds=passive.timeout_seconds,
        ok=output_ok,
        output_text=test_result.output_text,
        latency_ms=test_result.latency_ms,
        message=message,
    )


def appliance_smoke_to_dict(result: ApplianceSmokeResult) -> dict[str, Any]:
    return {
        "role": result.role,
        "backend": result.backend,
        "model": result.model,
        "base_url": result.base_url,
        "timeout_seconds": result.timeout_seconds,
        "ok": result.ok,
        "output_text": result.output_text,
        "latency_ms": result.latency_ms,
        "message": result.message,
        "network_check_performed": result.network_check_performed,
    }
