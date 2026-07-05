import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from ark_pi.deploy.bundle import (
    BUNDLE_SCHEMA_VERSION,
    MANIFEST_FILENAME,
    PLAN_JSON_REPORT_PATH,
    PREFLIGHT_REPORT_PATH,
    README_FILENAME,
)
from ark_pi.deploy.preflight import (
    LLM_ENV_FILENAME,
    LLM_SERVICE_FILENAME,
    RAG_ENV_FILENAME,
    RAG_SERVICE_FILENAME,
)
from ark_pi.deploy.templates import DeployRole

VerifyCheckStatus = Literal["pass", "warning", "fail"]
VerifyOverallStatus = Literal["valid", "warning", "invalid"]
BundleRole = Literal["rag", "llm", "all", "unknown"]

FORBIDDEN_ENTRY_PREFIXES = (
    "data/",
    "workspace/",
    "source/",
    "models/",
    ".venv/",
    "deploy/generated/",
)

ALLOWED_TOP_LEVEL = frozenset({README_FILENAME, MANIFEST_FILENAME})


@dataclass(frozen=True)
class BundleVerifyCheck:
    id: str
    label: str
    status: VerifyCheckStatus
    message: str
    details: dict[str, object]


@dataclass(frozen=True)
class DeploymentBundleVerifyResult:
    bundle_path: str
    role: BundleRole
    overall_status: VerifyOverallStatus
    entry_count: int
    manifest_entry_count: int
    host_mutations_performed: bool
    network_checks_performed: bool
    checks: list[BundleVerifyCheck]
    message: str


def _check(
    check_id: str,
    label: str,
    status: VerifyCheckStatus,
    message: str,
    *,
    details: dict[str, object] | None = None,
) -> BundleVerifyCheck:
    return BundleVerifyCheck(
        id=check_id,
        label=label,
        status=status,
        message=message,
        details=details or {},
    )


def _overall_status(checks: list[BundleVerifyCheck]) -> VerifyOverallStatus:
    if any(check.status == "fail" for check in checks):
        return "invalid"
    if any(check.status == "warning" for check in checks):
        return "warning"
    return "valid"


def _sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _expected_entry_paths(role: DeployRole) -> frozenset[str]:
    common = {
        README_FILENAME,
        MANIFEST_FILENAME,
        PREFLIGHT_REPORT_PATH,
        PLAN_JSON_REPORT_PATH,
        "reports/deployment-plan.md",
    }
    rag = {
        f"templates/{RAG_ENV_FILENAME}",
        f"templates/{RAG_SERVICE_FILENAME}",
    }
    llm = {
        f"templates/{LLM_ENV_FILENAME}",
        f"templates/{LLM_SERVICE_FILENAME}",
    }
    if role == "rag":
        return frozenset(common | rag)
    if role == "llm":
        return frozenset(common | llm)
    return frozenset(common | rag | llm)


def _parse_role(value: object) -> BundleRole:
    if value in {"rag", "llm", "all"}:
        return value
    return "unknown"


def _entry_is_forbidden(name: str) -> str | None:
    if name.startswith("/") or PurePosixPath(name).is_absolute():
        return "absolute path"
    if ".." in PurePosixPath(name).parts:
        return "path traversal"
    if name == ".env" or name.endswith("/.env"):
        return "env secret file"
    for prefix in FORBIDDEN_ENTRY_PREFIXES:
        if name == prefix.rstrip("/") or name.startswith(prefix):
            return f"forbidden prefix {prefix!r}"
    if name in ALLOWED_TOP_LEVEL:
        return None
    if name.startswith("reports/"):
        return None
    if name.startswith("templates/"):
        return None
    return "entry outside allowed bundle layout"


