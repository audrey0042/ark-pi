import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from ark_pi.web.app import create_app
from ark_pi.config import clear_settings_cache

SAMPLE_TEXT = (
    "Ark Pi splits work across two Raspberry Pis. "
    "The RAG Pi owns document ingestion, chunking, indexing, retrieval, and prompt assembly. "
    "The LLM Pi runs llama.cpp and generates text from assembled prompts."
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _ingest_payload(tmp_path: Path, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "title": "Ark Pi overview",
        "text": SAMPLE_TEXT,
        "use_workspace": False,
        "chunks_path": str(tmp_path / "chunks.jsonl"),
        "index_dir": str(tmp_path / "index"),
    }
    payload.update(overrides)
    return payload


def test_ingest_text_happy_path_creates_chunks_and_index(
    client: TestClient,
    tmp_path: Path,
) -> None:
    payload = _ingest_payload(tmp_path)
    response = client.post("/api/ingest/text", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Ark Pi overview"
    assert data["chunks_path"] == payload["chunks_path"]
    assert data["index_dir"] == payload["index_dir"]
    assert data["backend"] == "simple"
    assert data["source_count"] == 1
    assert data["chunk_count"] >= 1
    assert "message" in data
    assert Path(data["chunks_path"]).is_file()
    assert (Path(data["index_dir"]) / "manifest.json").is_file()


def test_ingest_text_index_is_searchable(client: TestClient, tmp_path: Path) -> None:
    payload = _ingest_payload(tmp_path)
    ingest = client.post("/api/ingest/text", json=payload)
    assert ingest.status_code == 200
    index_dir = ingest.json()["index_dir"]

    search = client.post(
        "/api/search",
        json={"index_dir": index_dir, "query": "prompt assembly", "limit": 3},
    )
    assert search.status_code == 200
    results = search.json()["results"]
    assert len(results) >= 1
    assert any("prompt assembly" in item["text"] for item in results)


def test_ingest_text_index_is_askable_with_mock_backend(
    client: TestClient,
    tmp_path: Path,
) -> None:
    payload = _ingest_payload(tmp_path)
    ingest = client.post("/api/ingest/text", json=payload)
    assert ingest.status_code == 200
    index_dir = ingest.json()["index_dir"]

    ask = client.post(
        "/api/ask",
        json={"index_dir": index_dir, "question": "Which Pi owns prompt assembly?"},
    )
    assert ask.status_code == 200
    data = ask.json()
    assert "Mock LLM backend" in data["answer"]
    assert data["retrieved_count"] >= 1


def test_ingest_text_existing_chunks_without_force_returns_400(
    client: TestClient,
    tmp_path: Path,
) -> None:
    payload = _ingest_payload(tmp_path)
    first = client.post("/api/ingest/text", json=payload)
    assert first.status_code == 200

    second = client.post("/api/ingest/text", json=payload)
    assert second.status_code == 400
    data = second.json()
    assert data["error"] == "index_error"
    assert "already exists" in data["detail"]


def test_ingest_text_existing_chunks_with_force_succeeds(
    client: TestClient,
    tmp_path: Path,
) -> None:
    payload = _ingest_payload(tmp_path)
    first = client.post("/api/ingest/text", json=payload)
    assert first.status_code == 200

    second = client.post("/api/ingest/text", json={**payload, "force": True})
    assert second.status_code == 200
    assert second.json()["chunk_count"] >= 1


def test_ingest_text_empty_title_returns_422(client: TestClient, tmp_path: Path) -> None:
    payload = _ingest_payload(tmp_path, title="   ")
    response = client.post("/api/ingest/text", json=payload)
    assert response.status_code == 422


def test_ingest_text_whitespace_only_text_returns_422(
    client: TestClient,
    tmp_path: Path,
) -> None:
    payload = _ingest_payload(tmp_path, text="   \n\t  ")
    response = client.post("/api/ingest/text", json=payload)
    assert response.status_code == 422


def test_ingest_text_invalid_chunk_overlap_returns_400(
    client: TestClient,
    tmp_path: Path,
) -> None:
    payload = _ingest_payload(tmp_path, chunk_size=100, chunk_overlap=100)
    response = client.post("/api/ingest/text", json=payload)
    assert response.status_code == 400
    data = response.json()
    assert data["error"] == "index_error"
    assert "chunk-overlap" in data["detail"]


def test_ingest_text_chroma_without_chromadb(
    client: TestClient,
    tmp_path: Path,
) -> None:
    payload = _ingest_payload(tmp_path, backend="chroma")

    import builtins

    original_import = builtins.__import__

    def blocked_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "chromadb" or name.startswith("chromadb."):
            raise ImportError("chromadb is not installed")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=blocked_import):
        response = client.post("/api/ingest/text", json=payload)

    assert response.status_code == 400
    data = response.json()
    assert data["error"] == "index_dependency_missing"
    assert "pip install -e '.[chroma]'" in data["detail"]


def test_ingest_text_workspace_mode_happy_path(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = tmp_path / "workspace"
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(ws))
    clear_settings_cache()
    response = client.post(
        "/api/ingest/text",
        json={
            "title": "Overview",
            "text": SAMPLE_TEXT,
            "index_name": "sample",
            "use_workspace": True,
        },
    )
    clear_settings_cache()
    assert response.status_code == 200
    data = response.json()
    assert data["index_slug"] == "sample"
    assert data["catalog_updated"] is True
    assert (ws / "catalog.json").is_file()
