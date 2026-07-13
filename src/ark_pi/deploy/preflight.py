import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from ark_pi.deploy.templates import DEFAULT_OUTPUT_DIR, DeployRole

CheckStatus = Literal["pass", "warning", "fail"]
OverallStatus = Literal["ready", "warning", "blocked"]

RAG_ENV_FILENAME = "ark-rag.env"
RAG_SERVICE_FILENAME = "ark-rag.service"
LLM_ENV_FILENAME = "ark-llm.env"
LLM_SERVICE_FILENAME = "ark-llm.service"

LOCALHOST_LLM_URL_MARKERS = ("localhost", "127.0.0.1")


@dataclass(frozen=True)
class DeploymentPreflightCheck:
    id: str
    label: str
    status: CheckStatus
    message: str
    details: dict[str, object]


@dataclass(frozen=True)
class DeploymentPreflightResult:
    role: DeployRole
    generated_dir: str
    overall_status: OverallStatus
    generated_at: str
    host_mutations_performed: bool
    network_checks_performed: bool
    checks: list[DeploymentPreflightCheck]


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _overall_status(checks: list[DeploymentPreflightCheck]) -> OverallStatus:
    if any(check.status == "fail" for check in checks):
        return "blocked"
    if any(check.status == "warning" for check in checks):
        return "warning"
    return "ready"


def _resolve_generated_dir(generated_dir: Path | str) -> Path:
    if not str(generated_dir).strip():
        msg = "generated_dir must not be empty"
        raise ValueError(msg)
    return Path(generated_dir).expanduser().resolve()


def _expected_filenames(role: DeployRole) -> tuple[str, ...]:
    if role == "rag":
        return (RAG_ENV_FILENAME, RAG_SERVICE_FILENAME)
    if role == "llm":
        return (LLM_ENV_FILENAME, LLM_SERVICE_FILENAME)
    return (
        RAG_ENV_FILENAME,
        RAG_SERVICE_FILENAME,
        LLM_ENV_FILENAME,
        LLM_SERVICE_FILENAME,
    )


def _includes_rag(role: DeployRole) -> bool:
    return role in {"rag", "all"}


def _includes_llm(role: DeployRole) -> bool:
    return role in {"llm", "all"}


def parse_env_file(content: str) -> tuple[dict[str, str], list[str]]:
    values: dict[str, str] = {}
    errors: list[str] = []
    substantive_lines = 0
    for line_number, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        substantive_lines += 1
        if "=" not in stripped:
            errors.append(f"line {line_number}: malformed env entry")
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if not key:
            errors.append(f"line {line_number}: empty env key")
            continue
        values[key] = value
    if substantive_lines == 0:
        errors.append("env file has no KEY=VALUE entries")
    return values, errors


def _read_text(path: Path) -> tuple[str | None, str | None]:
    try:
        return path.read_text(encoding="utf-8"), None
    except OSError as exc:
        return None, str(exc)


def _check_generated_dir(generated_dir: Path) -> DeploymentPreflightCheck:
    if not generated_dir.exists():
        return DeploymentPreflightCheck(
            id="generated_dir",
            label="Generated template directory",
            status="fail",
            message=f"Generated template directory does not exist: {generated_dir}",
            details={"path": str(generated_dir)},
        )
    if not generated_dir.is_dir():
        return DeploymentPreflightCheck(
            id="generated_dir",
            label="Generated template directory",
            status="fail",
            message=f"Generated template path is not a directory: {generated_dir}",
            details={"path": str(generated_dir)},
        )
    return DeploymentPreflightCheck(
        id="generated_dir",
        label="Generated template directory",
        status="pass",
        message=f"Generated template directory exists: {generated_dir}",
        details={"path": str(generated_dir)},
    )


def _check_forbidden_target_safety() -> DeploymentPreflightCheck:
    return DeploymentPreflightCheck(
        id="forbidden_target_safety",
        label="Forbidden target safety",
        status="pass",
        message=(
            "Deployment preflight performs no writes under /etc, /usr, /opt, "
            "/lib/systemd, or /etc/systemd."
        ),
        details={"host_mutations_performed": False},
    )


