import json
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


def test_deploy_plan_help() -> None:
    result = runner.invoke(app, ["deploy", "plan", "--help"])
    assert result.exit_code == 0
    assert "--generated-dir" in result.stdout
    assert "--role" in result.stdout
    assert "--format" in result.stdout
    assert "--output" in result.stdout
    assert "--force" in result.stdout


def test_deploy_plan_after_render_exits_zero(rendered_dir: Path) -> None:
    result = runner.invoke(
        app,
        ["deploy", "plan", "--generated-dir", str(rendered_dir)],
    )

    assert result.exit_code == 0
    assert "Planned file copies" in result.stdout
    assert "Manual commands" in result.stdout


def test_deploy_plan_role_rag_exits_zero_and_mentions_ark_rag(rendered_dir: Path) -> None:
    result = runner.invoke(
        app,
        [
            "deploy",
            "plan",
            "--generated-dir",
            str(rendered_dir),
            "--role",
            "rag",
        ],
    )

    assert result.exit_code == 0
    assert "copy_rag_env" in result.stdout
    assert "ark-rag" in result.stdout


def test_deploy_plan_role_llm_exits_zero_and_mentions_ark_llm(rendered_dir: Path) -> None:
    result = runner.invoke(
        app,
        [
            "deploy",
            "plan",
            "--generated-dir",
            str(rendered_dir),
            "--role",
            "llm",
        ],
    )

    assert result.exit_code == 0
    assert "copy_llm_env" in result.stdout
    assert "ark-llm" in result.stdout


def test_deploy_plan_format_markdown_outputs_markdown(rendered_dir: Path) -> None:
    result = runner.invoke(
        app,
        [
            "deploy",
            "plan",
            "--generated-dir",
            str(rendered_dir),
            "--format",
            "markdown",
        ],
    )

    assert result.exit_code == 0
    assert "# Ark Pi Deployment Install Plan" in result.stdout
    assert "Dry-run safety" in result.stdout


def test_deploy_plan_format_json_outputs_parseable_json(rendered_dir: Path) -> None:
    result = runner.invoke(
        app,
        [
            "deploy",
            "plan",
            "--generated-dir",
            str(rendered_dir),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["dry_run"] is True
    assert "copy_steps" in data


def test_deploy_plan_markdown_output_writes_file(rendered_dir: Path, tmp_path: Path) -> None:
    output = tmp_path / "plan.md"
    result = runner.invoke(
        app,
        [
            "deploy",
            "plan",
            "--generated-dir",
            str(rendered_dir),
            "--format",
            "markdown",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert output.is_file()
    assert "Deployment Install Plan" in output.read_text(encoding="utf-8")


def test_deploy_plan_second_output_without_force_exits_nonzero(
    rendered_dir: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "plan.md"
    first = runner.invoke(
        app,
        [
            "deploy",
            "plan",
            "--generated-dir",
            str(rendered_dir),
            "--format",
            "json",
            "--output",
            str(output),
        ],
    )
    assert first.exit_code == 0

    second = runner.invoke(
        app,
        [
            "deploy",
            "plan",
            "--generated-dir",
            str(rendered_dir),
            "--format",
            "json",
            "--output",
            str(output),
        ],
    )
    assert second.exit_code != 0
    assert "Refusing to overwrite" in (second.stdout + second.stderr)


def test_deploy_plan_second_output_with_force_succeeds(
    rendered_dir: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "plan.md"
    first = runner.invoke(
        app,
        [
            "deploy",
            "plan",
            "--generated-dir",
            str(rendered_dir),
            "--format",
            "json",
            "--output",
            str(output),
        ],
    )
    assert first.exit_code == 0

    second = runner.invoke(
        app,
        [
            "deploy",
            "plan",
            "--generated-dir",
            str(rendered_dir),
            "--format",
            "json",
            "--output",
            str(output),
            "--force",
        ],
    )
    assert second.exit_code == 0


def test_deploy_plan_missing_generated_dir_exits_nonzero(tmp_path: Path) -> None:
    missing = tmp_path / "missing-generated"

    result = runner.invoke(
        app,
        ["deploy", "plan", "--generated-dir", str(missing)],
    )

    assert result.exit_code != 0
    assert "blocked" in (result.stdout + result.stderr).lower()
