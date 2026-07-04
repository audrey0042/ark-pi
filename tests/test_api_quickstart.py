from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from ark_pi.config import clear_settings_cache
from ark_pi.quickstart import DEFAULT_INDEX_NAME
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


def test_api_quickstart_succeeds_with_defaults(
    client: TestClient,
    unset_env: tuple[Path, Path],
) -> None:
    response = client.post("/api/quickstart", json={})

    assert response.status_code == 200
    data = response.json()
    assert data["index_name"] == DEFAULT_INDEX_NAME
    assert data["chunk_count"] > 0


def test_api_quickstart_returns_index_info_and_ask_answer(
    client: TestClient,
    unset_env: tuple[Path, Path],
) -> None:
    response = client.post("/api/quickstart", json={})

    assert response.status_code == 200
    data = response.json()
    assert data["index_slug"]
    assert data["source_path"]
    assert data["chunks_path"]
    assert data["index_dir"]
    assert data["source_count"] >= 1
    assert data["retrieved_count"] > 0
    assert "Mock LLM backend" in data["ask_answer"]
    assert data["preflight"]["network_checks_performed"] is False


def test_api_quickstart_lists_index_afterward(
    client: TestClient,
    unset_env: tuple[Path, Path],
) -> None:
    client.post("/api/quickstart", json={})

    list_response = client.get("/api/indexes")
    assert list_response.status_code == 200
    slugs = [entry["slug"] for entry in list_response.json()["indexes"]]
    assert DEFAULT_INDEX_NAME in slugs


def test_api_quickstart_second_post_without_force_returns_400(
    client: TestClient,
    unset_env: tuple[Path, Path],
) -> None:
    first = client.post("/api/quickstart", json={})
    assert first.status_code == 200

    second = client.post("/api/quickstart", json={})
    assert second.status_code == 400
    assert "Index already exists" in second.json()["detail"]


def test_api_quickstart_with_force_succeeds(
    client: TestClient,
    unset_env: tuple[Path, Path],
) -> None:
    first = client.post("/api/quickstart", json={})
    assert first.status_code == 200

    second = client.post("/api/quickstart", json={"force": True})
    assert second.status_code == 200
    assert second.json()["index_slug"] == first.json()["index_slug"]


def test_api_quickstart_does_not_call_llm_network(
    client: TestClient,
    unset_env: tuple[Path, Path],
) -> None:
    with patch("ark_pi.llm_client.openai_compat.httpx.post") as post:
        response = client.post("/api/quickstart", json={})

    post.assert_not_called()
    assert response.status_code == 200