def _check_template_files(
    generated_dir: Path,
    role: DeployRole,
) -> DeploymentPreflightCheck:
    expected = _expected_filenames(role)
    missing = [name for name in expected if not (generated_dir / name).is_file()]
    if missing:
        return DeploymentPreflightCheck(
            id="template_files",
            label="Template files",
            status="fail",
            message=f"Missing expected deployment template file(s): {', '.join(missing)}",
            details={"expected": list(expected), "missing": missing},
        )
    return DeploymentPreflightCheck(
        id="template_files",
        label="Template files",
        status="pass",
        message=f"All expected deployment template files are present for role {role!r}.",
        details={"expected": list(expected)},
    )


def _check_template_content(
    generated_dir: Path,
    role: DeployRole,
) -> DeploymentPreflightCheck:
    problems: list[str] = []

    if _includes_rag(role):
        rag_env_path = generated_dir / RAG_ENV_FILENAME
        rag_service_path = generated_dir / RAG_SERVICE_FILENAME
        rag_env, rag_env_error = _read_text(rag_env_path)
        rag_service, rag_service_error = _read_text(rag_service_path)
        if rag_env_error:
            problems.append(f"{RAG_ENV_FILENAME}: {rag_env_error}")
        elif rag_env is not None and "ARK_ROLE=rag" not in rag_env:
            problems.append(f"{RAG_ENV_FILENAME} missing ARK_ROLE=rag")
        if rag_service_error:
            problems.append(f"{RAG_SERVICE_FILENAME}: {rag_service_error}")
        elif rag_service is not None and "ark serve" not in rag_service:
            problems.append(f"{RAG_SERVICE_FILENAME} does not reference ark serve")

    if _includes_llm(role):
        llm_env_path = generated_dir / LLM_ENV_FILENAME
        llm_service_path = generated_dir / LLM_SERVICE_FILENAME
        llm_env, llm_env_error = _read_text(llm_env_path)
        llm_service, llm_service_error = _read_text(llm_service_path)
        if llm_env_error:
            problems.append(f"{LLM_ENV_FILENAME}: {llm_env_error}")
        elif llm_env is not None and "ARK_ROLE=llm" not in llm_env:
            problems.append(f"{LLM_ENV_FILENAME} missing ARK_ROLE=llm")
        if llm_service_error:
            problems.append(f"{LLM_SERVICE_FILENAME}: {llm_service_error}")
        elif llm_service is not None and "${ARK_LLAMA_BIN}" not in llm_service:
            problems.append(
                f"{LLM_SERVICE_FILENAME} does not reference llama-server variables"
            )

    if problems:
        return DeploymentPreflightCheck(
            id="template_content",
            label="Template content",
            status="fail",
            message="; ".join(problems),
            details={"problems": problems},
        )
    return DeploymentPreflightCheck(
        id="template_content",
        label="Template content",
        status="pass",
        message="Rendered templates contain expected role markers.",
        details={"role": role},
    )


def _check_env_parse(generated_dir: Path, role: DeployRole) -> DeploymentPreflightCheck:
    env_files: list[str] = []
    if _includes_rag(role):
        env_files.append(RAG_ENV_FILENAME)
    if _includes_llm(role):
        env_files.append(LLM_ENV_FILENAME)

    parse_errors: list[str] = []
    warning_only = False
    for filename in env_files:
        path = generated_dir / filename
        if not path.is_file():
            continue
        content, read_error = _read_text(path)
        if read_error:
            parse_errors.append(f"{filename}: {read_error}")
            continue
        if content is None:
            continue
        _values, errors = parse_env_file(content)
        for error in errors:
            if error == "env file has no KEY=VALUE entries":
                warning_only = True
                parse_errors.append(f"{filename}: {error}")
            else:
                parse_errors.append(f"{filename}: {error}")

    if parse_errors and not warning_only:
        return DeploymentPreflightCheck(
            id="env_parse",
            label="Env file parse",
            status="fail",
            message="; ".join(parse_errors),
            details={"errors": parse_errors},
        )
    if parse_errors and warning_only:
        return DeploymentPreflightCheck(
            id="env_parse",
            label="Env file parse",
            status="warning",
            message="; ".join(parse_errors),
            details={"errors": parse_errors},
        )
    return DeploymentPreflightCheck(
        id="env_parse",
        label="Env file parse",
        status="pass",
        message="Env files parse as simple KEY=VALUE lines.",
        details={"files": env_files},
    )


