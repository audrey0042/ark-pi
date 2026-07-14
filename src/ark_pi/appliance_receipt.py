from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from ark_pi import __version__
from ark_pi.appliance_ask_smoke import appliance_ask_smoke_to_dict, run_appliance_ask_smoke
from ark_pi.appliance_smoke import appliance_smoke_to_dict, run_appliance_smoke
from ark_pi.config import ArkSettings, get_settings, load_settings_from_env_file
from ark_pi.deploy.preflight import (
    LLM_SERVICE_FILENAME,
    RAG_ENV_FILENAME,
    RAG_SERVICE_FILENAME,
    deployment_preflight_to_dict,
    parse_env_file,
    run_deployment_preflight,
)
from ark_pi.deploy.templates import DeployRole
from ark_pi.llm_client.diagnostics import llm_passive_status
from ark_pi.llm_client.types import LlmClientError
from ark_pi.preflight import preflight_to_dict, run_preflight

RECEIPT_SCHEMA_NAME = "ark-pi-appliance-receipt"
RECEIPT_SCHEMA_VERSION = 1

ReceiptStatus = Literal["pass", "warning", "fail", "not_run"]
OverallReceiptStatus = Literal["pass", "warning", "fail"]

RAG_SERVICE_NAME = "ark-rag.service"
LLM_SERVICE_NAME = "ark-llm.service"

SYSTEMD_UNIT_DIR = Path("/etc/systemd/system")
SERVICE_ENV_DIR = Path("/etc/ark-pi")


@dataclass(frozen=True)
class ApplianceReceiptResult:
    payload: dict[str, Any]
    overall_status: OverallReceiptStatus
    output_path: Path | None


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def redact_url_credentials(url: str) -> str:
    stripped = url.strip()
    if not stripped:
        return stripped
    parts = urlsplit(stripped)
    if not parts.username and not parts.password:
        return stripped
    hostname = parts.hostname or ""
    if parts.port is not None:
        hostname = f"{hostname}:{parts.port}"
    return urlunsplit((parts.scheme, hostname, parts.path, parts.query, parts.fragment))


def _map_preflight_status(status: str) -> ReceiptStatus:
    if status == "pass":
        return "pass"
    if status == "warning":
        return "warning"
    return "fail"


def _map_deploy_overall_status(status: str) -> ReceiptStatus:
    if status == "ready":
        return "pass"
    if status == "warning":
        return "warning"
    return "fail"


def _exec_start_first_token(service_content: str) -> str | None:
    for line in service_content.splitlines():
        stripped = line.strip()
        if stripped.startswith("ExecStart="):
            command = stripped.removeprefix("ExecStart=").strip()
            if command:
                return command.split()[0]
    return None


def _read_text(path: Path) -> tuple[str | None, str | None]:
    try:
        return path.read_text(encoding="utf-8"), None
    except OSError as exc:
        return None, str(exc)


def _path_access(path: Path) -> dict[str, Any]:
    resolved = path.expanduser()
    exists = resolved.exists()
    entry: dict[str, Any] = {
        "path": str(resolved),
        "exists": exists,
    }
    if not exists:
        entry["readable"] = False
        entry["writable"] = False
        entry["executable"] = False
        return entry
    entry["is_directory"] = resolved.is_dir()
    entry["is_file"] = resolved.is_file()
    entry["readable"] = os.access(resolved, os.R_OK)
    entry["writable"] = os.access(resolved, os.W_OK)
    entry["executable"] = os.access(resolved, os.X_OK)
    if resolved.is_file():
        try:
            entry["size_bytes"] = resolved.stat().st_size
        except OSError:
            entry["size_bytes"] = None
    return entry


