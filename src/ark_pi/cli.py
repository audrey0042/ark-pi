import json
from enum import Enum
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ark_pi import __version__
from ark_pi import config as ark_config
from ark_pi import init as ark_init
from ark_pi import preflight as ark_preflight
from ark_pi import quickstart as ark_quickstart
from ark_pi.appliance_ask_smoke import appliance_ask_smoke_to_dict, run_appliance_ask_smoke
from ark_pi.appliance_receipt import (
    collect_appliance_receipt,
    resolve_receipt_output_path,
    write_receipt_atomic,
)
from ark_pi.appliance_smoke import appliance_smoke_to_dict, run_appliance_smoke
from ark_pi.corpus.ingest import (
    CorpusIngestError,
    CorpusIngestInterrupted,
    run_corpus_dry_run,
    run_corpus_ingest,
)
from ark_pi.corpus.status import CorpusStatusError, get_corpus_status
from ark_pi.corpus.types import (
    CorpusIngestOptions,
    dry_run_result_to_dict,
    ingest_result_to_dict,
    status_result_to_dict,
)
from ark_pi.corpus.wikipedia import (
    PrepareWikipediaOptions,
    WikipediaPrepareError,
    WikipediaPrepareInterrupted,
    dry_run_result_to_dict as prepare_dry_run_result_to_dict,
    prepare_wikipedia_result_to_dict,
    run_prepare_wikipedia,
    run_prepare_wikipedia_dry_run,
)
from ark_pi.embeddings import (
    EmbeddingError,
    active_test_to_dict,
    embeddings_passive_status,
    evaluate_result_to_dict,
    passive_status_to_dict,
    run_embeddings_active_test,
    run_embeddings_evaluate,
)
from ark_pi.deploy import templates as deploy_templates
from ark_pi.deploy.bundle import build_deployment_bundle, bundle_result_to_dict
from ark_pi.deploy.bundle_verify import bundle_verify_result_to_dict, verify_deployment_bundle
from ark_pi.deploy.bundle_unpack import unpack_deployment_bundle, unpack_result_to_dict
from ark_pi.deploy.plan import (
    build_deployment_install_plan,
    format_plan_json,
    plan_to_dict,
    render_plan_markdown,
    write_plan_output,
)
from ark_pi.deploy.preflight import (
    deployment_preflight_to_dict,
    run_deployment_preflight,
)
from ark_pi.ingest import chunking, sources as ingest_sources
from ark_pi.llm_client import LlmClientError, LlmRequest, create_llm_client
from ark_pi.llm_client.diagnostics import DEFAULT_DIAGNOSTIC_PROMPT, llm_passive_status, run_llm_active_test
from ark_pi.rag import ask as rag_ask
from ark_pi.rag import index as rag_index
from ark_pi.rag.index import IndexErrorBase
from ark_pi.workspace import catalog as workspace_catalog
from ark_pi.workspace import export as workspace_export
from ark_pi.workspace import importer as workspace_importer
from ark_pi.workspace import ingest as workspace_ingest
from ark_pi.workspace.catalog import WorkspaceError, WorkspaceIndexNotFoundError

app = typer.Typer(name="ark", help="Ark Pi — offline/local RAG appliance")
ingest_app = typer.Typer(help="Document ingestion commands")
index_app = typer.Typer(help="Local index commands")
workspace_app = typer.Typer(help="Workspace index commands")
llm_app = typer.Typer(help="LLM client commands")
deploy_app = typer.Typer(help="Deployment template commands")
appliance_app = typer.Typer(help="Appliance validation commands")
corpus_app = typer.Typer(help="Bulk corpus ingestion commands")
embeddings_app = typer.Typer(help="Embedding runtime commands")
app.add_typer(ingest_app, name="ingest")
app.add_typer(index_app, name="index")
app.add_typer(workspace_app, name="workspace")
app.add_typer(llm_app, name="llm")
app.add_typer(deploy_app, name="deploy")
app.add_typer(appliance_app, name="appliance")
app.add_typer(corpus_app, name="corpus")
app.add_typer(embeddings_app, name="embeddings")
console = Console()


class LlmBackendOption(str, Enum):
    mock = "mock"
    openai_compatible = "openai-compatible"


class IndexBackendOption(str, Enum):
    simple = "simple"
    chroma = "chroma"


class EmbeddingBackendOption(str, Enum):
    mock = "mock"
    sentence_transformers = "sentence-transformers"


class DeployRoleOption(str, Enum):
    rag = "rag"
    llm = "llm"
    all = "all"


class PlanFormatOption(str, Enum):
    table = "table"
    markdown = "markdown"
    json = "json"


def _handle_index_errors(exc: BaseException) -> None:
    typer.echo(str(exc), err=True)
    raise typer.Exit(code=1) from exc


def _handle_workspace_errors(exc: BaseException) -> None:
    typer.echo(str(exc), err=True)
    raise typer.Exit(code=1) from exc


def _handle_llm_errors(exc: BaseException) -> None:
    typer.echo(str(exc), err=True)
    raise typer.Exit(code=1) from exc


def _handle_embedding_errors(exc: BaseException) -> None:
    typer.echo(str(exc), err=True)
    raise typer.Exit(code=1) from exc


def _resolve_cli_settings(env_file: Path | None) -> ark_config.ArkSettings:
    if env_file is not None:
        return ark_config.load_settings_from_env_file(env_file)
    return ark_config.get_settings()


@app.command()
def version() -> None:
    """Print the package version."""
    console.print(__version__)


@app.command()
def status() -> None:
    """Print the configured role and basic paths."""
    settings = ark_config.get_settings()
    paths = ark_config.role_paths(settings)

    table = Table(title="Ark Pi Status")
    table.add_column("Key", style="bold")
    table.add_column("Value")

    table.add_row("role", settings.role)
    for key, value in paths.items():
        table.add_row(key, str(value))

    console.print(table)


@app.command(name="config")
def config_cmd() -> None:
    """Print sanitized loaded configuration."""
    settings = ark_config.get_settings()
    display = ark_config.settings_for_display(settings)
    console.print_json(json.dumps(display, indent=2))


@ingest_app.command("chunk")
def ingest_chunk(
    input_path: Path = typer.Option(
        ...,
        "--input",
        help="Source .txt file, directory of .txt files, or .jsonl file",
        exists=False,
    ),
    output_path: Path = typer.Option(
        ...,
        "--output",
        help="Output JSONL path for chunk records",
    ),
    chunk_size: int = typer.Option(1000, "--chunk-size", min=1),
    chunk_overlap: int = typer.Option(200, "--chunk-overlap", min=0),
    force: bool = typer.Option(False, "--force", help="Overwrite output if it exists"),
) -> None:
    """Read local documents and write deterministic chunk records to JSONL."""
    try:
        chunking.validate_chunk_params(chunk_size, chunk_overlap)
        loaded_sources = ingest_sources.load_sources(input_path)
        records = chunking.make_chunk_records(loaded_sources, chunk_size, chunk_overlap)
        chunking.write_chunks_jsonl(records, output_path, force=force)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except FileExistsError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    table = Table(title="Chunk Summary")
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_row("sources", str(len(loaded_sources)))
    table.add_row("chunks", str(len(records)))
    table.add_row("output", str(output_path))
    console.print(table)


def _truncate_snippet(text: str, max_length: int = 120) -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


