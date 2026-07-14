import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ark_pi.config import clear_settings_cache
from ark_pi.embeddings.factory import clear_embedder_cache, create_embedder
from ark_pi.rag import chroma_index, index as rag_index
from ark_pi.rag.chroma_index import distance_to_score
from ark_pi.rag.index import SearchResult
from ark_pi.rag.semantic_index import (
    EmbeddingIdentity,
    SemanticIndexCompatibilityError,
    SemanticIndexDependencyMissing,
    SemanticIndexUnavailable,
    SemanticQueryEmbeddingFailed,
    compute_embedding_fingerprint,
    search_semantic,
    validate_embedding_compatibility,
)


@pytest.fixture(autouse=True)
def _clear_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_cache()
    clear_embedder_cache()
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "mock")
    monkeypatch.setenv("ARK_EMBEDDING_MODEL", "test-model")


def _mock_identity() -> EmbeddingIdentity:
    return EmbeddingIdentity(
        backend="mock",
        model_name="test-model",
        dimensions=8,
        normalizes_vectors=True,
    )


def _write_semantic_manifest(index_dir: Path, identity: EmbeddingIdentity) -> str:
    index_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = compute_embedding_fingerprint(identity)
    manifest = {
        "schema_version": 2,
        "backend": "chroma",
        "chunk_count": 2,
        "collection_name": "test",
        "source_chunks": "test.jsonl",
        "embedding": {
            **identity.to_dict(),
            "fingerprint": fingerprint,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        },
    }
    (index_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return fingerprint


def test_distance_to_score_cosine() -> None:
    assert distance_to_score(0.2, normalizes_vectors=True) == pytest.approx(0.8)


def test_distance_to_score_l2() -> None:
    assert distance_to_score(1.5, normalizes_vectors=False) == pytest.approx(-1.5)


def test_sort_search_results_stable_tie_ordering() -> None:
    results = [
        SearchResult(score=0.5, id="b", title="", source="", chunk_index=0, text=""),
        SearchResult(score=0.5, id="a", title="", source="", chunk_index=0, text=""),
        SearchResult(score=0.9, id="z", title="", source="", chunk_index=0, text=""),
    ]
    sorted_results = chroma_index._sort_search_results(results)
    assert [result.id for result in sorted_results] == ["z", "a", "b"]


def test_validate_embedding_compatibility_rejects_model_mismatch() -> None:
    existing = _mock_identity()
    requested = EmbeddingIdentity(
        backend="mock",
        model_name="other-model",
        dimensions=8,
        normalizes_vectors=True,
    )
    with pytest.raises(SemanticIndexCompatibilityError, match="model"):
        validate_embedding_compatibility(existing, requested)


def test_search_semantic_rejects_index_without_embedding_metadata(tmp_path: Path) -> None:
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    (index_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "backend": "chroma",
                "chunk_count": 0,
                "collection_name": "test",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SemanticIndexUnavailable, match="embedding metadata"):
        search_semantic(index_dir, "query", limit=3)


def test_search_semantic_rejects_embedding_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_EMBEDDING_MODEL", "wrong-model")
    index_dir = tmp_path / "index"
    _write_semantic_manifest(index_dir, _mock_identity())
    with pytest.raises(SemanticIndexCompatibilityError, match="model"):
        search_semantic(index_dir, "water purification", limit=3)


def test_search_semantic_rejects_empty_query(tmp_path: Path) -> None:
    index_dir = tmp_path / "index"
    _write_semantic_manifest(index_dir, _mock_identity())
    with pytest.raises(ValueError, match="empty"):
        rag_index.search_index(index_dir, "   ", limit=3)


def test_search_semantic_ranks_relevant_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index_dir = tmp_path / "index"
    identity = _mock_identity()
    _write_semantic_manifest(index_dir, identity)

    from ark_pi import config as ark_config

    embedder = create_embedder(ark_config.get_settings())
    related_vector = embedder.embed_query("water purification methods")
    unrelated_vector = embedder.embed_query("bicycle repair tips")

    def fake_query_by_vector(
        _index_dir: Path,
        query_vector: list[float],
        *,
        limit: int,
        normalizes_vectors: bool,
    ) -> list[SearchResult]:
        related_score = sum(a * b for a, b in zip(query_vector, related_vector, strict=True))
        unrelated_score = sum(a * b for a, b in zip(query_vector, unrelated_vector, strict=True))
        return chroma_index._sort_search_results(
            [
                SearchResult(
                    score=unrelated_score,
                    id="unrelated",
                    title="Bike",
                    source="bike.txt",
                    chunk_index=0,
                    text="bicycle repair tips",
                ),
                SearchResult(
                    score=related_score,
                    id="related",
                    title="Water",
                    source="water.txt",
                    chunk_index=0,
                    text="water purification methods",
                ),
            ]
        )[:limit]

    monkeypatch.setattr(chroma_index, "query_by_vector", fake_query_by_vector)
    execution = search_semantic(index_dir, "water purification", limit=2)
    assert execution.search_mode == "semantic"
    assert execution.results[0].id == "related"
    assert execution.results[0].score >= execution.results[1].score
    assert execution.embedding_fingerprint is not None
    assert execution.query_embedding_latency_ms is not None
    assert execution.search_latency_ms is not None


def test_lexical_search_unchanged(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "index"
    record = {
        "id": "sample:000000:abc123def456",
        "title": "Sample",
        "source": "sample.txt",
        "chunk_index": 0,
        "text": "The RAG Pi owns retrieval and prompt assembly.",
        "sha256": "abc123def456789012345678901234567890123456789012345678901234567890",
    }
    chunks_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    rag_index.build_index(chunks_path, index_dir)

    execution = rag_index.search_index(index_dir, "prompt assembly", limit=3)
    assert execution.search_mode == "lexical"
    assert execution.backend == "simple"
    assert execution.score_semantics == "lexical_term_frequency"
    assert len(execution.results) == 1
    assert execution.results[0].title == "Sample"


def test_missing_chromadb_dependency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ark_pi.rag.index import IndexDependencyError

    index_dir = tmp_path / "index"
    _write_semantic_manifest(index_dir, _mock_identity())

    def raise_dependency(*_args: object, **_kwargs: object) -> None:
        raise IndexDependencyError("chromadb is not installed")

    monkeypatch.setattr(chroma_index, "query_by_vector", raise_dependency)
    with pytest.raises(SemanticIndexDependencyMissing, match="chromadb"):
        search_semantic(index_dir, "query", limit=3)


def test_backend_override_conflict(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "index"
    record = {
        "id": "sample:000000:abc123def456",
        "title": "Sample",
        "source": "sample.txt",
        "chunk_index": 0,
        "text": "text",
        "sha256": "abc123def456789012345678901234567890123456789012345678901234567890",
    }
    chunks_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    rag_index.build_index(chunks_path, index_dir)
    with pytest.raises(rag_index.IndexConfigurationError, match="does not match"):
        rag_index.search_index(index_dir, "text", backend="chroma")


def test_api_semantic_search_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from ark_pi.web.app import create_app

    index_dir = tmp_path / "index"
    _write_semantic_manifest(index_dir, _mock_identity())

    def fake_query_by_vector(
        _index_dir: Path,
        _query_vector: list[float],
        *,
        limit: int,
        normalizes_vectors: bool,
    ) -> list[SearchResult]:
        return [
            SearchResult(
                score=0.9,
                id="doc-1",
                title="Water",
                source="water.txt",
                chunk_index=0,
                text="water purification",
            )
        ][:limit]

    monkeypatch.setattr(chroma_index, "query_by_vector", fake_query_by_vector)
    app = create_app()
    test_client = TestClient(app)
    response = test_client.post(
        "/api/search",
        json={"index_dir": str(index_dir), "query": "water", "limit": 3},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["search_mode"] == "semantic"
    assert data["backend"] == "chroma"
    assert data["embedding_fingerprint"] is not None
    assert data["score_semantics"] == "cosine_similarity"
    assert len(data["results"]) == 1


def test_api_semantic_incompatible_returns_409(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from ark_pi.web.app import create_app

    monkeypatch.setenv("ARK_EMBEDDING_MODEL", "wrong-model")
    index_dir = tmp_path / "index"
    _write_semantic_manifest(index_dir, _mock_identity())

    app = create_app()
    test_client = TestClient(app)
    response = test_client.post(
        "/api/search",
        json={"index_dir": str(index_dir), "query": "water", "limit": 3},
    )
    assert response.status_code == 409
    data = response.json()
    assert data["error"] == "semantic_index_incompatible"


def test_cli_semantic_search_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typer.testing import CliRunner

    from ark_pi.cli import app

    index_dir = tmp_path / "index"
    _write_semantic_manifest(index_dir, _mock_identity())

    def fake_query_by_vector(
        _index_dir: Path,
        _query_vector: list[float],
        *,
        limit: int,
        normalizes_vectors: bool,
    ) -> list[SearchResult]:
        return [
            SearchResult(
                score=0.88,
                id="doc-1",
                title="Water",
                source="water.txt",
                chunk_index=0,
                text="water purification",
            )
        ][:limit]

    monkeypatch.setattr(chroma_index, "query_by_vector", fake_query_by_vector)
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "index",
            "search",
            "--index-dir",
            str(index_dir),
            "--query",
            "water",
            "--json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["search_mode"] == "semantic"
    assert payload["backend"] == "chroma"
    assert payload["result_count"] == 1
    assert payload["results"][0]["rank"] == 1


def test_query_embedding_failure_maps_to_semantic_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index_dir = tmp_path / "index"
    _write_semantic_manifest(index_dir, _mock_identity())

    from ark_pi.embeddings.errors import EmbeddingInvalidVector

    class BrokenEmbedder:
        backend_name = "mock"
        model_name = "test-model"
        dimensions = 8
        normalizes_vectors = True

        def embed_query(self, _text: str) -> list[float]:
            raise EmbeddingInvalidVector("embedding failed")

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [self.embed_query(text) for text in texts]

    monkeypatch.setattr(
        "ark_pi.rag.semantic_index.create_embedder",
        lambda *_args, **_kwargs: BrokenEmbedder(),
    )
    with pytest.raises(SemanticQueryEmbeddingFailed, match="embedding failed"):
        search_semantic(index_dir, "query", limit=3)


def test_real_chroma_semantic_search(tmp_path: Path) -> None:
    pytest.importorskip("chromadb")
    from ark_pi import config as ark_config
    from ark_pi.rag.index import ChunkDocument

    index_dir = tmp_path / "index"
    identity = _mock_identity()
    embedder = create_embedder(ark_config.get_settings())

    documents = [
        ChunkDocument(
            id="water",
            title="Water",
            source="water.txt",
            chunk_index=0,
            text="water purification and filtration methods",
            sha256="a" * 64,
        ),
        ChunkDocument(
            id="bike",
            title="Bike",
            source="bike.txt",
            chunk_index=0,
            text="bicycle repair and maintenance tips",
            sha256="b" * 64,
        ),
    ]
    embeddings = embedder.embed_documents([document.text for document in documents])
    chroma_index.append_documents(
        documents,
        index_dir,
        embeddings=embeddings,
        source_chunks="test.jsonl",
        embedding_identity=identity,
    )

    execution = rag_index.search_index(index_dir, "water purification", limit=2)
    assert execution.search_mode == "semantic"
    assert execution.results
    assert execution.results[0].id == "water"


def test_chroma_without_chromadb_api(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from ark_pi.web.app import create_app

    index_dir = tmp_path / "chroma_index"
    index_dir.mkdir()
    manifest = {
        "backend": "chroma",
        "schema_version": 1,
        "chunk_count": 0,
        "created_by": "ark-pi",
    }
    (index_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    original_import = __import__

    def blocked_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "chromadb" or name.startswith("chromadb."):
            raise ImportError("chromadb is not installed")
        return original_import(name, *args, **kwargs)

    app = create_app()
    test_client = TestClient(app)
    with patch("builtins.__import__", side_effect=blocked_import):
        response = test_client.post(
            "/api/search",
            json={
                "index_dir": str(index_dir),
                "query": "test",
                "backend": "chroma",
            },
        )

    assert response.status_code == 400
    data = response.json()
    assert data["error"] == "index_dependency_missing"