def _hash_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _configuration_snapshot(settings: ArkSettings, env_values: dict[str, str]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "role": settings.role,
        "index_backend": settings.index_backend,
        "workspace_dir": str(settings.workspace_dir),
        "source_dir": str(settings.source_dir),
        "index_dir": str(settings.index_dir),
        "llm_backend": settings.llm_backend,
        "llm_model": settings.llm_model,
        "llm_timeout_seconds": settings.llm_timeout_seconds,
        "embedding_backend": settings.embedding_backend,
        "embedding_model": settings.embedding_model,
        "embedding_model_path": (
            "" if settings.embedding_model_path is None else str(settings.embedding_model_path)
        ),
        "embedding_dimensions": settings.embedding_dimensions,
        "embedding_batch_size": settings.embedding_batch_size,
        "embedding_normalize": settings.embedding_normalize,
        "embedding_device": settings.embedding_device,
        "embedding_allow_network": settings.embedding_allow_network,
    }
    if settings.role in {"rag", "dev"}:
        snapshot["llm_base_url"] = redact_url_credentials(settings.llm_base_url)
    if settings.role in {"llm", "dev"}:
        snapshot["model_path"] = str(settings.model_path)
        snapshot["model_dir"] = str(settings.model_dir)
        snapshot["context_size"] = settings.context_size
        snapshot["threads"] = settings.threads
        llama_bin = env_values.get("ARK_LLAMA_BIN", "").strip()
        if llama_bin:
            snapshot["llama_bin"] = llama_bin
    return snapshot