def _check_zip_open(bundle_path: Path) -> tuple[BundleVerifyCheck, zipfile.ZipFile | None]:
    if not str(bundle_path).strip():
        return (
            _check(
                "zip_open",
                "Zip archive",
                "fail",
                "Bundle path must not be empty.",
            ),
            None,
        )
    resolved = bundle_path.expanduser().resolve()
    if not resolved.is_file():
        return (
            _check(
                "zip_open",
                "Zip archive",
                "fail",
                f"Bundle path is not a readable file: {resolved}",
                details={"path": str(resolved)},
            ),
            None,
        )
    try:
        archive = zipfile.ZipFile(resolved, "r")
    except zipfile.BadZipFile:
        return (
            _check(
                "zip_open",
                "Zip archive",
                "fail",
                f"Bundle is not a valid zip archive: {resolved}",
                details={"path": str(resolved)},
            ),
            None,
        )
    except OSError as exc:
        return (
            _check(
                "zip_open",
                "Zip archive",
                "fail",
                f"Cannot read bundle zip: {exc}",
                details={"path": str(resolved)},
            ),
            None,
        )
    return (
        _check(
            "zip_open",
            "Zip archive",
            "pass",
            f"Opened bundle zip: {resolved}",
            details={"path": str(resolved)},
        ),
        archive,
    )


def _check_manifest_present(names: list[str]) -> BundleVerifyCheck:
    manifest_count = sum(1 for name in names if name == MANIFEST_FILENAME)
    if manifest_count == 1:
        return _check(
            "manifest_present",
            "Manifest present",
            "pass",
            f"{MANIFEST_FILENAME} exists exactly once.",
        )
    if manifest_count == 0:
        return _check(
            "manifest_present",
            "Manifest present",
            "fail",
            f"Missing required {MANIFEST_FILENAME}.",
        )
    return _check(
        "manifest_present",
        "Manifest present",
        "fail",
        f"{MANIFEST_FILENAME} must appear exactly once; found {manifest_count}.",
        details={"count": manifest_count},
    )


def _check_manifest_schema(manifest: object) -> tuple[BundleVerifyCheck, dict[str, object] | None]:
    if not isinstance(manifest, dict):
        return (
            _check(
                "manifest_schema",
                "Manifest schema",
                "fail",
                "Manifest is not a JSON object.",
            ),
            None,
        )
    problems: list[str] = []
    if manifest.get("schema_version") != BUNDLE_SCHEMA_VERSION:
        problems.append(f"unsupported schema_version: {manifest.get('schema_version')!r}")
    if manifest.get("created_by") != "ark-pi":
        problems.append(f"unexpected created_by: {manifest.get('created_by')!r}")
    if manifest.get("bundle_type") != "deployment":
        problems.append(f"unexpected bundle_type: {manifest.get('bundle_type')!r}")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        problems.append("entries must be a list")
    if problems:
        return (
            _check(
                "manifest_schema",
                "Manifest schema",
                "fail",
                "; ".join(problems),
                details={"problems": problems},
            ),
            None,
        )
    return (
        _check(
            "manifest_schema",
            "Manifest schema",
            "pass",
            "Manifest schema is supported.",
        ),
        manifest,
    )


def _check_safety_flags(manifest: dict[str, object]) -> BundleVerifyCheck:
    problems: list[str] = []
    if manifest.get("dry_run") is not True:
        problems.append(f"dry_run must be true; got {manifest.get('dry_run')!r}")
    if manifest.get("host_mutations_performed") is not False:
        problems.append(
            "host_mutations_performed must be false; "
            f"got {manifest.get('host_mutations_performed')!r}"
        )
    if manifest.get("network_checks_performed") is not False:
        problems.append(
            "network_checks_performed must be false; "
            f"got {manifest.get('network_checks_performed')!r}"
        )
    if problems:
        return _check(
            "safety_flags",
            "Dry-run safety flags",
            "fail",
            "; ".join(problems),
            details={"problems": problems},
        )
    return _check(
        "safety_flags",
        "Dry-run safety flags",
        "pass",
        "Manifest dry-run safety flags are valid.",
    )


