import json
from dataclasses import dataclass
from pathlib import Path

REQUIRED_CHUNK_FIELDS = ("id", "title", "source", "chunk_index", "text", "sha256")
MANIFEST_FILE = "manifest.json"


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
            raise ValueError(msg) from exc
        if not isinstance(data, dict):
            msg = f"Expected JSON object on line {line_number} of {chunks_path}"
            raise ValueError(msg)
        missing = [field for field in REQUIRED_CHUNK_FIELDS if field not in data]
        if missing:
            msg = (
                f"Missing required chunk fields on line {line_number} of {chunks_path}: "
                f"{', '.join(missing)}"
            )
            raise ValueError(msg)
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
        raise ValueError(msg)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        msg = f"Invalid manifest in {manifest_path}"
        raise ValueError(msg)
    return data


def _backend_from_manifest(manifest: dict[str, object]) -> str:
    backend = manifest.get("backend")
    if backend != "simple":
        msg = f"Unsupported index backend: {backend!r}"
        raise ValueError(msg)
    return str(backend)


def build_index(
    chunks_path: Path,
    index_dir: Path,
    *,
    force: bool = False,
) -> IndexStats:
    from ark_pi.rag import simple_index

    documents = load_chunks_jsonl(chunks_path)
    return simple_index.build_index(
        documents,
        index_dir,
        source_chunks=str(chunks_path),
        force=force,
    )


def search_index(
    index_dir: Path,
    query: str,
    *,
    limit: int = 5,
) -> list[SearchResult]:
    from ark_pi.rag import simple_index

    validate_search_limit(limit)
    manifest = _load_manifest(index_dir)
    _backend_from_manifest(manifest)
    return simple_index.search_index(index_dir, query, limit=limit)


def index_stats(index_dir: Path) -> IndexStats:
    manifest = _load_manifest(index_dir)
    backend = _backend_from_manifest(manifest)
    return IndexStats(
        backend=backend,
        schema_version=int(manifest["schema_version"]),
        chunk_count=int(manifest["chunk_count"]),
        index_dir=index_dir,
        source_chunks=str(manifest["source_chunks"]) if manifest.get("source_chunks") else None,
    )
