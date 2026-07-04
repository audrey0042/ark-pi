from enum import Enum
from typing import Any, Self

from pydantic import BaseModel, Field, field_validator, model_validator


class IndexBackendOption(str, Enum):
    simple = "simple"
    chroma = "chroma"


class LlmBackendOption(str, Enum):
    mock = "mock"
    openai_compatible = "openai-compatible"


class HealthResponse(BaseModel):
    status: str
    service: str


class LlmPassiveStatusResponse(BaseModel):
    backend: str
    model: str
    base_url_configured: bool
    base_url_display: str | None
    timeout_seconds: float
    max_tokens: int
    temperature: float
    network_check_performed: bool
    message: str


class PreflightSummaryResponse(BaseModel):
    overall_status: str
    network_checks_performed: bool


class PreflightCheckResponse(BaseModel):
    id: str
    label: str
    status: str
    message: str
    details: dict[str, Any]


class PreflightResponse(BaseModel):
    role: str
    overall_status: str
    generated_at: str
    network_checks_performed: bool
    checks: list[PreflightCheckResponse]


class InitRequest(BaseModel):
    create_catalog: bool = True
    create_sample_source: bool = False
    force: bool = False


class InitResponse(BaseModel):
    created_paths: list[str]
    existing_paths: list[str]
    skipped: list[str]
    sample_source_path: str | None
    preflight: PreflightResponse
    message: str


class StatusResponse(BaseModel):
    service: str
    role: str
    paths: dict[str, str]
    config: dict[str, Any]
    llm: LlmPassiveStatusResponse
    preflight: PreflightSummaryResponse


class LlmTestRequest(BaseModel):
    prompt: str | None = None
    backend: LlmBackendOption | None = None
    base_url: str | None = None

    @field_validator("prompt")
    @classmethod
    def strip_prompt(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("base_url")
    @classmethod
    def strip_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class LlmTestResponse(BaseModel):
    backend: str
    model: str
    ok: bool
    output_text: str
    latency_ms: int | None
    error: str | None
    message: str


class IndexStatsResponse(BaseModel):
    backend: str
    schema_version: int
    chunk_count: int
    index_dir: str
    source_chunks: str | None = None


class SearchRequest(BaseModel):
    index_dir: str
    query: str
    limit: int = Field(default=5, gt=0)
    backend: IndexBackendOption | None = None

    @field_validator("query")
    @classmethod
    def strip_and_validate_query(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            msg = "query must not be empty"
            raise ValueError(msg)
        return stripped


class SearchResultItem(BaseModel):
    rank: int
    score: float
    id: str
    title: str
    source: str
    chunk_index: int
    text: str


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultItem]


class AskRequest(BaseModel):
    index_dir: str
    question: str
    limit: int = Field(default=5, gt=0)
    backend: IndexBackendOption | None = None
    llm_backend: LlmBackendOption | None = None
    llm_base_url: str | None = None
    max_tokens: int | None = Field(default=None, gt=0)
    temperature: float | None = Field(default=None, ge=0)
    include_context: bool = False
    include_prompt: bool = False

    @field_validator("question")
    @classmethod
    def strip_and_validate_question(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            msg = "question must not be empty"
            raise ValueError(msg)
        return stripped


class AskResponse(BaseModel):
    question: str
    answer: str
    retrieved_count: int
    context: list[SearchResultItem] | None = None
    prompt: str | None = None


class ErrorResponse(BaseModel):
    error: str
    detail: str


class TextIngestRequest(BaseModel):
    title: str
    text: str
    index_name: str | None = None
    use_workspace: bool = True
    chunks_path: str | None = None
    index_dir: str | None = None
    backend: IndexBackendOption | None = None
    chunk_size: int = Field(default=1000, gt=0)
    chunk_overlap: int = Field(default=200, ge=0)
    force: bool = False

    @field_validator("title")
    @classmethod
    def strip_and_validate_title(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            msg = "title must not be empty"
            raise ValueError(msg)
        return stripped

    @field_validator("text")
    @classmethod
    def strip_and_validate_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            msg = "text must not be empty"
            raise ValueError(msg)
        return stripped

    @field_validator("index_name")
    @classmethod
    def strip_index_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def validate_path_mode(self) -> Self:
        if self.use_workspace:
            if not self.index_name:
                msg = "index_name is required when use_workspace is true"
                raise ValueError(msg)
        else:
            if not self.chunks_path or not self.index_dir:
                msg = "chunks_path and index_dir are required when use_workspace is false"
                raise ValueError(msg)
        return self


class TextIngestResponse(BaseModel):
    title: str
    chunks_path: str
    index_dir: str
    backend: str
    chunk_count: int
    source_count: int
    message: str
    index_name: str | None = None
    index_slug: str | None = None
    catalog_updated: bool = False


class LocalPathIngestRequest(BaseModel):
    index_name: str
    source_path: str
    backend: IndexBackendOption | None = None
    chunk_size: int = Field(default=1000, gt=0)
    chunk_overlap: int = Field(default=200, ge=0)
    force: bool = False

    @field_validator("index_name")
    @classmethod
    def strip_and_validate_index_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            msg = "index_name must not be empty"
            raise ValueError(msg)
        return stripped

    @field_validator("source_path")
    @classmethod
    def strip_and_validate_source_path(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            msg = "source_path must not be empty"
            raise ValueError(msg)
        return stripped


class LocalPathIngestResponse(BaseModel):
    index_name: str
    index_slug: str
    source_path: str
    source_count: int
    chunk_count: int
    backend: str
    chunks_path: str
    index_dir: str
    catalog_updated: bool
    message: str


class IndexCatalogItem(BaseModel):
    name: str
    slug: str
    backend: str
    chunk_count: int
    source_count: int
    updated_at: str
    index_dir: str


class IndexCatalogListResponse(BaseModel):
    indexes: list[IndexCatalogItem]


class IndexCatalogDetailResponse(BaseModel):
    name: str
    slug: str
    backend: str
    chunks_path: str
    index_dir: str
    chunk_count: int
    source_count: int
    created_at: str
    updated_at: str


class DeleteIndexResponse(BaseModel):
    slug: str
    deleted: bool
    message: str


class WorkspaceExportRequest(BaseModel):
    output_path: str
    slug: str | None = None
    force: bool = False

    @field_validator("output_path")
    @classmethod
    def strip_and_validate_output_path(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            msg = "output_path must not be empty"
            raise ValueError(msg)
        return stripped

    @field_validator("slug")
    @classmethod
    def strip_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class WorkspaceExportResponse(BaseModel):
    output_path: str
    index_count: int
    archive_size_bytes: int
    message: str


class WorkspaceExportDownloadRequest(BaseModel):
    slug: str | None = None

    @field_validator("slug")
    @classmethod
    def strip_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class WorkspaceImportRequest(BaseModel):
    archive_path: str
    force: bool = False

    @field_validator("archive_path")
    @classmethod
    def strip_and_validate_archive_path(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            msg = "archive_path must not be empty"
            raise ValueError(msg)
        return stripped


class WorkspaceImportResponse(BaseModel):
    archive_path: str
    imported_count: int
    imported_slugs: list[str]
    message: str


class WorkspaceImportUploadResponse(BaseModel):
    imported_count: int
    imported_slugs: list[str]
    message: str
