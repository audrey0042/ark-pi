import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ark_pi import __version__
from ark_pi import config as ark_config
from ark_pi.ingest import chunking, sources as ingest_sources

app = typer.Typer(name="ark", help="Ark Pi — offline/local RAG appliance")
ingest_app = typer.Typer(help="Document ingestion commands")
app.add_typer(ingest_app, name="ingest")
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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
