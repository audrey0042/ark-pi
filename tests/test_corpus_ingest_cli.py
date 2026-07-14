import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ark_pi.cli import app
from ark_pi.config import clear_settings_cache

runner = CliRunner()


@pytest.fixture
def corpus_cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    jsonl_path = tmp_path / "corpus.jsonl"
    jsonl_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {"id": "one", "title": "First", "text": "The first local article."}
                ),
                json.dumps(
                    {"id": "two", "title": "Second", "text": "The second local article."}
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(workspace_dir))
    clear_settings_cache()
    yield workspace_dir, jsonl_path
    clear_settings_cache()


def test_corpus_ingest_help() -> None:
    result = runner.invoke(app, ["corpus", "ingest", "--help"])
    assert result.exit_code == 0
    assert "--index" in result.stdout
    assert "--resume" in result.stdout
    assert "--batch-size" in result.stdout


def test_corpus_status_help() -> None:
    result = runner.invoke(app, ["corpus", "status", "--help"])
    assert result.exit_code == 0
    assert "--json" in result.stdout
    assert "--run-id" in result.stdout


def test_corpus_ingest_jsonl_smoke(corpus_cli_env: tuple[Path, Path]) -> None:
    workspace_dir, jsonl_path = corpus_cli_env
    result = runner.invoke(
        app,
        [
            "corpus",
            "ingest",
            str(jsonl_path),
            "--index",
            "corpus-smoke",
            "--workspace-dir",
            str(workspace_dir),
            "--batch-size",
            "1",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "corpus-smoke" in result.stdout


def test_corpus_status_json(corpus_cli_env: tuple[Path, Path]) -> None:
    workspace_dir, jsonl_path = corpus_cli_env
    ingest = runner.invoke(
        app,
        [
            "corpus",
            "ingest",
            str(jsonl_path),
            "--index",
            "corpus-smoke",
            "--workspace-dir",
            str(workspace_dir),
            "--batch-size",
            "1",
        ],
    )
    assert ingest.exit_code == 0

    result = runner.invoke(
        app,
        [
            "corpus",
            "status",
            "--workspace-dir",
            str(workspace_dir),
            "--json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["index_slug"] == "corpus-smoke"
    assert payload["status"] == "completed"
    assert "resume_command" in payload


def test_corpus_dry_run_no_writes(corpus_cli_env: tuple[Path, Path]) -> None:
    workspace_dir, jsonl_path = corpus_cli_env
    result = runner.invoke(
        app,
        [
            "corpus",
            "ingest",
            str(jsonl_path),
            "--index",
            "corpus-smoke",
            "--workspace-dir",
            str(workspace_dir),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert not (workspace_dir / "indexes").exists()


def test_corpus_ingest_json_stdout_only(corpus_cli_env: tuple[Path, Path]) -> None:
    workspace_dir, jsonl_path = corpus_cli_env
    result = runner.invoke(
        app,
        [
            "corpus",
            "ingest",
            str(jsonl_path),
            "--index",
            "corpus-smoke",
            "--workspace-dir",
            str(workspace_dir),
            "--batch-size",
            "1",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["index_slug"] == "corpus-smoke"
    assert payload["records_completed"] == 2


def test_corpus_search_after_ingest(corpus_cli_env: tuple[Path, Path]) -> None:
    workspace_dir, jsonl_path = corpus_cli_env
    ingest = runner.invoke(
        app,
        [
            "corpus",
            "ingest",
            str(jsonl_path),
            "--index",
            "corpus-smoke",
            "--workspace-dir",
            str(workspace_dir),
            "--batch-size",
            "1",
        ],
    )
    assert ingest.exit_code == 0

    index_dir = workspace_dir / "indexes" / "corpus-smoke" / "index"
    search = runner.invoke(
        app,
        [
            "index",
            "search",
            "--index-dir",
            str(index_dir),
            "--query",
            "second local article",
        ],
    )
    assert search.exit_code == 0
    assert "second" in search.stdout.lower()


def test_malformed_jsonl_cli_fails(corpus_cli_env: tuple[Path, Path]) -> None:
    workspace_dir, jsonl_path = corpus_cli_env
    jsonl_path.write_text('{"title":"X","text":"ok"}\n{broken\n', encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "corpus",
            "ingest",
            str(jsonl_path),
            "--index",
            "corpus-smoke",
            "--workspace-dir",
            str(workspace_dir),
        ],
    )
    assert result.exit_code != 0
    assert "line 2" in result.stderr or "line 2" in result.stdout


def test_force_rebuild_requires_yes(corpus_cli_env: tuple[Path, Path]) -> None:
    workspace_dir, jsonl_path = corpus_cli_env
    runner.invoke(
        app,
        [
            "corpus",
            "ingest",
            str(jsonl_path),
            "--index",
            "corpus-smoke",
            "--workspace-dir",
            str(workspace_dir),
        ],
    )
    result = runner.invoke(
        app,
        [
            "corpus",
            "ingest",
            str(jsonl_path),
            "--index",
            "corpus-smoke",
            "--workspace-dir",
            str(workspace_dir),
            "--force-rebuild",
        ],
    )
    assert result.exit_code != 0
    assert "--yes" in result.stderr or "--yes" in result.stdout
