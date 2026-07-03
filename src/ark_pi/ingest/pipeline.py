from dataclasses import dataclass
from pathlib import Path

from ark_pi.ingest import chunking
from ark_pi.ingest.sources import SourceRecord
from ark_pi.rag import index as rag_index


def _project_root() -> Path | None:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return None


def validate_output_path(path: Path, *, label: str) -> Path:
    if not str(path).strip():
        msg = f"{label} must not be empty"
        raise ValueError(msg)
    resolved = path.expanduser().resolve()
    root = _project_root()
    if root is not None and resolved == root:
        msg = f"{label} must not be the repository root"
        raise ValueError(msg)
    return resolved


@dataclass(frozen=True)
class TextIngestResult:
    title: str
    chunks_path: Path
    index_dir: Path
    backend: str
    chunk_count: int
    source_count: int


def ingest_sources_to_index(
    sources: list[SourceRecord],
    chunks_path: Path,
    index_dir: Path,
    *,
    backend: str | None = None,
    config_backend: str = "simple",
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    force: bool = False,
) -> TextIngestResult:
    """Chunk loaded sources, write JSONL, and build a local index."""
    if not sources:
        msg = "sources produced no content to chunk"
        raise ValueError(msg)

    resolved_chunks_path = validate_output_path(chunks_path, label="chunks_path")
    resolved_index_dir = validate_output_path(index_dir, label="index_dir")

    chunking.validate_chunk_params(chunk_size, chunk_overlap)

    records = chunking.make_chunk_records(sources, chunk_size, chunk_overlap)
    if not records:
        msg = "sources produced no chunks after chunking"
        raise ValueError(msg)

    chunking.write_chunks_jsonl(records, resolved_chunks_path, force=force)
    stats = rag_index.build_index(
        resolved_chunks_path,
        resolved_index_dir,
        backend=backend,
        config_backend=config_backend,
        force=force,
    )

    title = sources[0].title
    return TextIngestResult(
        title=title,
        chunks_path=resolved_chunks_path,
        index_dir=resolved_index_dir,
        backend=stats.backend,
        chunk_count=stats.chunk_count,
        source_count=len(sources),
    )


def ingest_text_to_index(
    title: str,
    text: str,
    chunks_path: Path,
    index_dir: Path,
    *,
    backend: str | None = None,
    config_backend: str = "simple",
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    force: bool = False,
) -> TextIngestResult:
    """Chunk pasted text in memory, write JSONL, and build a local index."""
    stripped_title = title.strip()
    if not stripped_title:
        msg = "title must not be empty"
        raise ValueError(msg)

    stripped_text = text.strip()
    if not stripped_text:
        msg = "text must not be empty"
        raise ValueError(msg)

    source = SourceRecord(
        title=stripped_title,
        text=stripped_text,
        source=f"web:{stripped_title}",
    )
    return ingest_sources_to_index(
        [source],
        chunks_path,
        index_dir,
        backend=backend,
        config_backend=config_backend,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        force=force,
    )
