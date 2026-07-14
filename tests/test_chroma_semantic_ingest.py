import json
from pathlib import Path

import pytest

from ark_pi.config import clear_settings_cache
from ark_pi.corpus.ingest import run_corpus_ingest
from ark_pi.corpus.types import CorpusIngestOptions, CorpusRunStatus
from ark_pi.embeddings.factory import clear_embedder_cache
from ark_pi.rag import index as rag_index
from ark_pi.rag.semantic_index import EmbeddingIdentity, compute_embedding_fingerprint
from ark_pi.workspace.paths import index_paths

chromadb = pytest.importorskip("chromadb")


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
        json.dumps({"id": "one", "title": "First", "text": "The first local article for chroma."})
        + "\n",
        encoding="utf-8",
    )
    return workspace_dir, jsonl_path


def test_chroma_semantic_corpus_ingest_with_mock_embedder(
    corpus_env: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "mock")
    workspace_dir, source = corpus_env
    result = run_corpus_ingest(
        CorpusIngestOptions(
            source_path=source,
            index_slug="wiki-chroma",
            workspace_dir=workspace_dir,
            batch_size=1,
            backend="chroma",
            embedding_backend="mock",
        )
    )
    assert result.status == CorpusRunStatus.completed
    assert result.records_embedded >= 1

    _, index_dir = index_paths(workspace_dir, "wiki-chroma")
    stats = rag_index.index_stats(index_dir)
    assert stats.backend == "chroma"
    assert stats.embedding_fingerprint is not None
    assert stats.embedding_backend == "mock"

    manifest = json.loads((index_dir / "manifest.json").read_text(encoding="utf-8"))
    embedding = manifest["embedding"]
    identity = EmbeddingIdentity.from_dict(embedding)
    assert compute_embedding_fingerprint(identity) == stats.embedding_fingerprint