def _check_expected_entries(names: list[str], role: BundleRole) -> BundleVerifyCheck:
    if role == "unknown":
        return _check(
            "expected_entries",
            "Expected entries",
            "fail",
            "Cannot validate expected entries because manifest role is unknown.",
        )
    expected = _expected_entry_paths(role)
    actual = set(names)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        problems: list[str] = []
        if missing:
            problems.append(f"missing: {', '.join(missing)}")
        if extra:
            problems.append(f"unexpected: {', '.join(extra)}")
        return _check(
            "expected_entries",
            "Expected entries",
            "fail",
            "; ".join(problems),
            details={"missing": missing, "extra": extra, "role": role},
        )
    return _check(
        "expected_entries",
        "Expected entries",
        "pass",
        f"Bundle contains all required entries for role {role!r}.",
        details={"role": role, "entry_count": len(expected)},
    )


def _check_forbidden_entries(names: list[str]) -> BundleVerifyCheck:
    problems: list[str] = []
    for name in names:
        reason = _entry_is_forbidden(name)
        if reason is not None:
            problems.append(f"{name}: {reason}")
    if problems:
        return _check(
            "forbidden_entries",
            "Forbidden entries",
            "fail",
            "; ".join(problems),
            details={"problems": problems},
        )
    return _check(
        "forbidden_entries",
        "Forbidden entries",
        "pass",
        "No forbidden or unsafe archive entries detected.",
    )


def _check_checksums(
    archive: zipfile.ZipFile,
    manifest: dict[str, object],
    names: list[str],
) -> BundleVerifyCheck:
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        return _check(
            "checksums",
            "Checksums",
            "fail",
            "Manifest entries list is missing or invalid.",
        )

    manifest_paths: list[str] = []
    problems: list[str] = []
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            problems.append("manifest entry is not an object")
            continue
        path = raw_entry.get("path")
        expected_hash = raw_entry.get("sha256")
        expected_size = raw_entry.get("size_bytes")
        if not isinstance(path, str) or not path:
            problems.append("manifest entry missing path")
            continue
        manifest_paths.append(path)
        if path not in names:
            problems.append(f"missing zip entry: {path}")
            continue
        content = archive.read(path)
        if isinstance(expected_size, int) and len(content) != expected_size:
            problems.append(f"size mismatch for {path}")
        if isinstance(expected_hash, str):
            actual_hash = _sha256_hex(content)
            if actual_hash != expected_hash:
                problems.append(f"checksum mismatch for {path}")
        else:
            problems.append(f"missing sha256 for {path}")

    zip_only = sorted(set(names) - set(manifest_paths))
    allowed_extras = {MANIFEST_FILENAME}
    unexpected_extras = [path for path in zip_only if path not in allowed_extras]
    if unexpected_extras:
        problems.append(
            f"zip entries not listed in manifest: {', '.join(unexpected_extras)}"
        )

    if problems:
        return _check(
            "checksums",
            "Checksums",
            "fail",
            "; ".join(problems),
            details={"problems": problems},
        )
    return _check(
        "checksums",
        "Checksums",
        "pass",
        "All manifest entries match zip contents and SHA-256 checksums.",
        details={"entry_count": len(manifest_paths)},
    )


