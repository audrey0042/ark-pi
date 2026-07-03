from unittest.mock import patch

import httpx
import pytest
from typer.testing import CliRunner

from ark_pi.cli import app
from ark_pi.config import ArkSettings, clear_settings_cache
from ark_pi.llm_client.diagnostics import (
    DEFAULT_DIAGNOSTIC_PROMPT,
    llm_passive_status,
    run_llm_active_test,
)
from ark_pi.llm_client.types import LlmConfigurationError, LlmTransportError

runner = CliRunner()


def test_passive_status_mock_backend_performs_no_network_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_LLM_BACKEND", "mock")
    clear_settings_cache()

    with patch("ark_pi.llm_client.openai_compat.httpx.post") as post:
        status = llm_passive_status()

    post.assert_not_called()
    assert status.backend == "mock"
    assert status.network_check_performed is False
    assert "Mock LLM backend" in status.message


def test_passive_status_openai_compatible_with_base_url_reports_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_LLM_BACKEND", "openai-compatible")
    monkeypatch.setenv("ARK_LLM_BASE_URL", "http://192.168.50.2:8080")
    clear_settings_cache()

    status = llm_passive_status()

    assert status.backend == "openai-compatible"
    assert status.base_url_configured is True
    assert status.base_url_display == "http://192.168.50.2:8080"
    assert status.network_check_performed is False


def test_passive_status_openai_compatible_without_base_url_reports_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_LLM_BACKEND", "openai-compatible")
    monkeypatch.setenv("ARK_LLM_BASE_URL", "   ")
    clear_settings_cache()

    status = llm_passive_status()

    assert status.backend == "openai-compatible"
    assert status.base_url_configured is False
    assert status.base_url_display is None
    assert "not configured" in status.message


def test_active_test_mock_backend_succeeds_deterministically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_LLM_BACKEND", "mock")
    clear_settings_cache()

    result = run_llm_active_test(prompt=DEFAULT_DIAGNOSTIC_PROMPT)

    assert result.ok is True
    assert result.backend == "mock"
    assert result.error is None
    assert "Mock LLM backend" in result.output_text
    assert result.latency_ms is not None


def test_active_test_propagates_configuration_failure() -> None:
    settings = ArkSettings(llm_backend="openai-compatible", llm_base_url="")

    with pytest.raises(LlmConfigurationError, match="base_url"):
        run_llm_active_test(settings=settings)


def test_active_test_handles_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(*_args: object, **_kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", fake_post)
    settings = ArkSettings(
        llm_backend="openai-compatible",
        llm_base_url="http://127.0.0.1:8080",
    )

    with pytest.raises(LlmTransportError, match="connection refused"):
        run_llm_active_test(settings=settings)


def test_llm_status_help() -> None:
    result = runner.invoke(app, ["llm", "status", "--help"])
    assert result.exit_code == 0
    assert "passive" in result.stdout.lower() or "LLM" in result.stdout


def test_llm_test_help() -> None:
    result = runner.invoke(app, ["llm", "test", "--help"])
    assert result.exit_code == 0
    assert "--prompt" in result.stdout
    assert "--llm-backend" in result.stdout


def test_llm_status_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARK_LLM_BACKEND", "mock")
    clear_settings_cache()

    result = runner.invoke(app, ["llm", "status"])
    assert result.exit_code == 0
    assert "mock" in result.stdout
    assert "network_check_performed" in result.stdout


def test_llm_status_does_not_require_base_url_in_mock_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_LLM_BACKEND", "mock")
    monkeypatch.delenv("ARK_LLM_BASE_URL", raising=False)
    clear_settings_cache()

    result = runner.invoke(app, ["llm", "status"])
    assert result.exit_code == 0


def test_llm_test_mock_backend_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    result = runner.invoke(
        app,
        ["llm", "test", "--llm-backend", "mock"],
    )
    assert result.exit_code == 0
    assert "ok" in result.stdout
    assert "Mock LLM backend" in result.stdout


def test_llm_test_openai_compatible_missing_base_url_exits_nonzero() -> None:
    result = runner.invoke(
        app,
        [
            "llm",
            "test",
            "--llm-backend",
            "openai-compatible",
            "--llm-base-url",
            "",
        ],
    )
    assert result.exit_code != 0
    assert "base_url" in result.stderr or "base_url" in result.stdout
