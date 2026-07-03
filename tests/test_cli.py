import pytest
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