def _check_report_json(archive: zipfile.ZipFile, names: list[str]) -> BundleVerifyCheck:
    problems: list[str] = []
    for report_path in (PREFLIGHT_REPORT_PATH, PLAN_JSON_REPORT_PATH):
        if report_path not in names:
            problems.append(f"missing report: {report_path}")
            continue
        try:
            json.loads(archive.read(report_path).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            problems.append(f"invalid JSON in {report_path}: {exc}")
    if problems:
        return _check(
            "report_json",
            "Report JSON",
            "fail",
            "; ".join(problems),
            details={"problems": problems},
        )
    return _check(
        "report_json",
        "Report JSON",
        "pass",
        "Deployment report JSON files parse successfully.",
    )


def _check_plan_safety(plan: object) -> BundleVerifyCheck:
    if not isinstance(plan, dict):
        return _check(
            "plan_safety",
            "Plan safety",
            "fail",
            "Deployment plan JSON is not an object.",
        )
    problems: list[str] = []
    if plan.get("dry_run") is not True:
        problems.append(f"plan dry_run must be true; got {plan.get('dry_run')!r}")
    if plan.get("host_mutations_performed") is not False:
        problems.append("plan host_mutations_performed must be false")
    if plan.get("network_checks_performed") is not False:
        problems.append("plan network_checks_performed must be false")

    copy_steps = plan.get("copy_steps")
    if isinstance(copy_steps, list):
        for step in copy_steps:
            if isinstance(step, dict) and step.get("performed") is not False:
                problems.append(
                    f"copy step {step.get('id', '<unknown>')!r} has performed != false"
                )
    else:
        problems.append("plan copy_steps must be a list")

    manual_commands = plan.get("manual_commands")
    if isinstance(manual_commands, list):
        for command in manual_commands:
            if isinstance(command, dict) and command.get("performed") is not False:
                problems.append(
                    f"manual command {command.get('id', '<unknown>')!r} has performed != false"
                )
    else:
        problems.append("plan manual_commands must be a list")

    if problems:
        return _check(
            "plan_safety",
            "Plan safety",
            "fail",
            "; ".join(problems),
            details={"problems": problems},
        )
    return _check(
        "plan_safety",
        "Plan safety",
        "pass",
        "Deployment plan reports dry-run only with no performed steps.",
    )


def _check_template_sanity(
    archive: zipfile.ZipFile,
    names: list[str],
    role: BundleRole,
) -> BundleVerifyCheck:
    if role == "unknown":
        return _check(
            "template_sanity",
            "Template sanity",
            "fail",
            "Cannot validate templates because manifest role is unknown.",
        )

    problems: list[str] = []
    rag_templates = {
        f"templates/{RAG_ENV_FILENAME}",
        f"templates/{RAG_SERVICE_FILENAME}",
    }
    llm_templates = {
        f"templates/{LLM_ENV_FILENAME}",
        f"templates/{LLM_SERVICE_FILENAME}",
    }

    if role == "rag":
        forbidden = sorted(llm_templates & set(names))
        if forbidden:
            problems.append(f"rag bundle must not include llm templates: {', '.join(forbidden)}")
    elif role == "llm":
        forbidden = sorted(rag_templates & set(names))
        if forbidden:
            problems.append(f"llm bundle must not include rag templates: {', '.join(forbidden)}")

    checks: list[tuple[str, str, str]] = []
    if role in {"rag", "all"}:
        checks.extend(
            [
                (f"templates/{RAG_ENV_FILENAME}", "ARK_ROLE=rag", "rag env marker"),
                (f"templates/{RAG_SERVICE_FILENAME}", "ark serve", "rag service marker"),
            ]
        )
    if role in {"llm", "all"}:
        checks.extend(
            [
                (f"templates/{LLM_ENV_FILENAME}", "ARK_ROLE=llm", "llm env marker"),
                (
                    f"templates/{LLM_SERVICE_FILENAME}",
                    "${ARK_LLAMA_BIN}",
                    "llm service marker",
                ),
            ]
        )

    for path, marker, label in checks:
        if path not in names:
            problems.append(f"missing template: {path}")
            continue
        try:
            content = archive.read(path).decode("utf-8")
        except UnicodeDecodeError:
            problems.append(f"{path} is not valid UTF-8")
            continue
        if marker not in content:
            problems.append(f"{path} missing {label}")

    if problems:
        return _check(
            "template_sanity",
            "Template sanity",
            "fail",
            "; ".join(problems),
            details={"problems": problems},
        )
    return _check(
        "template_sanity",
        "Template sanity",
        "pass",
        f"Included templates match expected role markers for role {role!r}.",
        details={"role": role},
    )


def verify_deployment_bundle(bundle_path: Path | str) -> DeploymentBundleVerifyResult:
    """Verify a deployment bundle zip read-only without extracting files."""
    checks: list[BundleVerifyCheck] = []
    resolved_path = Path(bundle_path).expanduser().resolve() if str(bundle_path).strip() else Path()
    bundle_path_str = str(resolved_path) if str(bundle_path).strip() else ""
    role: BundleRole = "unknown"
    entry_count = 0
    manifest_entry_count = 0

    zip_check, archive = _check_zip_open(Path(bundle_path))
    checks.append(zip_check)
    if archive is None:
        overall = _overall_status(checks)
        return DeploymentBundleVerifyResult(
            bundle_path=bundle_path_str,
            role=role,
            overall_status=overall,
            entry_count=entry_count,
            manifest_entry_count=manifest_entry_count,
            host_mutations_performed=False,
            network_checks_performed=False,
            checks=checks,
            message=f"Deployment bundle verification {overall}: bundle could not be opened.",
        )

    try:
        names = archive.namelist()
        entry_count = len(names)

        manifest_present = _check_manifest_present(names)
        checks.append(manifest_present)

        manifest: dict[str, object] | None = None
        if manifest_present.status == "pass":
            try:
                raw_manifest = json.loads(archive.read(MANIFEST_FILENAME).decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError, KeyError) as exc:
                checks.append(
                    _check(
                        "manifest_schema",
                        "Manifest schema",
                        "fail",
                        f"Manifest is not valid JSON: {exc}",
                    )
                )
            else:
                schema_check, manifest = _check_manifest_schema(raw_manifest)
                checks.append(schema_check)
                if manifest is not None:
                    role = _parse_role(manifest.get("role"))
                    entries = manifest.get("entries")
                    if isinstance(entries, list):
                        manifest_entry_count = len(entries)

        checks.append(_check_forbidden_entries(names))

        if manifest is not None:
            checks.append(_check_safety_flags(manifest))
            checks.append(_check_expected_entries(names, role))
            checks.append(_check_checksums(archive, manifest, names))

        if PREFLIGHT_REPORT_PATH in names and PLAN_JSON_REPORT_PATH in names:
            checks.append(_check_report_json(archive, names))
            if PLAN_JSON_REPORT_PATH in names:
                try:
                    plan = json.loads(archive.read(PLAN_JSON_REPORT_PATH).decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass
                else:
                    checks.append(_check_plan_safety(plan))

        if manifest is not None and manifest_present.status == "pass":
            checks.append(_check_template_sanity(archive, names, role))
    finally:
        archive.close()

    overall = _overall_status(checks)
    if overall == "valid":
        message = (
            f"Deployment bundle verification valid for role {role!r} at {bundle_path_str}. "
            f"{entry_count} zip entr{'y' if entry_count == 1 else 'ies'} checked; "
            "no host mutations were performed."
        )
    elif overall == "warning":
        message = (
            f"Deployment bundle verification warning for role {role!r} at {bundle_path_str}. "
            "Review verification checks before using this bundle."
        )
    else:
        message = (
            f"Deployment bundle verification invalid for role {role!r} at {bundle_path_str}. "
            "Fix bundle problems before copying or using this archive."
        )

    return DeploymentBundleVerifyResult(
        bundle_path=bundle_path_str,
        role=role,
        overall_status=overall,
        entry_count=entry_count,
        manifest_entry_count=manifest_entry_count,
        host_mutations_performed=False,
        network_checks_performed=False,
        checks=checks,
        message=message,
    )


def bundle_verify_result_to_dict(result: DeploymentBundleVerifyResult) -> dict[str, object]:
    return {
        "bundle_path": result.bundle_path,
        "role": result.role,
        "overall_status": result.overall_status,
        "entry_count": result.entry_count,
        "manifest_entry_count": result.manifest_entry_count,
        "host_mutations_performed": result.host_mutations_performed,
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
        "message": result.message,
    }
