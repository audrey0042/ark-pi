import hashlib
import json
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ark_pi.deploy.plan import (
    build_deployment_install_plan,
    format_plan_json,
    render_plan_markdown,
)
from ark_pi.deploy.preflight import (
    LLM_ENV_FILENAME,
    LLM_SERVICE_FILENAME,
    OverallStatus,
    RAG_ENV_FILENAME,
    RAG_SERVICE_FILENAME,
    deployment_preflight_to_dict,
    run_deployment_preflight,
)
from ark_pi.deploy.templates import DEFAULT_OUTPUT_DIR, DeployRole

BUNDLE_SCHEMA_VERSION = 1
MANIFEST_FILENAME = "manifest.json"
README_FILENAME = "README.txt"
PREFLIGHT_REPORT_PATH = "reports/deployment-preflight.json"
PLAN_JSON_REPORT_PATH = "reports/deployment-plan.json"
PLAN_MD_REPORT_PATH = "reports/deployment-plan.md"

BUNDLE_FORBIDDEN_OUTPUT_ROOTS = (
    Path("/etc"),
    Path("/usr"),
    Path("/opt"),
    Path("/lib/systemd"),
    Path("/etc/systemd"),
)

BUNDLE_NOTES: tuple[str, ...] = (
    "This bundle is dry-run only.",
    "Review templates, preflight, and install plan before any manual Pi install.",
    "This bundle did not install services or mutate host service state.",
)


@dataclass(frozen=True)
class BundleManifestEntry:
    path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class DeploymentBundleResult:
    output_path: str
    role: DeployRole
    bundle_size_bytes: int
    entry_count: int
    preflight_overall_status: OverallStatus
    message: str


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _includes_rag(role: DeployRole) -> bool:
    return role in {"rag", "all"}


def _includes_llm(role: DeployRole) -> bool:
    return role in {"llm", "all"}


def validate_bundle_output_path(output_path: Path) -> Path:
    if not str(output_path).strip():
        msg = "output path must not be empty"
        raise ValueError(msg)
    resolved = output_path.expanduser().resolve()
    for forbidden in BUNDLE_FORBIDDEN_OUTPUT_ROOTS:
        forbidden_resolved = forbidden.resolve()
        if resolved == forbidden_resolved or _is_under(resolved, forbidden_resolved):
            msg = f"Refusing to write bundle output under {forbidden}"
            raise ValueError(msg)
    return resolved


def _resolve_generated_dir(generated_dir: Path | str) -> Path:
    if not str(generated_dir).strip():
        msg = "generated_dir must not be empty"
        raise ValueError(msg)
    return Path(generated_dir).expanduser().resolve()


def _read_template_bytes(generated_dir: Path, filename: str) -> bytes:
    source = generated_dir / filename
    if not source.is_file():
        msg = f"Missing expected deployment template file: {filename}"
        raise ValueError(msg)
    resolved = source.resolve()
    if not _is_under(resolved, generated_dir):
        msg = f"Refusing to include template outside generated_dir: {filename}"
        raise ValueError(msg)
    return resolved.read_bytes()


def _sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _template_zip_paths(role: DeployRole) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    if _includes_rag(role):
        entries.append((f"templates/{RAG_ENV_FILENAME}", RAG_ENV_FILENAME))
        entries.append((f"templates/{RAG_SERVICE_FILENAME}", RAG_SERVICE_FILENAME))
    if _includes_llm(role):
        entries.append((f"templates/{LLM_ENV_FILENAME}", LLM_ENV_FILENAME))
        entries.append((f"templates/{LLM_SERVICE_FILENAME}", LLM_SERVICE_FILENAME))
    return entries


def _render_readme(role: DeployRole, preflight_status: OverallStatus) -> str:
    return "\n".join(
        [
            "Ark Pi Deployment Bundle (dry-run review artifact)",
            "",
            f"Role: {role}",
            f"Preflight overall status: {preflight_status}",
            "",
            "This zip packages rendered deployment templates, preflight report,",
            "install plan, and checksum manifest for operator review.",
            "",
            "This bundle does NOT install services, copy files to system directories,",
            "run sudo, call systemctl, or mutate host service state.",
            "",
            "Copy this archive to another machine for human review before any manual",
            "Pi install steps.",
            "",
        ]
    )


