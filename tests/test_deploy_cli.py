import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ark_pi.cli import app
from ark_pi.deploy.templates import ARK_RAG_ENV

runner = CliRunner()


def test_deploy_render_help() -> None:
    result = runner.invoke(app, ["deploy", "render", "--help"])
    assert result.exit_code == 0
    assert "--output-dir" in result.stdout
    assert "--role" in result.stdout
    assert "--force" in result.stdout
    assert "--json" in result.stdout


def test_deploy_render_output_dir_tmp_succeeds(tmp_path: Path) -> None:
    output = tmp_path / "deploy-out"

    result = runner.invoke(app, ["deploy", "render", "--output-dir", str(output)])

    assert result.exit_code == 0
    assert (output / "ark-rag.env").is_file()
    assert (output / "ark-llm.service").is_file()
    assert "Review these files manually" in result.stdout


def test_deploy_render_role_rag_outputs_rag_files_only(tmp_path: Path) -> None:
    output = tmp_path / "rag-only"

    result = runner.invoke(
        app,
        ["deploy", "render", "--output-dir", str(output), "--role", "rag"],
    )

    assert result.exit_code == 0
    assert (output / "ark-rag.env").is_file()
    assert (output / "ark-rag.service").is_file()
    assert not (output / "ark-llm.env").exists()
    assert not (output / "ark-llm.service").exists()


def test_deploy_render_role_llm_outputs_llm_files_only(tmp_path: Path) -> None:
    output = tmp_path / "llm-only"

    result = runner.invoke(
        app,
        ["deploy", "render", "--output-dir", str(output), "--role", "llm"],
    )

    assert result.exit_code == 0
    assert (output / "ark-llm.env").is_file()
    assert (output / "ark-llm.service").is_file()
    assert not (output / "ark-rag.env").exists()
    assert not (output / "ark-rag.service").exists()


def test_deploy_render_second_without_force_exits_nonzero(tmp_path: Path) -> None:
    output = tmp_path / "deploy-out"
    first = runner.invoke(app, ["deploy", "render", "--output-dir", str(output)])
    assert first.exit_code == 0

    second = runner.invoke(app, ["deploy", "render", "--output-dir", str(output)])
    assert second.exit_code != 0
    assert "Refusing to overwrite" in (second.stdout + second.stderr)


def test_deploy_render_second_with_force_succeeds(tmp_path: Path) -> None:
    output = tmp_path / "deploy-out"
    first = runner.invoke(app, ["deploy", "render", "--output-dir", str(output), "--role", "rag"])
    assert first.exit_code == 0
    (output / "ark-rag.env").write_text("stale", encoding="utf-8")

    second = runner.invoke(
        app,
        ["deploy", "render", "--output-dir", str(output), "--role", "rag", "--force"],
    )
    assert second.exit_code == 0
    assert (output / "ark-rag.env").read_text(encoding="utf-8") == ARK_RAG_ENV


def test_deploy_render_json_outputs_parseable_json(tmp_path: Path) -> None:
    output = tmp_path / "deploy-out"

    result = runner.invoke(
        app,
        ["deploy", "render", "--output-dir", str(output), "--json"],
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["role"] == "all"
    assert len(data["generated_files"]) == 4
    assert "message" in data


def test_deploy_render_refuses_etc_output_dir() -> None:
    result = runner.invoke(
        app,
        ["deploy", "render", "--output-dir", "/etc/ark-pi-generated"],
    )

    assert result.exit_code != 0
    assert "Refusing to write deployment templates under /etc" in (result.stdout + result.stderr)
