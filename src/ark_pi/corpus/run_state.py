import json
from pathlib import Path
from typing import Any

from ark_pi.corpus.types import CorpusRunStatus, CorpusSourceFormat, SourceFingerprint
from ark_pi.workspace.paths import ensure_path_inside_workspace, resolve_workspace_dir

CORPUS_RUNS_DIR = "corpus-runs"
MANIFEST_FILENAME = "manifest.json"
CHECKPOINT_FILENAME = "checkpoint.json"
COMPLETION_FILENAME = "completion.sqlite"
ERRORS_FILENAME = "errors.jsonl"
SUMMARY_FILENAME = "summary.json"


def corpus_runs_root(workspace_dir: Path) -> Path:
    root = resolve_workspace_dir(workspace_dir) / CORPUS_RUNS_DIR
    ensure_path_inside_workspace(workspace_dir, root)
    return root


def run_dir(workspace_dir: Path, run_id: str) -> Path:
    path = corpus_runs_root(workspace_dir) / run_id
    ensure_path_inside_workspace(workspace_dir, path)
    return path


def manifest_path(workspace_dir: Path, run_id: str) -> Path:
    return run_dir(workspace_dir, run_id) / MANIFEST_FILENAME


def checkpoint_path(workspace_dir: Path, run_id: str) -> Path:
    return run_dir(workspace_dir, run_id) / CHECKPOINT_FILENAME


def completion_db_path(workspace_dir: Path, run_id: str) -> Path:
    return run_dir(workspace_dir, run_id) / COMPLETION_FILENAME


def errors_path(workspace_dir: Path, run_id: str) -> Path:
    return run_dir(workspace_dir, run_id) / ERRORS_FILENAME


def summary_path(workspace_dir: Path, run_id: str) -> Path:
    return run_dir(workspace_dir, run_id) / SUMMARY_FILENAME


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def write_manifest(
    workspace_dir: Path,
    run_id: str,
    *,
    source: str,
    source_format: CorpusSourceFormat,
    source_fingerprint: SourceFingerprint,
    index_slug: str,
    backend: str,
    batch_size: int,
    chunk_size: int,
    chunk_overlap: int,
) -> Path:
    path = manifest_path(workspace_dir, run_id)
    payload = {
        "run_id": run_id,
        "source": source,
        "source_format": source_format.value,
        "source_fingerprint": source_fingerprint.to_dict(),
        "index_slug": index_slug,
        "backend": backend,
        "batch_size": batch_size,
        "chunking_config": {
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
        },
    }
    _write_json_atomic(path, payload)
    return path


def write_summary(
    workspace_dir: Path,
    run_id: str,
    *,
    status: CorpusRunStatus,
    records_seen: int,
    records_completed: int,
    records_failed: int,
    chunks_written: int,
    elapsed_seconds: float,
) -> Path:
    path = summary_path(workspace_dir, run_id)
    payload = {
        "run_id": run_id,
        "status": status.value,
        "records_seen": records_seen,
        "records_completed": records_completed,
        "records_failed": records_failed,
        "chunks_written": chunks_written,
        "elapsed_seconds": elapsed_seconds,
    }
    _write_json_atomic(path, payload)
    return path


def append_error(
    workspace_dir: Path,
    run_id: str,
    *,
    document_id: str | None,
    position: int | None,
    error_type: str,
    message: str,
) -> None:
    path = errors_path(workspace_dir, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "document_id": document_id,
        "position": position,
        "error_type": error_type,
        "message": message,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def list_run_ids(workspace_dir: Path) -> list[str]:
    root = corpus_runs_root(workspace_dir)
    if not root.is_dir():
        return []
    run_ids: list[str] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / CHECKPOINT_FILENAME).is_file():
            run_ids.append(child.name)
    return run_ids


def find_latest_run_id(workspace_dir: Path) -> str | None:
    root = corpus_runs_root(workspace_dir)
    if not root.is_dir():
        return None
    candidates: list[tuple[str, str]] = []
    for child in root.iterdir():
        ckpt = child / CHECKPOINT_FILENAME
        if not ckpt.is_file():
            continue
        try:
            raw = json.loads(ckpt.read_text(encoding="utf-8"))
            updated_at = str(raw.get("updated_at", ""))
        except (json.JSONDecodeError, OSError):
            updated_at = ""
        candidates.append((updated_at, child.name))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]