def _manifest_to_dict(
    *,
    role: DeployRole,
    generated_dir: Path,
    preflight_status: OverallStatus,
    entries: list[BundleManifestEntry],
) -> dict[str, object]:
    return {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "created_by": "ark-pi",
        "bundle_type": "deployment",
        "created_at": _utc_now_iso(),
        "role": role,
        "dry_run": True,
        "host_mutations_performed": False,
        "network_checks_performed": False,
        "generated_dir": str(generated_dir),
        "preflight_overall_status": preflight_status,
        "entries": [
            {
                "path": entry.path,
                "size_bytes": entry.size_bytes,
                "sha256": entry.sha256,
            }
            for entry in entries
        ],
        "notes": list(BUNDLE_NOTES),
    }


def bundle_result_to_dict(result: DeploymentBundleResult) -> dict[str, object]:
    return {
        "output_path": result.output_path,
        "role": result.role,
        "bundle_size_bytes": result.bundle_size_bytes,
        "entry_count": result.entry_count,
        "preflight_overall_status": result.preflight_overall_status,
        "message": result.message,
    }


def build_deployment_bundle(
    generated_dir: Path | str = DEFAULT_OUTPUT_DIR,
    *,
    output_path: Path | str,
    role: DeployRole = "all",
    force: bool = False,
) -> DeploymentBundleResult:
    """Build a dry-run deployment bundle zip from rendered templates."""
    resolved_output = validate_bundle_output_path(Path(output_path))
    if resolved_output.exists() and not force:
        msg = (
            f"Refusing to overwrite existing bundle output: {resolved_output} "
            "(use force=true to overwrite)"
        )
        raise ValueError(msg)

    resolved_dir = _resolve_generated_dir(generated_dir)
    preflight = run_deployment_preflight(resolved_dir, role=role)
    if preflight.overall_status == "blocked":
        msg = (
            "Cannot build deployment bundle because deployment preflight is blocked. "
            "Render valid templates and fix template issues before creating a bundle."
        )
        raise ValueError(msg)

    plan = build_deployment_install_plan(resolved_dir, role=role)

    bundle_files: dict[str, bytes] = {}
    for zip_path, filename in _template_zip_paths(role):
        bundle_files[zip_path] = _read_template_bytes(resolved_dir, filename)

    preflight_json = json.dumps(deployment_preflight_to_dict(preflight), indent=2) + "\n"
    plan_json = format_plan_json(plan)
    plan_markdown = render_plan_markdown(plan)
    readme = _render_readme(role, preflight.overall_status)

    bundle_files[PREFLIGHT_REPORT_PATH] = preflight_json.encode("utf-8")
    bundle_files[PLAN_JSON_REPORT_PATH] = plan_json.encode("utf-8")
    bundle_files[PLAN_MD_REPORT_PATH] = plan_markdown.encode("utf-8")
    bundle_files[README_FILENAME] = readme.encode("utf-8")

    manifest_entries = [
        BundleManifestEntry(
            path=path,
            size_bytes=len(content),
            sha256=_sha256_hex(content),
        )
        for path, content in sorted(bundle_files.items())
    ]
    manifest_bytes = (
        json.dumps(
            _manifest_to_dict(
                role=role,
                generated_dir=resolved_dir,
                preflight_status=preflight.overall_status,
                entries=manifest_entries,
            ),
            indent=2,
        )
        + "\n"
    ).encode("utf-8")
    bundle_files[MANIFEST_FILENAME] = manifest_bytes

    entry_count = len(bundle_files)

    try:
        resolved_output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(resolved_output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path, content in sorted(bundle_files.items()):
                archive.writestr(path, content)
    except OSError as exc:
        msg = f"Cannot write deployment bundle {resolved_output}: {exc}"
        raise ValueError(msg) from exc

    bundle_size = resolved_output.stat().st_size
    message = (
        f"Dry-run deployment bundle for role {role!r} written to {resolved_output}. "
        f"Preflight status: {preflight.overall_status}. "
        f"{entry_count} entr{'y' if entry_count == 1 else 'ies'} packaged; "
        "no host mutations were performed."
    )

    return DeploymentBundleResult(
        output_path=str(resolved_output),
        role=role,
        bundle_size_bytes=bundle_size,
        entry_count=entry_count,
        preflight_overall_status=preflight.overall_status,
        message=message,
    )
