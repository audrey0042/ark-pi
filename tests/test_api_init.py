from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from ark_pi.config import clear_settings_cache
from ark_pi.init import SAMPLE_SOURCE_FILENAME
from ark_pi.web.app import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture
def unset_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    source = tmp_path / "sources"
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("ARK_SOURCE_DIR", str(source))
    monkeypatch.setenv("ARK_LLM_BACKEND", "mock")
    monkeypatch.setenv("ARK_INDEX_BACKEND", "simple")
    clear_settings_cache()
    yield workspace, source
    clear_settings_cache()


def test_api_init_creates_local_directories(
    client: TestClient,
    unset_env: tuple[Path, Path],
) -> None:
    workspace, source = unset_env

    response = client.post("/api/init", json={})

    assert response.status_code == 200
    data = response.json()
    assert workspace.is_dir()
    assert (workspace / "indexes").is_dir()
    assert source.is_dir()
    assert str(workspace) in data["created_paths"]
    assert isinstance(data["message"], str)


def test_api_init_with_create_sample_source_creates_sample(
    client: TestClient,
    unset_env: tuple[Path, Path],
) -> None:
    _workspace, source = unset_env

    response = client.post(
        "/api/init",
        json={"create_sample_source": True},
    )

    assert response.status_code == 200
    data = response.json()
    sample_path = source / SAMPLE_SOURCE_FILENAME
    assert sample_path.is_file()
    assert data["sample_source_path"] == str(sample_path)


def test_api_init_returns_preflight_response(
    client: TestClient,
    unset_env: tuple[Path, Path],
) -> None:
    response = client.post("/api/init", json={})

    assert response.status_code == 200
    preflight = response.json()["preflight"]
    assert preflight["overall_status"] in {"ready", "warning", "blocked"}
    assert preflight["network_checks_performed"] is False
    assert isinstance(preflight["checks"], list)
    assert len(preflight["checks"]) >= 8


def test_api_init_invalid_catalog_without_force_returns_400(
    client: TestClient,
    unset_env: tuple[Path, Path],
) -> None:
    workspace, _source = unset_env
    workspace.mkdir(parents=True)
    (workspace / "catalog.json").write_text("{bad", encoding="utf-8")

    response = client.post("/api/init", json={})

    assert response.status_code == 400
    assert "Invalid workspace catalog" in response.json()["detail"]


def test_api_init_does_not_call_llm(
    client: TestClient,
    unset_env: tuple[Path, Path],
) -> None:
    with patch("ark_pi.llm_client.openai_compat.httpx.post") as post:
        response = client.post("/api/init", json={})

    post.assert_not_called()
    assert response.status_code == 200
