import json

import httpx
import pytest

from ark_pi.llm_client.factory import create_llm_client
from ark_pi.llm_client.mock import MockLlmClient
from ark_pi.llm_client.openai_compat import OpenAiCompatibleClient
from ark_pi.llm_client.types import (
    LlmConfigurationError,
    LlmRequest,
    LlmResponseError,
    LlmTransportError,
)


def test_mock_returns_deterministic_response() -> None:
    client = MockLlmClient()
    request = LlmRequest(prompt="hello world")
    response = client.complete(request)

    assert response.text == (
        "Mock LLM backend: no real model was called.\n"
        "\n"
        "Received a prompt with 11 characters.\n"
        "This confirms retrieval, prompt assembly, and LLM client wiring are connected."
    )
    assert response.backend == "mock"


def test_mock_backend_name() -> None:
    client = MockLlmClient()
    response = client.complete(LlmRequest(prompt="test"))
    assert response.backend == "mock"


def test_factory_creates_mock_client() -> None:
    client = create_llm_client("mock")
    response = client.complete(LlmRequest(prompt="ping"))
    assert response.backend == "mock"
    assert "Mock LLM backend" in response.text


def test_factory_rejects_unknown_backend() -> None:
    with pytest.raises(LlmConfigurationError, match="Unknown LLM backend"):
        create_llm_client("unknown")


def test_openai_compatible_without_base_url_raises_configuration_error() -> None:
    with pytest.raises(LlmConfigurationError, match="base_url"):
        create_llm_client("openai-compatible")


def test_openai_compatible_parses_valid_response(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "choices": [{"message": {"content": "Generated answer"}}],
    }

    def fake_post(*_args: object, **_kwargs: object) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json=payload,
            request=httpx.Request("POST", "http://example.test/v1/chat/completions"),
        )

    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", fake_post)

    client = OpenAiCompatibleClient(base_url="http://example.test")
    response = client.complete(LlmRequest(prompt="Question?"))

    assert response.text == "Generated answer"
    assert response.backend == "openai-compatible"


def test_openai_compatible_timeout_raises_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(*_args: object, **_kwargs: object) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", fake_post)

    client = OpenAiCompatibleClient(base_url="http://example.test", timeout_seconds=1.0)
    with pytest.raises(LlmTransportError, match="timed out"):
        client.complete(LlmRequest(prompt="Question?"))


def test_openai_compatible_non_2xx_raises_response_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(*_args: object, **_kwargs: object) -> httpx.Response:
        return httpx.Response(
            status_code=500,
            text="server error",
            request=httpx.Request("POST", "http://example.test/v1/chat/completions"),
        )

    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", fake_post)

    client = OpenAiCompatibleClient(base_url="http://example.test")
    with pytest.raises(LlmResponseError, match="HTTP 500"):
        client.complete(LlmRequest(prompt="Question?"))


def test_openai_compatible_malformed_json_raises_response_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(*_args: object, **_kwargs: object) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            content=b"not-json",
            request=httpx.Request("POST", "http://example.test/v1/chat/completions"),
        )

    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", fake_post)

    client = OpenAiCompatibleClient(base_url="http://example.test")
    with pytest.raises(LlmResponseError, match="valid JSON"):
        client.complete(LlmRequest(prompt="Question?"))


def test_openai_compatible_missing_content_raises_response_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(*_args: object, **_kwargs: object) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={"choices": [{"message": {}}]},
            request=httpx.Request("POST", "http://example.test/v1/chat/completions"),
        )

    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", fake_post)

    client = OpenAiCompatibleClient(base_url="http://example.test")
    with pytest.raises(LlmResponseError, match="choices"):
        client.complete(LlmRequest(prompt="Question?"))


def test_openai_compatible_empty_base_url_raises_configuration_error() -> None:
    with pytest.raises(LlmConfigurationError, match="base_url"):
        OpenAiCompatibleClient(base_url="   ")
