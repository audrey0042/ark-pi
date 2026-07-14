import json
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from ark_pi.workspace.paths import index_root_dir, resolve_workspace_dir

CATALOG_SCHEMA_VERSION = 1
CATALOG_FILENAME = "catalog.json"


class WorkspaceError(Exception):
    """Raised for invalid workspace index operations."""


class WorkspaceIndexNotFoundError(Exception):
    """Raised when a workspace index slug is not in the catalog."""


@dataclass
class CatalogIndexEntry:
    name: str
    slug: str
    backend: str
    chunks_path: str
    index_dir: str
    chunk_count: int
    source_count: int
    created_at: str
    updated_at: str
    corpus_run_id: str | None = None
    source_fingerprint: str | None = None


def catalog_path(workspace_dir: Path) -> Path:
    return resolve_workspace_dir(workspace_dir) / CATALOG_FILENAME


def _entry_from_dict(data: dict[str, object]) -> CatalogIndexEntry:
    return CatalogIndexEntry(
        name=str(data["name"]),
        slug=str(data["slug"]),
        backend=str(data["backend"]),
        chunks_path=str(data["chunks_path"]),
        index_dir=str(data["index_dir"]),
        chunk_count=int(data["chunk_count"]),
        source_count=int(data["source_count"]),
        created_at=str(data["created_at"]),
        updated_at=str(data["updated_at"]),
        corpus_run_id=str(data["corpus_run_id"]) if data.get("corpus_run_id") else None,
        source_fingerprint=str(data["source_fingerprint"])
        if data.get("source_fingerprint")
        else None,
    )


def _entry_to_dict(entry: CatalogIndexEntry) -> dict[str, object]:
    payload = asdict(entry)
    if payload.get("corpus_run_id") is None:
        payload.pop("corpus_run_id", None)
    if payload.get("source_fingerprint") is None:
        payload.pop("source_fingerprint", None)
    return payload


def load_catalog(workspace_dir: Path) -> list[CatalogIndexEntry]:
    path = catalog_path(workspace_dir)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = f"Invalid catalog in {path}: {exc.msg}"
        raise ValueError(msg) from exc
    if not isinstance(raw, dict):
        msg = f"Invalid catalog in {path}"
        raise ValueError(msg)
    schema_version = raw.get("schema_version")
    if schema_version != CATALOG_SCHEMA_VERSION:
        msg = f"Unsupported catalog schema version: {schema_version!r}"
        raise ValueError(msg)
    indexes = raw.get("indexes")
    if not isinstance(indexes, list):
        msg = f"Invalid catalog indexes in {path}"
        raise ValueError(msg)
    return [_entry_from_dict(entry) for entry in indexes if isinstance(entry, dict)]


def get_index(workspace_dir: Path, slug: str) -> CatalogIndexEntry | None:
    for entry in load_catalog(workspace_dir):
        if entry.slug == slug:
            return entry
    return None


def list_indexes(workspace_dir: Path) -> list[CatalogIndexEntry]:
    entries = load_catalog(workspace_dir)
    return sorted(entries, key=lambda entry: entry.updated_at, reverse=True)


def upsert_index(workspace_dir: Path, entry: CatalogIndexEntry) -> None:
    path = catalog_path(workspace_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = load_catalog(workspace_dir)
    updated = False
    new_entries: list[CatalogIndexEntry] = []
    for existing in entries:
        if existing.slug == entry.slug:
            new_entries.append(entry)
            updated = True
        else:
            new_entries.append(existing)
    if not updated:
        new_entries.append(entry)
    payload = {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "indexes": [_entry_to_dict(item) for item in new_entries],
    }
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


@dataclass(frozen=True)
class DeleteIndexResult:
    slug: str
    deleted: bool
    message: str


def remove_index_from_catalog(workspace_dir: Path, slug: str) -> None:
    path = catalog_path(workspace_dir)
    entries = load_catalog(workspace_dir)
    remaining = [entry for entry in entries if entry.slug != slug]
    if len(remaining) == len(entries):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "indexes": [_entry_to_dict(item) for item in remaining],
    }
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def delete_index(workspace_dir: Path, slug: str) -> DeleteIndexResult:
    try:
        index_root = index_root_dir(workspace_dir, slug)
    except ValueError as exc:
        raise WorkspaceError(str(exc)) from exc

    slug_name = index_root.name
    entry = get_index(workspace_dir, slug_name)
    if entry is None:
        raise WorkspaceIndexNotFoundError("Workspace index not found.")

    directory_existed = index_root.is_dir()
    if directory_existed:
        try:
            shutil.rmtree(index_root)
        except OSError as exc:
            msg = f"Failed to delete index directory: {index_root}"
            raise WorkspaceError(msg) from exc

    remove_index_from_catalog(workspace_dir, slug_name)

    if directory_existed:
        message = f"Deleted workspace index {slug_name!r}."
    else:
        message = (
            f"Removed catalog entry for {slug_name!r}; "
            "index directory was already missing."
        )

    return DeleteIndexResult(slug=slug_name, deleted=True, message=message)


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
