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
from ark_pi.deploy import templates as deploy_templates
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
app.add_typer(ingest_app, name="ingest")
app.add_typer(index_app, name="index")
app.add_typer(workspace_app, name="workspace")
app.add_typer(llm_app, name="llm")
app.add_typer(deploy_app, name="deploy")
console = Console()


class LlmBackendOption(str, Enum):
    mock = "mock"
    openai_compatible = "openai-compatible"


class IndexBackendOption(str, Enum):
    simple = "simple"
    chroma = "chroma"


class DeployRoleOption(str, Enum):
    rag = "rag"
    llm = "llm"
    all = "all"


def _handle_index_errors(exc: BaseException) -> None:
    typer.echo(str(exc), err=True)
    raise typer.Exit(code=1) from exc


def _handle_workspace_errors(exc: BaseException) -> None:
    typer.echo(str(exc), err=True)
    raise typer.Exit(code=1) from exc


def _handle_llm_errors(exc: BaseException) -> None:
    typer.echo(str(exc), err=True)
    raise typer.Exit(code=1) from exc


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
    as_json: bool = typer.Option(False, "--json", help="Output API-shaped JSON"),
) -> None:
    """Render ark-rag and ark-llm env/systemd templates for review (does not install)."""
    try:
        result = deploy_templates.render_deployment_templates(
            output_dir,
            role=role.value,
            force=force,
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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
