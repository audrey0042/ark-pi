import io
import json
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO

from ark_pi.workspace.catalog import (
    CATALOG_SCHEMA_VERSION,
    CatalogIndexEntry,
    WorkspaceError,
    WorkspaceIndexNotFoundError,
    get_index,
    list_indexes,
    utc_now_iso,
)
from ark_pi.workspace.paths import ensure_path_inside_workspace, index_root_dir, resolve_workspace_dir

EXPORT_MANIFEST_FILENAME = "export_manifest.json"
EXPORT_SCHEMA_VERSION = 1
CREATED_BY = "ark-pi"
EXPORT_TYPE = "workspace"
ALL_INDEXES_DOWNLOAD_FILENAME = "ark-pi-workspace-export.zip"


class WorkspaceExportError(WorkspaceError):
    """Raised for invalid workspace export operations."""


@dataclass(frozen=True)
class ExportResult:
    output_path: Path
    index_count: int
    archive_size_bytes: int
    message: str


@dataclass(frozen=True)
class ExportArchiveInfo:
    index_count: int
    archive_size_bytes: int
    exported_slugs: list[str]


def export_download_filename(slug: str | None) -> str:
    if slug is not None:
        return f"ark-pi-index-{slug}.zip"
    return ALL_INDEXES_DOWNLOAD_FILENAME


def _resolve_output_path(output_path: Path) -> Path:
    if not str(output_path).strip():
        msg = "Export path must not be empty."
        raise WorkspaceExportError(msg)
    return output_path.expanduser().resolve()


def _select_entries(workspace_dir: Path, slug: str | None) -> list[CatalogIndexEntry]:
    if slug is not None:
        try:
            index_root_dir(workspace_dir, slug)
        except ValueError as exc:
            raise WorkspaceExportError(str(exc)) from exc
        entry = get_index(workspace_dir, slug)
        if entry is None:
            raise WorkspaceIndexNotFoundError("Workspace index not found.")
        return [entry]

    entries = list_indexes(workspace_dir)
    if not entries:
        msg = "Workspace catalog is empty."
        raise WorkspaceExportError(msg)
    return entries


def _catalog_payload(entries: list[CatalogIndexEntry]) -> dict[str, object]:
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "indexes": [asdict(entry) for entry in entries],
    }


def _manifest_payload(entries: list[CatalogIndexEntry]) -> dict[str, object]:
    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "created_by": CREATED_BY,
        "export_type": EXPORT_TYPE,
        "exported_at": utc_now_iso(),
        "index_count": len(entries),
        "indexes": [
            {
                "name": entry.name,
                "slug": entry.slug,
                "backend": entry.backend,
                "chunk_count": entry.chunk_count,
                "source_count": entry.source_count,
            }
            for entry in entries
        ],
    }


def _add_index_files(
    archive: zipfile.ZipFile,
    workspace_dir: Path,
    slug: str,
) -> None:
    workspace_root = resolve_workspace_dir(workspace_dir)
    index_root = index_root_dir(workspace_dir, slug)
    if not index_root.exists():
        return

    for path in index_root.rglob("*"):
        if not path.is_file():
            continue
        resolved = path.resolve()
        ensure_path_inside_workspace(workspace_root, resolved)
        relative = path.relative_to(index_root)
        arcname = Path("indexes") / slug / relative
        archive.write(resolved, arcname=str(arcname))


def _write_export_archive(
    archive: zipfile.ZipFile,
    workspace_dir: Path,
    entries: list[CatalogIndexEntry],
) -> None:
    catalog_json = json.dumps(_catalog_payload(entries), indent=2) + "\n"
    manifest_json = json.dumps(_manifest_payload(entries), indent=2) + "\n"
    archive.writestr("catalog.json", catalog_json)
    archive.writestr(EXPORT_MANIFEST_FILENAME, manifest_json)
    for entry in entries:
        _add_index_files(archive, workspace_dir, entry.slug)


def write_workspace_export_zip(
    workspace_dir: Path,
    fileobj: BinaryIO,
    *,
    slug: str | None = None,
) -> ExportArchiveInfo:
    """Write workspace catalog and index data to a zip archive file object."""
    entries = _select_entries(workspace_dir, slug)
    with zipfile.ZipFile(fileobj, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        _write_export_archive(archive, workspace_dir, entries)

    if hasattr(fileobj, "tell"):
        archive_size = fileobj.tell()
    else:
        archive_size = 0

    return ExportArchiveInfo(
        index_count=len(entries),
        archive_size_bytes=archive_size,
        exported_slugs=[entry.slug for entry in entries],
    )


def export_workspace_to_bytes(
    workspace_dir: Path,
    *,
    slug: str | None = None,
) -> tuple[bytes, ExportArchiveInfo]:
    """Export workspace catalog and index data to an in-memory zip archive."""
    buffer = io.BytesIO()
    info = write_workspace_export_zip(workspace_dir, buffer, slug=slug)
    data = buffer.getvalue()
    return data, ExportArchiveInfo(
        index_count=info.index_count,
        archive_size_bytes=len(data),
        exported_slugs=info.exported_slugs,
    )


def export_workspace(
    workspace_dir: Path,
    output_path: Path,
    *,
    slug: str | None = None,
    force: bool = False,
) -> ExportResult:
    """Export workspace catalog and index data to a zip archive."""
    resolved_output = _resolve_output_path(output_path)
    entries = _select_entries(workspace_dir, slug)

    if resolved_output.exists() and not force:
        msg = "Export path already exists. Use force to overwrite."
        raise WorkspaceExportError(msg)

    resolved_output.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(resolved_output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        _write_export_archive(archive, workspace_dir, entries)

    archive_size = resolved_output.stat().st_size
    if slug is not None:
        message = (
            f"Exported workspace index {slug!r} to {resolved_output} "
            f"({archive_size} bytes)."
        )
    else:
        message = (
            f"Exported {len(entries)} workspace index(es) to {resolved_output} "
            f"({archive_size} bytes)."
        )

    return ExportResult(
        output_path=resolved_output,
        index_count=len(entries),
        archive_size_bytes=archive_size,
        message=message,
    )
