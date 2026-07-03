from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

Role = Literal["rag", "llm", "dev"]
IndexBackend = Literal["simple", "chroma"]
LlmBackend = Literal["mock", "openai-compatible"]


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
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    llm_base_url: str = "http://127.0.0.1:8080"
    distance_threshold: float = 0.5

    # LLM client
    llm_backend: LlmBackend = "mock"
    llm_model: str = "local"
    llm_timeout_seconds: float = Field(default=30.0, gt=0)
    llm_max_tokens: int = Field(default=512, gt=0)
    llm_temperature: float = Field(default=0.0, ge=0)

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


def settings_for_display(settings: ArkSettings) -> dict[str, Any]:
    data = settings.model_dump(mode="json")
    for name in ArkSettings.model_fields:
        value = getattr(settings, name)
        if isinstance(value, SecretStr):
            data[name] = "***"
    return data


def api_status_payload() -> dict[str, Any]:
    settings = get_settings()
    return {
        "service": "ark-pi",
        "role": settings.role,
        "paths": {key: str(value) for key, value in role_paths(settings).items()},
        "config": settings_for_display(settings),
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