def _exec_start_binary(service_content: str) -> str | None:
    for line in service_content.splitlines():
        stripped = line.strip()
        if stripped.startswith("ExecStart="):
            command = stripped.removeprefix("ExecStart=").strip()
            if command:
                return command.split()[0]
    return None


def _path_is_executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _check_rag_ark_binary(generated_dir: Path) -> DeploymentPreflightCheck:
    service_path = generated_dir / RAG_SERVICE_FILENAME
    if not service_path.is_file():
        return DeploymentPreflightCheck(
            id="rag_ark_binary",
            label="RAG ark binary",
            status="fail",
            message=f"{RAG_SERVICE_FILENAME} is missing.",
            details={"path": str(service_path)},
        )
    content, read_error = _read_text(service_path)
    if read_error or content is None:
        return DeploymentPreflightCheck(
            id="rag_ark_binary",
            label="RAG ark binary",
            status="fail",
            message=f"Could not read {RAG_SERVICE_FILENAME}: {read_error}",
            details={"path": str(service_path)},
        )
    binary_token = _exec_start_binary(content)
    if binary_token is None:
        return DeploymentPreflightCheck(
            id="rag_ark_binary",
            label="RAG ark binary",
            status="fail",
            message=f"Could not find ExecStart in {RAG_SERVICE_FILENAME}.",
            details={"path": str(service_path)},
        )
    binary_path = Path(binary_token)
    if _path_is_executable(binary_path):
        return DeploymentPreflightCheck(
            id="rag_ark_binary",
            label="RAG ark binary",
            status="pass",
            message=f"RAG service binary exists and is executable: {binary_path}",
            details={"path": str(binary_path)},
        )
    return DeploymentPreflightCheck(
        id="rag_ark_binary",
        label="RAG ark binary",
        status="warning",
        message=(
            f"RAG service binary is not present or not executable: {binary_path} "
            "(expected on a dev laptop before Pi install)."
        ),
        details={"path": str(binary_path)},
    )


def _check_rag_data_paths(generated_dir: Path) -> DeploymentPreflightCheck:
    env_path = generated_dir / RAG_ENV_FILENAME
    content, read_error = _read_text(env_path)
    if read_error or content is None:
        return DeploymentPreflightCheck(
            id="rag_data_paths",
            label="RAG data paths",
            status="fail",
            message=f"Could not read {RAG_ENV_FILENAME}: {read_error}",
            details={"path": str(env_path)},
        )
    values, errors = parse_env_file(content)
    if errors and errors != ["env file has no KEY=VALUE entries"]:
        return DeploymentPreflightCheck(
            id="rag_data_paths",
            label="RAG data paths",
            status="fail",
            message=f"Could not parse {RAG_ENV_FILENAME}.",
            details={"errors": errors},
        )
    missing_paths: list[str] = []
    for key in ("ARK_WORKSPACE_DIR", "ARK_SOURCE_DIR"):
        raw = values.get(key, "").strip()
        if not raw:
            missing_paths.append(f"{key} is missing")
            continue
        path = Path(raw)
        if not path.exists():
            missing_paths.append(str(path))
    if missing_paths:
        return DeploymentPreflightCheck(
            id="rag_data_paths",
            label="RAG data paths",
            status="warning",
            message=(
                "Configured RAG workspace/source paths do not exist yet: "
                + ", ".join(missing_paths)
            ),
            details={"missing": missing_paths},
        )
    return DeploymentPreflightCheck(
        id="rag_data_paths",
        label="RAG data paths",
        status="pass",
        message="Configured RAG workspace and source directories exist.",
        details={
            "workspace_dir": values.get("ARK_WORKSPACE_DIR", ""),
            "source_dir": values.get("ARK_SOURCE_DIR", ""),
        },
    )


