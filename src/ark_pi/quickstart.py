from dataclasses import dataclass

from ark_pi.config import ArkSettings
from ark_pi.init import SAMPLE_SOURCE_FILENAME, InitResult, initialize_appliance
from ark_pi.preflight import PreflightResult, preflight_to_dict, run_preflight
from ark_pi.rag import ask as rag_ask
from ark_pi.workspace import ingest as workspace_ingest

DEFAULT_INDEX_NAME = "ark-pi-sample"
DEFAULT_QUESTION = "What can Ark Pi do?"


@dataclass(frozen=True)
class QuickstartResult:
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
    preflight: PreflightResult
    message: str
    setup: InitResult


def run_quickstart(
    *,
    settings: ArkSettings | None = None,
    index_name: str = DEFAULT_INDEX_NAME,
    question: str = DEFAULT_QUESTION,
    force: bool = False,
) -> QuickstartResult:
    """Initialize storage, build a sample index, and verify the local RAG loop with mock LLM."""
    if settings is None:
        from ark_pi.config import get_settings

        settings = get_settings()

    stripped_name = index_name.strip()
    if not stripped_name:
        msg = "index_name must not be empty"
        raise ValueError(msg)

    stripped_question = question.strip()
    if not stripped_question:
        msg = "question must not be empty"
        raise ValueError(msg)

    setup = initialize_appliance(
        settings=settings,
        create_catalog=True,
        create_sample_source=True,
        force=force,
    )

    if setup.sample_source_path is None:
        msg = f"Sample source {SAMPLE_SOURCE_FILENAME!r} was not created"
        raise ValueError(msg)

    ingest_result = workspace_ingest.ingest_source_path_to_workspace_index(
        SAMPLE_SOURCE_FILENAME,
        stripped_name,
        settings.source_dir,
        settings.workspace_dir,
        config_backend=settings.index_backend,
        force=force,
    )

    ask_result = rag_ask.run_ask(
        ingest_result.index_dir,
        stripped_question,
        llm_backend="mock",
    )

    if ask_result.no_context:
        msg = "Quickstart ask smoke found no relevant context in the sample index"
        raise ValueError(msg)

    preflight = run_preflight(settings)

    message = (
        f"Quickstart built index {ingest_result.index_name!r} with "
        f"{ingest_result.chunk_count} chunk(s) from {ingest_result.source_count} source(s). "
        f"Mock ask retrieved {ask_result.retrieved_count} chunk(s). "
        f"Preflight status: {preflight.overall_status}."
    )

    return QuickstartResult(
        index_name=ingest_result.index_name,
        index_slug=ingest_result.index_slug,
        source_path=str(ingest_result.source_path),
        chunks_path=str(ingest_result.chunks_path),
        index_dir=str(ingest_result.index_dir),
        source_count=ingest_result.source_count,
        chunk_count=ingest_result.chunk_count,
        ask_question=ask_result.question,
        ask_answer=ask_result.answer,
        retrieved_count=ask_result.retrieved_count,
        preflight=preflight,
        message=message,
        setup=setup,
    )


def quickstart_to_dict(result: QuickstartResult) -> dict[str, object]:
    return {
        "index_name": result.index_name,
        "index_slug": result.index_slug,
        "source_path": result.source_path,
        "chunks_path": result.chunks_path,
        "index_dir": result.index_dir,
        "source_count": result.source_count,
        "chunk_count": result.chunk_count,
        "ask_question": result.ask_question,
        "ask_answer": result.ask_answer,
        "retrieved_count": result.retrieved_count,
        "preflight": preflight_to_dict(result.preflight),
        "message": result.message,
    }
