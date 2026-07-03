import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from ark_pi.config import ArkSettings
from ark_pi.llm_client.diagnostics import llm_passive_status
from ark_pi.rag.backends import CHROMA_INSTALL_HINT
from ark_pi.workspace import catalog as workspace_catalog
from ark_pi.workspace.paths import index_root_dir, resolve_workspace_dir

CheckStatus = Literal["pass", "warning", "fail"]
OverallStatus = Literal["ready", "warning", "blocked"]


@dataclass(frozen=True)
class PreflightCheck:
    id: str
    label: str
    status: CheckStatus
    message: str
    details: dict[str, object]


@dataclass(frozen=True)
class PreflightResult:
    role: str
    overall_status: OverallStatus
    generated_at: str
    network_checks_performed: bool
    checks: list[PreflightCheck]


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _overall_status(checks: list[PreflightCheck]) -> OverallStatus:
    if any(check.status == "fail" for check in checks):
        return "blocked"
    if any(check.status == "warning" for check in checks):
        return "warning"
    return "ready"


def _resolved_path(path: Path) -> Path:
    return path.expanduser().resolve()


def _check_config(settings: ArkSettings) -> PreflightCheck:
    return PreflightCheck(
        id="config",
        label="Configuration",
        status="pass",
        message="Core configuration loaded.",
        details={
            "role": settings.role,
            "workspace_dir": str(settings.workspace_dir),
            "source_dir": str(settings.source_dir),
            "index_backend": settings.index_backend,
            "llm_backend": settings.llm_backend,
            "max_import_bytes": settings.max_import_bytes,
        },
    )


def _check_workspace_dir(settings: ArkSettings) -> PreflightCheck:
    path = _resolved_path(settings.workspace_dir)
    if path.exists() and not path.is_dir():
        return PreflightCheck(
            id="workspace_dir",
            label="Workspace directory",
            status="fail",
            message=f"Workspace path exists but is not a directory: {path}",
            details={"path": str(path)},
        )
    if not path.exists():
        return PreflightCheck(
            id="workspace_dir",
            label="Workspace directory",
            status="warning",
            message=f"Workspace directory does not exist yet: {path}",
            details={"path": str(path), "exists": False},
        )
    readable = os.access(path, os.R_OK)
    writable = os.access(path, os.W_OK)
    if not readable or not writable:
        return PreflightCheck(
            id="workspace_dir",
            label="Workspace directory",
            status="fail",
            message=f"Workspace directory is not readable and writable: {path}",
            details={"path": str(path), "readable": readable, "writable": writable},
        )
    return PreflightCheck(
        id="workspace_dir",
        label="Workspace directory",
        status="pass",
        message=f"Workspace directory is ready: {path}",
        details={"path": str(path), "readable": True, "writable": True},
    )


def _check_source_dir(settings: ArkSettings) -> PreflightCheck:
    path = _resolved_path(settings.source_dir)
    if path.exists() and not path.is_dir():
        return PreflightCheck(
            id="source_dir",
            label="Source directory",
            status="fail",
            message=f"Source path exists but is not a directory: {path}",
            details={"path": str(path)},
        )
    if not path.exists():
        return PreflightCheck(
            id="source_dir",
            label="Source directory",
            status="warning",
            message=f"Source directory does not exist yet: {path}",
            details={"path": str(path), "exists": False},
        )
    readable = os.access(path, os.R_OK)
    if not readable:
        return PreflightCheck(
            id="source_dir",
            label="Source directory",
            status="fail",
            message=f"Source directory is not readable: {path}",
            details={"path": str(path), "readable": False},
        )
    return PreflightCheck(
        id="source_dir",
        label="Source directory",
        status="pass",
        message=f"Source directory is readable: {path}",
        details={"path": str(path), "readable": True},
    )


def _check_catalog(settings: ArkSettings) -> PreflightCheck:
    path = workspace_catalog.catalog_path(settings.workspace_dir)
    if not path.is_file():
        return PreflightCheck(
            id="workspace_catalog",
            label="Workspace catalog",
            status="warning",
            message="Workspace catalog does not exist yet.",
            details={"path": str(path), "index_count": 0},
        )
    try:
        entries = workspace_catalog.load_catalog(settings.workspace_dir)
    except ValueError as exc:
        return PreflightCheck(
            id="workspace_catalog",
            label="Workspace catalog",
            status="fail",
            message=str(exc),
            details={"path": str(path)},
        )
    except OSError as exc:
        return PreflightCheck(
            id="workspace_catalog",
            label="Workspace catalog",
            status="fail",
            message=f"Could not read workspace catalog: {exc}",
            details={"path": str(path)},
        )
    return PreflightCheck(
        id="workspace_catalog",
        label="Workspace catalog",
        status="pass",
        message=f"Workspace catalog is readable with {len(entries)} index(es).",
        details={"path": str(path), "index_count": len(entries)},
    )


