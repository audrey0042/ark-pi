import json
from pathlib import Path

import pytest

from ark_pi.llm_client.types import LlmRequest
from ark_pi.rag import ask as rag_ask
from ark_pi.rag import index as rag_index


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


def test_run_ask_no_matches_does_not_call_llm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index_dir = _build_index(tmp_path)
    calls: list[LlmRequest] = []

    def fake_complete(_self: object, request: LlmRequest) -> object:
        calls.append(request)
        raise AssertionError("LLM client should not be called when there are no matches")

    monkeypatch.setattr(
        "ark_pi.llm_client.mock.MockLlmClient.complete",
        fake_complete,
    )

    result = rag_ask.run_ask(index_dir, "quantum physics")

    assert result.no_context is True
    assert result.retrieved_count == 0
    assert result.answer == rag_ask.NO_CONTEXT_ANSWER
    assert result.prompt is None
    assert calls == []


def test_run_ask_happy_path_returns_answer_prompt_and_results(tmp_path: Path) -> None:
    index_dir = _build_index(tmp_path)

    result = rag_ask.run_ask(index_dir, "Which Pi owns prompt assembly?")

    assert result.no_context is False
    assert result.retrieved_count == 1
    assert len(result.results) == 1
    assert "Mock LLM backend" in result.answer
    assert result.prompt is not None
    assert "Context:" in result.prompt
    assert "Question:" in result.prompt