@index_app.command("build")
def index_build(
    chunks_path: Path = typer.Option(
        ...,
        "--chunks",
        help="Input chunk JSONL from ark ingest chunk",
        exists=False,
    ),
    index_dir: Path = typer.Option(
        ...,
        "--index-dir",
        help="Directory to write the local index",
    ),
    backend: IndexBackendOption | None = typer.Option(
        None,
        "--backend",
        help="Index backend (default: from config, usually simple)",
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite a non-empty index directory"),
) -> None:
    """Build a local searchable index from chunk JSONL."""
    settings = ark_config.get_settings()
    resolved_backend = backend.value if backend is not None else None
    try:
        stats = rag_index.build_index(
            chunks_path,
            index_dir,
            backend=resolved_backend,
            config_backend=settings.index_backend,
            force=force,
        )
    except IndexErrorBase as exc:
        _handle_index_errors(exc)
    except ValueError as exc:
        _handle_index_errors(exc)
    except FileNotFoundError as exc:
        _handle_index_errors(exc)
    except FileExistsError as exc:
        _handle_index_errors(exc)

    table = Table(title="Index Build Summary")
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_row("backend", stats.backend)
    table.add_row("chunks", str(stats.chunk_count))
    table.add_row("index_dir", str(stats.index_dir))
    console.print(table)


@workspace_app.command("list")
def workspace_list() -> None:
    """List named workspace indexes from the local catalog."""
    settings = ark_config.get_settings()
    entries = workspace_catalog.list_indexes(settings.workspace_dir)
    if not entries:
        console.print("No workspace indexes found.")
        return

    table = Table(title="Workspace Indexes")
    table.add_column("Name", style="bold")
    table.add_column("Slug")
    table.add_column("Backend")
    table.add_column("Chunks", justify="right")
    table.add_column("Sources", justify="right")
    table.add_column("Updated")

    for entry in entries:
        table.add_row(
            entry.name,
            entry.slug,
            entry.backend,
            str(entry.chunk_count),
            str(entry.source_count),
            entry.updated_at,
        )
    console.print(table)


@workspace_app.command("show")
def workspace_show(
    slug: str = typer.Option(..., "--slug", help="Workspace index slug"),
) -> None:
    """Show details for one named workspace index."""
    settings = ark_config.get_settings()
    entry = workspace_catalog.get_index(settings.workspace_dir, slug)
    if entry is None:
        typer.echo(f"Workspace index not found: {slug}", err=True)
        raise typer.Exit(code=1)

    table = Table(title=f"Workspace Index: {entry.name}")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("name", entry.name)
    table.add_row("slug", entry.slug)
    table.add_row("backend", entry.backend)
    table.add_row("chunk_count", str(entry.chunk_count))
    table.add_row("source_count", str(entry.source_count))
    table.add_row("chunks_path", entry.chunks_path)
    table.add_row("index_dir", entry.index_dir)
    table.add_row("created_at", entry.created_at)
    table.add_row("updated_at", entry.updated_at)
    console.print(table)


@workspace_app.command("delete")
def workspace_delete(
    slug: str = typer.Option(..., "--slug", help="Workspace index slug to delete"),
    yes: bool = typer.Option(False, "--yes", help="Confirm destructive delete"),
) -> None:
    """Delete a named workspace index and remove its catalog entry."""
    if not yes:
        typer.echo(
            "Refusing to delete without --yes. Pass --yes to confirm deletion.",
            err=True,
        )
        raise typer.Exit(code=1)

    settings = ark_config.get_settings()
    try:
        result = workspace_catalog.delete_index(settings.workspace_dir, slug)
    except WorkspaceIndexNotFoundError as exc:
        _handle_workspace_errors(exc)
    except WorkspaceError as exc:
        _handle_workspace_errors(exc)

    table = Table(title="Workspace Delete Summary")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("slug", result.slug)
    table.add_row("deleted", str(result.deleted))
    table.add_row("message", result.message)
    console.print(table)


@workspace_app.command("export")
def workspace_export_cmd(
    output_path: Path = typer.Option(
        ...,
        "--output",
        help="Output zip archive path",
    ),
    slug: str | None = typer.Option(
        None,
        "--slug",
        help="Export only this workspace index slug",
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing archive"),
) -> None:
    """Export workspace catalog and indexes to a zip archive."""
    settings = ark_config.get_settings()
    try:
        result = workspace_export.export_workspace(
            settings.workspace_dir,
            output_path,
            slug=slug,
            force=force,
        )
    except WorkspaceIndexNotFoundError as exc:
        _handle_workspace_errors(exc)
    except workspace_export.WorkspaceExportError as exc:
        _handle_workspace_errors(exc)

    table = Table(title="Workspace Export Summary")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("output_path", str(result.output_path))
    table.add_row("index_count", str(result.index_count))
    table.add_row("archive_size_bytes", str(result.archive_size_bytes))
    table.add_row("message", result.message)
    console.print(table)


@workspace_app.command("import")
def workspace_import_cmd(
    archive_path: Path = typer.Option(
        ...,
        "--archive",
        help="Input zip archive path",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Replace imported indexes that already exist",
    ),
) -> None:
    """Import workspace catalog and indexes from an Ark Pi export zip archive."""
    settings = ark_config.get_settings()
    try:
        result = workspace_importer.import_workspace(
            settings.workspace_dir,
            archive_path,
            force=force,
        )
    except workspace_importer.WorkspaceImportError as exc:
        _handle_workspace_errors(exc)

    table = Table(title="Workspace Import Summary")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("archive_path", str(result.archive_path))
    table.add_row("imported_count", str(result.imported_count))
    table.add_row("imported_slugs", ", ".join(result.imported_slugs))
    table.add_row("message", result.message)
    console.print(table)


@workspace_app.command("ingest-path")
def workspace_ingest_path(
    source: str = typer.Option(
        ...,
        "--source",
        help="Source .txt file or directory path (relative to ARK_SOURCE_DIR)",
    ),
    index_name: str = typer.Option(
        ...,
        "--index-name",
        help="Named workspace index to create or rebuild",
    ),
    backend: IndexBackendOption | None = typer.Option(
        None,
        "--backend",
        help="Index backend (default: from config, usually simple)",
    ),
    chunk_size: int = typer.Option(1000, "--chunk-size", min=1),
    chunk_overlap: int = typer.Option(200, "--chunk-overlap", min=0),
    force: bool = typer.Option(False, "--force", help="Rebuild an existing named index"),
) -> None:
    """Ingest a server-side text file or directory into a named workspace index."""
    settings = ark_config.get_settings()
    resolved_backend = backend.value if backend is not None else None
    try:
        result = workspace_ingest.ingest_source_path_to_workspace_index(
            source,
            index_name,
            settings.source_dir,
            settings.workspace_dir,
            backend=resolved_backend,
            config_backend=settings.index_backend,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            force=force,
        )
    except IndexErrorBase as exc:
        _handle_index_errors(exc)
    except ValueError as exc:
        _handle_index_errors(exc)
    except FileNotFoundError as exc:
        _handle_index_errors(exc)
    except FileExistsError as exc:
        _handle_index_errors(exc)

    table = Table(title="Workspace Path Ingest Summary")
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_row("index_name", result.index_name)
    table.add_row("index_slug", result.index_slug)
    table.add_row("source_path", str(result.source_path))
    table.add_row("backend", result.backend)
    table.add_row("sources", str(result.source_count))
    table.add_row("chunks", str(result.chunk_count))
    table.add_row("chunks_path", str(result.chunks_path))
    table.add_row("index_dir", str(result.index_dir))
    table.add_row("catalog_updated", str(result.catalog_updated))
    console.print(table)


@index_app.command("stats")
def index_stats_cmd(
    index_dir: Path = typer.Option(
        ...,
        "--index-dir",
        help="Path to a built index directory",
        exists=False,
    ),
    backend: IndexBackendOption | None = typer.Option(
        None,
        "--backend",
        help="Index backend (default: read from manifest)",
    ),
) -> None:
    """Print index manifest details."""
    resolved_backend = backend.value if backend is not None else None
    try:
        stats = rag_index.index_stats(index_dir, backend=resolved_backend)
    except IndexErrorBase as exc:
        _handle_index_errors(exc)
    except ValueError as exc:
        _handle_index_errors(exc)
    except FileNotFoundError as exc:
        _handle_index_errors(exc)

    table = Table(title="Index Stats")
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_row("backend", stats.backend)
    table.add_row("schema_version", str(stats.schema_version))
    table.add_row("chunk_count", str(stats.chunk_count))
    table.add_row("index_dir", str(stats.index_dir))
    if stats.source_chunks is not None:
        table.add_row("source_chunks", stats.source_chunks)
    console.print(table)


@index_app.command("search")
def index_search(
    index_dir: Path = typer.Option(
        ...,
        "--index-dir",
        help="Path to a built index directory",
        exists=False,
    ),
    query: str = typer.Option(..., "--query", help="Search query"),
    backend: IndexBackendOption | None = typer.Option(
        None,
        "--backend",
        help="Index backend (default: read from manifest)",
    ),
    limit: int = typer.Option(5, "--limit", min=1),
) -> None:
    """Search a local index using the configured backend."""
    resolved_backend = backend.value if backend is not None else None
    try:
        results = rag_index.search_index(
            index_dir,
            query,
            backend=resolved_backend,
            limit=limit,
        )
    except IndexErrorBase as exc:
        _handle_index_errors(exc)
    except ValueError as exc:
        _handle_index_errors(exc)
    except FileNotFoundError as exc:
        _handle_index_errors(exc)

    if not results:
        console.print("No matches found.")
        return

    table = Table(title=f"Search Results ({len(results)})")
    table.add_column("Rank", style="bold")
    table.add_column("Score")
    table.add_column("Title")
    table.add_column("Chunk ID")
    table.add_column("Snippet")

    for rank, result in enumerate(results, start=1):
        table.add_row(
            str(rank),
            f"{result.score:.2f}",
            result.title,
            result.id,
            _truncate_snippet(result.text),
        )
    console.print(table)


@app.command("ask")
def ask(
    index_dir: Path = typer.Option(
        ...,
        "--index-dir",
        help="Path to a built index directory",
        exists=False,
    ),
    question: str = typer.Option(..., "--question", help="Question to ask the local index"),
    limit: int = typer.Option(5, "--limit", min=1),
    show_context: bool = typer.Option(False, "--show-context", help="Show retrieved context chunks"),
    show_prompt: bool = typer.Option(False, "--show-prompt", help="Show the assembled RAG prompt"),
    llm_backend: LlmBackendOption | None = typer.Option(
        None,
        "--llm-backend",
        help="LLM backend to use (default: from config, usually mock)",
    ),
    llm_base_url: str | None = typer.Option(
        None,
        "--llm-base-url",
        help="Base URL for openai-compatible backend",
    ),
    max_tokens: int | None = typer.Option(
        None,
        "--max-tokens",
        min=1,
        help="Maximum tokens for LLM completion",
    ),
    temperature: float | None = typer.Option(
        None,
        "--temperature",
        help="Sampling temperature for LLM completion",
    ),
) -> None:
    """Search the local index, assemble a prompt, and call the configured LLM backend."""
    stripped_question = question.strip()
    if not stripped_question:
        typer.echo("Question must not be empty.", err=True)
        raise typer.Exit(code=1)

    resolved_llm_backend = llm_backend.value if llm_backend is not None else None

    try:
        result = rag_ask.run_ask(
            index_dir,
            stripped_question,
            limit=limit,
            llm_backend=resolved_llm_backend,
            llm_base_url=llm_base_url,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except IndexErrorBase as exc:
        _handle_index_errors(exc)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except FileNotFoundError as exc:
        _handle_index_errors(exc)
    except LlmClientError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if result.no_context:
        console.print(result.answer)
        return

    console.print(f"Question: {result.question}")
    console.print()
    console.print(result.answer)
    console.print()
    console.print(f"Retrieved chunks: {result.retrieved_count}")

    if show_context:
        table = Table(title=f"Retrieved Context ({result.retrieved_count})")
        table.add_column("Rank", style="bold")
        table.add_column("Score")
        table.add_column("Title")
        table.add_column("Chunk ID")
        table.add_column("Snippet")

        for rank, chunk in enumerate(result.results, start=1):
            table.add_row(
                str(rank),
                f"{chunk.score:.2f}",
                chunk.title,
                chunk.id,
                _truncate_snippet(chunk.text),
            )
        console.print(table)

    if show_prompt and result.prompt is not None:
        console.print(Panel(result.prompt, title="Assembled Prompt", expand=False))


@app.command("serve")
def serve(
    host: str | None = typer.Option(None, "--host", help="Host to bind the API server"),
    port: int | None = typer.Option(None, "--port", min=1, help="Port to bind the API server"),
) -> None:
    """Run the local FastAPI RAG API with uvicorn."""
    import uvicorn

    settings = ark_config.get_settings()
    uvicorn.run(
        "ark_pi.web.app:create_app",
        factory=True,
        host=host or settings.host,
        port=port or settings.port,
    )


@llm_app.command("status")
def llm_status_cmd() -> None:
    """Show passive LLM configuration (no network call)."""
    settings = ark_config.get_settings()
    status = llm_passive_status(settings)

    table = Table(title="LLM Status")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("backend", status.backend)
    table.add_row("model", status.model)
    table.add_row("base_url_configured", str(status.base_url_configured))
    table.add_row("base_url_display", status.base_url_display or "")
    table.add_row("timeout_seconds", str(status.timeout_seconds))
    table.add_row("max_tokens", str(status.max_tokens))
    table.add_row("temperature", str(status.temperature))
    table.add_row("network_check_performed", str(status.network_check_performed))
    table.add_row("message", status.message)
    console.print(table)


@llm_app.command("test")
def llm_test_cmd(
    prompt: str = typer.Option(
        DEFAULT_DIAGNOSTIC_PROMPT,
        "--prompt",
        help="Diagnostic prompt to send",
    ),
    llm_backend: LlmBackendOption | None = typer.Option(
        None,
        "--llm-backend",
        help="LLM backend to test (default: from config)",
    ),
    llm_base_url: str | None = typer.Option(
        None,
        "--llm-base-url",
        help="Base URL for openai-compatible backend",
    ),
) -> None:
    """Run an explicit LLM diagnostic test through the configured backend."""
    resolved_backend = llm_backend.value if llm_backend is not None else None
    try:
        result = run_llm_active_test(
            prompt=prompt,
            backend=resolved_backend,
            base_url=llm_base_url,
        )
    except LlmClientError as exc:
        _handle_llm_errors(exc)

    table = Table(title="LLM Test Result")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("backend", result.backend)
    table.add_row("model", result.model)
    table.add_row("ok", str(result.ok))
    table.add_row("latency_ms", str(result.latency_ms))
    table.add_row("output_text", result.output_text)
    table.add_row("message", result.message)
    console.print(table)


@embeddings_app.command("status")
def embeddings_status_cmd(
    env_file: Path | None = typer.Option(
        None,
        "--env-file",
        help="Deployment env file (e.g. /etc/ark-pi/ark-rag.env)",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON output"),
) -> None:
    """Show passive embedding configuration (no model load or network call)."""
    settings = _resolve_cli_settings(env_file)
    status = embeddings_passive_status(settings)

    if as_json:
        console.print_json(json.dumps(passive_status_to_dict(status)))
        return

    table = Table(title="Embedding Status")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("backend", status.backend)
    table.add_row("model", status.model)
    table.add_row("model_path", status.model_path)
    table.add_row("model_path_exists", str(status.model_path_exists))
    table.add_row("expected_dimensions", str(status.expected_dimensions))
    table.add_row("batch_size", str(status.batch_size))
    table.add_row("normalize", str(status.normalize))
    table.add_row("device", status.device)
    table.add_row("allow_network", str(status.allow_network))
    table.add_row("dependency_importable", str(status.dependency_importable))
    table.add_row("model_load_performed", str(status.model_load_performed))
    table.add_row("network_check_performed", str(status.network_check_performed))
    table.add_row("message", status.message)
    console.print(table)


@embeddings_app.command("test")
def embeddings_test_cmd(
    env_file: Path | None = typer.Option(
        None,
        "--env-file",
        help="Deployment env file (e.g. /etc/ark-pi/ark-rag.env)",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON output"),
    text: list[str] = typer.Option(
        [],
        "--text",
        help="Text to embed (repeatable; defaults to built-in fixture texts)",
    ),
    model_path: Path | None = typer.Option(
        None,
        "--model-path",
        help="Override local embedding model directory",
    ),
    allow_network: bool = typer.Option(
        False,
        "--allow-network",
        help="Permit remote model resolution when no local model path is set",
    ),
) -> None:
    """Run an explicit embedding diagnostic test through the configured backend."""
    settings = _resolve_cli_settings(env_file)
    texts = text or None
    try:
        result = run_embeddings_active_test(
            texts=texts,
            settings=settings,
            allow_network=allow_network or settings.embedding_allow_network,
            model_path=model_path,
        )
    except EmbeddingError as exc:
        _handle_embedding_errors(exc)

    if as_json:
        console.print_json(json.dumps(active_test_to_dict(result)))
        return

    table = Table(title="Embedding Test Result")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("ok", str(result.ok))
    table.add_row("backend", result.backend)
    table.add_row("model", result.model)
    table.add_row("resolved_model_path", result.resolved_model_path or "")
    table.add_row("dimensions", str(result.dimensions))
    table.add_row("batch_size", str(result.batch_size))
    table.add_row("normalize", str(result.normalize))
    table.add_row("load_ms", str(result.load_ms))
    table.add_row("embedding_ms", str(result.embedding_ms))
    table.add_row("texts_embedded", str(result.texts_embedded))
    table.add_row("vectors_finite", str(result.vectors_finite))
    table.add_row("related_similarity", f"{result.related_similarity:.4f}")
    table.add_row("unrelated_similarity", f"{result.unrelated_similarity:.4f}")
    table.add_row("related_ranks_higher", str(result.related_ranks_higher))
    table.add_row("message", result.message)
    console.print(table)


@embeddings_app.command("evaluate")
def embeddings_evaluate_cmd(
    env_file: Path | None = typer.Option(
        None,
        "--env-file",
        help="Deployment env file (e.g. /etc/ark-pi/ark-rag.env)",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON output"),
    fixture: Path | None = typer.Option(
        None,
        "--fixture",
        help="Optional local JSON evaluation fixture",
    ),
    model_path: Path | None = typer.Option(
        None,
        "--model-path",
        help="Override local embedding model directory",
    ),
    allow_network: bool = typer.Option(
        False,
        "--allow-network",
        help="Permit remote model resolution when no local model path is set",
    ),
) -> None:
    """Run offline retrieval-quality evaluation without modifying indexes."""
    settings = _resolve_cli_settings(env_file)
    try:
        result = run_embeddings_evaluate(
            settings=settings,
            fixture_path=fixture,
            allow_network=allow_network or settings.embedding_allow_network,
            model_path=model_path,
        )
    except (EmbeddingError, ValueError) as exc:
        _handle_embedding_errors(exc)

    if as_json:
        console.print_json(json.dumps(evaluate_result_to_dict(result)))
        return

    table = Table(title="Embedding Evaluation Result")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("ok", str(result.ok))
    table.add_row("backend", result.backend)
    table.add_row("model", result.model)
    table.add_row("resolved_model_path", result.resolved_model_path or "")
    table.add_row("dimensions", str(result.dimensions))
    table.add_row("top1_accuracy", f"{result.top1_accuracy:.4f}")
    table.add_row("recall_at_3", f"{result.recall_at_3:.4f}")
    table.add_row("mean_reciprocal_rank", f"{result.mean_reciprocal_rank:.4f}")
    table.add_row("query_count", str(result.query_count))
    table.add_row("documents_count", str(result.documents_count))
    table.add_row("total_latency_ms", str(result.total_latency_ms))
    table.add_row("message", result.message)
    console.print(table)


@appliance_app.command("smoke")
def appliance_smoke_cmd(
    env_file: Path | None = typer.Option(
        None,
        "--env-file",
        help="Deployment env file (e.g. /etc/ark-pi/ark-rag.env)",
    ),
    llm_base_url: str | None = typer.Option(
        None,
        "--llm-base-url",
        help="Override LLM base URL for the smoke test",
    ),
    timeout: float | None = typer.Option(
        None,
        "--timeout",
        help="Override LLM timeout in seconds",
    ),
    as_json: bool = typer.Option(False, "--json", help="Output JSON receipt"),
) -> None:
    """Validate RAG-to-LLM connectivity with an explicit network smoke test."""
    try:
        result = run_appliance_smoke(
            env_file=env_file,
            llm_base_url=llm_base_url,
            timeout_seconds=timeout,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except LlmClientError as exc:
        _handle_llm_errors(exc)

    if as_json:
        console.print_json(json.dumps(appliance_smoke_to_dict(result)))
    else:
        table = Table(title="Appliance Smoke Result")
        table.add_column("Field", style="bold")
        table.add_column("Value")
        table.add_row("role", result.role)
        table.add_row("llm_backend", result.backend)
        table.add_row("model", result.model)
        table.add_row("base_url", result.base_url or "")
        table.add_row("timeout_seconds", str(result.timeout_seconds))
        table.add_row("ok", str(result.ok))
        table.add_row("latency_ms", str(result.latency_ms))
        table.add_row("output_text", result.output_text)
        table.add_row("message", result.message)
        console.print(table)

    if not result.ok:
        raise typer.Exit(code=1)


@appliance_app.command("ask-smoke")
def appliance_ask_smoke_cmd(
    env_file: Path | None = typer.Option(
        None,
        "--env-file",
        help="Deployment env file (e.g. /etc/ark-pi/ark-rag.env)",
    ),
    timeout: float | None = typer.Option(
        None,
        "--timeout",
        help="Override LLM timeout in seconds",
    ),
    keep: bool = typer.Option(
        False,
        "--keep",
        help="Preserve isolated smoke corpus and index after the run",
    ),
    as_json: bool = typer.Option(False, "--json", help="Output JSON receipt"),
) -> None:
    """Run an isolated end-to-end RAG ask smoke test through the configured LLM."""
    try:
        result = run_appliance_ask_smoke(
            env_file=env_file,
            timeout_seconds=timeout,
            keep=keep,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if as_json:
        console.print_json(json.dumps(appliance_ask_smoke_to_dict(result)))
    else:
        table = Table(title="Appliance Ask Smoke Result")
        table.add_column("Field", style="bold")
        table.add_column("Value")
        table.add_row("ok", str(result.ok))
        table.add_row("role", result.role)
        table.add_row("index_backend", result.index_backend)
        table.add_row("index_slug", result.index_slug)
        table.add_row("source_path", result.source_path)
        table.add_row("question", result.question)
        table.add_row("retrieval_ok", str(result.retrieval_ok))
        table.add_row("retrieved_result_count", str(result.retrieved_result_count))
        table.add_row("retrieved_context_preview", result.retrieved_context_preview)
        table.add_row("llm_ok", str(result.llm_ok))
        table.add_row("answer", result.answer)
        table.add_row("expected_phrase", result.expected_phrase)
        table.add_row("latency_ms", str(result.latency_ms))
        table.add_row("cleanup_performed", str(result.cleanup_performed))
        if result.cleanup_error is not None:
            table.add_row("cleanup_error", result.cleanup_error)
        table.add_row("message", result.message)
        console.print(table)

    if not result.ok:
        raise typer.Exit(code=1)


@appliance_app.command("receipt")
def appliance_receipt_cmd(
    env_file: Path | None = typer.Option(
        None,
        "--env-file",
        help="Deployment env file (e.g. /etc/ark-pi/ark-rag.env)",
    ),
    as_json: bool = typer.Option(False, "--json", help="Print receipt JSON to stdout"),
    output: Path | None = typer.Option(
        None,
        "--output",
        help="Write receipt JSON atomically to PATH",
    ),
    receipt_dir: Path | None = typer.Option(
        None,
        "--receipt-dir",
        help="Write a timestamped receipt JSON file under DIR",
    ),
    run_smoke: bool = typer.Option(
        False,
        "--run-smoke",
        help="Run connectivity smoke and embed the result (network activity)",
    ),
    run_ask_smoke: bool = typer.Option(
        False,
        "--run-ask-smoke",
        help="Run end-to-end ask smoke and embed the result",
    ),
    keep_smoke_artifacts: bool = typer.Option(
        False,
        "--keep-smoke-artifacts",
        help="Preserve ask-smoke artifacts when --run-ask-smoke is used",
    ),
    timeout: float | None = typer.Option(
        None,
        "--timeout",
        help="Override timeout for active smoke operations",
    ),
    hash_model: bool = typer.Option(
        False,
        "--hash-model",
        help="Include full model SHA256 in the receipt",
    ),
    fail_on_warning: bool = typer.Option(
        False,
        "--fail-on-warning",
        help="Exit nonzero when overall status is warning",
    ),
    allow_smoke_failure: bool = typer.Option(
        False,
        "--allow-smoke-failure",
        help="Exit zero even when an explicitly requested smoke check fails",
    ),
) -> None:
    """Collect a structured appliance validation receipt (offline by default)."""
    try:
        result = collect_appliance_receipt(
            env_file=env_file,
            hash_model=hash_model,
            run_smoke=run_smoke,
            run_ask_smoke=run_ask_smoke,
            keep_smoke_artifacts=keep_smoke_artifacts,
            timeout_seconds=timeout,
            allow_smoke_failure=allow_smoke_failure,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    output_path = resolve_receipt_output_path(output=output, receipt_dir=receipt_dir)
    if output_path is not None:
        write_receipt_atomic(output_path, result.payload)
        result = type(result)(
            payload=result.payload,
            overall_status=result.overall_status,
            output_path=output_path,
        )

    if as_json:
        console.print_json(json.dumps(result.payload))
    else:
        table = Table(title="Appliance Validation Receipt")
        table.add_column("Field", style="bold")
        table.add_column("Value")
        table.add_row("overall_status", result.overall_status)
        table.add_row("role", str(result.payload["configuration"]["role"]))
        table.add_row("schema", f"{result.payload['schema_name']} v{result.payload['schema_version']}")
        table.add_row(
            "connectivity_smoke",
            str(result.payload["active_smoke"]["connectivity"]["status"]),
        )
        table.add_row("ask_smoke", str(result.payload["active_smoke"]["ask"]["status"]))
        if result.output_path is not None:
            table.add_row("output_path", str(result.output_path))
        if result.payload["warnings"]:
            table.add_row("warnings", "; ".join(result.payload["warnings"]))
        if result.payload["next_steps"]:
            table.add_row("next_steps", result.payload["next_steps"][0])
        console.print(table)
        if len(result.payload["next_steps"]) > 1:
            for step in result.payload["next_steps"][1:]:
                console.print(f"- {step}")
        if result.output_path is not None and not as_json:
            console.print(f"Receipt written to {result.output_path}")

    if result.overall_status == "fail":
        static_fail = any(
            check.get("status") == "fail" for check in result.payload["checks"]
        )
        smoke_failed = (
            result.payload["active_smoke"]["connectivity"].get("status") == "fail"
            or result.payload["active_smoke"]["ask"].get("status") == "fail"
        )
        if not (allow_smoke_failure and smoke_failed and not static_fail):
            raise typer.Exit(code=1)
    elif result.overall_status == "warning" and fail_on_warning:
        raise typer.Exit(code=1)


@llm_app.command("mock")
def llm_mock(
    prompt: str = typer.Option(..., "--prompt", help="Prompt to send to the mock LLM backend"),
) -> None:
    """Call the mock LLM backend directly (no network)."""
    client = create_llm_client("mock")
    response = client.complete(LlmRequest(prompt=prompt))
    console.print(response.text)


@app.command()
def init(
    sample: bool = typer.Option(
        False,
        "--sample",
        help="Create a tiny sample .txt source file",
    ),
    no_catalog: bool = typer.Option(
        False,
        "--no-catalog",
        help="Do not create catalog.json",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Allow replacing invalid catalog or sample source",
    ),
    as_json: bool = typer.Option(False, "--json", help="Output API-shaped JSON"),
) -> None:
    """Create local appliance workspace and source directories (no network calls)."""
    try:
        result = ark_init.initialize_appliance(
            settings=ark_config.get_settings(),
            create_catalog=not no_catalog,
            create_sample_source=sample,
            force=force,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if as_json:
        console.print_json(json.dumps(ark_init.init_to_dict(result)))
        return

    if result.created_paths:
        created_table = Table(title="Created paths")
        created_table.add_column("Path")
        for path in result.created_paths:
            created_table.add_row(path)
        console.print(created_table)

    if result.existing_paths:
        existing_table = Table(title="Existing paths")
        existing_table.add_column("Path")
        for path in result.existing_paths:
            existing_table.add_row(path)
        console.print(existing_table)

    if result.skipped:
        skipped_table = Table(title="Skipped paths")
        skipped_table.add_column("Path")
        for path in result.skipped:
            skipped_table.add_row(path)
        console.print(skipped_table)

    if result.sample_source_path:
        console.print(f"Sample source: {result.sample_source_path}")

    console.print(f"Preflight status: [bold]{result.preflight.overall_status}[/bold]")
    console.print(result.message)


@app.command()
def quickstart(
    index_name: str = typer.Option(
        ark_quickstart.DEFAULT_INDEX_NAME,
        "--index-name",
        help="Workspace index name for the sample",
    ),
    question: str = typer.Option(
        ark_quickstart.DEFAULT_QUESTION,
        "--question",
        help="Smoke-test question for mock ask",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Rebuild the sample index if it already exists",
    ),
    as_json: bool = typer.Option(False, "--json", help="Output API-shaped JSON"),
) -> None:
    """Initialize storage, build a sample index, and verify the RAG loop with mock LLM."""
    try:
        result = ark_quickstart.run_quickstart(
            settings=ark_config.get_settings(),
            index_name=index_name,
            question=question,
            force=force,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if as_json:
        console.print_json(json.dumps(ark_quickstart.quickstart_to_dict(result)))
        return

    setup = result.setup
    if setup.created_paths:
        created_table = Table(title="Created paths")
        created_table.add_column("Path")
        for path in setup.created_paths:
            created_table.add_row(path)
        console.print(created_table)

    if setup.existing_paths:
        existing_table = Table(title="Existing paths")
        existing_table.add_column("Path")
        for path in setup.existing_paths:
            existing_table.add_row(path)
        console.print(existing_table)

    if setup.skipped:
        skipped_table = Table(title="Skipped paths")
        skipped_table.add_column("Path")
        for path in setup.skipped:
            skipped_table.add_row(path)
        console.print(skipped_table)

    console.print(f"Index: [bold]{result.index_name}[/bold] ({result.index_slug})")
    console.print(f"Chunks: {result.chunk_count} from {result.source_count} source(s)")
    console.print(f"Index dir: {result.index_dir}")
    console.print(f"Ask: {result.ask_question}")
    console.print(f"Retrieved: {result.retrieved_count} chunk(s)")
    console.print(f"Answer: {result.ask_answer}")
    console.print(f"Preflight status: [bold]{result.preflight.overall_status}[/bold]")
    console.print(result.message)


@deploy_app.command("render")
def deploy_render(
    output_dir: Path = typer.Option(
        deploy_templates.DEFAULT_OUTPUT_DIR,
        "--output-dir",
        help="Directory for rendered deployment templates",
    ),
    role: DeployRoleOption = typer.Option(
        DeployRoleOption.all,
        "--role",
        help="Render templates for ark-rag, ark-llm, or both",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite existing generated files",
    ),
    prefix: str | None = typer.Option(
        None,
        "--prefix",
        help="Install prefix for LLM WorkingDirectory (default: /opt/ark-pi)",
    ),
    llama_bin: str | None = typer.Option(
        None,
        "--llama-bin",
        help="Path to llama-server binary for ark-llm.env",
    ),
    model_dir: str | None = typer.Option(
        None,
        "--model-dir",
        help="Model directory for ark-llm.env",
    ),
    model_path: str | None = typer.Option(
        None,
        "--model-path",
        help="GGUF model path for ark-llm.env",
    ),
    llama_host: str | None = typer.Option(
        None,
        "--llama-host",
        help="Bind host for llama-server",
    ),
    llama_port: int | None = typer.Option(
        None,
        "--llama-port",
        help="Bind port for llama-server",
    ),
    context_size: int | None = typer.Option(
        None,
        "--context-size",
        help="Context size for llama-server",
    ),
    threads: int | None = typer.Option(
        None,
        "--threads",
        help="Thread count for llama-server",
    ),
    llm_base_url: str | None = typer.Option(
        None,
        "--llm-base-url",
        help="Partner LLM base URL for ark-rag.env (ARK_LLM_BASE_URL)",
    ),
    as_json: bool = typer.Option(False, "--json", help="Output API-shaped JSON"),
) -> None:
    """Render ark-rag and ark-llm env/systemd templates for review (does not install)."""
    llm_overrides: dict[str, object] = {}
    if prefix is not None:
        llm_overrides["prefix"] = prefix
    if llama_bin is not None:
        llm_overrides["llama_bin"] = llama_bin
    if model_dir is not None:
        llm_overrides["model_dir"] = model_dir
    if model_path is not None:
        llm_overrides["model_path"] = model_path
    if llama_host is not None:
        llm_overrides["llama_host"] = llama_host
    if llama_port is not None:
        llm_overrides["llama_port"] = llama_port
    if context_size is not None:
        llm_overrides["context_size"] = context_size
    if threads is not None:
        llm_overrides["threads"] = threads

    llm_config = None
    if llm_overrides:
        base = deploy_templates.LlmRenderConfig()
        llm_config = deploy_templates.LlmRenderConfig(
            **{**base.__dict__, **llm_overrides}
        )

    rag_config = None
    if llm_base_url is not None:
        base = deploy_templates.RagRenderConfig()
        rag_config = deploy_templates.RagRenderConfig(
            **{**base.__dict__, "llm_base_url": llm_base_url}
        )

    try:
        result = deploy_templates.render_deployment_templates(
            output_dir,
            role=role.value,
            force=force,
            llm_config=llm_config,
            rag_config=rag_config,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if as_json:
        console.print_json(json.dumps(deploy_templates.render_to_dict(result)))
        return

    table = Table(title="Deployment templates rendered")
    table.add_column("File")
    table.add_column("Kind")
    table.add_column("Role")
    for generated in result.generated_files:
        table.add_row(generated.path, generated.kind, generated.role)
    console.print(table)
    console.print(result.message)


@deploy_app.command("preflight")
def deploy_preflight(
    generated_dir: Path = typer.Option(
        deploy_templates.DEFAULT_OUTPUT_DIR,
        "--generated-dir",
        help="Directory containing rendered deployment templates",
    ),
    role: DeployRoleOption = typer.Option(
        DeployRoleOption.all,
        "--role",
        help="Preflight rendered templates for ark-rag, ark-llm, or both",
    ),
    as_json: bool = typer.Option(False, "--json", help="Output API-shaped JSON"),
) -> None:
    """Run dry-run deployment preflight against rendered templates (does not install)."""
    result = run_deployment_preflight(
        generated_dir,
        role=role.value,
    )

    if as_json:
        console.print_json(json.dumps(deployment_preflight_to_dict(result)))
    else:
        console.print(f"Overall status: [bold]{result.overall_status}[/bold]")
        table = Table(title="Deployment Preflight")
        table.add_column("Check", style="bold")
        table.add_column("Status")
        table.add_column("Message")
        for check in result.checks:
            table.add_row(check.id, check.status, check.message)
        console.print(table)

    if result.overall_status == "blocked":
        raise typer.Exit(code=1)


@deploy_app.command("plan")
def deploy_plan(
    generated_dir: Path = typer.Option(
        deploy_templates.DEFAULT_OUTPUT_DIR,
        "--generated-dir",
        help="Directory containing rendered deployment templates",
    ),
    role: DeployRoleOption = typer.Option(
        DeployRoleOption.all,
        "--role",
        help="Build install plan for ark-rag, ark-llm, or both",
    ),
    output_format: PlanFormatOption = typer.Option(
        PlanFormatOption.table,
        "--format",
        help="Output format",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        help="Optional file path for markdown or json output",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite existing output file",
    ),
) -> None:
    """Build a dry-run deployment install plan (does not copy files or run commands)."""
    try:
        plan = build_deployment_install_plan(
            generated_dir,
            role=role.value,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if output is not None:
        if output_format == PlanFormatOption.table:
            typer.echo("--format table cannot be written to --output; use markdown or json.", err=True)
            raise typer.Exit(code=1)
        content = (
            render_plan_markdown(plan)
            if output_format == PlanFormatOption.markdown
            else format_plan_json(plan)
        )
        try:
            written = write_plan_output(output, content, force=force)
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
        console.print(f"Wrote deployment install plan to {written}")
        return

    if output_format == PlanFormatOption.json:
        console.print_json(format_plan_json(plan).rstrip())
        return

    if output_format == PlanFormatOption.markdown:
        console.print(render_plan_markdown(plan))
        return

    console.print(f"Overall preflight status: [bold]{plan.preflight.overall_status}[/bold]")
    console.print(plan.message)

    copy_table = Table(title="Planned file copies")
    copy_table.add_column("ID", style="bold")
    copy_table.add_column("Role")
    copy_table.add_column("Destination")
    copy_table.add_column("Performed")
    for step in plan.copy_steps:
        copy_table.add_row(step.id, step.role, step.destination, str(step.performed))
    console.print(copy_table)

    command_table = Table(title="Manual commands")
    command_table.add_column("ID", style="bold")
    command_table.add_column("Role")
    command_table.add_column("Command")
    command_table.add_column("Performed")
    for command in plan.manual_commands:
        command_table.add_row(
            command.id,
            command.role,
            command.command,
            str(command.performed),
        )
    console.print(command_table)

    if plan.warnings:
        console.print("[bold]Warnings[/bold]")
        for warning in plan.warnings:
            console.print(f"- {warning}")


@deploy_app.command("bundle")
def deploy_bundle(
    output: Path = typer.Option(
        ...,
        "--output",
        help="Zip output path for the deployment bundle",
    ),
    generated_dir: Path = typer.Option(
        deploy_templates.DEFAULT_OUTPUT_DIR,
        "--generated-dir",
        help="Directory containing rendered deployment templates",
    ),
    role: DeployRoleOption = typer.Option(
        DeployRoleOption.all,
        "--role",
        help="Package bundle for ark-rag, ark-llm, or both",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite existing bundle output file",
    ),
    as_json: bool = typer.Option(False, "--json", help="Output API-shaped JSON"),
) -> None:
    """Build a dry-run deployment bundle zip (does not install or mutate the host)."""
    try:
        result = build_deployment_bundle(
            generated_dir,
            output_path=output,
            role=role.value,
            force=force,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if as_json:
        console.print_json(json.dumps(bundle_result_to_dict(result)))
        return

    console.print(f"Output: [bold]{result.output_path}[/bold]")
    console.print(f"Role: {result.role}")
    console.print(f"Entries: {result.entry_count}")
    console.print(f"Size: {result.bundle_size_bytes} bytes")
    console.print(f"Preflight status: [bold]{result.preflight_overall_status}[/bold]")
    console.print(result.message)


@deploy_app.command("verify-bundle")
def deploy_verify_bundle(
    bundle: Path = typer.Option(
        ...,
        "--bundle",
        help="Deployment bundle zip archive to verify",
    ),
    as_json: bool = typer.Option(False, "--json", help="Output API-shaped JSON"),
) -> None:
    """Verify a deployment bundle zip read-only (does not extract or mutate the host)."""
    result = verify_deployment_bundle(bundle)

    if as_json:
        console.print_json(json.dumps(bundle_verify_result_to_dict(result)))
    else:
        console.print(f"Overall status: [bold]{result.overall_status}[/bold]")
        console.print(f"Role: {result.role}")
        console.print(f"Zip entries: {result.entry_count}")
        console.print(f"Manifest entries: {result.manifest_entry_count}")
        table = Table(title="Deployment Bundle Verification")
        table.add_column("Check", style="bold")
        table.add_column("Status")
        table.add_column("Message")
        for check in result.checks:
            table.add_row(check.id, check.status, check.message)
        console.print(table)
        console.print(result.message)

    if result.overall_status == "invalid":
        raise typer.Exit(code=1)


@deploy_app.command("unpack-bundle")
def deploy_unpack_bundle(
    bundle: Path = typer.Option(
        ...,
        "--bundle",
        help="Deployment bundle zip archive to unpack",
    ),
    staging_dir: Path = typer.Option(
        ...,
        "--staging-dir",
        help="Safe staging directory for verified bundle extraction",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Replace existing contents in the staging directory",
    ),
    as_json: bool = typer.Option(False, "--json", help="Output API-shaped JSON"),
) -> None:
    """Verify and unpack a deployment bundle into a staging directory (does not install)."""
    try:
        result = unpack_deployment_bundle(
            bundle,
            staging_dir=staging_dir,
            force=force,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if as_json:
        console.print_json(json.dumps(unpack_result_to_dict(result)))
        return

    console.print(f"Verification status: [bold]{result.verification_status}[/bold]")
    console.print(f"Role: {result.role}")
    console.print(f"Staging directory: {result.staging_dir}")
    console.print(f"Extracted files: {result.extracted_count}")
    for path in result.extracted_files:
        console.print(f"- {path}")
    console.print(result.message)


@app.command()
def preflight(
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON"),
) -> None:
    """Run passive appliance readiness checks (no network calls)."""
    result = ark_preflight.run_preflight(ark_config.get_settings())

    if as_json:
        console.print_json(json.dumps(ark_preflight.preflight_to_dict(result)))
    else:
        console.print(f"Overall status: [bold]{result.overall_status}[/bold]")
        table = Table(title="Appliance Preflight")
        table.add_column("Check", style="bold")
        table.add_column("Status")
        table.add_column("Message")
        for check in result.checks:
            table.add_row(check.id, check.status, check.message)
        console.print(table)

    if result.overall_status == "blocked":
        raise typer.Exit(code=1)


def _resolve_workspace_dir(
    workspace_dir: Path | None,
    settings: ark_config.ArkSettings,
) -> Path:
    if workspace_dir is not None:
        return workspace_dir.expanduser().resolve()
    return settings.workspace_dir.expanduser().resolve()


def _handle_corpus_errors(exc: BaseException) -> None:
    typer.echo(str(exc), err=True)
    raise typer.Exit(code=1) from exc


def _corpus_progress(message: str) -> None:
    typer.echo(message, err=True)


@corpus_app.command("ingest")
def corpus_ingest(
    source: Path = typer.Argument(..., help="JSONL file or directory of .txt files"),
    index: str = typer.Option(..., "--index", help="Destination workspace index slug"),
    workspace_dir: Path | None = typer.Option(
        None,
        "--workspace-dir",
        help="Workspace directory (default: ARK_WORKSPACE_DIR)",
    ),
    batch_size: int = typer.Option(100, "--batch-size", min=1),
    chunk_size: int = typer.Option(1000, "--chunk-size", min=1),
    chunk_overlap: int = typer.Option(200, "--chunk-overlap", min=0),
    backend: IndexBackendOption = typer.Option(
        IndexBackendOption.simple,
        "--backend",
        help="Index backend (simple=lexical, chroma=semantic vectors)",
    ),
    embedding_backend: EmbeddingBackendOption | None = typer.Option(
        None,
        "--embedding-backend",
        help="Embedding backend override for semantic (--backend chroma) ingest",
    ),
    embedding_model_path: Path | None = typer.Option(
        None,
        "--embedding-model-path",
        help="Local embedding model directory for semantic ingest",
    ),
    allow_network: bool = typer.Option(
        False,
        "--allow-network",
        help="Permit remote model resolution during semantic ingest",
    ),
    resume: bool = typer.Option(False, "--resume", help="Resume from checkpoint"),
    run_id: str | None = typer.Option(None, "--run-id", help="Override run identifier"),
    force_rebuild: bool = typer.Option(
        False,
        "--force-rebuild",
        help="Discard run state and destination index",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate and plan without writes"),
    continue_on_error: bool = typer.Option(
        False,
        "--continue-on-error",
        help="Record failures and continue",
    ),
    show_status: bool = typer.Option(
        False,
        "--status",
        help="Show status for this run instead of ingesting",
    ),
    yes: bool = typer.Option(False, "--yes", help="Confirm destructive operations"),
    as_json: bool = typer.Option(False, "--json", help="Output machine-readable JSON"),
) -> None:
    """Ingest a bulk corpus into a named workspace index."""
    settings = ark_config.get_settings()
    resolved_workspace = _resolve_workspace_dir(workspace_dir, settings)

    if show_status:
        try:
            status = get_corpus_status(resolved_workspace, run_id=run_id)
        except CorpusStatusError as exc:
            _handle_corpus_errors(exc)
        if as_json:
            console.print_json(json.dumps(status_result_to_dict(status)))
            return
        table = Table(title="Corpus Run Status")
        table.add_column("Field", style="bold")
        table.add_column("Value")
        table.add_row("Run ID", status.run_id)
        table.add_row("Index", status.index_slug)
        table.add_row("Backend", status.index_backend)
        table.add_row("Status", status.status.value)
        table.add_row("Completed", str(status.records_completed))
        table.add_row("Failed", str(status.records_failed))
        table.add_row("Chunks", str(status.chunks_written))
        if status.embedding_fingerprint is not None:
            table.add_row("Embedding fingerprint", status.embedding_fingerprint[:16] + "...")
            table.add_row("Embedded chunks", str(status.records_embedded))
        if status.progress_percent is not None:
            table.add_row("Progress", f"{status.progress_percent}%")
        table.add_row("Updated", status.updated_at)
        table.add_row("Resume", status.resume_command)
        console.print(table)
        return

    options = CorpusIngestOptions(
        source_path=source,
        index_slug=index,
        workspace_dir=resolved_workspace,
        batch_size=batch_size,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        backend=backend.value,
        resume=resume,
        run_id=run_id,
        force_rebuild=force_rebuild,
        dry_run=dry_run,
        continue_on_error=continue_on_error,
        yes=yes,
        embedding_backend=embedding_backend.value if embedding_backend is not None else None,
        embedding_model_path=embedding_model_path,
        allow_network=allow_network if allow_network else None,
    )

    if dry_run:
        try:
            dry = run_corpus_dry_run(options)
        except CorpusIngestError as exc:
            _handle_corpus_errors(exc)
        if as_json:
            console.print_json(json.dumps(dry_run_result_to_dict(dry)))
            return
        table = Table(title="Corpus Ingest Dry Run")
        table.add_column("Field", style="bold")
        table.add_column("Value")
        table.add_row("Run ID", dry.run_id)
        table.add_row("Index", dry.index_slug)
        table.add_row("Backend", dry.backend)
        table.add_row("Source", dry.source)
        table.add_row("Format", dry.source_format.value)
        table.add_row("Fingerprint", dry.source_fingerprint.fingerprint[:16] + "...")
        if dry.embedding_fingerprint is not None:
            table.add_row("Embedding fingerprint", dry.embedding_fingerprint[:16] + "...")
        if dry.estimated_records is not None:
            table.add_row("Estimated records", str(dry.estimated_records))
        table.add_row("Run directory", str(dry.run_dir))
        table.add_row("Batch size", str(dry.batch_size))
        console.print(table)
        return

    try:
        result = run_corpus_ingest(
            options,
            progress_callback=_corpus_progress if not as_json else None,
        )
    except CorpusIngestInterrupted as exc:
        result = exc.result
        if as_json:
            console.print_json(json.dumps(ingest_result_to_dict(result)))
        else:
            typer.echo(result.message, err=True)
        raise typer.Exit(code=2) from exc
    except CorpusIngestError as exc:
        _handle_corpus_errors(exc)

    if as_json:
        console.print_json(json.dumps(ingest_result_to_dict(result)))
    else:
        table = Table(title="Corpus Ingest Summary")
        table.add_column("Field", style="bold")
        table.add_column("Value")
        table.add_row("Run ID", result.run_id)
        table.add_row("Index", result.index_slug)
        table.add_row("Backend", result.index_backend)
        table.add_row("Status", result.status.value)
        table.add_row("Documents completed", str(result.records_completed))
        table.add_row("Documents failed", str(result.records_failed))
        table.add_row("Documents skipped", str(result.records_skipped))
        table.add_row("Chunks written", str(result.chunks_written))
        if result.embedding_fingerprint is not None:
            table.add_row("Embedding fingerprint", result.embedding_fingerprint[:16] + "...")
            table.add_row("Chunks embedded", str(result.records_embedded))
        table.add_row("Elapsed (s)", f"{result.elapsed_seconds:.1f}")
        table.add_row("Checkpoint", str(result.checkpoint_path))
        if result.partial:
            table.add_row("Resume", result.resume_command)
        console.print(table)

    if result.partial or result.records_failed > 0:
        raise typer.Exit(code=2)
    if result.status.value in ("interrupted", "failed"):
        raise typer.Exit(code=2)


@corpus_app.command("status")
def corpus_status(
    workspace_dir: Path | None = typer.Option(
        None,
        "--workspace-dir",
        help="Workspace directory (default: ARK_WORKSPACE_DIR)",
    ),
    run_id: str | None = typer.Option(None, "--run-id", help="Corpus run identifier"),
    as_json: bool = typer.Option(False, "--json", help="Output machine-readable JSON"),
) -> None:
    """Show read-only status for a corpus ingest run."""
    settings = ark_config.get_settings()
    resolved_workspace = _resolve_workspace_dir(workspace_dir, settings)
    try:
        status = get_corpus_status(resolved_workspace, run_id=run_id)
    except CorpusStatusError as exc:
        _handle_corpus_errors(exc)

    if as_json:
        console.print_json(json.dumps(status_result_to_dict(status)))
        return

    table = Table(title="Corpus Run Status")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Run ID", status.run_id)
    table.add_row("Source", status.source)
    table.add_row("Index", status.index_slug)
    table.add_row("Backend", status.index_backend)
    table.add_row("Status", status.status.value)
    table.add_row("Seen", str(status.records_seen))
    table.add_row("Completed", str(status.records_completed))
    table.add_row("Failed", str(status.records_failed))
    table.add_row("Chunks", str(status.chunks_written))
    if status.embedding_fingerprint is not None:
        table.add_row("Embedding fingerprint", status.embedding_fingerprint[:16] + "...")
        table.add_row("Embedded chunks", str(status.records_embedded))
        table.add_row("Committed batches", str(status.committed_batches))
    if status.progress_percent is not None:
        table.add_row("Progress", f"{status.progress_percent}%")
    table.add_row("Updated", status.updated_at)
    table.add_row("Resume", status.resume_command)
    console.print(table)


@corpus_app.command("prepare-wikipedia")
def corpus_prepare_wikipedia(
    input_path: Path = typer.Argument(..., help="Local MediaWiki XML, .xml.gz, or .xml.bz2 dump"),
    output: Path = typer.Option(..., "--output", help="Final canonical JSONL output path"),
    project: str = typer.Option("simplewiki", "--project", help="Source project identifier"),
    base_url: str = typer.Option(
        "https://simple.wikipedia.org/wiki/",
        "--base-url",
        help="Base article URL for provenance",
    ),
    source_url: str | None = typer.Option(
        None,
        "--source-url",
        help="Original URL from which the dump was obtained",
    ),
    dump_date: str | None = typer.Option(None, "--dump-date", help="Known dump date (YYYYMMDD)"),
    namespace: list[int] = typer.Option(
        [0],
        "--namespace",
        help="Include only selected MediaWiki namespaces (repeatable)",
    ),
    include_redirects: bool = typer.Option(
        False,
        "--include-redirects",
        help="Emit redirect pages instead of skipping them",
    ),
    min_text_chars: int = typer.Option(
        100,
        "--min-text-chars",
        min=0,
        help="Skip normalized articles shorter than this threshold",
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        min=1,
        help="Stop after emitting this many records",
    ),
    resume: bool = typer.Option(False, "--resume", help="Resume a compatible interrupted run"),
    force: bool = typer.Option(
        False,
        "--force",
        help="Replace existing output and preparation state",
    ),
    yes: bool = typer.Option(False, "--yes", help="Confirm destructive --force without prompt"),
    checkpoint_every: int = typer.Option(
        1000,
        "--checkpoint-every",
        min=1,
        help="Persist preparation state after this many scanned pages",
    ),
    continue_on_page_error: bool = typer.Option(
        False,
        "--continue-on-page-error",
        help="Record page errors and continue processing",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate source and print plan only"),
    expected_sha1: str | None = typer.Option(
        None,
        "--expected-sha1",
        help="Verify compressed dump SHA-1 before processing",
    ),
    expected_sha256: str | None = typer.Option(
        None,
        "--expected-sha256",
        help="Verify compressed dump SHA-256 before processing",
    ),
    checksum_file: Path | None = typer.Option(
        None,
        "--checksum-file",
        help="Wikimedia-style checksum list matching input basename",
    ),
    as_json: bool = typer.Option(False, "--json", help="Output machine-readable JSON"),
) -> None:
    """Normalize a local MediaWiki pages-articles dump to canonical corpus JSONL."""
    options = PrepareWikipediaOptions(
        input_path=input_path,
        output_path=output,
        project=project,
        base_url=base_url,
        source_url=source_url,
        dump_date=dump_date,
        namespace_filters=tuple(namespace),
        include_redirects=include_redirects,
        min_text_chars=min_text_chars,
        limit=limit,
        resume=resume,
        force=force,
        yes=yes,
        checkpoint_every=checkpoint_every,
        continue_on_page_error=continue_on_page_error,
        dry_run=dry_run,
        expected_sha1=expected_sha1,
        expected_sha256=expected_sha256,
        checksum_file=checksum_file,
    )

    if dry_run:
        try:
            dry = run_prepare_wikipedia_dry_run(options)
        except WikipediaPrepareError as exc:
            _handle_corpus_errors(exc)
        if as_json:
            console.print_json(json.dumps(prepare_dry_run_result_to_dict(dry)))
            return
        table = Table(title="Wikipedia Preparation Dry Run")
        table.add_column("Field", style="bold")
        table.add_column("Value")
        table.add_row("Input", dry.input_path)
        table.add_row("Output", dry.output_path)
        table.add_row("Project", dry.project)
        table.add_row("Namespaces", ", ".join(str(n) for n in dry.namespace_filters))
        table.add_row("Fingerprint", dry.input_fingerprint.sha256[:16] + "...")
        table.add_row("Checkpoint", str(dry.checkpoint_path))
        table.add_row("Message", dry.message)
        console.print(table)
        return

    try:
        result = run_prepare_wikipedia(
            options,
            progress_callback=_corpus_progress if not as_json else None,
        )
    except WikipediaPrepareInterrupted as exc:
        result = exc.result
        if as_json:
            console.print_json(json.dumps(prepare_wikipedia_result_to_dict(result)))
        else:
            typer.echo(result.message, err=True)
        raise typer.Exit(code=2) from exc
    except WikipediaPrepareError as exc:
        _handle_corpus_errors(exc)

    if as_json:
        console.print_json(json.dumps(prepare_wikipedia_result_to_dict(result)))
    else:
        table = Table(title="Wikipedia Preparation Summary")
        table.add_column("Field", style="bold")
        table.add_column("Value")
        table.add_row("Input", result.input_path)
        table.add_row("Output", result.output_path)
        table.add_row("Project", result.project)
        table.add_row("Status", result.status.value)
        table.add_row("Pages scanned", str(result.pages_scanned))
        table.add_row("Records emitted", str(result.records_emitted))
        table.add_row("Redirects skipped", str(result.redirects_skipped))
        table.add_row("Namespace skipped", str(result.namespace_pages_skipped))
        table.add_row("Short pages skipped", str(result.short_pages_skipped))
        table.add_row("Page errors", str(result.page_errors))
        table.add_row("Elapsed (s)", f"{result.elapsed_seconds:.1f}")
        table.add_row("Checkpoint", str(result.checkpoint_path))
        if result.manifest_path is not None:
            table.add_row("Manifest", str(result.manifest_path))
        if result.partial:
            table.add_row("Resume", result.resume_command)
        else:
            table.add_row("Ingest", result.ingest_command)
        console.print(table)

    if result.partial or result.page_errors > 0:
        raise typer.Exit(code=2)
    if result.status.value in ("interrupted", "failed"):
        raise typer.Exit(code=2)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
