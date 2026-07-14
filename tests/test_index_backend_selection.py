import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ark_pi.cli import app
from ark_pi.config import get_settings
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


def test_default_backend_is_simple() -> None:
    settings = get_settings()
    assert settings.index_backend == "simple"


def test_invalid_backend_exits_nonzero(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "index"
    _write_chunks(chunks_path)

    result = runner.invoke(
        app,
        [
            "index",
            "build",
            "--chunks",
            str(chunks_path),
            "--index-dir",
            str(index_dir),
            "--backend",
            "not-a-backend",
        ],
    )
    assert result.exit_code != 0


def test_build_search_stats_with_simple_backend(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "index"
    _write_chunks(chunks_path)

    build = runner.invoke(
        app,
        [
            "index",
            "build",
            "--backend",
            "simple",
            "--chunks",
            str(chunks_path),
            "--index-dir",
            str(index_dir),
        ],
    )
    assert build.exit_code == 0
    assert "simple" in build.stdout

    stats = runner.invoke(
        app,
        ["index", "stats", "--backend", "simple", "--index-dir", str(index_dir)],
    )
    assert stats.exit_code == 0
    assert "simple" in stats.stdout

    search = runner.invoke(
        app,
        [
            "index",
            "search",
            "--backend",
            "simple",
            "--index-dir",
            str(index_dir),
            "--query",
            "prompt assembly",
        ],
    )
    assert search.exit_code == 0


def test_config_accepts_chroma_backend_without_importing_chromadb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_INDEX_BACKEND", "chroma")
    settings = get_settings()
    assert settings.index_backend == "chroma"

    import ark_pi.rag.chroma_index  # noqa: F401

    config = runner.invoke(app, ["config"], env={"ARK_INDEX_BACKEND": "chroma"})
    assert config.exit_code == 0
    assert "chroma" in config.stdout


def test_backend_mismatch_fails_clearly(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "index"
    _write_chunks(chunks_path)
    rag_index.build_index(chunks_path, index_dir, backend="simple")

    with pytest.raises(rag_index.IndexConfigurationError, match="does not match"):
        rag_index.search_index(index_dir, "prompt", backend="chroma").results
