from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from ark_pi.config import clear_settings_cache
from ark_pi.web.app import create_app

SAMPLE_TEXT = (
    "Ark Pi splits work across two Raspberry Pis. "
    "The RAG Pi owns document ingestion, chunking, indexing, retrieval, and prompt assembly. "
    "The LLM Pi runs llama.cpp and generates text from assembled prompts."
)


@pytest.fixture
def workspace_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ws = tmp_path / "workspace"
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(ws))
    clear_settings_cache()
    yield ws
    clear_settings_cache()


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_list_indexes_empty_when_no_catalog(client: TestClient, workspace_env) -> None:
    response = client.get("/api/indexes")
    assert response.status_code == 200
    assert response.json()["indexes"] == []


def test_workspace_ingest_builds_index_and_updates_catalog(
    client: TestClient,
    workspace_env,
) -> None:
    response = client.post(
        "/api/ingest/text",
        json={
            "title": "Ark Pi overview",
            "text": SAMPLE_TEXT,
            "index_name": "My Index",
            "use_workspace": True,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["index_name"] == "My Index"
    assert data["index_slug"] == "my-index"
    assert data["catalog_updated"] is True
    assert data["chunk_count"] >= 1
    assert (workspace_env / "catalog.json").is_file()
    assert (workspace_env / "indexes" / "my-index" / "index" / "manifest.json").is_file()


def test_list_and_get_index_after_ingest(client: TestClient, workspace_env) -> None:
    ingest = client.post(
        "/api/ingest/text",
        json={
            "title": "Overview",
            "text": SAMPLE_TEXT,
            "index_name": "sample",
            "use_workspace": True,
        },
    )
    assert ingest.status_code == 200

    listed = client.get("/api/indexes")
    assert listed.status_code == 200
    indexes = listed.json()["indexes"]
    assert len(indexes) == 1
    assert indexes[0]["slug"] == "sample"

    detail = client.get("/api/indexes/sample")
    assert detail.status_code == 200
    assert detail.json()["name"] == "sample"


def test_search_and_ask_against_workspace_index(client: TestClient, workspace_env) -> None:
    ingest = client.post(
        "/api/ingest/text",
        json={
            "title": "Overview",
            "text": SAMPLE_TEXT,
            "index_name": "sample",
            "use_workspace": True,
        },
    )
    index_dir = ingest.json()["index_dir"]

    search = client.post(
        "/api/search",
        json={"index_dir": index_dir, "query": "prompt assembly", "limit": 3},
    )
    assert search.status_code == 200
    assert len(search.json()["results"]) >= 1

    ask = client.post(
        "/api/ask",
        json={"index_dir": index_dir, "question": "Which Pi owns prompt assembly?"},
    )
    assert ask.status_code == 200
    assert "Mock LLM backend" in ask.json()["answer"]


def test_rebuild_workspace_index_without_force_returns_400(
    client: TestClient,
    workspace_env,
) -> None:
    payload = {
        "title": "Overview",
        "text": SAMPLE_TEXT,
        "index_name": "sample",
        "use_workspace": True,
    }
    first = client.post("/api/ingest/text", json=payload)
    assert first.status_code == 200

    second = client.post("/api/ingest/text", json=payload)
    assert second.status_code == 400
    assert "already exists" in second.json()["detail"]


def test_rebuild_workspace_index_with_force_succeeds(
    client: TestClient,
    workspace_env,
) -> None:
    payload = {
        "title": "Overview",
        "text": SAMPLE_TEXT,
        "index_name": "sample",
        "use_workspace": True,
    }
    first = client.post("/api/ingest/text", json=payload)
    assert first.status_code == 200

    second = client.post("/api/ingest/text", json={**payload, "force": True})
    assert second.status_code == 200


def test_get_missing_index_returns_404(client: TestClient, workspace_env) -> None:
    response = client.get("/api/indexes/missing")
    assert response.status_code == 404
    data = response.json()
    assert data["error"] == "not_found"


def test_traversal_index_name_returns_400(client: TestClient, workspace_env) -> None:
    response = client.post(
        "/api/ingest/text",
        json={
            "title": "Bad",
            "text": SAMPLE_TEXT,
            "index_name": "../escape",
            "use_workspace": True,
        },
    )
    assert response.status_code == 400


def test_chroma_workspace_ingest_without_chromadb(client: TestClient, workspace_env) -> None:
    import builtins

    original_import = builtins.__import__

    def blocked_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "chromadb" or name.startswith("chromadb."):
            raise ImportError("chromadb is not installed")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=blocked_import):
        response = client.post(
            "/api/ingest/text",
            json={
                "title": "Overview",
                "text": SAMPLE_TEXT,
                "index_name": "sample",
                "use_workspace": True,
                "backend": "chroma",
            },
        )

    assert response.status_code == 400
    assert "pip install -e '.[chroma]'" in response.json()["detail"]
