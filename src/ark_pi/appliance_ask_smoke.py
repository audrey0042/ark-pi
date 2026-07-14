import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ark_pi.config import ArkSettings, get_settings, load_settings_from_env_file
from ark_pi.llm_client.types import LlmClientError
from ark_pi.rag import ask as rag_ask
from ark_pi.rag import index as rag_index
from ark_pi.workspace import catalog as workspace_catalog
from ark_pi.workspace import ingest as workspace_ingest
from ark_pi.workspace.catalog import WorkspaceError, WorkspaceIndexNotFoundError
from ark_pi.workspace.paths import resolve_source_dir, resolve_workspace_dir

SMOKE_INDEX_SLUG = "ark-smoke"
SMOKE_INDEX_NAME = "ark-smoke"
SMOKE_SOURCE_FILENAME = "ark-pi-smoke-beacon.txt"
SMOKE_CORPUS_TEXT = (
    "The Ark Pi smoke-test beacon phrase is copper lantern.\n"
    "This sentence exists only to verify local document ingestion, indexing,\n"
    "retrieval, prompt assembly, and LLM generation.\n"
)
SMOKE_QUESTION = "What is the Ark Pi smoke-test beacon phrase?"
EXPECTED_PHRASE = "copper lantern"
CONTEXT_PREVIEW_LIMIT = 200


@dataclass(frozen=True)
class ApplianceAskSmokeResult:
    ok: bool
    role: str
    index_backend: str
    index_slug: str
    source_path: str
    question: str
    retrieval_ok: bool
    retrieved_result_count: int
    retrieved_context_preview: str
    llm_ok: bool
    answer: str
    expected_phrase: str
    latency_ms: int | None
    cleanup_performed: bool
    message: str
    cleanup_error: str | None = None


def _resolve_settings(env_file: Path | None) -> ArkSettings:
    if env_file is not None:
        return load_settings_from_env_file(env_file)
    return get_settings()


def _validate_rag_role(settings: ArkSettings) -> None:
    if settings.role == "llm":
        msg = (
            "Unsupported role 'llm': ask-smoke requires a RAG workspace with "
            "source and index directories."
        )
        raise ValueError(msg)


def _ensure_data_directories(settings: ArkSettings) -> None:
    for path in (settings.workspace_dir, settings.source_dir):
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            msg = f"Cannot create directory {path}: {exc}"
            raise ValueError(msg) from exc


def _is_smoke_source_path(source_path: Path, source_dir: Path) -> bool:
    resolved_source_dir = resolve_source_dir(source_dir)
    resolved_source = source_path.expanduser().resolve()
    return (
        resolved_source.name == SMOKE_SOURCE_FILENAME
        and resolved_source.parent == resolved_source_dir
    )


def _write_smoke_source(source_dir: Path) -> Path:
    resolved_source_dir = resolve_source_dir(source_dir)
    source_path = resolved_source_dir / SMOKE_SOURCE_FILENAME
    try:
        source_path.write_text(SMOKE_CORPUS_TEXT, encoding="utf-8")
    except OSError as exc:
        msg = f"Cannot write smoke source file {source_path}: {exc}"
        raise ValueError(msg) from exc
    return source_path


def _context_preview(results: list[rag_index.SearchResult]) -> str:
    combined = " ".join(result.text for result in results)
    normalized = " ".join(combined.split())
    if len(normalized) <= CONTEXT_PREVIEW_LIMIT:
        return normalized
    return normalized[: CONTEXT_PREVIEW_LIMIT - 3] + "..."


def _phrase_present(text: str, phrase: str) -> bool:
    return phrase.lower() in text.lower()


def _cleanup_smoke_artifacts(settings: ArkSettings) -> tuple[bool, str | None]:
    errors: list[str] = []

    workspace_dir = resolve_workspace_dir(settings.workspace_dir)
    if workspace_catalog.get_index(workspace_dir, SMOKE_INDEX_SLUG) is not None:
        try:
            workspace_catalog.delete_index(workspace_dir, SMOKE_INDEX_SLUG)
        except (WorkspaceError, WorkspaceIndexNotFoundError, ValueError) as exc:
            errors.append(f"index cleanup failed: {exc}")

    source_path = resolve_source_dir(settings.source_dir) / SMOKE_SOURCE_FILENAME
    if source_path.is_file() and _is_smoke_source_path(source_path, settings.source_dir):
        try:
            source_path.unlink()
        except OSError as exc:
            errors.append(f"source cleanup failed: {exc}")

    if errors:
        return False, "; ".join(errors)
    return True, None


