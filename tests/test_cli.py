import pytest
from pathlib import Path
from typer.testing import CliRunner

from ark_pi.cli import app

runner = CliRunner()

def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.stdout


def test_status_dev_role() -> None:
    result = runner.invoke(app, ["status"], env={"ARK_ROLE": "dev"})
    assert result.exit_code == 0
    assert "dev" in result.stdout
    assert "indexes/chroma" in result.stdout


@pytest.mark.parametrize("role", ["rag", "llm"])
def test_status_role(role: str) -> None:
    result = runner.invoke(app, ["status"], env={"ARK_ROLE": role})
    assert result.exit_code == 0
    assert role in result.stdout


def test_config_cmd() -> None:
    result = runner.invoke(app, ["config"], env={"ARK_ROLE": "dev"})
    assert result.exit_code == 0
    assert "role" in result.stdout
    assert "indexes/chroma" in result.stdout


def test_workspace_ingest_path_help() -> None:
    result = runner.invoke(app, ["workspace", "ingest-path", "--help"])
    assert result.exit_code == 0
    assert "--source" in result.stdout
    assert "--index-name" in result.stdout


def test_workspace_ingest_path_happy_path(tmp_path: Path) -> None:
    source_dir = tmp_path / "sources"
    workspace_dir = tmp_path / "workspace"
    source_dir.mkdir()
    (source_dir / "sample.txt").write_text(
        "Ark Pi can ingest local text files.\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "workspace",
            "ingest-path",
            "--source",
            "sample.txt",
            "--index-name",
            "local-sample",
        ],
        env={
            "ARK_SOURCE_DIR": str(source_dir),
            "ARK_WORKSPACE_DIR": str(workspace_dir),
        },
    )
    assert result.exit_code == 0
    assert "local-sample" in result.stdout
    assert (workspace_dir / "catalog.json").is_file()


def test_workspace_ingest_path_outside_source_dir_exits_nonzero(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "sources"
    workspace_dir = tmp_path / "workspace"
    source_dir.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("Outside content.", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "workspace",
            "ingest-path",
            "--source",
            str(outside),
            "--index-name",
            "bad",
        ],
        env={
            "ARK_SOURCE_DIR": str(source_dir),
            "ARK_WORKSPACE_DIR": str(workspace_dir),
        },
    )
    assert result.exit_code != 0
    assert "inside configured source_dir" in result.stderr or "inside configured source_dir" in result.stdout
