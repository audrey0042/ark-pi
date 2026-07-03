from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from ark_pi.config import clear_settings_cache
from ark_pi.web.app import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_api_llm_status_returns_config_summary_without_network(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_LLM_BACKEND", "mock")
    clear_settings_cache()

    with patch("ark_pi.llm_client.openai_compat.httpx.post") as post:
        response = client.get("/api/llm/status")

    post.assert_not_called()
    assert response.status_code == 200
    data = response.json()
    assert data["backend"] == "mock"
    assert data["network_check_performed"] is False
    assert "message" in data


def test_api_llm_test_mock_backend_returns_ok_true(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_LLM_BACKEND", "mock")
    clear_settings_cache()

    response = client.post("/api/llm/test", json={"backend": "mock"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["backend"] == "mock"
    assert "Mock LLM backend" in data["output_text"]
    assert data["latency_ms"] is not None


def test_api_llm_test_openai_compatible_missing_base_url_returns_400(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_LLM_BACKEND", "openai-compatible")
    monkeypatch.setenv("ARK_LLM_BASE_URL", "")
    clear_settings_cache()

    response = client.post("/api/llm/test", json={})
    assert response.status_code == 400
    assert "base_url" in response.json()["detail"]


def test_api_llm_test_transport_error_returns_502(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(*_args: object, **_kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", fake_post)

    response = client.post(
        "/api/llm/test",
        json={
            "backend": "openai-compatible",
            "base_url": "http://127.0.0.1:8080",
        },
    )
    assert response.status_code == 502
    assert "connection refused" in response.json()["detail"]


def test_api_status_includes_passive_llm_summary_without_network(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_LLM_BACKEND", "mock")
    clear_settings_cache()

    with patch("ark_pi.llm_client.openai_compat.httpx.post") as post:
        response = client.get("/api/status")

    post.assert_not_called()
    assert response.status_code == 200
    data = response.json()
    assert "llm" in data
    assert data["llm"]["backend"] == "mock"
    assert data["llm"]["network_check_performed"] is False
