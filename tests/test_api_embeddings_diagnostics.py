from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from ark_pi.config import clear_settings_cache
from ark_pi.web.app import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_api_embeddings_status_returns_config_summary_without_network(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "mock")
    clear_settings_cache()

    with patch("ark_pi.embeddings.factory.create_embedder") as create:
        response = client.get("/api/embeddings/status")

    create.assert_not_called()
    assert response.status_code == 200
    data = response.json()
    assert data["backend"] == "mock"
    assert data["model_load_performed"] is False
    assert data["network_check_performed"] is False


def test_api_embeddings_test_mock_backend_returns_ok_true(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "mock")
    clear_settings_cache()

    response = client.post("/api/embeddings/test", json={})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["backend"] == "mock"
    assert data["texts_embedded"] == 3
    assert data["vectors_finite"] is True


def test_api_embeddings_test_missing_model_path_returns_400(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing-model"
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "sentence-transformers")
    monkeypatch.setenv("ARK_EMBEDDING_MODEL_PATH", str(missing))
    clear_settings_cache()

    response = client.post("/api/embeddings/test", json={})
    assert response.status_code == 400
    assert "does not exist" in response.json()["detail"]


def test_api_status_includes_passive_embeddings_summary_without_network(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "mock")
    clear_settings_cache()

    with patch("ark_pi.embeddings.factory.create_embedder") as create:
        response = client.get("/api/status")

    create.assert_not_called()
    assert response.status_code == 200
    data = response.json()
    assert "embeddings" in data
    assert data["embeddings"]["backend"] == "mock"
    assert data["embeddings"]["model_load_performed"] is False
