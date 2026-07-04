from pathlib import Path

import json

import pytest
from typer.testing import CliRunner

from ark_pi.cli import app
from ark_pi.deploy.templates import render_deployment_templates

runner = CliRunner()


@pytest.fixture
def rendered_dir(tmp_path: Path) -> Path:
    render_deployment_templates(tmp_path, force=True)
    return tmp_path


def test_deploy_preflight_help() -> None:
    result = runner.invoke(app, ["deploy", "preflight", "--help"])
    assert result.exit_code == 0
    assert "--generated-dir" in result.stdout
    assert "--role" in result.stdout
    assert "--json" in result.stdout


def test_deploy_preflight_after_render_exits_zero_for_warning_only(
    rendered_dir: Path,
) -> None:
    result = runner.invoke(
        app,
        ["deploy", "preflight", "--generated-dir", str(rendered_dir)],
    )

    assert result.exit_code == 0
    assert "warning" in result.stdout.lower() or "ready" in result.stdout.lower()


def test_deploy_preflight_missing_generated_dir_exits_nonzero(tmp_path: Path) -> None:
    missing = tmp_path / "missing-generated"

    result = runner.invoke(
        app,
        ["deploy", "preflight", "--generated-dir", str(missing)],
    )

    assert result.exit_code != 0
    assert "blocked" in result.stdout.lower()


def test_deploy_preflight_role_rag_works(rendered_dir: Path) -> None:
    result = runner.invoke(
        app,
        [
            "deploy",
            "preflight",
            "--generated-dir",
            str(rendered_dir),
            "--role",
            "rag",
        ],
    )

    assert result.exit_code == 0
    assert "rag_ark_binary" in result.stdout


def test_deploy_preflight_role_llm_works(rendered_dir: Path) -> None:
    result = runner.invoke(
        app,
        [
            "deploy",
            "preflight",
            "--generated-dir",
            str(rendered_dir),
            "--role",
            "llm",
        ],
    )

    assert result.exit_code == 0
    assert "llm_port" in result.stdout


def test_deploy_preflight_json_outputs_parseable_json(rendered_dir: Path) -> None:
    result = runner.invoke(
        app,
        [
            "deploy",
            "preflight",
            "--generated-dir",
            str(rendered_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert "overall_status" in data
    assert "checks" in data
    assert data["host_mutations_performed"] is False
