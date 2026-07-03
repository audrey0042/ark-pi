from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class IndexBackendOption(str, Enum):
    simple = "simple"
    chroma = "chroma"


class LlmBackendOption(str, Enum):
    mock = "mock"
    openai_compatible = "openai-compatible"


class HealthResponse(BaseModel):
    status: str
    service: str


class StatusResponse(BaseModel):
    service: str
    role: str
    paths: dict[str, str]
    config: dict[str, Any]


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
