from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DeployRole = Literal["rag", "llm", "all"]
TemplateKind = Literal["env", "systemd"]
TemplateRole = Literal["rag", "llm"]

DEFAULT_OUTPUT_DIR = Path("./deploy/generated")

FORBIDDEN_OUTPUT_ROOTS = (
    Path("/etc"),
    Path("/usr"),
    Path("/lib/systemd"),
    Path("/etc/systemd"),
)

ARK_RAG_ENV = """\
ARK_ROLE=rag
ARK_HOST=0.0.0.0
ARK_PORT=8000
ARK_WORKSPACE_DIR=/srv/ark-pi/data/workspace
ARK_SOURCE_DIR=/srv/ark-pi/data/sources
ARK_INDEX_BACKEND=simple
ARK_LLM_BACKEND=openai-compatible
ARK_LLM_BASE_URL=http://ark-llm.local:8080
ARK_LLM_MODEL=local
ARK_MAX_IMPORT_BYTES=52428800
"""

ARK_RAG_SERVICE = """\
[Unit]
Description=Ark Pi RAG API

[Service]
EnvironmentFile=/etc/ark-pi/ark-rag.env
WorkingDirectory=/opt/ark-pi
ExecStart=/opt/ark-pi/.venv/bin/ark serve --host ${ARK_HOST} --port ${ARK_PORT}
Restart=on-failure

[Install]
WantedBy=multi-user.target
"""

ARK_LLM_ENV = """\
ARK_ROLE=llm
ARK_LLM_HOST=0.0.0.0
ARK_LLM_PORT=8080
ARK_LLAMACPP_SERVER_BIN=/opt/llama.cpp/llama-server
ARK_LLAMACPP_MODEL_PATH=/srv/ark-pi/models/model.gguf
ARK_LLAMACPP_CTX_SIZE=4096
ARK_LLAMACPP_THREADS=4
ARK_LLAMACPP_EXTRA_ARGS=
"""

ARK_LLM_SERVICE = """\
[Unit]
Description=Ark Pi LLM Server

[Service]
EnvironmentFile=/etc/ark-pi/ark-llm.env
ExecStart=${ARK_LLAMACPP_SERVER_BIN} --host ${ARK_LLM_HOST} --port ${ARK_LLM_PORT} --model ${ARK_LLAMACPP_MODEL_PATH} --ctx-size ${ARK_LLAMACPP_CTX_SIZE} --threads ${ARK_LLAMACPP_THREADS} ${ARK_LLAMACPP_EXTRA_ARGS}
Restart=on-failure

[Install]
WantedBy=multi-user.target
"""


@dataclass(frozen=True)
class TemplateDefinition:
    filename: str
    content: str
    kind: TemplateKind
    role: TemplateRole


@dataclass(frozen=True)
class GeneratedFile:
    path: str
    kind: TemplateKind
    role: TemplateRole


@dataclass(frozen=True)
class RenderResult:
    output_dir: str
    role: DeployRole
    generated_files: list[GeneratedFile]
    skipped: list[str]
    message: str


RAG_TEMPLATES: tuple[TemplateDefinition, ...] = (
    TemplateDefinition("ark-rag.env", ARK_RAG_ENV, "env", "rag"),
    TemplateDefinition("ark-rag.service", ARK_RAG_SERVICE, "systemd", "rag"),
)

LLM_TEMPLATES: tuple[TemplateDefinition, ...] = (
    TemplateDefinition("ark-llm.env", ARK_LLM_ENV, "env", "llm"),
    TemplateDefinition("ark-llm.service", ARK_LLM_SERVICE, "systemd", "llm"),
)


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate_output_dir(output_dir: Path) -> Path:
    if not str(output_dir).strip():
        msg = "output_dir must not be empty"
        raise ValueError(msg)
    resolved = output_dir.expanduser().resolve()
    for forbidden in FORBIDDEN_OUTPUT_ROOTS:
        forbidden_resolved = forbidden.resolve()
        if resolved == forbidden_resolved or _is_under(resolved, forbidden_resolved):
            msg = f"Refusing to write deployment templates under {forbidden}"
            raise ValueError(msg)
    return resolved


def _templates_for_role(role: DeployRole) -> tuple[TemplateDefinition, ...]:
    if role == "rag":
        return RAG_TEMPLATES
    if role == "llm":
        return LLM_TEMPLATES
    return RAG_TEMPLATES + LLM_TEMPLATES


def render_deployment_templates(
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    *,
    role: DeployRole = "all",
    force: bool = False,
) -> RenderResult:
    """Render deployment env and systemd templates to output_dir (dry-run scaffold only)."""
    resolved_output = validate_output_dir(Path(output_dir))
    templates = _templates_for_role(role)

    existing_conflicts: list[str] = []
    for template in templates:
        target = resolved_output / template.filename
        if target.exists() and not force:
            existing_conflicts.append(str(target))

    if existing_conflicts:
        joined = ", ".join(existing_conflicts)
        msg = f"Refusing to overwrite existing file(s): {joined} (use force=true to overwrite)"
        raise ValueError(msg)

    try:
        resolved_output.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        msg = f"Cannot create output directory {resolved_output}: {exc}"
        raise ValueError(msg) from exc

    generated_files: list[GeneratedFile] = []
    for template in templates:
        target = resolved_output / template.filename
        try:
            target.write_text(template.content, encoding="utf-8")
        except OSError as exc:
            msg = f"Cannot write deployment template {target}: {exc}"
            raise ValueError(msg) from exc
        generated_files.append(
            GeneratedFile(
                path=str(target),
                kind=template.kind,
                role=template.role,
            )
        )

    message = (
        f"Rendered {len(generated_files)} deployment template(s) to {resolved_output} "
        f"for role {role!r}. Review these files manually; they are not installed."
    )

    return RenderResult(
        output_dir=str(resolved_output),
        role=role,
        generated_files=generated_files,
        skipped=[],
        message=message,
    )


def render_to_dict(result: RenderResult) -> dict[str, object]:
    return {
        "output_dir": result.output_dir,
        "role": result.role,
        "generated_files": [
            {
                "path": generated.path,
                "kind": generated.kind,
                "role": generated.role,
            }
            for generated in result.generated_files
        ],
        "skipped": result.skipped,
        "message": result.message,
    }
