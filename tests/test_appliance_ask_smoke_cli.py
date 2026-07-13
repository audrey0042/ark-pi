import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from ark_pi.appliance_ask_smoke import EXPECTED_PHRASE, SMOKE_INDEX_SLUG, SMOKE_SOURCE_FILENAME
from ark_pi.cli import app
from ark_pi.config import clear_settings_cache, load_settings_from_env_file
from ark_pi.workspace import catalog as workspace_catalog

runner = CliRunner()


def _fake_llm_post(*_args: object, **_kwargs: object) -> httpx.Response:
    return httpx.Response(
        status_code=200,
        json={
            "choices": [
                {
                    "message": {
                        "content": "The beacon phrase is copper lantern.",
                    }
                }
            ]
        },
        request=httpx.Request("POST", "http://example.test/v1/chat/completions"),
    )


@pytest.fixture
def rag_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    source = tmp_path / "sources"
    workspace.mkdir()
    source.mkdir()
    monkeypatch.setenv("ARK_ROLE", "dev")
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("ARK_SOURCE_DIR", str(source))
    monkeypatch.setenv("ARK_LLM_BACKEND", "openai-compatible")
    monkeypatch.setenv("ARK_LLM_BASE_URL", "http://example.test")
    monkeypatch.setenv("ARK_INDEX_BACKEND", "simple")
    clear_settings_cache()
    yield workspace, source
    clear_settings_cache()


def test_appliance_ask_smoke_help() -> None:
    result = runner.invoke(app, ["appliance", "ask-smoke", "--help"])
    assert result.exit_code == 0
    assert "--env-file" in result.stdout
    assert "--json" in result.stdout
    assert "--keep" in result.stdout
    assert "--timeout" in result.stdout


def test_appliance_ask_smoke_cli_success(
    rag_env: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", _fake_llm_post)

    result = runner.invoke(app, ["appliance", "ask-smoke"])

    assert result.exit_code == 0
    assert "retrieval_ok" in result.stdout
    assert "True" in result.stdout
    assert "llm_ok" in result.stdout
    assert EXPECTED_PHRASE in result.stdout


def test_appliance_ask_smoke_cli_json(
    rag_env: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", _fake_llm_post)

    result = runner.invoke(app, ["appliance", "ask-smoke", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["ok"] is True
    assert data["retrieval_ok"] is True
    assert data["llm_ok"] is True
    assert EXPECTED_PHRASE in data["answer"].lower()
    assert data["index_slug"] == SMOKE_INDEX_SLUG


def test_appliance_ask_smoke_cli_env_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    source = tmp_path / "sources"
    workspace.mkdir()
    source.mkdir()
    env_path = tmp_path / "ark-rag.env"
    env_path.write_text(
        "\n".join(
            [
                "ARK_ROLE=rag",
                "ARK_WORKSPACE_DIR=" + str(workspace),
                "ARK_SOURCE_DIR=" + str(source),
                "ARK_LLM_BACKEND=openai-compatible",
                "ARK_LLM_BASE_URL=http://example.test",
                "ARK_INDEX_BACKEND=simple",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", _fake_llm_post)

    result = runner.invoke(
        app,
        ["appliance", "ask-smoke", "--env-file", str(env_path), "--json"],
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["role"] == "rag"
    settings = load_settings_from_env_file(env_path)
    assert settings.workspace_dir == workspace.resolve()


def test_appliance_ask_smoke_cli_timeout_override(
    rag_env: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, float] = {}

    def fake_post(*_args: object, **kwargs: object) -> httpx.Response:
        timeout = kwargs.get("timeout")
        if timeout is not None:
            captured["timeout"] = float(timeout)
        return _fake_llm_post()

    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", fake_post)

    result = runner.invoke(app, ["appliance", "ask-smoke", "--timeout", "7.5"])

    assert result.exit_code == 0
    assert captured.get("timeout") == 7.5


def test_appliance_ask_smoke_cli_keep(
    rag_env: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, source = rag_env
    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", _fake_llm_post)

    result = runner.invoke(app, ["appliance", "ask-smoke", "--keep"])

    assert result.exit_code == 0
    assert (source / SMOKE_SOURCE_FILENAME).is_file()
    assert workspace_catalog.get_index(workspace, SMOKE_INDEX_SLUG) is not None


def test_appliance_ask_smoke_cli_default_cleans_artifacts(
    rag_env: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, source = rag_env
    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", _fake_llm_post)

    result = runner.invoke(app, ["appliance", "ask-smoke"])

    assert result.exit_code == 0
    assert not (source / SMOKE_SOURCE_FILENAME).exists()
    assert workspace_catalog.get_index(workspace, SMOKE_INDEX_SLUG) is None


def test_appliance_ask_smoke_cli_llm_role_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    source = tmp_path / "sources"
    workspace.mkdir()
    source.mkdir()
    monkeypatch.setenv("ARK_ROLE", "llm")
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("ARK_SOURCE_DIR", str(source))
    clear_settings_cache()

    result = runner.invoke(app, ["appliance", "ask-smoke"])

    assert result.exit_code != 0
    assert "Unsupported role 'llm'" in result.stdout + result.stderr


def test_appliance_ask_smoke_cli_llm_failure_exits_nonzero(
    rag_env: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_post(*_args: object, **_kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", fail_post)

    result = runner.invoke(app, ["appliance", "ask-smoke", "--json"])

    assert result.exit_code != 0
    data = json.loads(result.stdout)
    assert data["ok"] is False
    assert data["retrieval_ok"] is True
    assert data["llm_ok"] is False
