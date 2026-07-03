import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ark_pi.cli import app

runner = CliRunner()


def _invoke_chunk(
    input_path: Path,
    output_path: Path,
    *,
    force: bool = False,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> object:
    args = [
        "ingest",
        "chunk",
        "--input",
        str(input_path),
        "--output",
        str(output_path),
    ]
    if force:
        args.append("--force")
    if chunk_size is not None:
        args.extend(["--chunk-size", str(chunk_size)])
    if chunk_overlap is not None:
        args.extend(["--chunk-overlap", str(chunk_overlap)])
    return runner.invoke(app, args)


def test_ingest_chunk_help() -> None:
    result = runner.invoke(app, ["ingest", "chunk", "--help"])
    assert result.exit_code == 0
    assert "--input" in result.stdout
    assert "--output" in result.stdout


def test_ingest_chunk_txt_file(tmp_path: Path) -> None:
    input_file = tmp_path / "example.txt"
    output_file = tmp_path / "example_chunks.jsonl"
    input_file.write_text("Ark Pi chunking test document.", encoding="utf-8")

    result = _invoke_chunk(input_file, output_file)
    assert result.exit_code == 0

    lines = output_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert set(record.keys()) == {"id", "title", "source", "chunk_index", "text", "sha256"}
    assert record["title"] == "example"
    assert "chunking test" in record["text"]


def test_ingest_chunk_refuses_overwrite_without_force(tmp_path: Path) -> None:
    input_file = tmp_path / "example.txt"
    output_file = tmp_path / "example_chunks.jsonl"
    input_file.write_text("First version.", encoding="utf-8")

    first = _invoke_chunk(input_file, output_file)
    assert first.exit_code == 0
    original = output_file.read_text(encoding="utf-8")

    second = _invoke_chunk(input_file, output_file)
    assert second.exit_code != 0
    assert output_file.read_text(encoding="utf-8") == original


def test_ingest_chunk_overwrites_with_force(tmp_path: Path) -> None:
    input_file = tmp_path / "example.txt"
    output_file = tmp_path / "example_chunks.jsonl"
    input_file.write_text("Initial.", encoding="utf-8")

    assert _invoke_chunk(input_file, output_file).exit_code == 0
    input_file.write_text("Updated content for forced rewrite.", encoding="utf-8")

    result = _invoke_chunk(input_file, output_file, force=True)
    assert result.exit_code == 0
    record = json.loads(output_file.read_text(encoding="utf-8").strip())
    assert "Updated content" in record["text"]


def test_ingest_chunk_directory_input(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "one.txt").write_text("One.", encoding="utf-8")
    (docs_dir / "two.txt").write_text("Two.", encoding="utf-8")
    output_file = tmp_path / "all_chunks.jsonl"

    result = _invoke_chunk(docs_dir, output_file)
    assert result.exit_code == 0
    assert "sources" in result.stdout
    lines = output_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_ingest_chunk_jsonl_input(tmp_path: Path) -> None:
    input_file = tmp_path / "source.jsonl"
    output_file = tmp_path / "chunks.jsonl"
    input_file.write_text(
        '{"title": "Wiki", "text": "Ark Pi local RAG appliance."}\n',
        encoding="utf-8",
    )

    result = _invoke_chunk(input_file, output_file)
    assert result.exit_code == 0
    record = json.loads(output_file.read_text(encoding="utf-8").strip())
    assert record["title"] == "Wiki"


def test_ingest_chunk_malformed_jsonl_exits_nonzero(tmp_path: Path) -> None:
    input_file = tmp_path / "bad.jsonl"
    output_file = tmp_path / "chunks.jsonl"
    input_file.write_text('{"title": "No text key"}\n', encoding="utf-8")

    result = _invoke_chunk(input_file, output_file)
    assert result.exit_code != 0


def test_ingest_chunk_invalid_overlap_exits_nonzero(tmp_path: Path) -> None:
    input_file = tmp_path / "example.txt"
    output_file = tmp_path / "chunks.jsonl"
    input_file.write_text("Overlap validation.", encoding="utf-8")

    result = _invoke_chunk(input_file, output_file, chunk_size=100, chunk_overlap=100)
    assert result.exit_code != 0


def test_ingest_chunk_invalid_chunk_size_exits_nonzero(tmp_path: Path) -> None:
    input_file = tmp_path / "example.txt"
    output_file = tmp_path / "chunks.jsonl"
    input_file.write_text("Size validation.", encoding="utf-8")

    result = _invoke_chunk(input_file, output_file, chunk_size=0)
    assert result.exit_code != 0
