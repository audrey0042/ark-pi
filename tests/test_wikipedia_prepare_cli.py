"""CLI tests for Wikipedia dump preparation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ark_pi.cli import app
from tests.mediawiki_fixtures import ensure_compressed_fixtures

runner = CliRunner()


@pytest.fixture
def prepare_cli_env(tmp_path: Path) -> dict[str, Path]:
    paths = ensure_compressed_fixtures(tmp_path)
    output = tmp_path / "articles.jsonl"
    return {**paths, "output": output}


def test_prepare_wikipedia_help() -> None:
    result = runner.invoke(app, ["corpus", "prepare-wikipedia", "--help"])
    assert result.exit_code == 0
    assert "--output" in result.stdout
    assert "--resume" in result.stdout
    assert "--namespace" in result.stdout
    assert "--json" in result.stdout


def test_prepare_wikipedia_json_output(prepare_cli_env: dict[str, Path]) -> None:
    result = runner.invoke(
        app,
        [
            "corpus",
            "prepare-wikipedia",
            str(prepare_cli_env["plain"]),
            "--output",
            str(prepare_cli_env["output"]),
            "--min-text-chars",
            "50",
            "--checkpoint-every",
            "1",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["records_emitted"] == 1
    assert payload["ingest_command"].startswith("ark corpus ingest")


def test_prepare_wikipedia_dry_run(prepare_cli_env: dict[str, Path]) -> None:
    result = runner.invoke(
        app,
        [
            "corpus",
            "prepare-wikipedia",
            str(prepare_cli_env["plain"]),
            "--output",
            str(prepare_cli_env["output"]),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert not prepare_cli_env["output"].exists()


def test_prepare_wikipedia_force_requires_yes(prepare_cli_env: dict[str, Path]) -> None:
    first = runner.invoke(
        app,
        [
            "corpus",
            "prepare-wikipedia",
            str(prepare_cli_env["plain"]),
            "--output",
            str(prepare_cli_env["output"]),
            "--min-text-chars",
            "50",
            "--checkpoint-every",
            "1",
        ],
    )
    assert first.exit_code == 0
    second = runner.invoke(
        app,
        [
            "corpus",
            "prepare-wikipedia",
            str(prepare_cli_env["plain"]),
            "--output",
            str(prepare_cli_env["output"]),
            "--force",
        ],
    )
    assert second.exit_code == 1
    assert "--yes" in second.stderr or "--yes" in second.stdout


def test_prepare_wikipedia_bzip2_smoke(prepare_cli_env: dict[str, Path]) -> None:
    result = runner.invoke(
        app,
        [
            "corpus",
            "prepare-wikipedia",
            str(prepare_cli_env["bzip2"]),
            "--output",
            str(prepare_cli_env["output"]),
            "--limit",
            "1",
            "--min-text-chars",
            "50",
            "--checkpoint-every",
            "1",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert prepare_cli_env["output"].is_file()
