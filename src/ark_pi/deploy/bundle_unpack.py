import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from ark_pi.deploy.bundle import MANIFEST_FILENAME, README_FILENAME
from ark_pi.deploy.bundle_verify import BundleRole, verify_deployment_bundle

VerificationStatus = Literal["valid", "warning"]

FORBIDDEN_STAGING_ROOTS = (
    Path("/"),
    Path("/etc"),
    Path("/usr"),
    Path("/opt"),
    Path("/lib"),
    Path("/lib/systemd"),
    Path("/etc/systemd"),
    Path("/srv"),
)


@dataclass(frozen=True)
class DeploymentBundleUnpackResult:
    bundle_path: str
    staging_dir: str
    role: BundleRole
    verification_status: VerificationStatus
    extracted_count: int
    extracted_files: list[str]
    message: str


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate_staging_dir(staging_dir: Path | str) -> Path:
    if not str(staging_dir).strip():
        msg = "staging_dir must not be empty"
        raise ValueError(msg)
    resolved = Path(staging_dir).expanduser().resolve()
    for forbidden in FORBIDDEN_STAGING_ROOTS:
        forbidden_resolved = forbidden.resolve()
        if resolved == forbidden_resolved:
            msg = f"Refusing to unpack into forbidden staging directory: {forbidden}"
            raise ValueError(msg)
        if forbidden_resolved != Path("/") and _is_under(resolved, forbidden_resolved):
            msg = f"Refusing to unpack into forbidden staging directory under {forbidden}"
            raise ValueError(msg)
    return resolved


def _staging_has_contents(staging_dir: Path) -> bool:
    if not staging_dir.exists():
        return False
    return any(staging_dir.iterdir())


def _clear_staging_dir(staging_dir: Path) -> None:
    if not staging_dir.exists():
        return
    for child in staging_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _entry_is_allowed(name: str) -> bool:
    if name in {README_FILENAME, MANIFEST_FILENAME}:
        return True
    if name.startswith("templates/") and not name.endswith("/"):
        return PurePosixPath(name).parts[0] == "templates" and ".." not in PurePosixPath(name).parts
    if name.startswith("reports/") and not name.endswith("/"):
        return PurePosixPath(name).parts[0] == "reports" and ".." not in PurePosixPath(name).parts
    return False


def _entry_is_unsafe(name: str) -> str | None:
    if name.startswith("/") or PurePosixPath(name).is_absolute():
        return "absolute path"
    if ".." in PurePosixPath(name).parts:
        return "path traversal"
    if not _entry_is_allowed(name):
        return "entry outside allowed bundle layout"
    return None


def _resolve_extract_target(staging_dir: Path, entry_name: str) -> Path:
    unsafe = _entry_is_unsafe(entry_name)
    if unsafe is not None:
        msg = f"Refusing to extract unsafe archive entry {entry_name!r}: {unsafe}"
        raise ValueError(msg)
    target = (staging_dir / entry_name).resolve()
    staging_resolved = staging_dir.resolve()
    if not _is_under(target, staging_resolved):
        msg = f"Refusing to extract archive entry outside staging directory: {entry_name}"
        raise ValueError(msg)
    return target


def _zip_entry_is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def _extract_verified_bundle(staging_dir: Path, bundle_path: Path) -> list[str]:
    extracted: list[str] = []
    with zipfile.ZipFile(bundle_path, "r") as archive:
        for info in archive.infolist():
            name = info.filename
            if name.endswith("/"):
                continue
            if _zip_entry_is_symlink(info):
                msg = f"Refusing to extract symlink archive entry: {name}"
                raise ValueError(msg)
            unsafe = _entry_is_unsafe(name)
            if unsafe is not None:
                msg = f"Refusing to extract unsafe archive entry {name!r}: {unsafe}"
                raise ValueError(msg)
            target = _resolve_extract_target(staging_dir, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
            extracted.append(name)
    return sorted(extracted)


def unpack_result_to_dict(result: DeploymentBundleUnpackResult) -> dict[str, object]:
    return {
        "bundle_path": result.bundle_path,
        "staging_dir": result.staging_dir,
        "role": result.role,
        "verification_status": result.verification_status,
        "extracted_count": result.extracted_count,
        "extracted_files": result.extracted_files,
        "message": result.message,
    }


def unpack_deployment_bundle(
    bundle_path: Path | str,
    *,
    staging_dir: Path | str,
    force: bool = False,
) -> DeploymentBundleUnpackResult:
    """Verify and unpack a deployment bundle into a safe staging directory."""
    resolved_bundle = Path(bundle_path).expanduser().resolve()
    resolved_staging = validate_staging_dir(staging_dir)

    verification = verify_deployment_bundle(resolved_bundle)
    if verification.overall_status == "invalid":
        msg = (
            "Cannot unpack deployment bundle because verification is invalid. "
            "Fix or replace the bundle before extraction."
        )
        raise ValueError(msg)

    if _staging_has_contents(resolved_staging) and not force:
        msg = (
            f"Refusing to unpack into non-empty staging directory: {resolved_staging} "
            "(use force=true to replace existing contents)"
        )
        raise ValueError(msg)

    if force:
        _clear_staging_dir(resolved_staging)

    resolved_staging.mkdir(parents=True, exist_ok=True)

    try:
        extracted_files = _extract_verified_bundle(resolved_staging, resolved_bundle)
    except OSError as exc:
        msg = f"Cannot extract deployment bundle into {resolved_staging}: {exc}"
        raise ValueError(msg) from exc

    verification_status: VerificationStatus = verification.overall_status
    message = (
        f"Verified deployment bundle unpacked to {resolved_staging}. "
        f"Verification status: {verification_status}. "
        f"{len(extracted_files)} file(s) extracted; no services were installed."
    )

    return DeploymentBundleUnpackResult(
        bundle_path=str(resolved_bundle),
        staging_dir=str(resolved_staging),
        role=verification.role,
        verification_status=verification_status,
        extracted_count=len(extracted_files),
        extracted_files=extracted_files,
        message=message,
    )
