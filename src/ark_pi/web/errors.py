from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ark_pi.embeddings import (
    EmbeddingBackendUnavailable,
    EmbeddingBatchFailed,
    EmbeddingDependencyMissing,
    EmbeddingDimensionMismatch,
    EmbeddingError,
    EmbeddingInvalidVector,
    EmbeddingModelLoadFailed,
    EmbeddingModelMissing,
    EmbeddingNetworkDisabled,
)
from ark_pi.llm_client import LlmConfigurationError, LlmResponseError, LlmTransportError
from ark_pi.rag.index import IndexErrorBase, SearchResult
from ark_pi.workspace.catalog import WorkspaceError, WorkspaceIndexNotFoundError
from ark_pi.web.schemas import ErrorResponse, SearchResultItem


def search_result_to_item(result: SearchResult, rank: int) -> SearchResultItem:
    return SearchResultItem(
        rank=rank,
        score=result.score,
        id=result.id,
        title=result.title,
        source=result.source,
        chunk_index=result.chunk_index,
        text=result.text,
    )


def search_results_to_items(results: list[SearchResult]) -> list[SearchResultItem]:
    return [search_result_to_item(result, rank) for rank, result in enumerate(results, start=1)]


def _error_response(status_code: int, error: str, detail: str) -> JSONResponse:
    body = ErrorResponse(error=error, detail=detail)
    return JSONResponse(status_code=status_code, content=body.model_dump())


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(IndexErrorBase)
    async def handle_index_error(_request: Request, exc: IndexErrorBase) -> JSONResponse:
        return _error_response(400, "index_error", str(exc))

    @app.exception_handler(ValueError)
    async def handle_value_error(_request: Request, exc: ValueError) -> JSONResponse:
        return _error_response(400, "index_error", str(exc))

    @app.exception_handler(FileNotFoundError)
    async def handle_file_not_found(_request: Request, exc: FileNotFoundError) -> JSONResponse:
        return _error_response(400, "index_error", str(exc))

    @app.exception_handler(FileExistsError)
    async def handle_file_exists(_request: Request, exc: FileExistsError) -> JSONResponse:
        return _error_response(400, "index_error", str(exc))

    @app.exception_handler(LlmConfigurationError)
    async def handle_llm_configuration_error(
        _request: Request,
        exc: LlmConfigurationError,
    ) -> JSONResponse:
        return _error_response(400, "llm_configuration_error", str(exc))

    @app.exception_handler(LlmTransportError)
    async def handle_llm_transport_error(
        _request: Request,
        exc: LlmTransportError,
    ) -> JSONResponse:
        return _error_response(502, "llm_upstream_error", str(exc))

    @app.exception_handler(LlmResponseError)
    async def handle_llm_response_error(
        _request: Request,
        exc: LlmResponseError,
    ) -> JSONResponse:
        return _error_response(502, "llm_upstream_error", str(exc))

    @app.exception_handler(EmbeddingBackendUnavailable)
    async def handle_embedding_backend_unavailable(
        _request: Request,
        exc: EmbeddingBackendUnavailable,
    ) -> JSONResponse:
        return _error_response(400, "embedding_configuration_error", str(exc))

    @app.exception_handler(EmbeddingDependencyMissing)
    async def handle_embedding_dependency_missing(
        _request: Request,
        exc: EmbeddingDependencyMissing,
    ) -> JSONResponse:
        return _error_response(400, "embedding_configuration_error", str(exc))

    @app.exception_handler(EmbeddingModelMissing)
    async def handle_embedding_model_missing(
        _request: Request,
        exc: EmbeddingModelMissing,
    ) -> JSONResponse:
        return _error_response(400, "embedding_configuration_error", str(exc))

    @app.exception_handler(EmbeddingNetworkDisabled)
    async def handle_embedding_network_disabled(
        _request: Request,
        exc: EmbeddingNetworkDisabled,
    ) -> JSONResponse:
        return _error_response(400, "embedding_configuration_error", str(exc))

    @app.exception_handler(EmbeddingDimensionMismatch)
    async def handle_embedding_dimension_mismatch(
        _request: Request,
        exc: EmbeddingDimensionMismatch,
    ) -> JSONResponse:
        return _error_response(400, "embedding_configuration_error", str(exc))

    @app.exception_handler(EmbeddingInvalidVector)
    async def handle_embedding_invalid_vector(
        _request: Request,
        exc: EmbeddingInvalidVector,
    ) -> JSONResponse:
        return _error_response(400, "embedding_configuration_error", str(exc))

    @app.exception_handler(EmbeddingModelLoadFailed)
    async def handle_embedding_model_load_failed(
        _request: Request,
        exc: EmbeddingModelLoadFailed,
    ) -> JSONResponse:
        return _error_response(502, "embedding_runtime_error", str(exc))

    @app.exception_handler(EmbeddingBatchFailed)
    async def handle_embedding_batch_failed(
        _request: Request,
        exc: EmbeddingBatchFailed,
    ) -> JSONResponse:
        return _error_response(502, "embedding_runtime_error", str(exc))

    @app.exception_handler(EmbeddingError)
    async def handle_embedding_error(
        _request: Request,
        exc: EmbeddingError,
    ) -> JSONResponse:
        return _error_response(502, "embedding_runtime_error", str(exc))

    @app.exception_handler(WorkspaceIndexNotFoundError)
    async def handle_workspace_index_not_found(
        _request: Request,
        exc: WorkspaceIndexNotFoundError,
    ) -> JSONResponse:
        return _error_response(404, "not_found", str(exc))

    @app.exception_handler(WorkspaceError)
    async def handle_workspace_error(_request: Request, exc: WorkspaceError) -> JSONResponse:
        return _error_response(400, "workspace_error", str(exc))
