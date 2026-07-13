import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from ark_pi.appliance_smoke import EXPECTED_DIAGNOSTIC_OUTPUT, run_appliance_smoke
from ark_pi.cli import app
from ark_pi.config import clear_settings_cache, load_settings_from_env_file

runner = CliRunner()


def _fake_ok_post(*_args: object, **_kwargs: object) -> httpx.Response:
    return httpx.Response(
        status_code=200,
        json={"choices": [{"message": {"content": EXPECTED_DIAGNOSTIC_OUTPUT}}]},
        request=httpx.Request("POST", "http://example.test/v1/chat/completions"),
    )


def _fake_wrong_post(*_args: object, **_kwargs: object) -> httpx.Response:
    return httpx.Response(
        status_code=200,
        json={"choices": [{"message": {"content": "wrong-output"}}]},
        request=httpx.Request("POST", "http://example.test/v1/chat/completions"),
    )


def test_appliance_smoke_help() -> None:
    result = runner.invoke(app, ["appliance", "smoke", "--help"])
    assert result.exit_code == 0
    assert "--env-file" in result.stdout
    assert "--json" in result.stdout
    assert "--llm-base-url" in result.stdout
    assert "--timeout" in result.stdout


def test_appliance_smoke_success_with_fake_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", _fake_ok_post)
    monkeypatch.setenv("ARK_LLM_BACKEND", "openai-compatible")
    monkeypatch.setenv("ARK_LLM_BASE_URL", "http://example.test")
    clear_settings_cache()

    result = runner.invoke(
        app,
        [
            "appliance",
            "smoke",
            "--llm-base-url",
            "http://example.test",
        ],
    )

    assert result.exit_code == 0
    assert "ok" in result.stdout
    assert "True" in result.stdout
    assert EXPECTED_DIAGNOSTIC_OUTPUT in result.stdout


def test_appliance_smoke_connection_refused_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(*_args: object, **_kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", fake_post)
    monkeypatch.setenv("ARK_LLM_BACKEND", "openai-compatible")
    monkeypatch.setenv("ARK_LLM_BASE_URL", "http://127.0.0.1:8080")
    clear_settings_cache()

    result = runner.invoke(
        app,
        ["appliance", "smoke", "--llm-base-url", "http://127.0.0.1:8080"],
    )

    assert result.exit_code != 0
    assert "connection refused" in result.stdout + result.stderr


def test_appliance_smoke_wrong_output_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", _fake_wrong_post)
    monkeypatch.setenv("ARK_LLM_BACKEND", "openai-compatible")
    monkeypatch.setenv("ARK_LLM_BASE_URL", "http://example.test")
    clear_settings_cache()

    result = runner.invoke(
        app,
        ["appliance", "smoke", "--llm-base-url", "http://example.test"],
    )

    assert result.exit_code != 0
    assert "wrong-output" in result.stdout


def test_appliance_smoke_json_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", _fake_ok_post)
    monkeypatch.setenv("ARK_LLM_BACKEND", "openai-compatible")
    monkeypatch.setenv("ARK_LLM_BASE_URL", "http://example.test")
    clear_settings_cache()

    result = runner.invoke(
        app,
        ["appliance", "smoke", "--llm-base-url", "http://example.test", "--json"],
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["ok"] is True
    assert data["output_text"] == EXPECTED_DIAGNOSTIC_OUTPUT
    assert data["base_url"] == "http://example.test"


def test_appliance_smoke_loads_env_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = tmp_path / "ark-rag.env"
    env_path.write_text(
        "\n".join(
            [
                "ARK_ROLE=rag",
                "ARK_LLM_BACKEND=openai-compatible",
                "ARK_LLM_BASE_URL=http://example.test",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", _fake_ok_post)
    clear_settings_cache()

    result = runner.invoke(
        app,
        ["appliance", "smoke", "--env-file", str(env_path), "--json"],
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["role"] == "rag"
    assert data["backend"] == "openai-compatible"
    assert data["base_url"] == "http://example.test"
    assert data["ok"] is True


def test_appliance_smoke_unreadable_env_file_exits_nonzero(tmp_path: Path) -> None:
    env_path = tmp_path / "ark-rag.env"
    env_path.write_text("ARK_ROLE=rag\n", encoding="utf-8")
    env_path.chmod(0o000)

    result = runner.invoke(app, ["appliance", "smoke", "--env-file", str(env_path)])

    assert result.exit_code != 0
    combined = result.stdout + result.stderr
    assert "Cannot read env file" in combined or "is not readable" in combined


def test_load_settings_from_env_file(tmp_path: Path) -> None:
    env_path = tmp_path / "ark-rag.env"
    env_path.write_text(
        "ARK_ROLE=rag\nARK_LLM_BASE_URL=http://192.168.1.134:8080\n",
        encoding="utf-8",
    )

    settings = load_settings_from_env_file(env_path)

    assert settings.role == "rag"
    assert settings.llm_base_url == "http://192.168.1.134:8080"


def test_load_settings_from_env_file_rejects_malformed_lines(tmp_path: Path) -> None:
    env_path = tmp_path / "bad.env"
    env_path.write_text("not-valid\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid env file"):
        load_settings_from_env_file(env_path)


def test_run_appliance_smoke_validates_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", _fake_wrong_post)
    monkeypatch.setenv("ARK_LLM_BACKEND", "openai-compatible")
    monkeypatch.setenv("ARK_LLM_BASE_URL", "http://example.test")
    clear_settings_cache()

    result = run_appliance_smoke(llm_base_url="http://example.test")

    assert result.ok is False
    assert "wrong-output" in result.output_text
