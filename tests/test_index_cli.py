import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ark_pi.cli import app

runner = CliRunner()


def _write_chunks(path: Path) -> None:
    records = [
        {
            "id": "sample:000000:abc123def456",
            "title": "Sample",
            "source": "sample.txt",
            "chunk_index": 0,
            "text": "The RAG Pi owns retrieval and prompt assembly.",
            "sha256": "abc123def456789012345678901234567890123456789012345678901234567890",
        }
    ]
    path.write_text(json.dumps(records[0]) + "\n", encoding="utf-8")


def test_index_build_help() -> None:
    result = runner.invoke(app, ["index", "build", "--help"])
    assert result.exit_code == 0
    assert "--chunks" in result.stdout


def test_index_search_help() -> None:
    result = runner.invoke(app, ["index", "search", "--help"])
    assert result.exit_code == 0
    assert "--query" in result.stdout
    assert "--embedding-backend" in result.stdout
    assert "--json" in result.stdout


def test_index_stats_help() -> None:
    result = runner.invoke(app, ["index", "stats", "--help"])
    assert result.exit_code == 0
    assert "--index-dir" in result.stdout


def test_index_build_stats_search_happy_path(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "index"
    _write_chunks(chunks_path)

    build = runner.invoke(
        app,
        [
            "index",
            "build",
            "--chunks",
            str(chunks_path),
            "--index-dir",
            str(index_dir),
        ],
    )
    assert build.exit_code == 0
    assert "simple" in build.stdout

    stats = runner.invoke(app, ["index", "stats", "--index-dir", str(index_dir)])
    assert stats.exit_code == 0
    assert "simple" in stats.stdout
    assert "1" in stats.stdout

    search = runner.invoke(
        app,
        [
            "index",
            "search",
            "--index-dir",
            str(index_dir),
            "--query",
            "prompt assembly",
            "--limit",
            "3",
        ],
    )
    assert search.exit_code == 0
    assert "Sample" in search.stdout or "sample:000000" in search.stdout


def test_index_rebuild_without_force_fails(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "index"
    _write_chunks(chunks_path)

    assert (
        runner.invoke(
            app,
            ["index", "build", "--chunks", str(chunks_path), "--index-dir", str(index_dir)],
        ).exit_code
        == 0
    )

    rebuild = runner.invoke(
        app,
        ["index", "build", "--chunks", str(chunks_path), "--index-dir", str(index_dir)],
    )
    assert rebuild.exit_code != 0


def test_index_rebuild_with_force_succeeds(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "index"
    _write_chunks(chunks_path)

    assert (
        runner.invoke(
            app,
            ["index", "build", "--chunks", str(chunks_path), "--index-dir", str(index_dir)],
        ).exit_code
        == 0
    )

    rebuild = runner.invoke(
        app,
        [
            "index",
            "build",
            "--chunks",
            str(chunks_path),
            "--index-dir",
            str(index_dir),
            "--force",
        ],
    )
    assert rebuild.exit_code == 0


def test_index_search_invalid_limit_exits_nonzero(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "index"
    _write_chunks(chunks_path)
    runner.invoke(
        app,
        ["index", "build", "--chunks", str(chunks_path), "--index-dir", str(index_dir)],
    )

    result = runner.invoke(
        app,
        [
            "index",
            "search",
            "--index-dir",
            str(index_dir),
            "--query",
            "prompt",
            "--limit",
            "0",
        ],
    )
    assert result.exit_code != 0


def test_index_build_missing_chunks_exits_nonzero(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "index",
            "build",
            "--chunks",
            str(tmp_path / "missing.jsonl"),
            "--index-dir",
            str(tmp_path / "index"),
        ],
    )
    assert result.exit_code != 0
