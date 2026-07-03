import json
from pathlib import Path

from typer.testing import CliRunner

from ark_pi.cli import app
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


def test_ask_help() -> None:
    result = runner.invoke(app, ["ask", "--help"])
    assert result.exit_code == 0
    assert "--question" in result.stdout
    assert "--llm-backend" in result.stdout


def test_ask_no_matches_exits_zero(tmp_path: Path) -> None:
    index_dir = _build_index(tmp_path)
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


def test_ask_invalid_index_dir_exits_nonzero(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "ask",
            "--index-dir",
            str(tmp_path / "missing"),
            "--question",
            "prompt assembly",
        ],
    )
    assert result.exit_code != 0


def test_ask_empty_question_exits_nonzero(tmp_path: Path) -> None:
    index_dir = _build_index(tmp_path)
    result = runner.invoke(
        app,
        [
            "ask",
            "--index-dir",
            str(index_dir),
            "--question",
            "   ",
        ],
    )
    assert result.exit_code != 0


def test_ask_invalid_limit_exits_nonzero(tmp_path: Path) -> None:
    index_dir = _build_index(tmp_path)
    result = runner.invoke(
        app,
        [
            "ask",
            "--index-dir",
            str(index_dir),
            "--question",
            "prompt assembly",
            "--limit",
            "0",
        ],
    )
    assert result.exit_code != 0
