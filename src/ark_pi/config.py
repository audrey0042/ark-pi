from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from ark_pi.deploy.preflight import parse_env_file
from ark_pi.embeddings.diagnostics import embeddings_passive_status
from ark_pi.llm_client.diagnostics import llm_passive_status

Role = Literal["rag", "llm", "dev"]
IndexBackend = Literal["simple", "chroma"]
LlmBackend = Literal["mock", "openai-compatible"]
EmbeddingBackend = Literal["mock", "sentence-transformers"]
EmbeddingDevice = Literal["cpu"]


class ArkSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ARK_",
        extra="ignore",
    )

    role: Role = "dev"

    # RAG / API
    host: str = "0.0.0.0"
    port: int = 8000
    data_dir: Path = Path("./data")
    source_dir: Path = Path("./data/sources")
    workspace_dir: Path = Path("./data/workspace")
    index_dir: Path = Path("./indexes")
    index_backend: IndexBackend = "simple"
    # TODO: derive chroma_dir from index_dir when ARK_INDEX_DIR is overridden
    chroma_dir: Path = Path("./indexes/chroma")
    collection_name: str = "wiki_minilm_l6_v2"
    embedding_backend: EmbeddingBackend = "mock"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_model_path: Path | None = None
    embedding_dimensions: int = Field(default=384, ge=0)
    embedding_batch_size: int = Field(default=16, gt=0)
    embedding_normalize: bool = True
    embedding_device: EmbeddingDevice = "cpu"
    embedding_allow_network: bool = False
    llm_base_url: str = "http://127.0.0.1:8080"
    distance_threshold: float = 0.5

    # LLM client
    llm_backend: LlmBackend = "mock"
    llm_model: str = "local"
    llm_timeout_seconds: float = Field(default=30.0, gt=0)
    llm_max_tokens: int = Field(default=512, gt=0)
    llm_temperature: float = Field(default=0.0, ge=0)
    max_import_bytes: int = Field(default=52_428_800, gt=0)

    # LLM / llama.cpp server (ark-llm Pi)
    llama_host: str = "0.0.0.0"
    llama_port: int = 8080
    model_dir: Path = Path("./models")
    model_path: Path = Path("./models/model.gguf")
    context_size: int = 4096
    threads: int = 4


@lru_cache
def get_settings() -> ArkSettings:
    return ArkSettings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()


def load_settings_from_env_file(path: Path) -> ArkSettings:
    """Load settings from a deployment env file (e.g. /etc/ark-pi/ark-rag.env)."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        hint = ""
        if isinstance(exc, PermissionError):
            hint = " (try running with sudo for root-only env files under /etc/ark-pi/)"
        raise ValueError(f"Cannot read env file {path}: {exc}{hint}") from exc

    _values, errors = parse_env_file(content)
    structural_errors = [
        error for error in errors if error != "env file has no KEY=VALUE entries"
    ]
    if structural_errors:
        joined = "; ".join(structural_errors)
        raise ValueError(f"Invalid env file {path}: {joined}")

    return ArkSettings(_env_file=str(path), _env_file_encoding="utf-8")


def settings_for_display(settings: ArkSettings) -> dict[str, Any]:
    data = settings.model_dump(mode="json")
    for name in ArkSettings.model_fields:
        value = getattr(settings, name)
        if isinstance(value, SecretStr):
            data[name] = "***"
    return data


def api_status_payload() -> dict[str, Any]:
    settings = get_settings()
    llm_passive = llm_passive_status(settings)
    embedding_passive = embeddings_passive_status(settings)
    from ark_pi import preflight as ark_preflight

    preflight = ark_preflight.run_preflight(settings)
    return {
        "service": "ark-pi",
        "role": settings.role,
        "paths": {key: str(value) for key, value in role_paths(settings).items()},
        "config": settings_for_display(settings),
        "llm": {
            "backend": llm_passive.backend,
            "model": llm_passive.model,
            "base_url_configured": llm_passive.base_url_configured,
            "base_url_display": llm_passive.base_url_display,
            "timeout_seconds": llm_passive.timeout_seconds,
            "max_tokens": llm_passive.max_tokens,
            "temperature": llm_passive.temperature,
            "network_check_performed": llm_passive.network_check_performed,
            "message": llm_passive.message,
        },
        "embeddings": {
            "backend": embedding_passive.backend,
            "model": embedding_passive.model,
            "model_path": embedding_passive.model_path,
            "model_path_exists": embedding_passive.model_path_exists,
            "expected_dimensions": embedding_passive.expected_dimensions,
            "batch_size": embedding_passive.batch_size,
            "normalize": embedding_passive.normalize,
            "device": embedding_passive.device,
            "allow_network": embedding_passive.allow_network,
            "dependency_importable": embedding_passive.dependency_importable,
            "model_load_performed": embedding_passive.model_load_performed,
            "network_check_performed": embedding_passive.network_check_performed,
            "message": embedding_passive.message,
        },
        "preflight": {
            "overall_status": preflight.overall_status,
            "network_checks_performed": preflight.network_checks_performed,
        },
    }


def role_paths(settings: ArkSettings) -> dict[str, Path | str]:
    match settings.role:
        case "rag":
            return {
                "data_dir": settings.data_dir,
                "source_dir": settings.source_dir,
                "workspace_dir": settings.workspace_dir,
                "index_dir": settings.index_dir,
                "chroma_dir": settings.chroma_dir,
                "llm_base_url": settings.llm_base_url,
            }
        case "llm":
            return {
                "model_dir": settings.model_dir,
                "model_path": settings.model_path,
            }
        case "dev":
            return {
                "data_dir": settings.data_dir,
                "source_dir": settings.source_dir,
                "workspace_dir": settings.workspace_dir,
                "index_dir": settings.index_dir,
                "chroma_dir": settings.chroma_dir,
                "model_dir": settings.model_dir,
                "model_path": settings.model_path,
                "llm_base_url": settings.llm_base_url,
            }
        case _:
            raise AssertionError(f"Unhandled role: {settings.role!r}")