def _check_workspace_indexes(
    settings: ArkSettings,
    catalog_check: PreflightCheck,
) -> PreflightCheck:
    index_count = catalog_check.details.get("index_count", 0)
    if catalog_check.status == "fail":
        return PreflightCheck(
            id="workspace_indexes",
            label="Workspace indexes",
            status="fail",
            message="Cannot verify workspace indexes because the catalog is invalid.",
            details={"index_count": index_count},
        )
    if catalog_check.status == "warning" or index_count == 0:
        return PreflightCheck(
            id="workspace_indexes",
            label="Workspace indexes",
            status="warning",
            message="No workspace indexes are cataloged yet.",
            details={"index_count": 0, "missing_slugs": []},
        )

    try:
        entries = workspace_catalog.load_catalog(settings.workspace_dir)
    except ValueError as exc:
        return PreflightCheck(
            id="workspace_indexes",
            label="Workspace indexes",
            status="fail",
            message=str(exc),
            details={"index_count": index_count},
        )

    workspace_root = resolve_workspace_dir(settings.workspace_dir)
    missing_slugs: list[str] = []
    for entry in entries:
        try:
            index_root = index_root_dir(settings.workspace_dir, entry.slug)
        except ValueError as exc:
            return PreflightCheck(
                id="workspace_indexes",
                label="Workspace indexes",
                status="fail",
                message=str(exc),
                details={"slug": entry.slug},
            )
        try:
            index_root.relative_to(workspace_root)
        except ValueError:
            return PreflightCheck(
                id="workspace_indexes",
                label="Workspace indexes",
                status="fail",
                message=f"Catalog index path escapes workspace: {entry.slug!r}",
                details={"slug": entry.slug, "index_root": str(index_root)},
            )
        if not index_root.is_dir():
            missing_slugs.append(entry.slug)

    if missing_slugs:
        return PreflightCheck(
            id="workspace_indexes",
            label="Workspace indexes",
            status="fail",
            message=f"Missing index directories for: {', '.join(missing_slugs)}",
            details={"index_count": len(entries), "missing_slugs": missing_slugs},
        )

    return PreflightCheck(
        id="workspace_indexes",
        label="Workspace indexes",
        status="pass",
        message=f"All {len(entries)} cataloged index root(s) exist under the workspace.",
        details={"index_count": len(entries), "missing_slugs": []},
    )


def _count_txt_files(source_dir: Path) -> int:
    count = 0
    for path in source_dir.rglob("*.txt"):
        if path.is_file():
            count += 1
    return count


def _check_source_ingest(settings: ArkSettings) -> PreflightCheck:
    path = _resolved_path(settings.source_dir)
    if not path.is_dir():
        return PreflightCheck(
            id="source_ingest",
            label="Source ingest readiness",
            status="warning",
            message="Source directory is not available for local file ingest.",
            details={"path": str(path), "txt_file_count": 0},
        )
    txt_count = _count_txt_files(path)
    if txt_count == 0:
        return PreflightCheck(
            id="source_ingest",
            label="Source ingest readiness",
            status="warning",
            message="Source directory contains no .txt files yet.",
            details={"path": str(path), "txt_file_count": 0},
        )
    return PreflightCheck(
        id="source_ingest",
        label="Source ingest readiness",
        status="pass",
        message=f"Source directory contains {txt_count} .txt file(s).",
        details={"path": str(path), "txt_file_count": txt_count},
    )


def _chroma_importable() -> bool:
    try:
        import chromadb  # noqa: F401
    except ImportError:
        return False
    return True


