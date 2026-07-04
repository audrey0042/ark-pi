from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from ark_pi import config as ark_config
from ark_pi import init as ark_init
from ark_pi import preflight as ark_preflight
from ark_pi import quickstart as ark_quickstart
from ark_pi.ingest import pipeline as ingest_pipeline
from ark_pi.llm_client import diagnostics as llm_diagnostics
from ark_pi.llm_client.diagnostics import DEFAULT_DIAGNOSTIC_PROMPT
from ark_pi.rag import ask as rag_ask
from ark_pi.rag import index as rag_index
from ark_pi.workspace import catalog as workspace_catalog
from ark_pi.workspace import export as workspace_export
from ark_pi.workspace import importer as workspace_importer
from ark_pi.workspace import ingest as workspace_ingest
from ark_pi.web.errors import register_exception_handlers, search_results_to_items
from ark_pi.web.schemas import (
    AskRequest,
    DeleteIndexResponse,
    HealthResponse,
    IndexBackendOption,
    IndexCatalogDetailResponse,
    IndexCatalogItem,
    IndexCatalogListResponse,
    IndexStatsResponse,
    InitRequest,
    InitResponse,
    LocalPathIngestRequest,
    LocalPathIngestResponse,
    LlmPassiveStatusResponse,
    LlmTestRequest,
    LlmTestResponse,
    PreflightResponse,
    QuickstartRequest,
    QuickstartResponse,
    SearchRequest,
    SearchResponse,
    StatusResponse,
    TextIngestRequest,
    TextIngestResponse,
    WorkspaceExportDownloadRequest,
    WorkspaceExportRequest,
    WorkspaceExportResponse,
    WorkspaceImportRequest,
    WorkspaceImportResponse,
    WorkspaceImportUploadResponse,
)
from ark_pi.web.ui import index_response

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

    @app.get("/api/llm/status", response_model=LlmPassiveStatusResponse)
    def api_llm_status() -> LlmPassiveStatusResponse:
        status = llm_diagnostics.llm_passive_status(ark_config.get_settings())
        return LlmPassiveStatusResponse(
            backend=status.backend,
            model=status.model,
            base_url_configured=status.base_url_configured,
            base_url_display=status.base_url_display,
            timeout_seconds=status.timeout_seconds,
            max_tokens=status.max_tokens,
            temperature=status.temperature,
            network_check_performed=status.network_check_performed,
            message=status.message,
        )

    @app.post("/api/llm/test", response_model=LlmTestResponse)
    def api_llm_test(request: LlmTestRequest) -> LlmTestResponse:
        prompt = request.prompt or DEFAULT_DIAGNOSTIC_PROMPT
        backend = request.backend.value if request.backend is not None else None
        result = llm_diagnostics.run_llm_active_test(
            prompt=prompt,
            backend=backend,
            base_url=request.base_url,
        )
        return LlmTestResponse(
            backend=result.backend,
            model=result.model,
            ok=result.ok,
            output_text=result.output_text,
            latency_ms=result.latency_ms,
            error=result.error,
            message=result.message,
        )

    @app.post("/api/init", response_model=InitResponse)
    def api_init(request: InitRequest) -> InitResponse:
        result = ark_init.initialize_appliance(
            settings=ark_config.get_settings(),
            create_catalog=request.create_catalog,
            create_sample_source=request.create_sample_source,
            force=request.force,
        )
        preflight = result.preflight
        return InitResponse(
            created_paths=result.created_paths,
            existing_paths=result.existing_paths,
            skipped=result.skipped,
            sample_source_path=result.sample_source_path,
            preflight=PreflightResponse(
                role=preflight.role,
                overall_status=preflight.overall_status,
                generated_at=preflight.generated_at,
                network_checks_performed=preflight.network_checks_performed,
                checks=[
                    {
                        "id": check.id,
                        "label": check.label,
                        "status": check.status,
                        "message": check.message,
                        "details": check.details,
                    }
                    for check in preflight.checks
                ],
            ),
            message=result.message,
        )

    @app.post("/api/quickstart", response_model=QuickstartResponse)
    def api_quickstart(request: QuickstartRequest) -> QuickstartResponse:
        result = ark_quickstart.run_quickstart(
            settings=ark_config.get_settings(),
            index_name=request.index_name,
            question=request.question,
            force=request.force,
        )
        preflight = result.preflight
        return QuickstartResponse(
            index_name=result.index_name,
            index_slug=result.index_slug,
            source_path=result.source_path,
            chunks_path=result.chunks_path,
            index_dir=result.index_dir,
            source_count=result.source_count,
            chunk_count=result.chunk_count,
            ask_question=result.ask_question,
            ask_answer=result.ask_answer,
            retrieved_count=result.retrieved_count,
            preflight=PreflightResponse(
                role=preflight.role,
                overall_status=preflight.overall_status,
                generated_at=preflight.generated_at,
                network_checks_performed=preflight.network_checks_performed,
                checks=[
                    {
                        "id": check.id,
                        "label": check.label,
                        "status": check.status,
                        "message": check.message,
                        "details": check.details,
                    }
                    for check in preflight.checks
                ],
            ),
            message=result.message,
        )

    @app.get("/api/preflight", response_model=PreflightResponse)
    def api_preflight() -> PreflightResponse:
        result = ark_preflight.run_preflight(ark_config.get_settings())
        return PreflightResponse(
            role=result.role,
            overall_status=result.overall_status,
            generated_at=result.generated_at,
            network_checks_performed=result.network_checks_performed,
            checks=[
                {
                    "id": check.id,
                    "label": check.label,
                    "status": check.status,
                    "message": check.message,
                    "details": check.details,
                }
                for check in result.checks
            ],
        )

    @app.get("/api/indexes", response_model=IndexCatalogListResponse)
    def api_list_indexes() -> IndexCatalogListResponse:
        settings = ark_config.get_settings()
        entries = workspace_catalog.list_indexes(settings.workspace_dir)
        return IndexCatalogListResponse(
            indexes=[
                IndexCatalogItem(
                    name=entry.name,
                    slug=entry.slug,
                    backend=entry.backend,
                    chunk_count=entry.chunk_count,
                    source_count=entry.source_count,
                    updated_at=entry.updated_at,
                    index_dir=entry.index_dir,
                )
                for entry in entries
            ]
        )

    @app.get("/api/indexes/{slug}", response_model=IndexCatalogDetailResponse)
    def api_get_index(slug: str) -> IndexCatalogDetailResponse | JSONResponse:
        settings = ark_config.get_settings()
        entry = workspace_catalog.get_index(settings.workspace_dir, slug)
        if entry is None:
            return JSONResponse(
                status_code=404,
                content={"error": "not_found", "detail": f"Index not found: {slug}"},
            )
        return IndexCatalogDetailResponse(
            name=entry.name,
            slug=entry.slug,
            backend=entry.backend,
            chunks_path=entry.chunks_path,
            index_dir=entry.index_dir,
            chunk_count=entry.chunk_count,
            source_count=entry.source_count,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        )

    @app.delete("/api/indexes/{slug}", response_model=DeleteIndexResponse)
    def api_delete_index(slug: str) -> DeleteIndexResponse:
        settings = ark_config.get_settings()
        result = workspace_catalog.delete_index(settings.workspace_dir, slug)
        return DeleteIndexResponse(
            slug=result.slug,
            deleted=result.deleted,
            message=result.message,
        )

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

    @app.post("/api/ingest/text", response_model=TextIngestResponse)
    def api_ingest_text(request: TextIngestRequest) -> TextIngestResponse:
        settings = ark_config.get_settings()
        resolved_backend = request.backend.value if request.backend is not None else None

        if request.use_workspace:
            index_name = request.index_name
            if index_name is None:
                msg = "index_name is required when use_workspace is true"
                raise ValueError(msg)
            result = workspace_ingest.ingest_text_to_workspace_index(
                request.title,
                request.text,
                index_name,
                settings.workspace_dir,
                backend=resolved_backend,
                config_backend=settings.index_backend,
                chunk_size=request.chunk_size,
                chunk_overlap=request.chunk_overlap,
                force=request.force,
            )
            message = (
                f"Built {result.backend} index {result.index_name!r} with "
                f"{result.chunk_count} chunk(s) from {result.source_count} source"
            )
            return TextIngestResponse(
                title=result.title,
                chunks_path=str(result.chunks_path),
                index_dir=str(result.index_dir),
                backend=result.backend,
                chunk_count=result.chunk_count,
                source_count=result.source_count,
                message=message,
                index_name=result.index_name,
                index_slug=result.index_slug,
                catalog_updated=result.catalog_updated,
            )

        chunks_path = request.chunks_path
        index_dir = request.index_dir
        if chunks_path is None or index_dir is None:
            msg = "chunks_path and index_dir are required when use_workspace is false"
            raise ValueError(msg)
        result = ingest_pipeline.ingest_text_to_index(
            request.title,
            request.text,
            Path(chunks_path),
            Path(index_dir),
            backend=resolved_backend,
            config_backend=settings.index_backend,
            chunk_size=request.chunk_size,
            chunk_overlap=request.chunk_overlap,
            force=request.force,
        )
        message = (
            f"Built {result.backend} index with {result.chunk_count} chunk(s) "
            f"from {result.source_count} source at {result.index_dir}"
        )
        return TextIngestResponse(
            title=result.title,
            chunks_path=str(result.chunks_path),
            index_dir=str(result.index_dir),
            backend=result.backend,
            chunk_count=result.chunk_count,
            source_count=result.source_count,
            message=message,
            catalog_updated=False,
        )

    @app.post("/api/ingest/path", response_model=LocalPathIngestResponse)
    def api_ingest_path(request: LocalPathIngestRequest) -> LocalPathIngestResponse:
        settings = ark_config.get_settings()
        resolved_backend = request.backend.value if request.backend is not None else None
        result = workspace_ingest.ingest_source_path_to_workspace_index(
            request.source_path,
            request.index_name,
            settings.source_dir,
            settings.workspace_dir,
            backend=resolved_backend,
            config_backend=settings.index_backend,
            chunk_size=request.chunk_size,
            chunk_overlap=request.chunk_overlap,
            force=request.force,
        )
        message = (
            f"Built {result.backend} index {result.index_name!r} with "
            f"{result.chunk_count} chunk(s) from {result.source_count} source(s) "
            f"at {result.source_path}"
        )
        return LocalPathIngestResponse(
            index_name=result.index_name,
            index_slug=result.index_slug,
            source_path=str(result.source_path),
            source_count=result.source_count,
            chunk_count=result.chunk_count,
            backend=result.backend,
            chunks_path=str(result.chunks_path),
            index_dir=str(result.index_dir),
            catalog_updated=result.catalog_updated,
            message=message,
        )

    @app.post("/api/workspace/export", response_model=WorkspaceExportResponse)
    def api_workspace_export(request: WorkspaceExportRequest) -> WorkspaceExportResponse:
        settings = ark_config.get_settings()
        result = workspace_export.export_workspace(
            settings.workspace_dir,
            Path(request.output_path),
            slug=request.slug,
            force=request.force,
        )
        return WorkspaceExportResponse(
            output_path=str(result.output_path),
            index_count=result.index_count,
            archive_size_bytes=result.archive_size_bytes,
            message=result.message,
        )

    @app.post("/api/workspace/export/download")
    def api_workspace_export_download(
        request: WorkspaceExportDownloadRequest,
    ) -> Response:
        settings = ark_config.get_settings()
        data, _info = workspace_export.export_workspace_to_bytes(
            settings.workspace_dir,
            slug=request.slug,
        )
        filename = workspace_export.export_download_filename(request.slug)
        return Response(
            content=data,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.post("/api/workspace/import", response_model=WorkspaceImportResponse)
    def api_workspace_import(request: WorkspaceImportRequest) -> WorkspaceImportResponse:
        settings = ark_config.get_settings()
        result = workspace_importer.import_workspace(
            settings.workspace_dir,
            Path(request.archive_path),
            force=request.force,
        )
        return WorkspaceImportResponse(
            archive_path=str(result.archive_path),
            imported_count=result.imported_count,
            imported_slugs=result.imported_slugs,
            message=result.message,
        )

    @app.post("/api/workspace/import/upload", response_model=WorkspaceImportUploadResponse)
    async def api_workspace_import_upload(
        request: Request,
        force: bool = Query(False),
    ) -> WorkspaceImportUploadResponse | JSONResponse:
        settings = ark_config.get_settings()
        body = await request.body()
        if not body:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "workspace_error",
                    "detail": "Uploaded archive is empty.",
                },
            )
        if len(body) > settings.max_import_bytes:
            return JSONResponse(
                status_code=413,
                content={
                    "error": "payload_too_large",
                    "detail": (
                        f"Uploaded archive exceeds maximum size of "
                        f"{settings.max_import_bytes} bytes."
                    ),
                },
            )
        result = workspace_importer.import_workspace_archive_bytes(
            settings.workspace_dir,
            body,
            force=force,
        )
        return WorkspaceImportUploadResponse(
            imported_count=result.imported_count,
            imported_slugs=result.imported_slugs,
            message=result.message,
        )

    @app.get("/", include_in_schema=False)
    @app.get("/ui", include_in_schema=False)
    def web_ui() -> HTMLResponse:
        return index_response()

    return app
