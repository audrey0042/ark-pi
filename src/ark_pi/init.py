import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ark_pi.config import ArkSettings
from ark_pi.preflight import PreflightResult, preflight_to_dict, run_preflight
from ark_pi.workspace import catalog as workspace_catalog
from ark_pi.workspace.catalog import CATALOG_SCHEMA_VERSION
from ark_pi.workspace.paths import resolve_source_dir, resolve_workspace_dir

SAMPLE_SOURCE_FILENAME = "ark-pi-sample.txt"
SAMPLE_SOURCE_TEXT = (
    "Ark Pi is a local RAG appliance for offline document search and "
    "question answering.\n\n"
    "Place plain text (.txt) source files in your configured source directory, "
    "ingest them into workspace indexes, and ask questions through the CLI, "
    "API, or built-in web UI.\n"
)

CatalogStatus = Literal["missing", "valid", "invalid"]


@dataclass(frozen=True)
class InitResult:
    created_paths: list[str]
    existing_paths: list[str]
    skipped: list[str]
    sample_source_path: str | None
    preflight: PreflightResult
    message: str


def _validate_configured_dir(path: Path, label: str) -> Path:
    if not str(path).strip():
        msg = f"{label} must not be empty"
        raise ValueError(msg)
    resolved = path.expanduser().resolve()
    if resolved.exists() and not resolved.is_dir():
        msg = f"{label} exists but is not a directory: {resolved}"
        raise ValueError(msg)
    return resolved


def _ensure_directory(path: Path) -> Literal["created", "existing"]:
    if path.exists():
        if not path.is_dir():
            msg = f"Path exists but is not a directory: {path}"
            raise ValueError(msg)
        return "existing"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        msg = f"Cannot create directory {path}: {exc}"
        raise ValueError(msg) from exc
    return "created"


def _catalog_status(workspace_dir: Path) -> CatalogStatus:
    path = workspace_catalog.catalog_path(workspace_dir)
    if not path.is_file():
        return "missing"
    try:
        workspace_catalog.load_catalog(workspace_dir)
    except ValueError:
        return "invalid"
    return "valid"


def _write_empty_catalog(workspace_dir: Path) -> None:
    path = workspace_catalog.catalog_path(workspace_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "indexes": [],
    }
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _ensure_sample_source(source_dir: Path, *, force: bool) -> tuple[str | None, Literal["created", "existing", "skipped", "replaced"]]:
    sample_path = source_dir / SAMPLE_SOURCE_FILENAME
    try:
        sample_path.relative_to(source_dir)
    except ValueError as exc:
        msg = f"Sample source path escapes source directory: {sample_path}"
        raise ValueError(msg) from exc

    if sample_path.is_file():
        if force:
            sample_path.write_text(SAMPLE_SOURCE_TEXT, encoding="utf-8")
            return str(sample_path), "replaced"
        return str(sample_path), "skipped"

    try:
        sample_path.write_text(SAMPLE_SOURCE_TEXT, encoding="utf-8")
    except OSError as exc:
        msg = f"Cannot write sample source file {sample_path}: {exc}"
        raise ValueError(msg) from exc
    return str(sample_path), "created"


def initialize_appliance(
    *,
    settings: ArkSettings | None = None,
    create_catalog: bool = True,
    create_sample_source: bool = False,
    force: bool = False,
) -> InitResult:
    """Create local appliance directories and optional seed files, then run passive preflight."""
    if settings is None:
        from ark_pi.config import get_settings

        settings = get_settings()

    workspace_root = _validate_configured_dir(settings.workspace_dir, "workspace_dir")
    source_root = _validate_configured_dir(settings.source_dir, "source_dir")

    created_paths: list[str] = []
    existing_paths: list[str] = []
    skipped: list[str] = []
    sample_source_path: str | None = None

    workspace_status = _ensure_directory(workspace_root)
    if workspace_status == "created":
        created_paths.append(str(workspace_root))
    else:
        existing_paths.append(str(workspace_root))

    indexes_dir = workspace_root / "indexes"
    indexes_status = _ensure_directory(indexes_dir)
    if indexes_status == "created":
        created_paths.append(str(indexes_dir))
    else:
        existing_paths.append(str(indexes_dir))

    source_status = _ensure_directory(source_root)
    if source_status == "created":
        created_paths.append(str(source_root))
    else:
        existing_paths.append(str(source_root))

    if create_catalog:
        catalog_file = workspace_catalog.catalog_path(settings.workspace_dir)
        status = _catalog_status(settings.workspace_dir)
        if status == "missing":
            _write_empty_catalog(settings.workspace_dir)
            created_paths.append(str(catalog_file))
        elif status == "valid":
            existing_paths.append(str(catalog_file))
        elif force:
            _write_empty_catalog(settings.workspace_dir)
            created_paths.append(str(catalog_file))
        else:
            msg = f"Invalid workspace catalog at {catalog_file}; use force=true to replace it"
            raise ValueError(msg)
    else:
        catalog_file = workspace_catalog.catalog_path(settings.workspace_dir)
        skipped.append(str(catalog_file))

    if create_sample_source:
        resolved_source = resolve_source_dir(settings.source_dir)
        sample_path, sample_action = _ensure_sample_source(resolved_source, force=force)
        sample_source_path = sample_path
        if sample_action == "created":
            created_paths.append(sample_path)
        elif sample_action == "replaced":
            created_paths.append(sample_path)
        elif sample_action == "existing":
            existing_paths.append(sample_path)
        else:
            skipped.append(sample_path)

    preflight = run_preflight(settings)

    parts: list[str] = []
    if created_paths:
        parts.append(f"Created {len(created_paths)} path(s)")
    if existing_paths:
        parts.append(f"{len(existing_paths)} path(s) already existed")
    if skipped:
        parts.append(f"Skipped {len(skipped)} path(s)")
    message = "; ".join(parts) if parts else "Local appliance storage is ready"
    message += f". Preflight status: {preflight.overall_status}."

    return InitResult(
        created_paths=created_paths,
        existing_paths=existing_paths,
        skipped=skipped,
        sample_source_path=sample_source_path,
        preflight=preflight,
        message=message,
    )


def init_to_dict(result: InitResult) -> dict[str, object]:
    return {
        "created_paths": result.created_paths,
        "existing_paths": result.existing_paths,
        "skipped": result.skipped,
        "sample_source_path": result.sample_source_path,
        "preflight": preflight_to_dict(result.preflight),
        "message": result.message,
    }
