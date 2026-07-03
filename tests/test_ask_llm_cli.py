import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ark_pi.cli import app
from ark_pi.llm_client.types import LlmRequest
from ark_pi.rag import index as rag_index

runner = CliRunner()


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


def test_ask_default_uses_mock_backend(tmp_path: Path) -> None:
    index_dir = _build_index(tmp_path)
    result = runner.invoke(
        app,
        [
            "ask",
            "--index-dir",
            str(index_dir),
            "--question",
            "Which Pi owns prompt assembly?",
        ],
    )
    assert result.exit_code == 0
    assert "Mock LLM backend" in result.stdout
    assert "Retrieved chunks: 1" in result.stdout


def test_ask_explicit_mock_backend(tmp_path: Path) -> None:
    index_dir = _build_index(tmp_path)
    result = runner.invoke(
        app,
        [
            "ask",
            "--index-dir",
            str(index_dir),
            "--question",
            "prompt assembly",
            "--llm-backend",
            "mock",
        ],
    )
    assert result.exit_code == 0
    assert "Mock LLM backend" in result.stdout


def test_ask_no_matches_exits_zero_without_calling_llm(
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

    result = runner.invoke(
        app,
        [
            "ask",
            "--index-dir",
            str(index_dir),
            "--question",
            "quantum physics",
        ],
    )
    assert result.exit_code == 0
    assert "No relevant context found." in result.stdout
    assert calls == []


def test_ask_invalid_backend_exits_nonzero(tmp_path: Path) -> None:
    index_dir = _build_index(tmp_path)
    result = runner.invoke(
        app,
        [
            "ask",
            "--index-dir",
            str(index_dir),
            "--question",
            "prompt assembly",
            "--llm-backend",
            "invalid",
        ],
    )
    assert result.exit_code != 0


def test_ask_invalid_max_tokens_exits_nonzero(tmp_path: Path) -> None:
    index_dir = _build_index(tmp_path)
    result = runner.invoke(
        app,
        [
            "ask",
            "--index-dir",
            str(index_dir),
            "--question",
            "prompt assembly",
            "--max-tokens",
            "0",
        ],
    )
    assert result.exit_code != 0


def test_ask_invalid_temperature_exits_nonzero(tmp_path: Path) -> None:
    index_dir = _build_index(tmp_path)
    result = runner.invoke(
        app,
        [
            "ask",
            "--index-dir",
            str(index_dir),
            "--question",
            "prompt assembly",
            "--temperature",
            "-1",
        ],
    )
    assert result.exit_code != 0


def test_ask_show_context(tmp_path: Path) -> None:
    index_dir = _build_index(tmp_path)
    result = runner.invoke(
        app,
        [
            "ask",
            "--index-dir",
            str(index_dir),
            "--question",
            "prompt assembly",
            "--show-context",
        ],
    )
    assert result.exit_code == 0
    assert "Sample" in result.stdout or "sample:000000" in result.stdout


def test_ask_show_prompt(tmp_path: Path) -> None:
    index_dir = _build_index(tmp_path)
    result = runner.invoke(
        app,
        [
            "ask",
            "--index-dir",
            str(index_dir),
            "--question",
            "prompt assembly",
            "--show-prompt",
        ],
    )
    assert result.exit_code == 0
    assert "Context:" in result.stdout
    assert "Question:" in result.stdout


def test_llm_mock_command() -> None:
    result = runner.invoke(app, ["llm", "mock", "--prompt", "hello"])
    assert result.exit_code == 0
    assert "Mock LLM backend" in result.stdout
    assert "Received a prompt with 5 characters." in result.stdout
