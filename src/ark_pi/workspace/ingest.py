from dataclasses import dataclass
from pathlib import Path

from ark_pi.ingest import pipeline as ingest_pipeline
from ark_pi.ingest import sources as ingest_sources
from ark_pi.workspace import catalog as workspace_catalog
from ark_pi.workspace.paths import (
    index_paths,
    resolve_source_path,
    validate_index_name,
    validate_txt_source_path,
)


@dataclass(frozen=True)
class WorkspaceIngestResult:
    title: str
    chunks_path: Path
    index_dir: Path
    backend: str
    chunk_count: int
    source_count: int
    index_name: str
    index_slug: str
    catalog_updated: bool


@dataclass(frozen=True)
class WorkspacePathIngestResult:
    source_path: Path
    chunks_path: Path
    index_dir: Path
    backend: str
    chunk_count: int
    source_count: int
    index_name: str
    index_slug: str
    catalog_updated: bool


def ingest_text_to_workspace_index(
    title: str,
    text: str,
    index_name: str,
    workspace_dir: Path,
    *,
    backend: str | None = None,
    config_backend: str = "simple",
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    force: bool = False,
) -> WorkspaceIngestResult:
    slug = validate_index_name(index_name)
    display_name = index_name.strip()
    existing = workspace_catalog.get_index(workspace_dir, slug)
    if existing is not None and not force:
        msg = f"Index already exists: {display_name!r} (use force=true to rebuild)"
        raise ValueError(msg)

    chunks_path, index_dir = index_paths(workspace_dir, slug)
    result = ingest_pipeline.ingest_text_to_index(
        title,
        text,
        chunks_path,
        index_dir,
        backend=backend,
        config_backend=config_backend,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        force=force,
    )

    now = workspace_catalog.utc_now_iso()
    created_at = existing.created_at if existing is not None else now
    entry = workspace_catalog.CatalogIndexEntry(
        name=display_name,
        slug=slug,
        backend=result.backend,
        chunks_path=str(result.chunks_path),
        index_dir=str(result.index_dir),
        chunk_count=result.chunk_count,
        source_count=result.source_count,
        created_at=created_at,
        updated_at=now,
    )
    workspace_catalog.upsert_index(workspace_dir, entry)

    return WorkspaceIngestResult(
        title=result.title,
        chunks_path=result.chunks_path,
        index_dir=result.index_dir,
        backend=result.backend,
        chunk_count=result.chunk_count,
        source_count=result.source_count,
        index_name=display_name,
        index_slug=slug,
        catalog_updated=True,
    )


def ingest_source_path_to_workspace_index(
    source_path: str,
    index_name: str,
    source_dir: Path,
    workspace_dir: Path,
    *,
    backend: str | None = None,
    config_backend: str = "simple",
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    force: bool = False,
) -> WorkspacePathIngestResult:
    slug = validate_index_name(index_name)
    display_name = index_name.strip()
    existing = workspace_catalog.get_index(workspace_dir, slug)
    if existing is not None and not force:
        msg = f"Index already exists: {display_name!r} (use force=true to rebuild)"
        raise ValueError(msg)

    resolved_source = resolve_source_path(source_dir, source_path)
    validate_txt_source_path(resolved_source)
    loaded_sources = ingest_sources.load_txt_sources(resolved_source)

    chunks_path, index_dir = index_paths(workspace_dir, slug)
    result = ingest_pipeline.ingest_sources_to_index(
        loaded_sources,
        chunks_path,
        index_dir,
        backend=backend,
        config_backend=config_backend,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        force=force,
    )

    now = workspace_catalog.utc_now_iso()
    created_at = existing.created_at if existing is not None else now
    entry = workspace_catalog.CatalogIndexEntry(
        name=display_name,
        slug=slug,
        backend=result.backend,
        chunks_path=str(result.chunks_path),
        index_dir=str(result.index_dir),
        chunk_count=result.chunk_count,
        source_count=result.source_count,
        created_at=created_at,
        updated_at=now,
    )
    workspace_catalog.upsert_index(workspace_dir, entry)

    return WorkspacePathIngestResult(
        source_path=resolved_source,
        chunks_path=result.chunks_path,
        index_dir=result.index_dir,
        backend=result.backend,
        chunk_count=result.chunk_count,
        source_count=result.source_count,
        index_name=display_name,
        index_slug=slug,
        catalog_updated=True,
    )
