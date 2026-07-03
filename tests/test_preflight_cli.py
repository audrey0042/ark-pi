import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ark_pi.cli import app
from ark_pi.config import clear_settings_cache

runner = CliRunner()


@pytest.fixture
def env_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    source = tmp_path / "sources"
    workspace.mkdir()
    source.mkdir()
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("ARK_SOURCE_DIR", str(source))
    monkeypatch.setenv("ARK_LLM_BACKEND", "mock")
    monkeypatch.setenv("ARK_INDEX_BACKEND", "simple")
    clear_settings_cache()
    yield workspace, source
    clear_settings_cache()


def test_preflight_help() -> None:
    result = runner.invoke(app, ["preflight", "--help"])
    assert result.exit_code == 0
    assert "--json" in result.stdout


def test_preflight_exits_zero_for_warning_only_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(tmp_path / "missing-workspace"))
    monkeypatch.setenv("ARK_SOURCE_DIR", str(tmp_path / "missing-sources"))
    monkeypatch.setenv("ARK_LLM_BACKEND", "mock")
    clear_settings_cache()

    result = runner.invoke(app, ["preflight"])
    assert result.exit_code == 0
    assert "warning" in result.stdout.lower()


def test_preflight_exits_nonzero_for_blocked_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "catalog.json").write_text("{bad", encoding="utf-8")
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("ARK_SOURCE_DIR", str(tmp_path / "sources"))
    clear_settings_cache()

    result = runner.invoke(app, ["preflight"])
    assert result.exit_code != 0
    assert "blocked" in result.stdout.lower()


def test_preflight_json_outputs_parseable_json(env_paths: tuple[Path, Path]) -> None:
    result = runner.invoke(app, ["preflight", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert "overall_status" in data
    assert "checks" in data
