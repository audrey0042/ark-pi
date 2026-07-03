import io
import json
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from ark_pi.workspace.catalog import (
    CATALOG_SCHEMA_VERSION,
    CatalogIndexEntry,
    WorkspaceError,
    get_index,
    remove_index_from_catalog,
    upsert_index,
)
from ark_pi.workspace.export import (
    CREATED_BY,
    EXPORT_MANIFEST_FILENAME,
    EXPORT_SCHEMA_VERSION,
    EXPORT_TYPE,
)
from ark_pi.workspace.paths import (
    ensure_path_inside_workspace,
    index_paths,
    index_root_dir,
    resolve_workspace_dir,
    validate_slug,
)

_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")


class WorkspaceImportError(WorkspaceError):
    """Raised for invalid workspace import operations."""


@dataclass(frozen=True)
class ImportResult:
    archive_path: Path | None
    imported_count: int
    imported_slugs: list[str]
    message: str


def _resolve_archive_path(archive_path: Path) -> Path:
    if not str(archive_path).strip():
        msg = "Archive path must not be empty."
        raise WorkspaceImportError(msg)
    return archive_path.expanduser().resolve()


def _normalize_arcname(name: str) -> str:
    return name.replace("\\", "/")


def _is_absolute_arcname(name: str) -> bool:
    normalized = _normalize_arcname(name)
    if normalized.startswith("/"):
        return True
    return _WINDOWS_DRIVE_RE.match(normalized) is not None


def _is_symlink_entry(info: zipfile.ZipInfo) -> bool:
    unix_mode = info.external_attr >> 16
    return (unix_mode & 0o170000) == 0o120000


def _validate_arcname(name: str) -> None:
    normalized = _normalize_arcname(name)
    if not normalized or normalized.endswith("/"):
        return

    if _is_absolute_arcname(normalized):
        msg = f"Archive contains unsafe path: {name!r}"
        raise WorkspaceImportError(msg)

    parts = PurePosixPath(normalized).parts
    if ".." in parts:
        msg = f"Archive contains unsafe path: {name!r}"
        raise WorkspaceImportError(msg)

    if len(parts) == 1:
        if parts[0] not in {"catalog.json", EXPORT_MANIFEST_FILENAME}:
            msg = f"Archive entry not allowed: {name!r}"
            raise WorkspaceImportError(msg)
        return

    if parts[0] != "indexes":
        msg = f"Archive entry not allowed: {name!r}"
        raise WorkspaceImportError(msg)

    if len(parts) < 2:
        msg = f"Archive entry not allowed: {name!r}"
        raise WorkspaceImportError(msg)

    try:
        validate_slug(parts[1])
    except ValueError as exc:
        msg = f"Archive contains invalid index slug: {parts[1]!r}"
        raise WorkspaceImportError(msg) from exc