def _check_rag_llm_base_url(generated_dir: Path) -> DeploymentPreflightCheck:
    env_path = generated_dir / RAG_ENV_FILENAME
    content, read_error = _read_text(env_path)
    if read_error or content is None:
        return DeploymentPreflightCheck(
            id="rag_llm_base_url",
            label="RAG LLM base URL",
            status="fail",
            message=f"Could not read {RAG_ENV_FILENAME}: {read_error}",
            details={"path": str(env_path)},
        )
    values, _errors = parse_env_file(content)
    base_url = values.get("ARK_LLM_BASE_URL", "").strip()
    if not base_url:
        return DeploymentPreflightCheck(
            id="rag_llm_base_url",
            label="RAG LLM base URL",
            status="fail",
            message="ARK_LLM_BASE_URL is missing or empty in ark-rag.env.",
            details={},
        )
    lowered = base_url.lower()
    if not (lowered.startswith("http://") or lowered.startswith("https://")):
        return DeploymentPreflightCheck(
            id="rag_llm_base_url",
            label="RAG LLM base URL",
            status="fail",
            message=(
                f"ARK_LLM_BASE_URL must start with http:// or https:// (got: {base_url})"
            ),
            details={"base_url": base_url},
        )
    if any(marker in lowered for marker in LOCALHOST_LLM_URL_MARKERS):
        return DeploymentPreflightCheck(
            id="rag_llm_base_url",
            label="RAG LLM base URL",
            status="warning",
            message=(
                f"ARK_LLM_BASE_URL points at localhost ({base_url}); "
                "two-Pi deployment usually needs the ark-llm host."
            ),
            details={"base_url": base_url},
        )
    return DeploymentPreflightCheck(
        id="rag_llm_base_url",
        label="RAG LLM base URL",
        status="pass",
        message=f"ARK_LLM_BASE_URL is configured: {base_url}",
        details={"base_url": base_url},
    )


def _llm_env_value(values: dict[str, str], *keys: str) -> str:
    for key in keys:
        raw = values.get(key, "").strip()
        if raw:
            return raw
    return ""


def _check_llm_llama_binary(generated_dir: Path) -> DeploymentPreflightCheck:
    env_path = generated_dir / LLM_ENV_FILENAME
    content, read_error = _read_text(env_path)
    if read_error or content is None:
        return DeploymentPreflightCheck(
            id="llm_llama_binary",
            label="LLM llama-server binary",
            status="fail",
            message=f"Could not read {LLM_ENV_FILENAME}: {read_error}",
            details={"path": str(env_path)},
        )
    values, _errors = parse_env_file(content)
    binary_raw = _llm_env_value(values, "ARK_LLAMA_BIN", "ARK_LLAMACPP_SERVER_BIN")
    if not binary_raw:
        return DeploymentPreflightCheck(
            id="llm_llama_binary",
            label="LLM llama-server binary",
            status="fail",
            message="ARK_LLAMA_BIN is missing or empty in ark-llm.env.",
            details={},
        )
    binary_path = Path(binary_raw)
    if _path_is_executable(binary_path):
        return DeploymentPreflightCheck(
            id="llm_llama_binary",
            label="LLM llama-server binary",
            status="pass",
            message=f"llama-server binary exists and is executable: {binary_path}",
            details={"path": str(binary_path)},
        )
    return DeploymentPreflightCheck(
        id="llm_llama_binary",
        label="LLM llama-server binary",
        status="warning",
        message=(
            f"llama-server binary is not present or not executable: {binary_path} "
            "(expected before llama.cpp is installed)."
        ),
        details={"path": str(binary_path)},
    )


