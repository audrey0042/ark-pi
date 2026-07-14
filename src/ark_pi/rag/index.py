import json
from dataclasses import dataclass
from pathlib import Path

from ark_pi.rag.backends import (
    resolve_build_backend,
    resolve_query_backend,
    validate_backend_name,
)

REQUIRED_CHUNK_FIELDS = ("id", "title", "source", "chunk_index", "text", "sha256")
MANIFEST_FILE = "manifest.json"
CREATED_BY = "ark-pi"


class IndexErrorBase(Exception):
    """Base class for index and backend failures."""


class IndexConfigurationError(IndexErrorBase):
    """Invalid backend selection or index configuration."""


class IndexDependencyError(IndexErrorBase):
    """Optional index backend dependency is not installed."""


class IndexFormatError(IndexErrorBase):
    """Index directory or manifest is malformed."""


@dataclass(frozen=True)
class ChunkDocument:
    id: str
    title: str
    source: str
    chunk_index: int
    text: str
    sha256: str


@dataclass(frozen=True)
class SearchResult:
    score: float
    id: str
    title: str
    source: str
    chunk_index: int
    text: str


@dataclass(frozen=True)
class IndexStats:
    backend: str
    schema_version: int
    chunk_count: int
    index_dir: Path
    source_chunks: str | None = None