def _read_manifest(archive: zipfile.ZipFile) -> dict[str, object]:
    if EXPORT_MANIFEST_FILENAME not in archive.namelist():
        msg = f"Archive is missing {EXPORT_MANIFEST_FILENAME}."
        raise WorkspaceImportError(msg)

    try:
        raw = json.loads(archive.read(EXPORT_MANIFEST_FILENAME).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        msg = f"Invalid {EXPORT_MANIFEST_FILENAME} in archive."
        raise WorkspaceImportError(msg) from exc

    if not isinstance(raw, dict):
        msg = f"Invalid {EXPORT_MANIFEST_FILENAME} in archive."
        raise WorkspaceImportError(msg)

    schema_version = raw.get("schema_version")
    if schema_version != EXPORT_SCHEMA_VERSION:
        msg = f"Unsupported workspace export schema: {schema_version!r}"
        raise WorkspaceImportError(msg)

    if raw.get("created_by") != CREATED_BY:
        msg = "Archive was not created by Ark Pi."
        raise WorkspaceImportError(msg)

    if raw.get("export_type") != EXPORT_TYPE:
        msg = f"Unsupported export type: {raw.get('export_type')!r}"
        raise WorkspaceImportError(msg)

    return raw


def _read_catalog_entries(archive: zipfile.ZipFile) -> list[CatalogIndexEntry]:
    if "catalog.json" not in archive.namelist():
        msg = "Archive is missing catalog.json."
        raise WorkspaceImportError(msg)

    try:
        raw = json.loads(archive.read("catalog.json").decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        msg = "Invalid catalog.json in archive."
        raise WorkspaceImportError(msg) from exc

    if not isinstance(raw, dict):
        msg = "Invalid catalog.json in archive."
        raise WorkspaceImportError(msg)

    schema_version = raw.get("schema_version")
    if schema_version != CATALOG_SCHEMA_VERSION:
        msg = f"Unsupported catalog schema version: {schema_version!r}"
        raise WorkspaceImportError(msg)

    indexes = raw.get("indexes")
    if not isinstance(indexes, list):
        msg = "Invalid catalog indexes in archive."
        raise WorkspaceImportError(msg)

    entries: list[CatalogIndexEntry] = []
    for item in indexes:
        if not isinstance(item, dict):
            msg = "Invalid catalog entry in archive."
            raise WorkspaceImportError(msg)
        try:
            slug = validate_slug(str(item["slug"]))
        except ValueError as exc:
            msg = f"Invalid catalog slug in archive: {item.get('slug')!r}"
            raise WorkspaceImportError(msg) from exc
        entries.append(
            CatalogIndexEntry(
                name=str(item["name"]),
                slug=slug,
                backend=str(item["backend"]),
                chunks_path=str(item["chunks_path"]),
                index_dir=str(item["index_dir"]),
                chunk_count=int(item["chunk_count"]),
                source_count=int(item["source_count"]),
                created_at=str(item["created_at"]),
                updated_at=str(item["updated_at"]),
            )
        )

    if not entries:
        msg = "Archive catalog contains no indexes."
        raise WorkspaceImportError(msg)

    return entries


def _validate_required_index_files(
    archive_names: set[str],
    slugs: set[str],
) -> None:
    for slug in slugs:
        chunks_arcname = f"indexes/{slug}/chunks.jsonl"
        if chunks_arcname not in archive_names:
            msg = f"Archive is missing required file: {chunks_arcname}"
            raise WorkspaceImportError(msg)
        prefix = f"indexes/{slug}/index/"
        if not any(name.startswith(prefix) and not name.endswith("/") for name in archive_names):
            msg = f"Archive is missing index data for slug: {slug!r}"
            raise WorkspaceImportError(msg)


def _slug_exists(workspace_dir: Path, slug: str) -> bool:
    if get_index(workspace_dir, slug) is not None:
        return True
    try:
        root = index_root_dir(workspace_dir, slug)
    except ValueError:
        return False
    return root.exists()


def _remove_slug(workspace_dir: Path, slug: str) -> None:
    try:
        root = index_root_dir(workspace_dir, slug)
    except ValueError as exc:
        raise WorkspaceImportError(str(exc)) from exc
    if root.is_dir():
        shutil.rmtree(root)
    remove_index_from_catalog(workspace_dir, slug)


def _remap_entry(
    entry: CatalogIndexEntry,
    workspace_dir: Path,
) -> CatalogIndexEntry:
    chunks_path, index_dir = index_paths(workspace_dir, entry.slug)
    return CatalogIndexEntry(
        name=entry.name,
        slug=entry.slug,
        backend=entry.backend,
        chunks_path=str(chunks_path),
        index_dir=str(index_dir),
        chunk_count=entry.chunk_count,
        source_count=entry.source_count,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


def _extract_index_files(
    archive: zipfile.ZipFile,
    workspace_dir: Path,
    slug: str,
) -> None:
    workspace_root = resolve_workspace_dir(workspace_dir)
    index_root = index_root_dir(workspace_dir, slug)
    prefix = f"indexes/{slug}/"

    for info in archive.infolist():
        normalized = _normalize_arcname(info.filename)
        if info.is_dir() or normalized.endswith("/"):
            continue
        if not normalized.startswith(prefix):
            continue

        relative = PurePosixPath(normalized).relative_to(PurePosixPath("indexes") / slug)
        destination = (index_root / Path(relative.as_posix())).resolve()
        ensure_path_inside_workspace(workspace_root, destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(archive.read(info.filename))


def _build_import_message(imported_slugs: list[str], source_description: str) -> str:
    count = len(imported_slugs)
    if count == 1:
        return (
            f"Imported workspace index {imported_slugs[0]!r} from {source_description}."
        )
    return f"Imported {count} workspace index(es) from {source_description}."


def _import_workspace_zipfile(
    archive: zipfile.ZipFile,
    workspace_dir: Path,
    *,
    force: bool,
    source_description: str,
) -> ImportResult:
    archive_names = {_normalize_arcname(name) for name in archive.namelist()}

    for info in archive.infolist():
        if _is_symlink_entry(info):
            msg = f"Archive contains symlink entry: {info.filename!r}"
            raise WorkspaceImportError(msg)
        _validate_arcname(info.filename)

    _read_manifest(archive)
    entries = _read_catalog_entries(archive)
    imported_slugs = [entry.slug for entry in entries]
    _validate_required_index_files(archive_names, set(imported_slugs))

    conflicts = [slug for slug in imported_slugs if _slug_exists(workspace_dir, slug)]
    if conflicts and not force:
        slug_list = ", ".join(conflicts)
        msg = (
            f"Workspace index already exists: {slug_list}. "
            "Use force to replace it."
        )
        raise WorkspaceImportError(msg)

    if force:
        for slug in imported_slugs:
            if _slug_exists(workspace_dir, slug):
                _remove_slug(workspace_dir, slug)

    for entry in entries:
        _extract_index_files(archive, workspace_dir, entry.slug)
        upsert_index(workspace_dir, _remap_entry(entry, workspace_dir))

    message = _build_import_message(imported_slugs, source_description)
    return ImportResult(
        archive_path=None,
        imported_count=len(imported_slugs),
        imported_slugs=imported_slugs,
        message=message,
    )


def import_workspace_archive_fileobj(
    workspace_dir: Path,
    fileobj: BinaryIO,
    *,
    force: bool = False,
    source_description: str = "uploaded archive",
) -> ImportResult:
    """Import workspace catalog and index data from a zip archive file object."""
    try:
        archive = zipfile.ZipFile(fileobj, mode="r")
    except zipfile.BadZipFile as exc:
        msg = "Archive is not a valid zip file."
        raise WorkspaceImportError(msg) from exc

    with archive:
        return _import_workspace_zipfile(
            archive,
            workspace_dir,
            force=force,
            source_description=source_description,
        )


def import_workspace_archive_bytes(
    workspace_dir: Path,
    archive_bytes: bytes,
    *,
    force: bool = False,
) -> ImportResult:
    """Import workspace catalog and index data from an in-memory zip archive."""
    if not archive_bytes:
        msg = "Uploaded archive is empty."
        raise WorkspaceImportError(msg)
    return import_workspace_archive_fileobj(
        workspace_dir,
        io.BytesIO(archive_bytes),
        force=force,
    )


def import_workspace(
    workspace_dir: Path,
    archive_path: Path,
    *,
    force: bool = False,
) -> ImportResult:
    """Import workspace catalog and index data from an Ark Pi export zip archive."""
    resolved_archive = _resolve_archive_path(archive_path)
    if not resolved_archive.is_file():
        msg = f"Archive path does not exist: {resolved_archive}"
        raise WorkspaceImportError(msg)

    with resolved_archive.open("rb") as stream:
        result = import_workspace_archive_fileobj(
            workspace_dir,
            stream,
            force=force,
            source_description=str(resolved_archive),
        )

    return ImportResult(
        archive_path=resolved_archive,
        imported_count=result.imported_count,
        imported_slugs=result.imported_slugs,
        message=result.message,
    )
