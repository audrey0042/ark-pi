import json
from pathlib import Path

import pytest

from ark_pi.rag import index as rag_index
from ark_pi.rag.simple_index import tokenize


def _write_chunks(path: Path, records: list[dict[str, object]]) -> None:
    lines = [json.dumps(record, ensure_ascii=False) for record in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _sample_chunks() -> list[dict[str, object]]:
    return [
        {
            "id": "doc_a:000000:aaa111bbb222",
            "title": "RAG Pi",
            "source": "doc_a.txt",
            "chunk_index": 0,
            "text": "The RAG Pi owns retrieval and prompt assembly.",
            "sha256": "aaa111bbb222ccc333ddd444eee555fff6667778889990001112223334445",
        },
        {
            "id": "doc_b:000000:ccc333ddd444",
            "title": "LLM Pi",
            "source": "doc_b.txt",
            "chunk_index": 0,
            "text": "The LLM Pi owns generation with llama.cpp.",
            "sha256": "ccc333ddd444eee555fff6667778889990001112223334445556667778889990",
        },
    ]


def test_tokenize_lowercases_and_removes_punctuation() -> None:
    assert tokenize("Prompt-Assembly, RAG!") == ["prompt", "assembly", "rag"]


def test_build_index_writes_manifest_documents_and_terms(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "index"
    _write_chunks(chunks_path, _sample_chunks())

    stats = rag_index.build_index(chunks_path, index_dir)

    assert stats.backend == "simple"
    assert stats.schema_version == 1
    assert stats.chunk_count == 2
    assert (index_dir / "manifest.json").is_file()
    assert (index_dir / "documents.jsonl").is_file()
    assert (index_dir / "terms.json").is_file()

    manifest = json.loads((index_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["backend"] == "simple"
    assert manifest["chunk_count"] == 2


def test_index_stats_returns_chunk_count(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "index"
    _write_chunks(chunks_path, _sample_chunks())
    rag_index.build_index(chunks_path, index_dir)

    stats = rag_index.index_stats(index_dir)
    assert stats.chunk_count == 2
    assert stats.backend == "simple"


def test_search_returns_relevant_chunk_first(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "index"
    _write_chunks(chunks_path, _sample_chunks())
    rag_index.build_index(chunks_path, index_dir)

    results = rag_index.search_index(index_dir, "prompt assembly", limit=3)
    assert len(results) >= 1
    assert results[0].title == "RAG Pi"
    assert "prompt assembly" in results[0].text.lower()


def test_search_with_no_overlap_returns_empty(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "index"
    _write_chunks(chunks_path, _sample_chunks())
    rag_index.build_index(chunks_path, index_dir)

    results = rag_index.search_index(index_dir, "quantum physics", limit=5)
    assert results == []


def test_search_honors_limit(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "index"
    _write_chunks(chunks_path, _sample_chunks())
    rag_index.build_index(chunks_path, index_dir)

    results = rag_index.search_index(index_dir, "pi", limit=1)
    assert len(results) == 1


def test_build_refuses_non_empty_index_without_force(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "index"
    _write_chunks(chunks_path, _sample_chunks())
    rag_index.build_index(chunks_path, index_dir)

    with pytest.raises(FileExistsError, match="not empty"):
        rag_index.build_index(chunks_path, index_dir, force=False)


def test_build_with_force_succeeds(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "index"
    _write_chunks(chunks_path, _sample_chunks())
    rag_index.build_index(chunks_path, index_dir)

    updated = _sample_chunks()
    updated[0]["text"] = "Updated retrieval text about prompt assembly."
    _write_chunks(chunks_path, updated)

    stats = rag_index.build_index(chunks_path, index_dir, force=True)
    assert stats.chunk_count == 2
    results = rag_index.search_index(index_dir, "prompt assembly", limit=1)
    assert "Updated retrieval text" in results[0].text


def test_search_is_deterministic(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "index"
    _write_chunks(chunks_path, _sample_chunks())
    rag_index.build_index(chunks_path, index_dir)

    first = rag_index.search_index(index_dir, "prompt assembly llm", limit=5)
    second = rag_index.search_index(index_dir, "prompt assembly llm", limit=5)
    assert [(result.id, result.score) for result in first] == [
        (result.id, result.score) for result in second
    ]


def test_load_chunks_jsonl_rejects_malformed_record(tmp_path: Path) -> None:
    chunks_path = tmp_path / "bad.jsonl"
    chunks_path.write_text('{"id": "x", "title": "Missing fields"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="Missing required chunk fields"):
        rag_index.load_chunks_jsonl(chunks_path)
