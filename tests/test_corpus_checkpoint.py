import json
from pathlib import Path

import pytest

from ark_pi.corpus.checkpoint import (
    SCHEMA_NAME,
    SCHEMA_VERSION,
    CorpusCheckpointError,
    load_checkpoint,
    new_checkpoint,
    validate_checkpoint_compatibility,
    write_checkpoint,
)
from ark_pi.corpus.types import ChunkingConfig, CorpusRunStatus, CorpusSourceFormat


@pytest.fixture
def sample_checkpoint(tmp_path: Path) -> Path:
    ckpt = new_checkpoint(
        run_id="test-run",
        source="/tmp/sample.jsonl",
        source_format=CorpusSourceFormat.jsonl,
        source_fingerprint="abc123",
        index_slug="corpus-smoke",
        index_backend="simple",
        chunking_config=ChunkingConfig(chunk_size=1000, chunk_overlap=200),
        batch_size=10,
        estimated_records=5,
    )
    path = tmp_path / "checkpoint.json"
    write_checkpoint(path, ckpt)
    return path


def test_checkpoint_round_trip(sample_checkpoint: Path) -> None:
    loaded = load_checkpoint(sample_checkpoint)
    assert loaded.schema_name == SCHEMA_NAME
    assert loaded.schema_version == SCHEMA_VERSION
    assert loaded.run_id == "test-run"
    assert loaded.status == CorpusRunStatus.planned
    assert loaded.estimated_records == 5


def test_checkpoint_atomic_write_preserves_previous(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.json"
    first = new_checkpoint(
        run_id="run-a",
        source="/data/a.jsonl",
        source_format=CorpusSourceFormat.jsonl,
        source_fingerprint="fp-a",
        index_slug="idx",
        index_backend="simple",
        chunking_config=ChunkingConfig(chunk_size=1000, chunk_overlap=200),
        batch_size=1,
    )
    write_checkpoint(path, first)

    corrupt_tmp = path.with_suffix(path.suffix + ".tmp")
    corrupt_tmp.write_text("{not valid json", encoding="utf-8")

    loaded = load_checkpoint(path)
    assert loaded.run_id == "run-a"


def test_corrupt_checkpoint_fails_clearly(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(CorpusCheckpointError, match="Corrupt checkpoint"):
        load_checkpoint(path)
    assert path.is_file()


def test_validate_checkpoint_rejects_fingerprint_mismatch(sample_checkpoint: Path) -> None:
    loaded = load_checkpoint(sample_checkpoint)
    with pytest.raises(CorpusCheckpointError, match="fingerprint"):
        validate_checkpoint_compatibility(
            loaded,
            source_fingerprint="different",
            index_slug="corpus-smoke",
            index_backend="simple",
            chunking_config=ChunkingConfig(chunk_size=1000, chunk_overlap=200),
        )


def test_validate_checkpoint_rejects_index_slug_mismatch(sample_checkpoint: Path) -> None:
    loaded = load_checkpoint(sample_checkpoint)
    with pytest.raises(CorpusCheckpointError, match="index slug"):
        validate_checkpoint_compatibility(
            loaded,
            source_fingerprint="abc123",
            index_slug="other-index",
            index_backend="simple",
            chunking_config=ChunkingConfig(chunk_size=1000, chunk_overlap=200),
        )


def test_validate_checkpoint_rejects_chunk_config_mismatch(sample_checkpoint: Path) -> None:
    loaded = load_checkpoint(sample_checkpoint)
    with pytest.raises(CorpusCheckpointError, match="chunk_size"):
        validate_checkpoint_compatibility(
            loaded,
            source_fingerprint="abc123",
            index_slug="corpus-smoke",
            index_backend="simple",
            chunking_config=ChunkingConfig(chunk_size=500, chunk_overlap=200),
        )


def test_checkpoint_written_as_valid_json(sample_checkpoint: Path) -> None:
    payload = json.loads(sample_checkpoint.read_text(encoding="utf-8"))
    assert payload["schema_name"] == SCHEMA_NAME
    assert payload["chunking_config"]["chunk_size"] == 1000
