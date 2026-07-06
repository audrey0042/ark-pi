import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from ark_pi.deploy.preflight import (
    LLM_ENV_FILENAME,
    LLM_SERVICE_FILENAME,
    RAG_ENV_FILENAME,
    RAG_SERVICE_FILENAME,
    DeploymentPreflightResult,
    deployment_preflight_to_dict,
    run_deployment_preflight,
)
from ark_pi.deploy.templates import (
    DEFAULT_OUTPUT_DIR,
    FORBIDDEN_OUTPUT_ROOTS,
    DeployRole,
    TemplateRole,
)

PlanFormat = Literal["table", "markdown", "json"]

RAG_ENV_DEST = "/etc/ark-pi/ark-rag.env"
RAG_SERVICE_DEST = "/etc/systemd/system/ark-rag.service"
LLM_ENV_DEST = "/etc/ark-pi/ark-llm.env"
LLM_SERVICE_DEST = "/etc/systemd/system/ark-llm.service"

DRY_RUN_NOTES: tuple[str, ...] = (
    "This plan is dry-run only.",
    "Review each step before performing a manual Pi install.",
    "Future install automation may execute these steps; this slice does not.",
)


@dataclass(frozen=True)
class PlanCopyStep:
    id: str
    role: TemplateRole
    source: str
    destination: str
    mode: str | None
    requires_sudo: bool
    performed: bool
    message: str


@dataclass(frozen=True)
class PlanManualCommand:
    id: str
    role: TemplateRole
    command: str
    requires_sudo: bool
    performed: bool
    message: str


@dataclass(frozen=True)
class DeploymentInstallPlan:
    role: DeployRole
    generated_dir: str
    created_at: str
    dry_run: bool
    host_mutations_performed: bool
    network_checks_performed: bool
    preflight: DeploymentPreflightResult
    copy_steps: list[PlanCopyStep]
    manual_commands: list[PlanManualCommand]
    notes: list[str]
    warnings: list[str]
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


def validate_plan_output_path(output_path: Path) -> Path:
    if not str(output_path).strip():
        msg = "output path must not be empty"
        raise ValueError(msg)
    resolved = output_path.expanduser().resolve()
    for forbidden in FORBIDDEN_OUTPUT_ROOTS:
        forbidden_resolved = forbidden.resolve()
        if resolved == forbidden_resolved or _is_under(resolved, forbidden_resolved):
            msg = f"Refusing to write plan output under {forbidden}"
            raise ValueError(msg)
    return resolved


def _rag_copy_steps(generated_dir: Path) -> list[PlanCopyStep]:
    return [
        PlanCopyStep(
            id="copy_rag_env",
            role="rag",
            source=str(generated_dir / RAG_ENV_FILENAME),
            destination=RAG_ENV_DEST,
            mode="0640",
            requires_sudo=True,
            performed=False,
            message="Copy rendered ark-rag env file into /etc/ark-pi.",
        ),
        PlanCopyStep(
            id="copy_rag_service",
            role="rag",
            source=str(generated_dir / RAG_SERVICE_FILENAME),
            destination=RAG_SERVICE_DEST,
            mode="0644",
            requires_sudo=True,
            performed=False,
            message="Copy rendered ark-rag systemd unit into /etc/systemd/system.",
        ),
    ]


def _llm_copy_steps(generated_dir: Path) -> list[PlanCopyStep]:
    return [
        PlanCopyStep(
            id="copy_llm_env",
            role="llm",
            source=str(generated_dir / LLM_ENV_FILENAME),
            destination=LLM_ENV_DEST,
            mode="0640",
            requires_sudo=True,
            performed=False,
            message="Copy rendered ark-llm env file into /etc/ark-pi.",
        ),
        PlanCopyStep(
            id="copy_llm_service",
            role="llm",
            source=str(generated_dir / LLM_SERVICE_FILENAME),
            destination=LLM_SERVICE_DEST,
            mode="0644",
            requires_sudo=True,
            performed=False,
            message="Copy rendered ark-llm systemd unit into /etc/systemd/system.",
        ),
    ]


