import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ark_pi.corpus.types import ChunkingConfig, CorpusRunStatus, CorpusSourceFormat
from ark_pi.workspace.catalog import utc_now_iso

SCHEMA_NAME = "ark-pi-corpus-checkpoint"
SCHEMA_VERSION = 1


class CorpusCheckpointError(Exception):
    """Raised when checkpoint data is invalid or incompatible."""


@dataclass
class CorpusCheckpoint:
    schema_name: str
    schema_version: int
    run_id: str
    created_at: str
    updated_at: str
    source: str
    source_format: CorpusSourceFormat
    source_fingerprint: str
    index_slug: str
    index_backend: str
    chunking_config: ChunkingConfig
    batch_size: int
    records_seen: int
    records_completed: int
    records_failed: int
    chunks_written: int
    last_completed_position: int
    status: CorpusRunStatus
    estimated_records: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_name": self.schema_name,
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source": self.source,
            "source_format": self.source_format.value,
            "source_fingerprint": self.source_fingerprint,
            "index_slug": self.index_slug,
            "index_backend": self.index_backend,
            "chunking_config": self.chunking_config.to_dict(),
            "batch_size": self.batch_size,
            "records_seen": self.records_seen,
            "records_completed": self.records_completed,
            "records_failed": self.records_failed,
            "chunks_written": self.chunks_written,
            "last_completed_position": self.last_completed_position,
            "status": self.status.value,
        }
        if self.estimated_records is not None:
            payload["estimated_records"] = self.estimated_records
        return payload


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def write_checkpoint(path: Path, checkpoint: CorpusCheckpoint) -> None:
    _write_json_atomic(path, checkpoint.to_dict())


def load_checkpoint(path: Path) -> CorpusCheckpoint:
    if not path.is_file():
        msg = f"Checkpoint not found: {path}"
        raise CorpusCheckpointError(msg)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = f"Corrupt checkpoint (invalid JSON) in {path}: {exc.msg}"
        raise CorpusCheckpointError(msg) from exc
    if not isinstance(raw, dict):
        msg = f"Corrupt checkpoint (expected object) in {path}"
        raise CorpusCheckpointError(msg)

    schema_name = raw.get("schema_name")
    if schema_name != SCHEMA_NAME:
        msg = f"Unsupported checkpoint schema name: {schema_name!r} in {path}"
        raise CorpusCheckpointError(msg)
    schema_version = raw.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        msg = f"Unsupported checkpoint schema version: {schema_version!r} in {path}"
        raise CorpusCheckpointError(msg)

    try:
        chunking_raw = raw["chunking_config"]
        chunking_config = ChunkingConfig(
            chunk_size=int(chunking_raw["chunk_size"]),
            chunk_overlap=int(chunking_raw["chunk_overlap"]),
        )
        return CorpusCheckpoint(
            schema_name=str(schema_name),
            schema_version=int(schema_version),
            run_id=str(raw["run_id"]),
            created_at=str(raw["created_at"]),
            updated_at=str(raw["updated_at"]),
            source=str(raw["source"]),
            source_format=CorpusSourceFormat(str(raw["source_format"])),
            source_fingerprint=str(raw["source_fingerprint"]),
            index_slug=str(raw["index_slug"]),
            index_backend=str(raw["index_backend"]),
            chunking_config=chunking_config,
            batch_size=int(raw["batch_size"]),
            records_seen=int(raw["records_seen"]),
            records_completed=int(raw["records_completed"]),
            records_failed=int(raw["records_failed"]),
            chunks_written=int(raw["chunks_written"]),
            last_completed_position=int(raw["last_completed_position"]),
            status=CorpusRunStatus(str(raw["status"])),
            estimated_records=int(raw["estimated_records"])
            if raw.get("estimated_records") is not None
            else None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        msg = f"Corrupt checkpoint (missing or invalid fields) in {path}"
        raise CorpusCheckpointError(msg) from exc


def new_checkpoint(
    *,
    run_id: str,
    source: str,
    source_format: CorpusSourceFormat,
    source_fingerprint: str,
    index_slug: str,
    index_backend: str,
    chunking_config: ChunkingConfig,
    batch_size: int,
    estimated_records: int | None = None,
) -> CorpusCheckpoint:
    now = utc_now_iso()
    return CorpusCheckpoint(
        schema_name=SCHEMA_NAME,
        schema_version=SCHEMA_VERSION,
        run_id=run_id,
        created_at=now,
        updated_at=now,
        source=source,
        source_format=source_format,
        source_fingerprint=source_fingerprint,
        index_slug=index_slug,
        index_backend=index_backend,
        chunking_config=chunking_config,
        batch_size=batch_size,
        records_seen=0,
        records_completed=0,
        records_failed=0,
        chunks_written=0,
        last_completed_position=-1,
        status=CorpusRunStatus.planned,
        estimated_records=estimated_records,
    )


def validate_checkpoint_compatibility(
    checkpoint: CorpusCheckpoint,
    *,
    source_fingerprint: str,
    index_slug: str,
    index_backend: str,
    chunking_config: ChunkingConfig,
) -> None:
    if checkpoint.source_fingerprint != source_fingerprint:
        msg = (
            "Checkpoint source fingerprint does not match current source. "
            "Use --force-rebuild to start fresh."
        )
        raise CorpusCheckpointError(msg)
    if checkpoint.index_slug != index_slug:
        msg = (
            f"Checkpoint index slug {checkpoint.index_slug!r} does not match "
            f"requested index {index_slug!r}."
        )
        raise CorpusCheckpointError(msg)
    if checkpoint.index_backend != index_backend:
        msg = (
            f"Checkpoint backend {checkpoint.index_backend!r} does not match "
            f"requested backend {index_backend!r}."
        )
        raise CorpusCheckpointError(msg)
    if checkpoint.chunking_config.chunk_size != chunking_config.chunk_size:
        msg = "Checkpoint chunk_size does not match current configuration."
        raise CorpusCheckpointError(msg)
    if checkpoint.chunking_config.chunk_overlap != chunking_config.chunk_overlap:
        msg = "Checkpoint chunk_overlap does not match current configuration."
        raise CorpusCheckpointError(msg)
