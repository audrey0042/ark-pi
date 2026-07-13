import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from ark_pi.appliance_receipt import RECEIPT_SCHEMA_NAME
from ark_pi.cli import app
from ark_pi.config import clear_settings_cache

runner = CliRunner()


@pytest.fixture
def rag_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    data = tmp_path / "data"
    workspace = data / "workspace"
    source = data / "sources"
    generated = data / "deploy" / "generated"
    workspace.mkdir(parents=True)
    source.mkdir(parents=True)
    generated.mkdir(parents=True)
    env_path = tmp_path / "ark-rag.env"
    env_path.write_text(
        "\n".join(
            [
                "ARK_ROLE=rag",
                f"ARK_DATA_DIR={data}",
                f"ARK_WORKSPACE_DIR={workspace}",
                f"ARK_SOURCE_DIR={source}",
                "ARK_LLM_BACKEND=openai-compatible",
                "ARK_LLM_BASE_URL=http://192.168.1.134:8080",
                "ARK_INDEX_BACKEND=simple",
            ]
        ),
        encoding="utf-8",
    )
    (generated / "ark-rag.env").write_text(env_path.read_text(encoding="utf-8"), encoding="utf-8")
    (generated / "ark-rag.service").write_text(
        "\n".join(
            [
                "[Service]",
                "EnvironmentFile=/etc/ark-pi/ark-rag.env",
                "WorkingDirectory=/opt/ark-pi",
                "ExecStart=/opt/ark-pi/.venv/bin/ark serve --host ${ARK_HOST} --port ${ARK_PORT}",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ARK_DATA_DIR", str(data))
    clear_settings_cache()
    yield env_path, generated
    clear_settings_cache()


def test_appliance_receipt_help() -> None:
    result = runner.invoke(app, ["appliance", "receipt", "--help"])
    assert result.exit_code == 0
    assert "--env-file" in result.stdout
    assert "--json" in result.stdout
    assert "--output" in result.stdout
    assert "--run-smoke" in result.stdout
    assert "--run-ask-smoke" in result.stdout
    assert "--hash-model" in result.stdout


def test_appliance_receipt_json_only_stdout(
    rag_env: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path, _generated = rag_env
    monkeypatch.setattr(
        "ark_pi.appliance_receipt._query_systemctl",
        lambda _name: {"service": "ark-rag.service", "status": "not_run"},
    )

    result = runner.invoke(
        app,
        ["appliance", "receipt", "--env-file", str(env_path), "--json"],
    )

    assert result.exit_code in {0, 1}
    data = json.loads(result.stdout)
    assert data["schema_name"] == RECEIPT_SCHEMA_NAME
    assert data["configuration"]["llm_base_url"] == "http://192.168.1.134:8080"


def test_appliance_receipt_output_writes_file(
    rag_env: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path, _generated = rag_env
    output = tmp_path / "receipt.json"
    monkeypatch.setattr(
        "ark_pi.appliance_receipt._query_systemctl",
        lambda _name: {"service": "ark-rag.service", "status": "not_run"},
    )

    result = runner.invoke(
        app,
        [
            "appliance",
            "receipt",
            "--env-file",
            str(env_path),
            "--output",
            str(output),
        ],
    )

    assert output.is_file()
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["schema_name"] == RECEIPT_SCHEMA_NAME
    assert "Receipt written to" in result.stdout or result.exit_code in {0, 1}


def test_appliance_receipt_run_smoke_failure_exits_nonzero_by_default(
    rag_env: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path, _generated = rag_env

    def fail_post(*_args: object, **_kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", fail_post)
    monkeypatch.setattr(
        "ark_pi.appliance_receipt._query_systemctl",
        lambda _name: {"service": "ark-rag.service", "status": "not_run"},
    )

    output = env_path.parent / "failed-receipt.json"
    result = runner.invoke(
        app,
        [
            "appliance",
            "receipt",
            "--env-file",
            str(env_path),
            "--run-smoke",
            "--output",
            str(output),
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert output.is_file()
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["active_smoke"]["connectivity"]["status"] == "fail"


def test_appliance_receipt_allow_smoke_failure_exits_zero(
    rag_env: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path, _generated = rag_env

    def fail_post(*_args: object, **_kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", fail_post)
    monkeypatch.setattr(
        "ark_pi.appliance_receipt._query_systemctl",
        lambda _name: {"service": "ark-rag.service", "status": "not_run"},
    )

    result = runner.invoke(
        app,
        [
            "appliance",
            "receipt",
            "--env-file",
            str(env_path),
            "--run-smoke",
            "--allow-smoke-failure",
            "--json",
        ],
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["active_smoke"]["connectivity"]["status"] == "fail"


def test_appliance_receipt_llm_role_rejects_ask_smoke(tmp_path: Path) -> None:
    env_path = tmp_path / "ark-llm.env"
    env_path.write_text("ARK_ROLE=llm\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "appliance",
            "receipt",
            "--env-file",
            str(env_path),
            "--run-ask-smoke",
        ],
    )

    assert result.exit_code != 0
    assert "Unsupported on LLM-only role" in result.stdout + result.stderr