def _rag_manual_commands() -> list[PlanManualCommand]:
    return [
        PlanManualCommand(
            id="create_rag_dirs",
            role="rag",
            command="sudo mkdir -p /etc/ark-pi /srv/ark-pi/data/workspace /srv/ark-pi/data/sources",
            requires_sudo=True,
            performed=False,
            message="Create configuration and RAG data directories.",
        ),
        PlanManualCommand(
            id="install_rag_project",
            role="rag",
            command="sudo mkdir -p /opt/ark-pi && sudo rsync -a ./ /opt/ark-pi/",
            requires_sudo=True,
            performed=False,
            message="Example project copy step for a future manual install.",
        ),
        PlanManualCommand(
            id="install_rag_python_env",
            role="rag",
            command="cd /opt/ark-pi && python3 -m venv .venv && .venv/bin/pip install -e .",
            requires_sudo=False,
            performed=False,
            message="Create the Python environment for ark serve.",
        ),
        PlanManualCommand(
            id="systemd_reload_rag",
            role="rag",
            command="sudo systemctl daemon-reload",
            requires_sudo=True,
            performed=False,
            message="Reload systemd after unit files are manually copied.",
        ),
        PlanManualCommand(
            id="enable_rag",
            role="rag",
            command="sudo systemctl enable --now ark-rag.service",
            requires_sudo=True,
            performed=False,
            message="Enable and start ark-rag after review.",
        ),
        PlanManualCommand(
            id="check_rag",
            role="rag",
            command="systemctl status ark-rag.service",
            requires_sudo=False,
            performed=False,
            message="Inspect ark-rag service status.",
        ),
    ]


def _llm_manual_commands() -> list[PlanManualCommand]:
    return [
        PlanManualCommand(
            id="create_llm_dirs",
            role="llm",
            command="sudo mkdir -p /etc/ark-pi /srv/ark-pi/models /srv/ark-pi/vendor",
            requires_sudo=True,
            performed=False,
            message="Create configuration, model, and llama.cpp directories.",
        ),
        PlanManualCommand(
            id="install_llama_cpp",
            role="llm",
            command="sh install.sh --role llm --llama-build --install-services --yes",
            requires_sudo=False,
            performed=False,
            message="Optional: build llama.cpp via install.sh --llama-build (does not download models).",
        ),
        PlanManualCommand(
            id="place_model",
            role="llm",
            command="# Place a GGUF model at /srv/ark-pi/models/model.gguf before enabling ark-llm.",
            requires_sudo=False,
            performed=False,
            message="Placeholder only. This slice does not download models.",
        ),
        PlanManualCommand(
            id="systemd_reload_llm",
            role="llm",
            command="sudo systemctl daemon-reload",
            requires_sudo=True,
            performed=False,
            message="Reload systemd after unit files are manually copied.",
        ),
        PlanManualCommand(
            id="enable_llm",
            role="llm",
            command="sudo systemctl enable --now ark-llm.service",
            requires_sudo=True,
            performed=False,
            message="Enable and start ark-llm after review.",
        ),
        PlanManualCommand(
            id="check_llm",
            role="llm",
            command="systemctl status ark-llm.service",
            requires_sudo=False,
            performed=False,
            message="Inspect ark-llm service status.",
        ),
    ]


def build_deployment_install_plan(
    generated_dir: Path | str = DEFAULT_OUTPUT_DIR,
    *,
    role: DeployRole = "all",
) -> DeploymentInstallPlan:
    """Build a dry-run deployment install plan from rendered templates."""
    resolved_dir = Path(generated_dir).expanduser().resolve()
    preflight = run_deployment_preflight(resolved_dir, role=role)

    if preflight.overall_status == "blocked":
        msg = (
            "Cannot build deployment install plan because deployment preflight is blocked. "
            "Render valid templates and fix template issues before planning an install."
        )
        raise ValueError(msg)

    copy_steps: list[PlanCopyStep] = []
    manual_commands: list[PlanManualCommand] = []
    if _includes_rag(role):
        copy_steps.extend(_rag_copy_steps(resolved_dir))
        manual_commands.extend(_rag_manual_commands())
    if _includes_llm(role):
        copy_steps.extend(_llm_copy_steps(resolved_dir))
        manual_commands.extend(_llm_manual_commands())

    warnings = [
        f"{check.label}: {check.message}"
        for check in preflight.checks
        if check.status == "warning"
    ]

    message = (
        f"Dry-run deployment install plan for role {role!r} using templates in "
        f"{resolved_dir}. Preflight status: {preflight.overall_status}. "
        f"{len(copy_steps)} copy step(s) and {len(manual_commands)} manual command(s) planned; "
        "none were performed."
    )

    return DeploymentInstallPlan(
        role=role,
        generated_dir=str(resolved_dir),
        created_at=_utc_now_iso(),
        dry_run=True,
        host_mutations_performed=False,
        network_checks_performed=False,
        preflight=preflight,
        copy_steps=copy_steps,
        manual_commands=manual_commands,
        notes=list(DRY_RUN_NOTES),
        warnings=warnings,
        message=message,
    )


