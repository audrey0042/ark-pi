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
def source_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    src = tmp_path / "sources"
    src.mkdir()
    monkeypatch.setenv("ARK_SOURCE_DIR", str(src))
    clear_settings_cache()
    yield src
    clear_settings_cache()


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


def test_path_ingest_happy_path_creates_named_index(
    client: TestClient,
    source_env: Path,
    workspace_env: Path,
) -> None:
    (source_env / "sample.txt").write_text(SAMPLE_TEXT, encoding="utf-8")

    response = client.post(
        "/api/ingest/path",
        json={"index_name": "local-sample", "source_path": "sample.txt"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["index_name"] == "local-sample"
    assert data["index_slug"] == "local-sample"
    assert data["source_count"] == 1
    assert data["chunk_count"] >= 1
    assert data["catalog_updated"] is True
    assert (workspace_env / "catalog.json").is_file()


def test_path_ingest_lists_created_index(
    client: TestClient,
    source_env: Path,
    workspace_env: Path,
) -> None:
    (source_env / "sample.txt").write_text(SAMPLE_TEXT, encoding="utf-8")
    ingest = client.post(
        "/api/ingest/path",
        json={"index_name": "local-sample", "source_path": "sample.txt"},
    )
    assert ingest.status_code == 200

    listed = client.get("/api/indexes")
    assert listed.status_code == 200
    indexes = listed.json()["indexes"]
    assert len(indexes) == 1
    assert indexes[0]["slug"] == "local-sample"


def test_path_ingest_search_and_ask(
    client: TestClient,
    source_env: Path,
    workspace_env: Path,
) -> None:
    (source_env / "sample.txt").write_text(SAMPLE_TEXT, encoding="utf-8")
    ingest = client.post(
        "/api/ingest/path",
        json={"index_name": "local-sample", "source_path": "sample.txt"},
    )
    assert ingest.status_code == 200
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


def test_path_ingest_directory_of_txt_files(
    client: TestClient,
    source_env: Path,
    workspace_env: Path,
) -> None:
    docs = source_env / "docs"
    docs.mkdir()
    (docs / "a.txt").write_text("First document about retrieval.", encoding="utf-8")
    (docs / "b.txt").write_text("Second document about indexing.", encoding="utf-8")

    response = client.post(
        "/api/ingest/path",
        json={"index_name": "docs-index", "source_path": "docs"},
    )
    assert response.status_code == 200
    assert response.json()["source_count"] == 2


def test_path_ingest_outside_source_dir_returns_400(
    client: TestClient,
    source_env: Path,
    workspace_env: Path,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text(SAMPLE_TEXT, encoding="utf-8")

    response = client.post(
        "/api/ingest/path",
        json={"index_name": "bad", "source_path": str(outside)},
    )
    assert response.status_code == 400
    assert "inside configured source_dir" in response.json()["detail"]


def test_path_ingest_unsupported_file_returns_400(
    client: TestClient,
    source_env: Path,
    workspace_env: Path,
) -> None:
    (source_env / "data.jsonl").write_text(
        '{"title":"T","text":"Body"}\n',
        encoding="utf-8",
    )

    response = client.post(
        "/api/ingest/path",
        json={"index_name": "bad", "source_path": "data.jsonl"},
    )
    assert response.status_code == 400
    assert "Only .txt files and directories" in response.json()["detail"]


def test_path_ingest_empty_directory_returns_400(
    client: TestClient,
    source_env: Path,
    workspace_env: Path,
) -> None:
    empty = source_env / "empty"
    empty.mkdir()

    response = client.post(
        "/api/ingest/path",
        json={"index_name": "bad", "source_path": "empty"},
    )
    assert response.status_code == 400
    assert "No .txt files found" in response.json()["detail"]


def test_path_ingest_chroma_without_chromadb(
    client: TestClient,
    source_env: Path,
    workspace_env: Path,
) -> None:
    (source_env / "sample.txt").write_text(SAMPLE_TEXT, encoding="utf-8")

    import builtins

    original_import = builtins.__import__

    def blocked_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "chromadb" or name.startswith("chromadb."):
            raise ImportError("chromadb is not installed")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=blocked_import):
        response = client.post(
            "/api/ingest/path",
            json={
                "index_name": "sample",
                "source_path": "sample.txt",
                "backend": "chroma",
            },
        )

    assert response.status_code == 400
    assert "pip install -e '.[chroma]'" in response.json()["detail"]