def _check_index_backend(settings: ArkSettings) -> PreflightCheck:
    backend = settings.index_backend
    if backend == "simple":
        return PreflightCheck(
            id="index_backend",
            label="Index backend",
            status="pass",
            message="Simple lexical index backend is configured.",
            details={"backend": backend},
        )
    if backend == "chroma":
        if _chroma_importable():
            return PreflightCheck(
                id="index_backend",
                label="Index backend",
                status="pass",
                message="Chroma index backend is configured and importable.",
                details={"backend": backend, "chromadb_importable": True},
            )
        return PreflightCheck(
            id="index_backend",
            label="Index backend",
            status="fail",
            message=CHROMA_INSTALL_HINT,
            details={"backend": backend, "chromadb_importable": False},
        )
    return PreflightCheck(
        id="index_backend",
        label="Index backend",
        status="fail",
        message=f"Unsupported index backend: {backend!r}",
        details={"backend": backend},
    )


def _check_llm(settings: ArkSettings) -> PreflightCheck:
    status = llm_passive_status(settings)
    details: dict[str, object] = {
        "backend": status.backend,
        "model": status.model,
        "base_url_configured": status.base_url_configured,
        "base_url_display": status.base_url_display,
        "network_check_performed": status.network_check_performed,
    }
    if status.backend == "mock":
        return PreflightCheck(
            id="llm",
            label="LLM configuration",
            status="pass",
            message=status.message,
            details=details,
        )
    if status.backend == "openai-compatible":
        if status.base_url_configured:
            return PreflightCheck(
                id="llm",
                label="LLM configuration",
                status="warning",
                message=(
                    f"{status.message} Preflight does not test LLM reachability."
                ),
                details=details,
            )
        return PreflightCheck(
            id="llm",
            label="LLM configuration",
            status="fail",
            message=status.message,
            details=details,
        )
    return PreflightCheck(
        id="llm",
        label="LLM configuration",
        status="fail",
        message=f"Unsupported LLM backend: {status.backend!r}",
        details=details,
    )


def _check_import_limit(settings: ArkSettings) -> PreflightCheck:
    if settings.max_import_bytes <= 0:
        return PreflightCheck(
            id="import_limit",
            label="Import size limit",
            status="fail",
            message="max_import_bytes must be positive.",
            details={"max_import_bytes": settings.max_import_bytes},
        )
    return PreflightCheck(
        id="import_limit",
        label="Import size limit",
        status="pass",
        message=f"Browser import limit is {settings.max_import_bytes} bytes.",
        details={"max_import_bytes": settings.max_import_bytes},
    )


def _check_disk_space(settings: ArkSettings) -> PreflightCheck:
    workspace_path = _resolved_path(settings.workspace_dir)
    inspect_path = workspace_path if workspace_path.exists() else workspace_path.parent
    try:
        usage = shutil.disk_usage(inspect_path)
    except OSError as exc:
        return PreflightCheck(
            id="disk_space",
            label="Disk space",
            status="warning",
            message=f"Could not inspect free disk space for {inspect_path}: {exc}",
            details={"path": str(inspect_path)},
        )
    return PreflightCheck(
        id="disk_space",
        label="Disk space",
        status="pass",
        message=f"Free disk space available at {inspect_path}.",
        details={
            "path": str(inspect_path),
            "free_bytes": usage.free,
            "total_bytes": usage.total,
        },
    )


def run_preflight(settings: ArkSettings | None = None) -> PreflightResult:
    """Run passive appliance readiness checks without network calls or mutations."""
    if settings is None:
        from ark_pi.config import get_settings

        settings = get_settings()

    catalog_check = _check_catalog(settings)
    checks = [
        _check_config(settings),
        _check_workspace_dir(settings),
        _check_source_dir(settings),
        catalog_check,
        _check_workspace_indexes(settings, catalog_check),
        _check_source_ingest(settings),
        _check_index_backend(settings),
        _check_llm(settings),
        _check_import_limit(settings),
        _check_disk_space(settings),
    ]
    return PreflightResult(
        role=settings.role,
        overall_status=_overall_status(checks),
        generated_at=_utc_now_iso(),
        network_checks_performed=False,
        checks=checks,
    )


def preflight_to_dict(result: PreflightResult) -> dict[str, object]:
    return {
        "role": result.role,
        "overall_status": result.overall_status,
        "generated_at": result.generated_at,
        "network_checks_performed": result.network_checks_performed,
        "checks": [
            {
                "id": check.id,
                "label": check.label,
                "status": check.status,
                "message": check.message,
                "details": check.details,
            }
            for check in result.checks
        ],
    }
