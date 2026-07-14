import json
from pathlib import Path

import pytest

from ark_pi.config import clear_settings_cache
from ark_pi.corpus.checkpoint import (
    SCHEMA_VERSION_SEMANTIC,
    load_checkpoint,
    new_checkpoint,
    validate_checkpoint_compatibility,
    write_checkpoint,
)
from ark_pi.corpus.types import ChunkingConfig, CorpusSourceFormat
from ark_pi.embeddings.factory import clear_embedder_cache
from ark_pi.embeddings.mock import MockEmbedder
from ark_pi.rag.index import ChunkDocument, IndexStats
from ark_pi.rag.semantic_index import (
    EmbeddingIdentity,
    SemanticIndexCompatibilityError,
    compute_embedding_fingerprint,
    embed_and_validate,
    identity_from_embedder,
    identity_from_settings,
    validate_embedding_compatibility,
)


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    clear_settings_cache()
    clear_embedder_cache()


def _mock_identity() -> EmbeddingIdentity:
    return EmbeddingIdentity(
        backend="mock",
        model_name="test-model",
        dimensions=8,
        normalizes_vectors=True,
    )


def test_embedding_fingerprint_is_stable() -> None:
    identity = _mock_identity()
    first = compute_embedding_fingerprint(identity)
    second = compute_embedding_fingerprint(identity)
    assert first == second
    assert len(first) == 64


def test_validate_embedding_compatibility_rejects_dimension_mismatch() -> None:
    existing = _mock_identity()
    requested = EmbeddingIdentity(
        backend="mock",
        model_name="test-model",
        dimensions=384,
        normalizes_vectors=True,
    )
    with pytest.raises(SemanticIndexCompatibilityError, match="dimension"):
        validate_embedding_compatibility(existing, requested)


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


def test_embed_and_validate_batches_texts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "mock")
    embedder = MockEmbedder(model_name="mock", normalize=True)
    texts = [f"sample text number {index}" for index in range(5)]
    vectors = embed_and_validate(embedder, texts, batch_size=2)
    assert len(vectors) == 5
    assert all(len(vector) == 8 for vector in vectors)


def test_identity_from_embedder_matches_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "mock")
    from ark_pi.config import get_settings

    settings = get_settings()
    embedder = MockEmbedder(model_name=settings.embedding_model, normalize=True)
    identity = identity_from_embedder(embedder, settings)
    assert identity.backend == "mock"
    assert identity.dimensions == 8


def test_identity_from_settings_uses_mock_dimensions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "mock")
    from ark_pi.config import get_settings

    identity = identity_from_settings(get_settings())
    assert identity.dimensions == 8


def test_semantic_checkpoint_v2_round_trip(tmp_path: Path) -> None:
    ckpt = new_checkpoint(
        run_id="semantic-run",
        source="/tmp/sample.jsonl",
        source_format=CorpusSourceFormat.jsonl,
        source_fingerprint="abc123",
        index_slug="wiki-semantic",
        index_backend="chroma",
        chunking_config=ChunkingConfig(chunk_size=1000, chunk_overlap=200),
        batch_size=10,
        embedding_fingerprint="deadbeef" * 8,
    )
    path = tmp_path / "checkpoint.json"
    write_checkpoint(path, ckpt)
    loaded = load_checkpoint(path)
    assert loaded.schema_version == SCHEMA_VERSION_SEMANTIC
    assert loaded.embedding_fingerprint == "deadbeef" * 8
    assert loaded.records_embedded == 0


def test_validate_checkpoint_rejects_lexical_to_semantic_resume(tmp_path: Path) -> None:
    ckpt = new_checkpoint(
        run_id="lexical-run",
        source="/tmp/sample.jsonl",
        source_format=CorpusSourceFormat.jsonl,
        source_fingerprint="abc123",
        index_slug="wiki",
        index_backend="simple",
        chunking_config=ChunkingConfig(chunk_size=1000, chunk_overlap=200),
        batch_size=10,
    )
    path = tmp_path / "checkpoint.json"
    write_checkpoint(path, ckpt)
    loaded = load_checkpoint(path)
    with pytest.raises(Exception, match="Lexical checkpoint cannot be resumed as semantic"):
        validate_checkpoint_compatibility(
            loaded,
            source_fingerprint="abc123",
            index_slug="wiki",
            index_backend="chroma",
            chunking_config=ChunkingConfig(chunk_size=1000, chunk_overlap=200),
            embedding_fingerprint="fp",
        )


def test_chroma_duplicate_conflict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ark_pi.rag.chroma_index import append_documents
    from ark_pi.rag.semantic_index import SemanticIndexDuplicateConflictError

    chromadb = pytest.importorskip("chromadb")

    index_dir = tmp_path / "index"
    identity = _mock_identity()
    documents = [
        ChunkDocument(
            id="slug:000001:abc123456789",
            title="Title",
            source="source",
            chunk_index=0,
            text="hello world",
            sha256="aaa",
        )
    ]
    embeddings = [[0.1] * 8]

    append_documents(
        documents,
        index_dir,
        embeddings=embeddings,
        source_chunks=str(tmp_path / "chunks.jsonl"),
        embedding_identity=identity,
    )

    conflicting = [
        ChunkDocument(
            id="slug:000001:abc123456789",
            title="Title",
            source="source",
            chunk_index=0,
            text="changed text",
            sha256="bbb",
        )
    ]
    with pytest.raises(SemanticIndexDuplicateConflictError, match="different content"):
        append_documents(
            conflicting,
            index_dir,
            embeddings=[[0.2] * 8],
            source_chunks=str(tmp_path / "chunks.jsonl"),
            embedding_identity=identity,
        )

    _ = chromadb
