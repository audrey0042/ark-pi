import pytest
from typer.testing import CliRunner

from ark_pi.cli import app

runner = CliRunner()


def test_serve_help() -> None:
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--host" in result.stdout
    assert "--port" in result.stdout


def test_serve_invokes_uvicorn_with_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(*args: object, **kwargs: object) -> None:
        calls.append({"args": args, "kwargs": kwargs})

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", fake_run)

    result = runner.invoke(app, ["serve", "--host", "127.0.0.1", "--port", "9000"])
    assert result.exit_code == 0
    assert len(calls) == 1
    call = calls[0]
    assert call["args"][0] == "ark_pi.web.app:create_app"
    assert call["kwargs"]["factory"] is True
    assert call["kwargs"]["host"] == "127.0.0.1"
    assert call["kwargs"]["port"] == 9000