def plan_to_dict(plan: DeploymentInstallPlan) -> dict[str, object]:
    return {
        "role": plan.role,
        "generated_dir": plan.generated_dir,
        "created_at": plan.created_at,
        "dry_run": plan.dry_run,
        "host_mutations_performed": plan.host_mutations_performed,
        "network_checks_performed": plan.network_checks_performed,
        "preflight": deployment_preflight_to_dict(plan.preflight),
        "copy_steps": [
            {
                "id": step.id,
                "role": step.role,
                "source": step.source,
                "destination": step.destination,
                "mode": step.mode,
                "requires_sudo": step.requires_sudo,
                "performed": step.performed,
                "message": step.message,
            }
            for step in plan.copy_steps
        ],
        "manual_commands": [
            {
                "id": command.id,
                "role": command.role,
                "command": command.command,
                "requires_sudo": command.requires_sudo,
                "performed": command.performed,
                "message": command.message,
            }
            for command in plan.manual_commands
        ],
        "notes": plan.notes,
        "warnings": plan.warnings,
        "message": plan.message,
    }


def render_plan_markdown(plan: DeploymentInstallPlan) -> str:
    lines = [
        "# Ark Pi Deployment Install Plan",
        "",
        "## Dry-run safety",
        "",
        "- This plan did not install services.",
        "- This plan did not run sudo.",
        "- This plan did not call systemctl.",
        "- This plan did not write to system directories.",
        "",
        "## Role",
        "",
        plan.role,
        "",
        "## Generated templates",
        "",
        plan.generated_dir,
        "",
        "## Deployment preflight summary",
        "",
        f"Overall status: {plan.preflight.overall_status}",
        "",
    ]
    for check in plan.preflight.checks:
        lines.append(f"- **{check.label}** ({check.status}): {check.message}")
    lines.extend(["", "## Planned file copies", ""])
    for step in plan.copy_steps:
        lines.append(
            f"- `{step.id}` ({step.role}): `{step.source}` -> `{step.destination}` "
            f"(mode={step.mode}, sudo={step.requires_sudo}, performed={step.performed})"
        )
        lines.append(f"  - {step.message}")
    lines.extend(["", "## Manual commands", ""])
    for command in plan.manual_commands:
        lines.append(
            f"- `{command.id}` ({command.role}, sudo={command.requires_sudo}, "
            f"performed={command.performed}): {command.message}"
        )
        lines.append(f"  ```bash")
        lines.append(f"  {command.command}")
        lines.append(f"  ```")
    lines.extend(["", "## Warnings and notes", ""])
    if plan.warnings:
        for warning in plan.warnings:
            lines.append(f"- Warning: {warning}")
    else:
        lines.append("- No deployment preflight warnings.")
    for note in plan.notes:
        lines.append(f"- Note: {note}")
    lines.extend(["", plan.message, ""])
    return "\n".join(lines)


def write_plan_output(
    output_path: Path | str,
    content: str,
    *,
    force: bool = False,
) -> Path:
    resolved = validate_plan_output_path(Path(output_path))
    if resolved.exists() and not force:
        msg = f"Refusing to overwrite existing plan output: {resolved} (use force=true to overwrite)"
        raise ValueError(msg)
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
    except OSError as exc:
        msg = f"Cannot write plan output {resolved}: {exc}"
        raise ValueError(msg) from exc
    return resolved


def format_plan_json(plan: DeploymentInstallPlan) -> str:
    return json.dumps(plan_to_dict(plan), indent=2) + "\n"
