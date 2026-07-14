from enum import Enum
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator


class IndexBackendOption(str, Enum):
    simple = "simple"
    chroma = "chroma"


class LlmBackendOption(str, Enum):
    mock = "mock"
    openai_compatible = "openai-compatible"


class EmbeddingBackendOption(str, Enum):
    mock = "mock"
    sentence_transformers = "sentence-transformers"


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


class EmbeddingsPassiveStatusResponse(BaseModel):
    backend: str
    model: str
    model_path: str
    model_path_exists: bool
    expected_dimensions: int
    batch_size: int
    normalize: bool
    device: str
    allow_network: bool
    dependency_importable: bool
    model_load_performed: bool
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


class QuickstartRequest(BaseModel):
    index_name: str = "ark-pi-sample"
    question: str = "What can Ark Pi do?"
    force: bool = False

    @field_validator("index_name")
    @classmethod
    def strip_index_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            msg = "index_name must not be empty"
            raise ValueError(msg)
        return stripped

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            msg = "question must not be empty"
            raise ValueError(msg)
        return stripped


class QuickstartResponse(BaseModel):
    index_name: str
    index_slug: str
    source_path: str
    chunks_path: str
    index_dir: str
    source_count: int
    chunk_count: int
    ask_question: str
    ask_answer: str
    retrieved_count: int
    preflight: PreflightResponse
    message: str


class DeploymentPreflightCheckResponse(BaseModel):
    id: str
    label: str
    status: str
    message: str
    details: dict[str, Any]


class DeploymentPreflightResponse(BaseModel):
    role: str
    generated_dir: str
    overall_status: str
    generated_at: str
    host_mutations_performed: bool
    network_checks_performed: bool
    checks: list[DeploymentPreflightCheckResponse]


class PlanCopyStepResponse(BaseModel):
    id: str
    role: str
    source: str
    destination: str
    mode: str | None
    requires_sudo: bool
    performed: bool
    message: str


class PlanManualCommandResponse(BaseModel):
    id: str
    role: str
    command: str
    requires_sudo: bool
    performed: bool
    message: str


class DeploymentInstallPlanResponse(BaseModel):
    role: str
    generated_dir: str
    created_at: str
    dry_run: bool
    host_mutations_performed: bool
    network_checks_performed: bool
    preflight: DeploymentPreflightResponse
    copy_steps: list[PlanCopyStepResponse]
    manual_commands: list[PlanManualCommandResponse]
    notes: list[str]
    warnings: list[str]
    message: str


class StatusResponse(BaseModel):
    service: str
    role: str
    paths: dict[str, str]
    config: dict[str, Any]
    llm: LlmPassiveStatusResponse
    embeddings: EmbeddingsPassiveStatusResponse
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


class EmbeddingsTestRequest(BaseModel):
    texts: list[str] | None = None
    backend: EmbeddingBackendOption | None = None
    model_path: str | None = None
    allow_network: bool | None = None

    @field_validator("texts")
    @classmethod
    def strip_texts(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        stripped = [item.strip() for item in value if item.strip()]
        return stripped or None

    @field_validator("model_path")
    @classmethod
    def strip_model_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class EmbeddingsTestResponse(BaseModel):
    ok: bool
    backend: str
    model: str
    resolved_model_path: str | None
    dimensions: int
    batch_size: int
    normalize: bool
    load_ms: int
    embedding_ms: int
    texts_embedded: int
    vectors_finite: bool
    related_similarity: float
    unrelated_similarity: float
    related_ranks_higher: bool
    message: str


class IndexStatsResponse(BaseModel):
    backend: str
    schema_version: int
    chunk_count: int
    index_dir: str
    source_chunks: str | None = None
    embedding_fingerprint: str | None = None
    embedding_backend: str | None = None
    embedding_model_name: str | None = None
    embedding_dimensions: int | None = None


class SearchRequest(BaseModel):
    index_dir: str
    query: str
    limit: int = Field(default=5, gt=0)
    backend: IndexBackendOption | None = None
    allow_network: bool | None = None

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
    backend: str
    search_mode: Literal["lexical", "semantic"]
    results: list[SearchResultItem]
    embedding_fingerprint: str | None = None
    score_semantics: str | None = None
    query_embedding_latency_ms: int | None = None
    search_latency_ms: int | None = None


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
