import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ark_pi import __version__
from ark_pi import config as ark_config
from ark_pi.ingest import chunking, sources as ingest_sources
from ark_pi.rag import dev_answer, prompting
from ark_pi.rag import index as rag_index

app = typer.Typer(name="ark", help="Ark Pi — offline/local RAG appliance")
ingest_app = typer.Typer(help="Document ingestion commands")
index_app = typer.Typer(help="Local index commands")
app.add_typer(ingest_app, name="ingest")
app.add_typer(index_app, name="index")
console = Console()


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
    force: bool = typer.Option(False, "--force", help="Overwrite a non-empty index directory"),
) -> None:
    """Build a local searchable index from chunk JSONL."""
    try:
        stats = rag_index.build_index(chunks_path, index_dir, force=force)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except FileExistsError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    table = Table(title="Index Build Summary")
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_row("backend", stats.backend)
    table.add_row("chunks", str(stats.chunk_count))
    table.add_row("index_dir", str(stats.index_dir))
    console.print(table)


@index_app.command("stats")
def index_stats_cmd(
    index_dir: Path = typer.Option(
        ...,
        "--index-dir",
        help="Path to a built index directory",
        exists=False,
    ),
) -> None:
    """Print index manifest details."""
    try:
        stats = rag_index.index_stats(index_dir)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

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
    limit: int = typer.Option(5, "--limit", min=1),
) -> None:
    """Search a local index using lexical token overlap."""
    try:
        results = rag_index.search_index(index_dir, query, limit=limit)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

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
) -> None:
    """Search the local index, assemble a prompt, and return a dev/mock answer."""
    stripped_question = question.strip()
    if not stripped_question:
        typer.echo("Question must not be empty.", err=True)
        raise typer.Exit(code=1)

    try:
        results = rag_index.search_index(index_dir, stripped_question, limit=limit)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if not results:
        console.print("No relevant context found.")
        return

    prompt = prompting.build_rag_prompt(stripped_question, results)
    answer = dev_answer.make_dev_answer(stripped_question, results, prompt)

    console.print(f"Question: {stripped_question}")
    console.print()
    console.print(answer)
    console.print()
    console.print(f"Retrieved chunks: {len(results)}")

    if show_context:
        table = Table(title=f"Retrieved Context ({len(results)})")
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

    if show_prompt:
        console.print(Panel(prompt, title="Assembled Prompt", expand=False))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
