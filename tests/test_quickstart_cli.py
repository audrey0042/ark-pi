import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ark_pi.cli import app
from ark_pi.config import clear_settings_cache
from ark_pi.quickstart import DEFAULT_INDEX_NAME

runner = CliRunner()


@pytest.fixture
def unset_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    source = tmp_path / "sources"
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("ARK_SOURCE_DIR", str(source))
    monkeypatch.setenv("ARK_LLM_BACKEND", "mock")
    monkeypatch.setenv("ARK_INDEX_BACKEND", "simple")
    clear_settings_cache()
    yield workspace, source
    clear_settings_cache()


def test_quickstart_help() -> None:
    result = runner.invoke(app, ["quickstart", "--help"])
    assert result.exit_code == 0
    assert "--index-name" in result.stdout
    assert "--question" in result.stdout
    assert "--force" in result.stdout
    assert "--json" in result.stdout


def test_quickstart_succeeds_with_defaults(unset_env: tuple[Path, Path]) -> None:
    workspace, _source = unset_env

    result = runner.invoke(app, ["quickstart"])

    assert result.exit_code == 0
    assert DEFAULT_INDEX_NAME in result.stdout
    assert "Mock LLM backend" in result.stdout
    assert "Preflight status" in result.stdout
    assert (workspace / "catalog.json").is_file()


def test_quickstart_json_outputs_parseable_json(unset_env: tuple[Path, Path]) -> None:
    result = runner.invoke(app, ["quickstart", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["index_name"] == DEFAULT_INDEX_NAME
    assert "ask_answer" in data
    assert "preflight" in data


def test_quickstart_second_run_without_force_exits_nonzero(
    unset_env: tuple[Path, Path],
) -> None:
    first = runner.invoke(app, ["quickstart"])
    assert first.exit_code == 0

    second = runner.invoke(app, ["quickstart"])
    assert second.exit_code != 0
    assert "Index already exists" in (second.stdout + second.stderr)


def test_quickstart_with_force_succeeds(unset_env: tuple[Path, Path]) -> None:
    first = runner.invoke(app, ["quickstart"])
    assert first.exit_code == 0

    second = runner.invoke(app, ["quickstart", "--force"])
    assert second.exit_code == 0
    assert "Mock LLM backend" in second.stdout
