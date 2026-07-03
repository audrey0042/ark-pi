from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from ark_pi import config as ark_config
from ark_pi.rag import ask as rag_ask
from ark_pi.rag import index as rag_index
from ark_pi.web.errors import register_exception_handlers, search_results_to_items
from ark_pi.web.schemas import (
    AskRequest,
    HealthResponse,
    IndexBackendOption,
    IndexStatsResponse,
    SearchRequest,
    SearchResponse,
    StatusResponse,
)

SERVICE_NAME = "ark-pi"


def create_app() -> FastAPI:
    app = FastAPI(title="Ark Pi RAG API", version="0.1.0")
    register_exception_handlers(app)

    @app.get("/healthz", response_model=HealthResponse)
    def healthz() -> HealthResponse:
        return HealthResponse(status="ok", service=SERVICE_NAME)

    @app.get("/api/status", response_model=StatusResponse)
    def api_status() -> StatusResponse:
        payload = ark_config.api_status_payload()
        return StatusResponse(**payload)

    @app.get("/api/index/stats", response_model=IndexStatsResponse)
    def api_index_stats(
        index_dir: str = Query(..., min_length=1),
        backend: IndexBackendOption | None = Query(default=None),
    ) -> IndexStatsResponse:
        resolved_backend = backend.value if backend is not None else None
        stats = rag_index.index_stats(Path(index_dir), backend=resolved_backend)
        return IndexStatsResponse(
            backend=stats.backend,
            schema_version=stats.schema_version,
            chunk_count=stats.chunk_count,
            index_dir=str(stats.index_dir),
            source_chunks=stats.source_chunks,
        )

    @app.post("/api/search", response_model=SearchResponse)
    def api_search(request: SearchRequest) -> SearchResponse:
        resolved_backend = request.backend.value if request.backend is not None else None
        results = rag_index.search_index(
            Path(request.index_dir),
            request.query,
            backend=resolved_backend,
            limit=request.limit,
        )
        return SearchResponse(
            query=request.query,
            results=search_results_to_items(results),
        )

    @app.post("/api/ask")
    def api_ask(request: AskRequest) -> JSONResponse:
        resolved_backend = request.backend.value if request.backend is not None else None
        resolved_llm_backend = (
            request.llm_backend.value if request.llm_backend is not None else None
        )
        result = rag_ask.run_ask(
            Path(request.index_dir),
            request.question,
            limit=request.limit,
            backend=resolved_backend,
            llm_backend=resolved_llm_backend,
            llm_base_url=request.llm_base_url,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
        )

        payload: dict[str, object] = {
            "question": result.question,
            "answer": result.answer,
            "retrieved_count": result.retrieved_count,
        }
        if request.include_context:
            payload["context"] = [
                item.model_dump() for item in search_results_to_items(result.results)
            ]
        if request.include_prompt and result.prompt is not None:
            payload["prompt"] = result.prompt

        return JSONResponse(content=payload)

    return app
