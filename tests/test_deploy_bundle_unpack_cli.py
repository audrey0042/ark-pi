import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ark_pi.cli import app
from ark_pi.deploy.bundle import build_deployment_bundle
from ark_pi.deploy.templates import render_deployment_templates

runner = CliRunner()


@pytest.fixture
def valid_bundle(tmp_path: Path) -> Path:
    rendered_dir = tmp_path / "generated"
    render_deployment_templates(rendered_dir, force=True)
    output = tmp_path / "bundle.zip"
    build_deployment_bundle(rendered_dir, output_path=output, force=True)
    return output


def test_deploy_unpack_bundle_help() -> None:
    result = runner.invoke(app, ["deploy", "unpack-bundle", "--help"])
    assert result.exit_code == 0
    assert "--bundle" in result.stdout
    assert "--staging-dir" in result.stdout
    assert "--force" in result.stdout
    assert "--json" in result.stdout


def test_deploy_unpack_bundle_valid_bundle_exits_zero(
    valid_bundle: Path,
    tmp_path: Path,
) -> None:
    staging = tmp_path / "staging"
    result = runner.invoke(
        app,
        [
            "deploy",
            "unpack-bundle",
            "--bundle",
            str(valid_bundle),
            "--staging-dir",
            str(staging),
            "--force",
        ],
    )

    assert result.exit_code == 0
    assert "Verification status" in result.stdout
    assert (staging / "README.txt").is_file()


def test_deploy_unpack_bundle_json_outputs_parseable_json(
    valid_bundle: Path,
    tmp_path: Path,
) -> None:
    staging = tmp_path / "staging"
    result = runner.invoke(
        app,
        [
            "deploy",
            "unpack-bundle",
            "--bundle",
            str(valid_bundle),
            "--staging-dir",
            str(staging),
            "--force",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["verification_status"] in {"valid", "warning"}
    assert payload["staging_dir"] == str(staging.resolve())
    assert payload["extracted_count"] == 9
    assert isinstance(payload["extracted_files"], list)


def test_deploy_unpack_bundle_invalid_bundle_exits_nonzero(tmp_path: Path) -> None:
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not-a-zip")
    staging = tmp_path / "staging"
    result = runner.invoke(
        app,
        [
            "deploy",
            "unpack-bundle",
            "--bundle",
            str(bad),
            "--staging-dir",
            str(staging),
            "--force",
        ],
    )

    assert result.exit_code == 1
    assert "verification is invalid" in result.stderr


def test_non_empty_staging_without_force_exits_nonzero(
    valid_bundle: Path,
    tmp_path: Path,
) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "existing.txt").write_text("keep", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "deploy",
            "unpack-bundle",
            "--bundle",
            str(valid_bundle),
            "--staging-dir",
            str(staging),
        ],
    )

    assert result.exit_code == 1
    assert "non-empty staging directory" in result.stderr


def test_non_empty_staging_with_force_exits_zero(
    valid_bundle: Path,
    tmp_path: Path,
) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "existing.txt").write_text("old", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "deploy",
            "unpack-bundle",
            "--bundle",
            str(valid_bundle),
            "--staging-dir",
            str(staging),
            "--force",
        ],
    )

    assert result.exit_code == 0
    assert not (staging / "existing.txt").exists()
    assert (staging / "manifest.json").is_file()
