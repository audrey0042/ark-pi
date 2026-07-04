import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ark_pi.cli import app
from ark_pi.config import clear_settings_cache
from ark_pi.init import SAMPLE_SOURCE_FILENAME

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


def test_init_help() -> None:
    result = runner.invoke(app, ["init", "--help"])
    assert result.exit_code == 0
    assert "--sample" in result.stdout
    assert "--no-catalog" in result.stdout
    assert "--force" in result.stdout
    assert "--json" in result.stdout


def test_init_succeeds_and_creates_directories(
    unset_env: tuple[Path, Path],
) -> None:
    workspace, source = unset_env

    result = runner.invoke(app, ["init"])

    assert result.exit_code == 0
    assert workspace.is_dir()
    assert (workspace / "indexes").is_dir()
    assert source.is_dir()
    assert "Preflight status" in result.stdout


def test_init_sample_creates_sample_source(unset_env: tuple[Path, Path]) -> None:
    _workspace, source = unset_env

    result = runner.invoke(app, ["init", "--sample"])

    assert result.exit_code == 0
    assert (source / SAMPLE_SOURCE_FILENAME).is_file()
    assert "Sample source" in result.stdout


def test_init_json_outputs_parseable_json(unset_env: tuple[Path, Path]) -> None:
    result = runner.invoke(app, ["init", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert "created_paths" in data
    assert "preflight" in data
    assert "overall_status" in data["preflight"]


def test_init_invalid_catalog_without_force_exits_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "catalog.json").write_text("{bad", encoding="utf-8")
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("ARK_SOURCE_DIR", str(tmp_path / "sources"))
    clear_settings_cache()

    result = runner.invoke(app, ["init"])

    assert result.exit_code != 0
    assert "Invalid workspace catalog" in (result.stdout + result.stderr)
