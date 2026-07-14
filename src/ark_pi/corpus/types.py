from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class CorpusRunStatus(str, Enum):
    planned = "planned"
    running = "running"
    interrupted = "interrupted"
    failed = "failed"
    completed = "completed"


class CorpusSourceFormat(str, Enum):
    jsonl = "jsonl"
    text_directory = "text_directory"


@dataclass(frozen=True)
class ChunkingConfig:
    chunk_size: int
    chunk_overlap: int

    def to_dict(self) -> dict[str, int]:
        return {
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
        }


@dataclass(frozen=True)
class CorpusDocument:
    document_id: str
    title: str
    text: str
    source: str
    content_digest: str
    position: int
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class SourceFingerprint:
    format: CorpusSourceFormat
    normalized_path: str
    fingerprint: str
    file_count: int | None = None
    total_bytes: int | None = None
    mtime: float | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "format": self.format.value,
            "normalized_path": self.normalized_path,
            "fingerprint": self.fingerprint,
        }
        if self.file_count is not None:
            payload["file_count"] = self.file_count
        if self.total_bytes is not None:
            payload["total_bytes"] = self.total_bytes
        if self.mtime is not None:
            payload["mtime"] = self.mtime
        return payload


@dataclass(frozen=True)
class CorpusIngestOptions:
    source_path: Path
    index_slug: str
    workspace_dir: Path
    batch_size: int = 100
    chunk_size: int = 1000
    chunk_overlap: int = 200
    backend: str = "simple"
    resume: bool = False
    run_id: str | None = None
    force_rebuild: bool = False
    dry_run: bool = False
    continue_on_error: bool = False
    yes: bool = False


@dataclass
class CorpusIngestProgress:
    records_seen: int = 0
    records_completed: int = 0
    records_failed: int = 0
    chunks_written: int = 0
    last_completed_position: int = -1


@dataclass(frozen=True)
class CorpusIngestResult:
    run_id: str
    index_slug: str
    source: str
    source_format: CorpusSourceFormat
    status: CorpusRunStatus
    records_seen: int
    records_completed: int
    records_failed: int
    chunks_written: int
    run_dir: Path
    checkpoint_path: Path
    resume_command: str
    elapsed_seconds: float
    partial: bool = False
    message: str = ""


@dataclass(frozen=True)
class CorpusDryRunResult:
    run_id: str
    index_slug: str
    source: str
    source_format: CorpusSourceFormat
    source_fingerprint: SourceFingerprint
    estimated_records: int | None
    run_dir: Path
    backend: str
    batch_size: int
    chunking_config: ChunkingConfig


@dataclass(frozen=True)
class CorpusStatusResult:
    run_id: str
    source: str
    index_slug: str
    status: CorpusRunStatus
    records_seen: int
    records_completed: int
    records_failed: int
    chunks_written: int
    progress_percent: float | None
    updated_at: str
    resume_command: str
    run_dir: Path


def chunking_config_to_dict(config: ChunkingConfig) -> dict[str, int]:
    return config.to_dict()


def ingest_result_to_dict(result: CorpusIngestResult) -> dict[str, object]:
    return {
        "run_id": result.run_id,
        "index_slug": result.index_slug,
        "source": result.source,
        "source_format": result.source_format.value,
        "status": result.status.value,
        "records_seen": result.records_seen,
        "records_completed": result.records_completed,
        "records_failed": result.records_failed,
        "chunks_written": result.chunks_written,
        "run_dir": str(result.run_dir),
        "checkpoint_path": str(result.checkpoint_path),
        "resume_command": result.resume_command,
        "elapsed_seconds": result.elapsed_seconds,
        "partial": result.partial,
        "message": result.message,
    }


def dry_run_result_to_dict(result: CorpusDryRunResult) -> dict[str, object]:
    return {
        "run_id": result.run_id,
        "index_slug": result.index_slug,
        "source": result.source,
        "source_format": result.source_format.value,
        "source_fingerprint": result.source_fingerprint.to_dict(),
        "estimated_records": result.estimated_records,
        "run_dir": str(result.run_dir),
        "backend": result.backend,
        "batch_size": result.batch_size,
        "chunking_config": result.chunking_config.to_dict(),
    }


def status_result_to_dict(result: CorpusStatusResult) -> dict[str, object]:
    payload: dict[str, object] = {
        "run_id": result.run_id,
        "source": result.source,
        "index_slug": result.index_slug,
        "status": result.status.value,
        "records_seen": result.records_seen,
        "records_completed": result.records_completed,
        "records_failed": result.records_failed,
        "chunks_written": result.chunks_written,
        "updated_at": result.updated_at,
        "resume_command": result.resume_command,
        "run_dir": str(result.run_dir),
    }
    if result.progress_percent is not None:
        payload["progress_percent"] = result.progress_percent
    return payload
