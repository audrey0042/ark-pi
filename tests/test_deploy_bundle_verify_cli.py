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


def test_deploy_verify_bundle_help() -> None:
    result = runner.invoke(app, ["deploy", "verify-bundle", "--help"])
    assert result.exit_code == 0
    assert "--bundle" in result.stdout
    assert "--json" in result.stdout


def test_deploy_verify_bundle_valid_bundle_exits_zero(valid_bundle: Path) -> None:
    result = runner.invoke(
        app,
        ["deploy", "verify-bundle", "--bundle", str(valid_bundle)],
    )

    assert result.exit_code == 0
    assert "Overall status: valid" in result.stdout
    assert "Deployment Bundle Verification" in result.stdout


def test_deploy_verify_bundle_json_outputs_parseable_json(valid_bundle: Path) -> None:
    result = runner.invoke(
        app,
        ["deploy", "verify-bundle", "--bundle", str(valid_bundle), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["overall_status"] == "valid"
    assert payload["bundle_path"] == str(valid_bundle.resolve())
    assert isinstance(payload["checks"], list)
    assert payload["checks"]


def test_deploy_verify_bundle_invalid_bundle_exits_nonzero(
    valid_bundle: Path,
    tmp_path: Path,
) -> None:
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not-a-zip")
    result = runner.invoke(
        app,
        ["deploy", "verify-bundle", "--bundle", str(bad)],
    )

    assert result.exit_code == 1
    assert "invalid" in result.stdout.lower()


def test_missing_bundle_exits_nonzero(tmp_path: Path) -> None:
    missing = tmp_path / "missing.zip"
    result = runner.invoke(
        app,
        ["deploy", "verify-bundle", "--bundle", str(missing)],
    )

    assert result.exit_code == 1
    assert "invalid" in result.stdout.lower()