def run_appliance_ask_smoke(
    *,
    env_file: Path | None = None,
    timeout_seconds: float | None = None,
    keep: bool = False,
) -> ApplianceAskSmokeResult:
    """Run an isolated end-to-end RAG ask smoke test against the configured LLM."""
    settings = _resolve_settings(env_file)
    _validate_rag_role(settings)
    _ensure_data_directories(settings)

    source_path = _write_smoke_source(settings.source_dir)
    ingest_result = workspace_ingest.ingest_source_path_to_workspace_index(
        SMOKE_SOURCE_FILENAME,
        SMOKE_INDEX_NAME,
        settings.source_dir,
        settings.workspace_dir,
        config_backend=settings.index_backend,
        force=True,
    )

    execution = rag_index.search_index(
        ingest_result.index_dir,
        SMOKE_QUESTION,
        backend=ingest_result.backend,
        limit=5,
    )
    search_results = execution.results
    retrieved_count = len(search_results)
    context_preview = _context_preview(search_results)

    if retrieved_count == 0:
        cleanup_performed, cleanup_error = _finalize_cleanup(settings, keep=keep)
        return ApplianceAskSmokeResult(
            ok=False,
            role=settings.role,
            index_backend=ingest_result.backend,
            index_slug=ingest_result.index_slug,
            source_path=str(source_path),
            question=SMOKE_QUESTION,
            retrieval_ok=False,
            retrieved_result_count=0,
            retrieved_context_preview=context_preview,
            llm_ok=False,
            answer="",
            expected_phrase=EXPECTED_PHRASE,
            latency_ms=None,
            cleanup_performed=cleanup_performed,
            cleanup_error=cleanup_error,
            message="Ask smoke failed: no retrieval hits for the deterministic question.",
        )

    retrieval_ok = _phrase_present(context_preview, EXPECTED_PHRASE)
    if not retrieval_ok:
        cleanup_performed, cleanup_error = _finalize_cleanup(settings, keep=keep)
        return ApplianceAskSmokeResult(
            ok=False,
            role=settings.role,
            index_backend=ingest_result.backend,
            index_slug=ingest_result.index_slug,
            source_path=str(source_path),
            question=SMOKE_QUESTION,
            retrieval_ok=False,
            retrieved_result_count=retrieved_count,
            retrieved_context_preview=context_preview,
            llm_ok=False,
            answer="",
            expected_phrase=EXPECTED_PHRASE,
            latency_ms=None,
            cleanup_performed=cleanup_performed,
            cleanup_error=cleanup_error,
            message=(
                "Ask smoke failed: retrieved context does not contain expected phrase "
                f"{EXPECTED_PHRASE!r}."
            ),
        )

    started = time.perf_counter()
    try:
        ask_result = rag_ask.run_ask(
            ingest_result.index_dir,
            SMOKE_QUESTION,
            backend=ingest_result.backend,
            settings=settings,
            timeout_seconds=timeout_seconds,
        )
    except LlmClientError as exc:
        cleanup_performed, cleanup_error = _finalize_cleanup(settings, keep=keep)
        return ApplianceAskSmokeResult(
            ok=False,
            role=settings.role,
            index_backend=ingest_result.backend,
            index_slug=ingest_result.index_slug,
            source_path=str(source_path),
            question=SMOKE_QUESTION,
            retrieval_ok=True,
            retrieved_result_count=retrieved_count,
            retrieved_context_preview=context_preview,
            llm_ok=False,
            answer="",
            expected_phrase=EXPECTED_PHRASE,
            latency_ms=None,
            cleanup_performed=cleanup_performed,
            cleanup_error=cleanup_error,
            message=f"Ask smoke failed: LLM error: {exc}",
        )
    latency_ms = int((time.perf_counter() - started) * 1000)

    llm_ok = _phrase_present(ask_result.answer, EXPECTED_PHRASE)
    ok = retrieval_ok and llm_ok

    if ok:
        message = (
            "Appliance ask smoke succeeded: retrieved and generated answer contain "
            f"{EXPECTED_PHRASE!r}."
        )
    elif not llm_ok:
        message = (
            "Ask smoke failed: generated answer does not contain expected phrase "
            f"{EXPECTED_PHRASE!r}."
        )
    else:
        message = "Ask smoke failed."

    cleanup_performed, cleanup_error = _finalize_cleanup(settings, keep=keep)
    if cleanup_error is not None and ok:
        message = f"{message} Cleanup failed: {cleanup_error}"

    return ApplianceAskSmokeResult(
        ok=ok,
        role=settings.role,
        index_backend=ingest_result.backend,
        index_slug=ingest_result.index_slug,
        source_path=str(source_path),
        question=SMOKE_QUESTION,
        retrieval_ok=retrieval_ok,
        retrieved_result_count=retrieved_count,
        retrieved_context_preview=context_preview,
        llm_ok=llm_ok,
        answer=ask_result.answer,
        expected_phrase=EXPECTED_PHRASE,
        latency_ms=latency_ms,
        cleanup_performed=cleanup_performed,
        cleanup_error=cleanup_error,
        message=message,
    )


def _finalize_cleanup(settings: ArkSettings, *, keep: bool) -> tuple[bool, str | None]:
    if keep:
        return False, None
    return _cleanup_smoke_artifacts(settings)


def appliance_ask_smoke_to_dict(result: ApplianceAskSmokeResult) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "role": result.role,
        "index_backend": result.index_backend,
        "index_slug": result.index_slug,
        "source_path": result.source_path,
        "question": result.question,
        "retrieval_ok": result.retrieval_ok,
        "retrieved_result_count": result.retrieved_result_count,
        "retrieved_context_preview": result.retrieved_context_preview,
        "llm_ok": result.llm_ok,
        "answer": result.answer,
        "expected_phrase": result.expected_phrase,
        "latency_ms": result.latency_ms,
        "cleanup_performed": result.cleanup_performed,
        "cleanup_error": result.cleanup_error,
        "message": result.message,
    }
