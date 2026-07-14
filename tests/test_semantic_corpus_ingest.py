import json
from pathlib import Path

import pytest

from ark_pi.config import clear_settings_cache
from ark_pi.corpus.checkpoint import load_checkpoint
from ark_pi.corpus.ingest import CorpusIngestError, run_corpus_dry_run, run_corpus_ingest
from ark_pi.corpus.run_state import checkpoint_path
from ark_pi.corpus.types import CorpusIngestOptions, CorpusRunStatus
from ark_pi.embeddings.factory import clear_embedder_cache
from ark_pi.rag import index as rag_index
from ark_pi.rag.index import ChunkDocument, IndexStats
from ark_pi.rag.semantic_index import EmbeddingIdentity, compute_embedding_fingerprint
from ark_pi.workspace.paths import index_paths


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    clear_settings_cache()
    clear_embedder_cache()


@pytest.fixture
def corpus_env(tmp_path: Path) -> tuple[Path, Path]:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    jsonl_path = tmp_path / "corpus.jsonl"
    jsonl_path.write_text(
        "\n".join(
            [
                json.dumps({"id": "one", "title": "First", "text": "The first local article."}),
                json.dumps({"id": "two", "title": "Second", "text": "The second local article."}),
                json.dumps({"id": "three", "title": "Third", "text": "The third local article."}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return workspace_dir, jsonl_path


def _semantic_options(
    workspace_dir: Path,
    source: Path,
    *,
    batch_size: int = 1,
    resume: bool = False,
    run_id: str | None = None,
    force_rebuild: bool = False,
    yes: bool = False,
) -> CorpusIngestOptions:
    return CorpusIngestOptions(
        source_path=source,
        index_slug="wiki-semantic",
        workspace_dir=workspace_dir,
        batch_size=batch_size,
        backend="chroma",
        resume=resume,
        run_id=run_id,
        force_rebuild=force_rebuild,
        yes=yes,
        embedding_backend="mock",
    )


def _fake_append_documents(
    documents: list[ChunkDocument],
    index_dir: Path,
    *,
    embeddings: list[list[float]],
    source_chunks: str,
    embedding_identity: EmbeddingIdentity,
    collection_name: str = "test",
) -> IndexStats:
    store_path = index_dir / "fake_store.json"
    index_dir.mkdir(parents=True, exist_ok=True)
    store: dict[str, dict[str, object]] = {}
    if store_path.is_file():
        store = json.loads(store_path.read_text(encoding="utf-8"))

    for document, _embedding in zip(documents, embeddings, strict=True):
        existing = store.get(document.id)
        if existing is not None:
            if existing.get("sha256") == document.sha256:
                continue
            msg = f"Document ID {document.id!r} already exists with different content."
            raise rag_index.IndexConfigurationError(msg)
        store[document.id] = {
            "sha256": document.sha256,
            "text": document.text,
        }

    store_path.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")
    fingerprint = compute_embedding_fingerprint(embedding_identity)
    manifest = {
        "schema_version": 2,
        "backend": "chroma",
        "chunk_count": len(store),
        "source_chunks": source_chunks,
        "collection_name": collection_name,
        "embedding": {
            **embedding_identity.to_dict(),
            "fingerprint": fingerprint,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        },
    }
    (index_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return IndexStats(
        backend="chroma",
        schema_version=2,
        chunk_count=len(store),
        index_dir=index_dir,
        source_chunks=source_chunks,
        embedding_fingerprint=fingerprint,
        embedding_backend=embedding_identity.backend,
        embedding_model_name=embedding_identity.model_name,
        embedding_dimensions=embedding_identity.dimensions,
    )


@pytest.fixture
def fake_chroma(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "ark_pi.rag.chroma_index.append_documents",
        _fake_append_documents,
    )


def test_semantic_corpus_ingest_fresh(
    corpus_env: tuple[Path, Path],
    fake_chroma: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "mock")
    workspace_dir, source = corpus_env
    result = run_corpus_ingest(_semantic_options(workspace_dir, source, batch_size=2))
    assert result.status == CorpusRunStatus.completed
    assert result.records_completed == 3
    assert result.chunks_written >= 3
    assert result.records_embedded >= 3
    assert result.embedding_fingerprint is not None

    _, index_dir = index_paths(workspace_dir, "wiki-semantic")
    stats = rag_index.index_stats(index_dir)
    assert stats.chunk_count >= 3
    assert stats.embedding_fingerprint == result.embedding_fingerprint


def test_semantic_corpus_ingest_resume_without_duplicates(
    corpus_env: tuple[Path, Path],
    fake_chroma: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "mock")
    workspace_dir, source = corpus_env
    calls = {"count": 0}

    def flaky_append(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise rag_index.IndexConfigurationError("simulated interrupt during batch 2")
        return _fake_append_documents(*args, **kwargs)

    monkeypatch.setattr("ark_pi.rag.chroma_index.append_documents", flaky_append)

    options = _semantic_options(workspace_dir, source, batch_size=1)
    with pytest.raises(CorpusIngestError, match="simulated interrupt"):
        run_corpus_ingest(options)

    dry = run_corpus_dry_run(_semantic_options(workspace_dir, source, batch_size=1))
    partial_ckpt = load_checkpoint(checkpoint_path(workspace_dir, dry.run_id))
    assert partial_ckpt.records_completed == 1
    partial_count = rag_index.index_stats(index_paths(workspace_dir, "wiki-semantic")[1]).chunk_count

    monkeypatch.setattr("ark_pi.rag.chroma_index.append_documents", _fake_append_documents)
    resumed = run_corpus_ingest(
        _semantic_options(workspace_dir, source, batch_size=1, resume=True, run_id=dry.run_id)
    )
    assert resumed.status == CorpusRunStatus.completed
    assert resumed.records_completed == 3
    final_count = rag_index.index_stats(index_paths(workspace_dir, "wiki-semantic")[1]).chunk_count
    assert final_count >= partial_count

    replay = run_corpus_ingest(_semantic_options(workspace_dir, source, batch_size=1))
    assert replay.message == "Run already completed."
    assert rag_index.index_stats(index_paths(workspace_dir, "wiki-semantic")[1]).chunk_count == final_count


def test_semantic_corpus_ingest_failure_leaves_checkpoint(
    corpus_env: tuple[Path, Path],
    fake_chroma: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "mock")
    workspace_dir, source = corpus_env
    calls = {"count": 0}

    def flaky_append(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise rag_index.IndexConfigurationError("simulated persistence failure")
        return _fake_append_documents(*args, **kwargs)

    monkeypatch.setattr("ark_pi.rag.chroma_index.append_documents", flaky_append)

    options = _semantic_options(workspace_dir, source, batch_size=1)
    with pytest.raises(CorpusIngestError, match="simulated persistence failure"):
        run_corpus_ingest(options)

    dry = run_corpus_dry_run(_semantic_options(workspace_dir, source, batch_size=1))
    ckpt = load_checkpoint(checkpoint_path(workspace_dir, dry.run_id))
    assert ckpt.records_completed == 1
    assert ckpt.committed_batches == 1


def test_semantic_corpus_ingest_embedding_mismatch(
    corpus_env: tuple[Path, Path],
    fake_chroma: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "mock")
    workspace_dir, source = corpus_env
    first = run_corpus_ingest(_semantic_options(workspace_dir, source, batch_size=2))
    assert first.status == CorpusRunStatus.completed

    monkeypatch.setenv("ARK_EMBEDDING_MODEL", "different-model-name")
    clear_settings_cache()
    mismatched_options = CorpusIngestOptions(
        source_path=source,
        index_slug="wiki-semantic",
        workspace_dir=workspace_dir,
        batch_size=2,
        backend="chroma",
        resume=True,
        run_id=first.run_id,
        embedding_backend="mock",
    )
    with pytest.raises(CorpusIngestError, match="embedding fingerprint"):
        run_corpus_ingest(mismatched_options)