def load_chunks_jsonl(chunks_path: Path) -> list[ChunkDocument]:
    if not chunks_path.exists():
        msg = f"Chunks file does not exist: {chunks_path}"
        raise FileNotFoundError(msg)

    documents: list[ChunkDocument] = []
    for line_number, line in enumerate(
        chunks_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            msg = f"Malformed JSON on line {line_number} of {chunks_path}: {exc.msg}"
            raise IndexFormatError(msg) from exc
        if not isinstance(data, dict):
            msg = f"Expected JSON object on line {line_number} of {chunks_path}"
            raise IndexFormatError(msg)
        missing = [field for field in REQUIRED_CHUNK_FIELDS if field not in data]
        if missing:
            msg = (
                f"Missing required chunk fields on line {line_number} of {chunks_path}: "
                f"{', '.join(missing)}"
            )
            raise IndexFormatError(msg)
        documents.append(
            ChunkDocument(
                id=str(data["id"]),
                title=str(data["title"]),
                source=str(data["source"]),
                chunk_index=int(data["chunk_index"]),
                text=str(data["text"]),
                sha256=str(data["sha256"]),
            )
        )
    return documents


def validate_search_limit(limit: int) -> None:
    if limit <= 0:
        msg = "limit must be greater than 0"
        raise ValueError(msg)


def _load_manifest(index_dir: Path) -> dict[str, object]:
    manifest_path = index_dir / MANIFEST_FILE
    if not index_dir.exists():
        msg = f"Index directory does not exist: {index_dir}"
        raise FileNotFoundError(msg)
    if not manifest_path.is_file():
        msg = f"Invalid index directory (missing {MANIFEST_FILE}): {index_dir}"
        raise IndexFormatError(msg)
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = f"Invalid manifest in {manifest_path}: {exc.msg}"
        raise IndexFormatError(msg) from exc
    if not isinstance(data, dict):
        msg = f"Invalid manifest in {manifest_path}"
        raise IndexFormatError(msg)
    return data


def _backend_from_manifest(manifest: dict[str, object]) -> str:
    backend = manifest.get("backend")
    if not isinstance(backend, str):
        msg = f"Invalid or missing backend in index manifest: {backend!r}"
        raise IndexFormatError(msg)
    return validate_backend_name(backend)


def _dispatch_build(
    backend: str,
    documents: list[ChunkDocument],
    index_dir: Path,
    *,
    source_chunks: str,
    force: bool,
) -> IndexStats:
    match backend:
        case "simple":
            from ark_pi.rag import simple_index

            return simple_index.build_index(
                documents,
                index_dir,
                source_chunks=source_chunks,
                force=force,
            )
        case "chroma":
            from ark_pi.rag import chroma_index

            return chroma_index.build_index(
                documents,
                index_dir,
                source_chunks=source_chunks,
                force=force,
            )
        case _:
            msg = f"Unhandled index backend: {backend!r}"
            raise IndexConfigurationError(msg)


def _dispatch_search(backend: str, index_dir: Path, query: str, *, limit: int) -> list[SearchResult]:
    match backend:
        case "simple":
            from ark_pi.rag import simple_index

            return simple_index.search_index(index_dir, query, limit=limit)
        case "chroma":
            from ark_pi.rag import chroma_index

            return chroma_index.search_index(index_dir, query, limit=limit)
        case _:
            msg = f"Unhandled index backend: {backend!r}"
            raise IndexConfigurationError(msg)


def _chunk_records_to_documents(records: list[dict[str, object]]) -> list[ChunkDocument]:
    documents: list[ChunkDocument] = []
    for data in records:
        documents.append(
            ChunkDocument(
                id=str(data["id"]),
                title=str(data["title"]),
                source=str(data["source"]),
                chunk_index=int(data["chunk_index"]),
                text=str(data["text"]),
                sha256=str(data["sha256"]),
            )
        )
    return documents


def _dispatch_append(
    backend: str,
    documents: list[ChunkDocument],
    index_dir: Path,
    *,
    source_chunks: str,
) -> IndexStats:
    match backend:
        case "simple":
            from ark_pi.rag import simple_index

            return simple_index.append_documents(
                documents,
                index_dir,
                source_chunks=source_chunks,
            )
        case "chroma":
            msg = (
                "Chroma backend does not support incremental corpus ingestion. "
                "Use --backend simple or ingest via a follow-up semantic slice."
            )
            raise IndexConfigurationError(msg)
        case _:
            msg = f"Unhandled index backend: {backend!r}"
            raise IndexConfigurationError(msg)


def append_to_index(
    chunk_records: list[dict[str, object]],
    index_dir: Path,
    *,
    backend: str,
    source_chunks: str,
) -> IndexStats:
    documents = _chunk_records_to_documents(chunk_records)
    return _dispatch_append(
        backend,
        documents,
        index_dir,
        source_chunks=source_chunks,
    )


def build_index(
    chunks_path: Path,
    index_dir: Path,
    *,
    backend: str | None = None,
    config_backend: str = "simple",
    force: bool = False,
) -> IndexStats:
    resolved_backend = resolve_build_backend(
        cli_backend=backend,
        config_backend=config_backend,
    )
    documents = load_chunks_jsonl(chunks_path)
    return _dispatch_build(
        resolved_backend,
        documents,
        index_dir,
        source_chunks=str(chunks_path),
        force=force,
    )


def search_index(
    index_dir: Path,
    query: str,
    *,
    backend: str | None = None,
    limit: int = 5,
) -> list[SearchResult]:
    validate_search_limit(limit)
    manifest = _load_manifest(index_dir)
    manifest_backend = _backend_from_manifest(manifest)
    resolved_backend = resolve_query_backend(
        cli_backend=backend,
        manifest_backend=manifest_backend,
    )
    return _dispatch_search(resolved_backend, index_dir, query, limit=limit)


def index_stats(index_dir: Path, *, backend: str | None = None) -> IndexStats:
    manifest = _load_manifest(index_dir)
    manifest_backend = _backend_from_manifest(manifest)
    resolved_backend = resolve_query_backend(
        cli_backend=backend,
        manifest_backend=manifest_backend,
    )
    source_chunks = manifest.get("source_chunks")
    return IndexStats(
        backend=resolved_backend,
        schema_version=int(manifest["schema_version"]),
        chunk_count=int(manifest["chunk_count"]),
        index_dir=index_dir,
        source_chunks=str(source_chunks) if source_chunks else None,
    )
