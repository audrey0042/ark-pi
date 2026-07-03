import json
from pathlib import Path

import pytest

from ark_pi.ingest.chunking import (
    make_chunk_id,
    make_chunk_records,
    sha256_hex,
    split_text,
    validate_chunk_params,
)
from ark_pi.ingest.sources import SourceRecord, load_sources


def test_split_text_short_produces_one_chunk() -> None:
    text = "Hello, Ark Pi."
    chunks = split_text(text, chunk_size=100, chunk_overlap=20)
    assert chunks == [text]


def test_split_text_long_produces_multiple_chunks() -> None:
    text = "a" * 2500
    chunk_size = 1000
    chunk_overlap = 200
    chunks = split_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    assert len(chunks) > 1
    assert all(len(chunk) <= chunk_size for chunk in chunks)


def test_split_text_overlap_is_correct() -> None:
    text = "abcdefghijklmnopqrstuvwxyz" * 10
    chunk_size = 50
    chunk_overlap = 10
    chunks = split_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    assert len(chunks) >= 2
    assert chunks[0][-10:] == chunks[1][:10]


def test_validate_chunk_params_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="chunk-size must be greater than 0"):
        validate_chunk_params(0, 0)
    with pytest.raises(ValueError, match="chunk-overlap must be greater than or equal to 0"):
        validate_chunk_params(100, -1)
    with pytest.raises(ValueError, match="chunk-overlap must be smaller than chunk-size"):
        validate_chunk_params(100, 100)


def test_split_text_whitespace_only_produces_no_chunks() -> None:
    assert split_text("   ", chunk_size=100, chunk_overlap=20) == []


def test_stable_ids_are_deterministic() -> None:
    text = "Stable chunk identity test."
    first = make_chunk_id("example_txt", 0, text)
    second = make_chunk_id("example_txt", 0, text)
    assert first == second
    assert first.startswith("example_txt:000000:")


def test_make_chunk_records_has_expected_fields() -> None:
    sources = [
        SourceRecord(title="Example", text="Chunk record schema test.", source="example.txt")
    ]
    records = make_chunk_records(sources, chunk_size=1000, chunk_overlap=200)
    assert len(records) == 1
    record = records[0]
    assert set(record.keys()) == {"id", "title", "source", "chunk_index", "text", "sha256"}
    assert record["sha256"] == sha256_hex(str(record["text"]))


def test_load_txt_file(tmp_path: Path) -> None:
    path = tmp_path / "note.txt"
    path.write_text("Plain text document.", encoding="utf-8")
    records = load_sources(path)
    assert len(records) == 1
    assert records[0].title == "note"
    assert records[0].text == "Plain text document."


def test_load_directory_of_txt_files(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("First.", encoding="utf-8")
    (tmp_path / "b.txt").write_text("Second.", encoding="utf-8")
    records = load_sources(tmp_path)
    assert len(records) == 2
    assert {record.title for record in records} == {"a", "b"}


def test_load_jsonl_with_title_and_text(tmp_path: Path) -> None:
    path = tmp_path / "docs.jsonl"
    path.write_text(
        '{"title": "Doc A", "text": "Alpha"}\n{"title": "Doc B", "text": "Beta"}\n',
        encoding="utf-8",
    )
    records = load_sources(path)
    assert len(records) == 2
    assert records[0].title == "Doc A"


def test_load_jsonl_rejects_malformed_record(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"title": "Missing text field"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="Missing required 'title' or 'text'"):
        load_sources(path)


def test_make_chunk_records_stable_across_runs() -> None:
    sources = [SourceRecord(title="T", text="Repeatable output.", source="repeat.txt")]
    first = make_chunk_records(sources, chunk_size=1000, chunk_overlap=200)
    second = make_chunk_records(sources, chunk_size=1000, chunk_overlap=200)
    assert first == second
