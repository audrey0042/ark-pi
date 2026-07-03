import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from ark_pi.rag import index as rag_index
from ark_pi.web.app import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _write_chunks(path: Path) -> None:
    record = {
        "id": "sample:000000:abc123def456",
        "title": "Sample",
        "source": "sample.txt",
        "chunk_index": 0,
        "text": "The RAG Pi owns retrieval and prompt assembly.",
        "sha256": "abc123def456789012345678901234567890123456789012345678901234567890",
    }
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")


def _build_index(tmp_path: Path) -> Path:
    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "index"
    _write_chunks(chunks_path)
    rag_index.build_index(chunks_path, index_dir)
    return index_dir


def test_create_app_without_chromadb() -> None:
    app = create_app()
    assert app.title == "Ark Pi RAG API"


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "ark-pi"


def test_api_status_does_not_probe_paths_or_network(client: TestClient) -> None:
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "ark-pi"
    assert "role" in data
    assert "paths" in data
    assert "config" in data
    assert "llm_backend" in data["config"]
    assert "llm" in data
    assert data["llm"]["network_check_performed"] is False


def test_api_search_happy_path(client: TestClient, tmp_path: Path) -> None:
    index_dir = _build_index(tmp_path)
    response = client.post(
        "/api/search",
        json={
            "index_dir": str(index_dir),
            "query": "prompt assembly",
            "limit": 3,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "prompt assembly"
    assert len(data["results"]) == 1
    item = data["results"][0]
    assert item["rank"] == 1
    assert item["id"] == "sample:000000:abc123def456"
    assert item["title"] == "Sample"
    assert "prompt assembly" in item["text"]


def test_api_search_no_matches(client: TestClient, tmp_path: Path) -> None:
    index_dir = _build_index(tmp_path)
    response = client.post(
        "/api/search",
        json={
            "index_dir": str(index_dir),
            "query": "quantum physics",
        },
    )
    assert response.status_code == 200
    assert response.json()["results"] == []


def test_api_ask_default_uses_mock_backend(client: TestClient, tmp_path: Path) -> None:
    index_dir = _build_index(tmp_path)
    response = client.post(
        "/api/ask",
        json={
            "index_dir": str(index_dir),
            "question": "Which Pi owns prompt assembly?",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "Mock LLM backend" in data["answer"]
    assert data["retrieved_count"] == 1
    assert "context" not in data
    assert "prompt" not in data


def test_api_ask_no_matches_does_not_call_llm(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index_dir = _build_index(tmp_path)
    calls: list[object] = []

    def fake_complete(_self: object, _request: object) -> object:
        calls.append(_request)
        raise AssertionError("LLM client should not be called when there are no matches")

    monkeypatch.setattr(
        "ark_pi.llm_client.mock.MockLlmClient.complete",
        fake_complete,
    )

    response = client.post(
        "/api/ask",
        json={
            "index_dir": str(index_dir),
            "question": "quantum physics",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["retrieved_count"] == 0
    assert data["answer"] == "No relevant context found."
    assert calls == []


def test_api_ask_include_context_true(client: TestClient, tmp_path: Path) -> None:
    index_dir = _build_index(tmp_path)
    response = client.post(
        "/api/ask",
        json={
            "index_dir": str(index_dir),
            "question": "prompt assembly",
            "include_context": True,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "context" in data
    assert len(data["context"]) == 1
    assert data["context"][0]["rank"] == 1


def test_api_ask_include_context_false(client: TestClient, tmp_path: Path) -> None:
    index_dir = _build_index(tmp_path)
    response = client.post(
        "/api/ask",
        json={
            "index_dir": str(index_dir),
            "question": "prompt assembly",
            "include_context": False,
        },
    )
    assert response.status_code == 200
    assert "context" not in response.json()


def test_api_ask_include_prompt_true(client: TestClient, tmp_path: Path) -> None:
    index_dir = _build_index(tmp_path)
    response = client.post(
        "/api/ask",
        json={
            "index_dir": str(index_dir),
            "question": "prompt assembly",
            "include_prompt": True,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "prompt" in data
    assert "Context:" in data["prompt"]


def test_api_ask_include_prompt_false(client: TestClient, tmp_path: Path) -> None:
    index_dir = _build_index(tmp_path)
    response = client.post(
        "/api/ask",
        json={
            "index_dir": str(index_dir),
            "question": "prompt assembly",
            "include_prompt": False,
        },
    )
    assert response.status_code == 200
    assert "prompt" not in response.json()


def test_api_search_invalid_index_dir(client: TestClient, tmp_path: Path) -> None:
    missing = tmp_path / "missing_index"
    response = client.post(
        "/api/search",
        json={
            "index_dir": str(missing),
            "query": "test",
        },
    )
    assert response.status_code == 400
    data = response.json()
    assert data["error"] == "index_error"
    assert "detail" in data


def test_api_search_invalid_limit(client: TestClient, tmp_path: Path) -> None:
    index_dir = _build_index(tmp_path)
    response = client.post(
        "/api/search",
        json={
            "index_dir": str(index_dir),
            "query": "test",
            "limit": 0,
        },
    )
    assert response.status_code == 422


def test_api_search_chroma_without_chromadb(client: TestClient, tmp_path: Path) -> None:
    index_dir = tmp_path / "chroma_index"
    index_dir.mkdir()
    manifest = {
        "backend": "chroma",
        "schema_version": 1,
        "chunk_count": 0,
        "created_by": "ark-pi",
    }
    (index_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    import builtins

    original_import = builtins.__import__

    def blocked_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "chromadb" or name.startswith("chromadb."):
            raise ImportError("chromadb is not installed")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=blocked_import):
        response = client.post(
            "/api/search",
            json={
                "index_dir": str(index_dir),
                "query": "test",
                "backend": "chroma",
            },
        )

    assert response.status_code == 400
    data = response.json()
    assert data["error"] == "index_error"
    assert "pip install -e '.[chroma]'" in data["detail"]