def _software_snapshot(install_prefix: Path, venv_ark: Path) -> dict[str, Any]:
    software: dict[str, Any] = {
        "ark_pi_version": __version__,
        "install_prefix": str(install_prefix),
        "venv_ark_path": str(venv_ark),
    }
    git_dir = install_prefix / ".git"
    if git_dir.is_dir():
        for key, args in (
            ("git_commit", ["rev-parse", "HEAD"]),
            ("git_branch", ["rev-parse", "--abbrev-ref", "HEAD"]),
        ):
            try:
                completed = subprocess.run(
                    ["git", "-C", str(install_prefix), *args],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            except (OSError, subprocess.SubprocessError):
                break
            if completed.returncode == 0:
                software[key] = completed.stdout.strip()
    return software


def _service_unit_path(service_name: str) -> Path:
    return SYSTEMD_UNIT_DIR / service_name


def _query_systemctl(service_name: str) -> dict[str, Any]:
    if shutil.which("systemctl") is None:
        return {
            "service": service_name,
            "status": "not_run",
            "message": "systemctl not found",
        }
    result: dict[str, Any] = {"service": service_name}
    unit_path = _service_unit_path(service_name)
    result["unit_present"] = unit_path.is_file()
    for field, args in (
        ("enabled", ["is-enabled", service_name]),
        ("active", ["is-active", service_name]),
    ):
        try:
            completed = subprocess.run(
                ["systemctl", *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            result["status"] = "warning"
            result["message"] = f"systemctl query failed: {exc}"
            return result
        value = completed.stdout.strip()
        result[f"{field}_state"] = value if completed.returncode == 0 else "unknown"
    try:
        completed = subprocess.run(
            ["systemctl", "show", service_name, "--property=SubState", "--value"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if completed.returncode == 0:
            result["substate"] = completed.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    result["status"] = "pass"
    return result


def _check_exec_start_literal(service_path: Path) -> dict[str, Any]:
    content, read_error = _read_text(service_path)
    if read_error or content is None:
        return {
            "id": "llm_exec_start_literal",
            "status": "fail",
            "message": f"Could not read service unit: {read_error}",
            "details": {"path": str(service_path)},
        }
    token = _exec_start_first_token(content)
    if token is None:
        return {
            "id": "llm_exec_start_literal",
            "status": "fail",
            "message": "ExecStart line missing from service unit.",
            "details": {"path": str(service_path)},
        }
    uses_variable = token.startswith("$") or "${" in token
    details = {
        "path": str(service_path),
        "exec_start_first_token": token,
        "uses_literal_executable_path": not uses_variable,
    }
    if uses_variable:
        return {
            "id": "llm_exec_start_literal",
            "status": "fail",
            "message": (
                f"ExecStart uses variable substitution ({token!r}); "
                "expected a literal llama-server executable path."
            ),
            "details": details,
        }
    return {
        "id": "llm_exec_start_literal",
        "status": "pass",
        "message": f"ExecStart uses literal executable path: {token}",
        "details": details,
    }


def _deploy_role(settings: ArkSettings) -> DeployRole:
    if settings.role == "rag":
        return "rag"
    if settings.role == "llm":
        return "llm"
    return "all"


def _generated_dir(settings: ArkSettings) -> Path:
    return (settings.data_dir / "deploy" / "generated").expanduser().resolve()


def _env_values_from_file(env_file: Path | None) -> dict[str, str]:
    if env_file is None:
        return {}
    content, read_error = _read_text(env_file)
    if read_error or content is None:
        return {}
    values, _errors = parse_env_file(content)
    return values


def _filesystem_entries(
    settings: ArkSettings,
    *,
    hash_model: bool,
    env_values: dict[str, str],
) -> list[dict[str, Any]]:
    install_prefix = Path(sys.executable).resolve().parent.parent
    paths: list[Path] = [
        install_prefix,
        settings.workspace_dir,
        settings.source_dir,
        settings.index_dir,
        _generated_dir(settings),
    ]
    if settings.role in {"llm", "dev"}:
        paths.extend([settings.model_dir, settings.model_path])
        llama_bin = env_values.get("ARK_LLAMA_BIN", "").strip()
        if llama_bin:
            paths.append(Path(llama_bin))
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.expanduser().resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        entry = _path_access(path)
        if hash_model and path == settings.model_path and path.is_file():
            entry["sha256"] = _hash_file_sha256(path)
        entries.append(entry)
    return entries


def _connectivity_smoke_entry(result: dict[str, Any] | None) -> dict[str, Any]:
    if result is None:
        return {
            "status": "not_run",
            "message": "Connectivity smoke was not requested.",
        }
    return {
        "status": "pass" if result.get("ok") else "fail",
        "ok": result.get("ok"),
        "backend": result.get("backend"),
        "base_url": result.get("base_url"),
        "latency_ms": result.get("latency_ms"),
        "output_text": result.get("output_text"),
        "message": result.get("message"),
    }


def _ask_smoke_entry(result: dict[str, Any] | None) -> dict[str, Any]:
    if result is None:
        return {
            "status": "not_run",
            "message": "Ask smoke was not requested.",
        }
    preview = str(result.get("retrieved_context_preview", ""))
    if len(preview) > 120:
        preview = preview[:117] + "..."
    return {
        "status": "pass" if result.get("ok") else "fail",
        "ok": result.get("ok"),
        "retrieval_ok": result.get("retrieval_ok"),
        "llm_ok": result.get("llm_ok"),
        "retrieved_result_count": result.get("retrieved_result_count"),
        "retrieved_context_preview": preview,
        "answer": result.get("answer"),
        "latency_ms": result.get("latency_ms"),
        "message": result.get("message"),
        "cleanup_performed": result.get("cleanup_performed"),
        "cleanup_error": result.get("cleanup_error"),
    }


def _derive_next_steps(
    checks: list[dict[str, Any]],
    *,
    run_smoke: bool,
    run_ask_smoke: bool,
    settings: ArkSettings,
) -> list[str]:
    steps: list[str] = []
    for check in checks:
        if check.get("status") in {"fail", "warning"}:
            message = str(check.get("message", ""))
            if message:
                steps.append(message)
    if settings.role in {"rag", "dev"} and not run_smoke:
        steps.append("Run with --run-smoke to test the configured partner LLM.")
    if settings.role in {"rag", "dev"} and not run_ask_smoke:
        steps.append("Run with --run-ask-smoke to test the complete RAG pipeline.")
    if settings.role in {"llm", "dev"}:
        model_entry = next(
            (item for item in checks if item.get("id") == "llm_model_path"),
            None,
        )
        if model_entry and model_entry.get("status") != "pass":
            steps.append(f"Place a GGUF model at {settings.model_path}.")
        binary_entry = next(
            (item for item in checks if item.get("id") == "llm_llama_binary"),
            None,
        )
        if binary_entry and binary_entry.get("status") != "pass":
            steps.append("Install or build llama-server and set ARK_LLAMA_BIN.")
    service_checks = [
        check
        for check in checks
        if check.get("id", "").startswith("service_")
        and check.get("status") != "pass"
    ]
    if service_checks:
        steps.append("Start or enable the role systemd service if needed.")
    deduped: list[str] = []
    for step in steps:
        if step not in deduped:
            deduped.append(step)
    return deduped


def _compute_overall_status(
    checks: list[dict[str, Any]],
    *,
    run_smoke: bool,
    run_ask_smoke: bool,
    allow_smoke_failure: bool,
    active_smoke: dict[str, Any],
) -> OverallReceiptStatus:
    if any(check.get("status") == "fail" for check in checks):
        return "fail"

    smoke_failures: list[bool] = []
    if run_smoke:
        smoke_failures.append(active_smoke["connectivity"].get("status") == "fail")
    if run_ask_smoke:
        smoke_failures.append(active_smoke["ask"].get("status") == "fail")
    if smoke_failures and any(smoke_failures) and not allow_smoke_failure:
        return "fail"

    if any(check.get("status") == "warning" for check in checks):
        return "warning"
    if not run_smoke and not run_ask_smoke:
        return "warning"
    if smoke_failures and any(smoke_failures) and allow_smoke_failure:
        return "warning"
    return "pass"


def collect_appliance_receipt(
    *,
    env_file: Path | None = None,
    hash_model: bool = False,
    run_smoke: bool = False,
    run_ask_smoke: bool = False,
    keep_smoke_artifacts: bool = False,
    timeout_seconds: float | None = None,
    allow_smoke_failure: bool = False,
    generated_dir: Path | None = None,
) -> ApplianceReceiptResult:
    """Collect a versioned appliance validation receipt."""
    settings = load_settings_from_env_file(env_file) if env_file else get_settings()
    env_values = _env_values_from_file(env_file)

    if settings.role == "llm" and run_ask_smoke:
        msg = "Unsupported on LLM-only role: --run-ask-smoke requires a RAG workspace."
        raise ValueError(msg)

    install_prefix = Path(sys.executable).resolve().parent.parent
    venv_ark = install_prefix / ".venv" / "bin" / "ark"
    resolved_generated = generated_dir if generated_dir is not None else _generated_dir(settings)

    checks: list[dict[str, Any]] = []
    warnings: list[str] = []

    preflight = run_preflight(settings)
    preflight_dict = preflight_to_dict(preflight)
    for check in preflight_dict["checks"]:
        checks.append(
            {
                "id": check["id"],
                "status": _map_preflight_status(str(check["status"])),
                "message": check["message"],
                "details": check.get("details", {}),
            }
        )

    passive = llm_passive_status(settings)
    deploy_result = run_deployment_preflight(resolved_generated, role=_deploy_role(settings))
    deploy_dict = deployment_preflight_to_dict(deploy_result)
    checks.append(
        {
            "id": "deployment_preflight",
            "status": _map_deploy_overall_status(str(deploy_dict["overall_status"])),
            "message": f"Deployment preflight status: {deploy_dict['overall_status']}",
            "details": {"generated_dir": str(resolved_generated)},
        }
    )
    for check in deploy_dict["checks"]:
        checks.append(
            {
                "id": f"deploy_{check['id']}",
                "status": _map_preflight_status(str(check["status"])),
                "message": check["message"],
                "details": check.get("details", {}),
            }
        )

    service_name = RAG_SERVICE_NAME if settings.role == "rag" else LLM_SERVICE_NAME
    if settings.role == "dev":
        service_name = RAG_SERVICE_NAME
    service_info = _query_systemctl(service_name)
    service_status: ReceiptStatus = "pass"
    if service_info.get("status") == "not_run":
        service_status = "not_run"
        warnings.append("Service state could not be determined (systemctl unavailable).")
    elif service_info.get("active_state") not in {None, "active", "unknown"}:
        if service_info.get("active_state") != "active":
            service_status = "warning"
            warnings.append(f"{service_name} is not active.")
    checks.append(
        {
            "id": f"service_{service_name}",
            "status": service_status,
            "message": f"Service state collected for {service_name}.",
            "details": service_info,
        }
    )

    if settings.role in {"llm", "dev"}:
        unit_path = _service_unit_path(LLM_SERVICE_NAME)
        if unit_path.is_file():
            checks.append(_check_exec_start_literal(unit_path))
        else:
            generated_unit = resolved_generated / LLM_SERVICE_FILENAME
            if generated_unit.is_file():
                checks.append(_check_exec_start_literal(generated_unit))

    connectivity_result: dict[str, Any] | None = None
    ask_result: dict[str, Any] | None = None

    if run_smoke:
        try:
            smoke = run_appliance_smoke(
                env_file=env_file,
                timeout_seconds=timeout_seconds,
            )
            connectivity_result = appliance_smoke_to_dict(smoke)
        except LlmClientError as exc:
            connectivity_result = {
                "ok": False,
                "message": str(exc),
                "output_text": "",
                "latency_ms": None,
            }
    elif settings.role in {"rag", "dev"}:
        warnings.append("No active connectivity smoke was performed.")

    if run_ask_smoke:
        ask = run_appliance_ask_smoke(
            env_file=env_file,
            timeout_seconds=timeout_seconds,
            keep=keep_smoke_artifacts,
        )
        ask_result = appliance_ask_smoke_to_dict(ask)
    elif settings.role in {"rag", "dev"}:
        warnings.append("No active ask smoke was performed.")

    if not hash_model and settings.role in {"llm", "dev"}:
        warnings.append("Model SHA256 was not requested (--hash-model).")

    active_smoke = {
        "connectivity": _connectivity_smoke_entry(connectivity_result),
        "ask": _ask_smoke_entry(ask_result),
    }

    role_readiness: dict[str, Any] = {
        "network_check_performed": run_smoke,
        "ask_smoke_performed": run_ask_smoke,
    }
    if settings.role in {"rag", "dev"}:
        role_readiness["partner_llm_url_configured"] = passive.base_url_configured
        role_readiness["llm_backend"] = passive.backend
    if settings.role in {"llm", "dev"}:
        llama_bin = env_values.get("ARK_LLAMA_BIN", "").strip()
        role_readiness["llama_server_binary"] = llama_bin or None
        model_path = settings.model_path
        role_readiness["model_file_exists"] = model_path.is_file()
        if model_path.is_file():
            role_readiness["model_size_bytes"] = model_path.stat().st_size
        if hash_model and model_path.is_file():
            role_readiness["model_sha256"] = _hash_file_sha256(model_path)

    overall_status = _compute_overall_status(
        checks,
        run_smoke=run_smoke,
        run_ask_smoke=run_ask_smoke,
        allow_smoke_failure=allow_smoke_failure,
        active_smoke=active_smoke,
    )

    env_file_path = str(env_file) if env_file is not None else None
    deployment_info: dict[str, Any] = {
        "generated_dir": str(resolved_generated),
        "env_file_path": env_file_path,
        "deployment_preflight": deploy_dict,
    }
    if env_file is not None:
        deployment_info["env_file_present"] = env_file.is_file()
    for filename in (RAG_ENV_FILENAME, RAG_SERVICE_FILENAME, LLM_SERVICE_FILENAME):
        generated_path = resolved_generated / filename
        deployment_info[f"generated_{filename.replace('.', '_')}"] = generated_path.is_file()

    payload: dict[str, Any] = {
        "schema_name": RECEIPT_SCHEMA_NAME,
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "generated_at": _utc_now_iso(),
        "overall_status": overall_status,
        "host": {
            "hostname": socket.gethostname(),
            "operating_system": platform.platform(),
            "architecture": platform.machine(),
            "python_version": platform.python_version(),
        },
        "software": _software_snapshot(install_prefix, venv_ark),
        "configuration": _configuration_snapshot(settings, env_values),
        "filesystem": _filesystem_entries(
            settings,
            hash_model=hash_model,
            env_values=env_values,
        ),
        "deployment": deployment_info,
        "services": service_info,
        "role_readiness": role_readiness,
        "checks": checks,
        "active_smoke": active_smoke,
        "warnings": warnings,
        "next_steps": _derive_next_steps(
            checks,
            run_smoke=run_smoke,
            run_ask_smoke=run_ask_smoke,
            settings=settings,
        ),
    }

    return ApplianceReceiptResult(payload=payload, overall_status=overall_status, output_path=None)


def write_receipt_atomic(path: Path, payload: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    serialized = json.dumps(payload, indent=2) + "\n"
    tmp_path.write_text(serialized, encoding="utf-8")
    tmp_path.replace(path)


def receipt_filename_timestamped() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"ark-pi-receipt-{stamp}.json"


def resolve_receipt_output_path(
    *,
    output: Path | None = None,
    receipt_dir: Path | None = None,
) -> Path | None:
    if output is not None:
        return output.expanduser()
    if receipt_dir is not None:
        return receipt_dir.expanduser() / receipt_filename_timestamped()
    return None
