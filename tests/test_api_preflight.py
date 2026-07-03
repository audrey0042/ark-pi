from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from ark_pi.config import clear_settings_cache
from ark_pi.web.app import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture
def ready_env(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "workspace"
    source = tmp_path / "sources"
    workspace.mkdir()
    source.mkdir()
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("ARK_SOURCE_DIR", str(source))
    monkeypatch.setenv("ARK_LLM_BACKEND", "mock")
    monkeypatch.setenv("ARK_INDEX_BACKEND", "simple")
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_api_preflight_returns_response_shape(client: TestClient, ready_env: None) -> None:
    response = client.get("/api/preflight")
    assert response.status_code == 200
    data = response.json()
    assert data["overall_status"] in {"ready", "warning", "blocked"}
    assert data["network_checks_performed"] is False
    assert isinstance(data["checks"], list)
    assert len(data["checks"]) >= 8
    first = data["checks"][0]
    assert {"id", "label", "status", "message", "details"} <= set(first.keys())


def test_api_preflight_does_not_call_llm(client: TestClient, ready_env: None) -> None:
    with patch("ark_pi.llm_client.openai_compat.httpx.post") as post:
        response = client.get("/api/preflight")

    post.assert_not_called()
    assert response.status_code == 200


def test_api_preflight_blocked_still_returns_200(
    client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "catalog.json").write_text("{invalid", encoding="utf-8")
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("ARK_SOURCE_DIR", str(tmp_path / "sources"))
    clear_settings_cache()

    response = client.get("/api/preflight")
    assert response.status_code == 200
    assert response.json()["overall_status"] == "blocked"
