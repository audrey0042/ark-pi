import json
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ark_pi.cli import app
from ark_pi.deploy.templates import render_deployment_templates

runner = CliRunner()


@pytest.fixture
def rendered_dir(tmp_path: Path) -> Path:
    render_deployment_templates(tmp_path, force=True)
    return tmp_path


def test_deploy_bundle_help() -> None:
    result = runner.invoke(app, ["deploy", "bundle", "--help"])
    assert result.exit_code == 0
    assert "--generated-dir" in result.stdout
    assert "--output" in result.stdout
    assert "--role" in result.stdout
    assert "--force" in result.stdout
    assert "--json" in result.stdout


def test_deploy_bundle_after_render_exits_zero(rendered_dir: Path, tmp_path: Path) -> None:
    output = tmp_path / "bundle.zip"
    result = runner.invoke(
        app,
        [
            "deploy",
            "bundle",
            "--generated-dir",
            str(rendered_dir),
            "--output",
            str(output),
            "--force",
        ],
    )

    assert result.exit_code == 0
    assert output.is_file()
    assert "Preflight status" in result.stdout


def test_deploy_bundle_role_rag_exits_zero_and_contains_rag_only(
    rendered_dir: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "bundle-rag.zip"
    result = runner.invoke(
        app,
        [
            "deploy",
            "bundle",
            "--generated-dir",
            str(rendered_dir),
            "--output",
            str(output),
            "--role",
            "rag",
            "--force",
        ],
    )

    assert result.exit_code == 0
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
    assert "templates/ark-rag.env" in names
    assert "templates/ark-rag.service" in names
    assert "templates/ark-llm.env" not in names
    assert "templates/ark-llm.service" not in names


def test_deploy_bundle_role_llm_exits_zero_and_contains_llm_only(
    rendered_dir: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "bundle-llm.zip"
    result = runner.invoke(
        app,
        [
            "deploy",
            "bundle",
            "--generated-dir",
            str(rendered_dir),
            "--output",
            str(output),
            "--role",
            "llm",
            "--force",
        ],
    )

    assert result.exit_code == 0
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
    assert "templates/ark-llm.env" in names
    assert "templates/ark-llm.service" in names
    assert "templates/ark-rag.env" not in names
    assert "templates/ark-rag.service" not in names


def test_deploy_bundle_json_outputs_parseable_json(rendered_dir: Path, tmp_path: Path) -> None:
    output = tmp_path / "bundle.zip"
    result = runner.invoke(
        app,
        [
            "deploy",
            "bundle",
            "--generated-dir",
            str(rendered_dir),
            "--output",
            str(output),
            "--force",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["output_path"] == str(output.resolve())
    assert payload["role"] == "all"
    assert payload["entry_count"] == 9
    assert payload["preflight_overall_status"] in {"ready", "warning"}


def test_second_output_without_force_exits_nonzero(rendered_dir: Path, tmp_path: Path) -> None:
    output = tmp_path / "bundle.zip"
    first = runner.invoke(
        app,
        [
            "deploy",
            "bundle",
            "--generated-dir",
            str(rendered_dir),
            "--output",
            str(output),
            "--force",
        ],
    )
    assert first.exit_code == 0

    second = runner.invoke(
        app,
        [
            "deploy",
            "bundle",
            "--generated-dir",
            str(rendered_dir),
            "--output",
            str(output),
        ],
    )

    assert second.exit_code == 1
    assert "Refusing to overwrite" in second.stderr


def test_second_output_with_force_succeeds(rendered_dir: Path, tmp_path: Path) -> None:
    output = tmp_path / "bundle.zip"
    runner.invoke(
        app,
        [
            "deploy",
            "bundle",
            "--generated-dir",
            str(rendered_dir),
            "--output",
            str(output),
            "--force",
        ],
    )

    result = runner.invoke(
        app,
        [
            "deploy",
            "bundle",
            "--generated-dir",
            str(rendered_dir),
            "--output",
            str(output),
            "--force",
        ],
    )

    assert result.exit_code == 0


def test_missing_generated_dir_exits_nonzero(tmp_path: Path) -> None:
    missing = tmp_path / "missing-generated"
    output = tmp_path / "bundle.zip"
    result = runner.invoke(
        app,
        [
            "deploy",
            "bundle",
            "--generated-dir",
            str(missing),
            "--output",
            str(output),
            "--force",
        ],
    )

    assert result.exit_code == 1
    assert "deployment preflight is blocked" in result.stderr