def _check_llm_model_path(generated_dir: Path) -> DeploymentPreflightCheck:
    env_path = generated_dir / LLM_ENV_FILENAME
    content, read_error = _read_text(env_path)
    if read_error or content is None:
        return DeploymentPreflightCheck(
            id="llm_model_path",
            label="LLM model path",
            status="fail",
            message=f"Could not read {LLM_ENV_FILENAME}: {read_error}",
            details={"path": str(env_path)},
        )
    values, _errors = parse_env_file(content)
    model_raw = _llm_env_value(values, "ARK_MODEL_PATH", "ARK_LLAMACPP_MODEL_PATH")
    if not model_raw:
        return DeploymentPreflightCheck(
            id="llm_model_path",
            label="LLM model path",
            status="fail",
            message="ARK_MODEL_PATH is missing or empty in ark-llm.env.",
            details={},
        )
    model_path = Path(model_raw)
    if model_path.is_file():
        return DeploymentPreflightCheck(
            id="llm_model_path",
            label="LLM model path",
            status="pass",
            message=f"Model file exists: {model_path}",
            details={"path": str(model_path)},
        )
    return DeploymentPreflightCheck(
        id="llm_model_path",
        label="LLM model path",
        status="warning",
        message=f"Model file does not exist yet: {model_path}",
        details={"path": str(model_path)},
    )


def _check_llm_port(generated_dir: Path) -> DeploymentPreflightCheck:
    env_path = generated_dir / LLM_ENV_FILENAME
    content, read_error = _read_text(env_path)
    if read_error or content is None:
        return DeploymentPreflightCheck(
            id="llm_port",
            label="LLM port",
            status="fail",
            message=f"Could not read {LLM_ENV_FILENAME}: {read_error}",
            details={"path": str(env_path)},
        )
    values, _errors = parse_env_file(content)
    port_raw = _llm_env_value(values, "ARK_LLAMA_PORT", "ARK_LLM_PORT")
    if not port_raw:
        return DeploymentPreflightCheck(
            id="llm_port",
            label="LLM port",
            status="fail",
            message="ARK_LLAMA_PORT is missing or empty in ark-llm.env.",
            details={},
        )
    if not re.fullmatch(r"[0-9]+", port_raw):
        return DeploymentPreflightCheck(
            id="llm_port",
            label="LLM port",
            status="fail",
            message=f"ARK_LLAMA_PORT is not a valid integer: {port_raw!r}",
            details={"port": port_raw},
        )
    port = int(port_raw)
    if port < 1 or port > 65535:
        return DeploymentPreflightCheck(
            id="llm_port",
            label="LLM port",
            status="fail",
            message=f"ARK_LLM_PORT is out of range: {port}",
            details={"port": port},
        )
    return DeploymentPreflightCheck(
        id="llm_port",
        label="LLM port",
        status="pass",
        message=f"ARK_LLM_PORT is valid: {port}",
        details={"port": port},
    )


def run_deployment_preflight(
    generated_dir: Path | str = DEFAULT_OUTPUT_DIR,
    *,
    role: DeployRole = "all",
) -> DeploymentPreflightResult:
    """Run dry-run deployment preflight against rendered templates (no host mutations)."""
    resolved_dir = _resolve_generated_dir(generated_dir)
    checks: list[DeploymentPreflightCheck] = [
        _check_generated_dir(resolved_dir),
        _check_forbidden_target_safety(),
    ]

    dir_ok = checks[0].status == "pass"
    if dir_ok:
        checks.extend(
            [
                _check_template_files(resolved_dir, role),
                _check_template_content(resolved_dir, role),
                _check_env_parse(resolved_dir, role),
            ]
        )
        if _includes_rag(role):
            checks.extend(
                [
                    _check_rag_ark_binary(resolved_dir),
                    _check_rag_data_paths(resolved_dir),
                    _check_rag_llm_base_url(resolved_dir),
                ]
            )
        if _includes_llm(role):
            checks.extend(
                [
                    _check_llm_llama_binary(resolved_dir),
                    _check_llm_model_path(resolved_dir),
                    _check_llm_port(resolved_dir),
                ]
            )

    return DeploymentPreflightResult(
        role=role,
        generated_dir=str(resolved_dir),
        overall_status=_overall_status(checks),
        generated_at=_utc_now_iso(),
        host_mutations_performed=False,
        network_checks_performed=False,
        checks=checks,
    )


def deployment_preflight_to_dict(result: DeploymentPreflightResult) -> dict[str, object]:
    return {
        "role": result.role,
        "generated_dir": result.generated_dir,
        "overall_status": result.overall_status,
        "generated_at": result.generated_at,
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
    }
