import json
from pathlib import Path

import httpx
import pytest

from ark_pi.appliance_receipt import (
    RECEIPT_SCHEMA_NAME,
    RECEIPT_SCHEMA_VERSION,
    collect_appliance_receipt,
    redact_url_credentials,
    resolve_receipt_output_path,
    write_receipt_atomic,
)
from ark_pi.config import clear_settings_cache


@pytest.fixture
def rag_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
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
                "ARK_SECRET_TOKEN=super-secret-value",
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
    yield env_path
    clear_settings_cache()


def test_receipt_schema_fields(rag_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    http_calls: list[object] = []

    def fail_post(*_args: object, **_kwargs: object) -> httpx.Response:
        http_calls.append(True)
        raise AssertionError("HTTP should not be called for offline receipt")

    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", fail_post)
    monkeypatch.setattr(
        "ark_pi.appliance_receipt._query_systemctl",
        lambda _name: {"service": "ark-rag.service", "status": "not_run"},
    )

    result = collect_appliance_receipt(env_file=rag_env)

    payload = result.payload
    assert payload["schema_name"] == RECEIPT_SCHEMA_NAME
    assert payload["schema_version"] == RECEIPT_SCHEMA_VERSION
    assert payload["configuration"]["role"] == "rag"
    assert payload["configuration"]["llm_base_url"] == "http://192.168.1.134:8080"
    assert payload["active_smoke"]["connectivity"]["status"] == "not_run"
    assert payload["active_smoke"]["ask"]["status"] == "not_run"
    assert http_calls == []
    serialized = json.dumps(payload)
    assert "super-secret-value" not in serialized
    assert "ARK_SECRET_TOKEN" not in serialized


def test_llm_receipt_contains_model_and_binary_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = tmp_path / "data"
    model_path = data / "models" / "model.gguf"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"gguf")
    llama_bin = tmp_path / "bin" / "llama-server"
    llama_bin.parent.mkdir()
    llama_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    llama_bin.chmod(0o755)
    generated = data / "deploy" / "generated"
    generated.mkdir(parents=True)
    env_path = tmp_path / "ark-llm.env"
    env_path.write_text(
        "\n".join(
            [
                "ARK_ROLE=llm",
                f"ARK_DATA_DIR={data}",
                f"ARK_MODEL_PATH={model_path}",
                f"ARK_LLAMA_BIN={llama_bin}",
            ]
        ),
        encoding="utf-8",
    )
    (generated / "ark-llm.env").write_text(env_path.read_text(encoding="utf-8"), encoding="utf-8")
    clear_settings_cache()
    monkeypatch.setattr(
        "ark_pi.appliance_receipt._query_systemctl",
        lambda _name: {"service": "ark-llm.service", "status": "not_run"},
    )

    result = collect_appliance_receipt(env_file=env_path)

    assert result.payload["configuration"]["model_path"] == str(model_path)
    assert result.payload["configuration"]["llama_bin"] == str(llama_bin)
    clear_settings_cache()


def test_run_smoke_embeds_structured_result(
    rag_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(*_args: object, **_kwargs: object) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={"choices": [{"message": {"content": "ark-pi-ok"}}]},
            request=httpx.Request("POST", "http://example.test/v1/chat/completions"),
        )

    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", fake_post)
    monkeypatch.setattr(
        "ark_pi.appliance_receipt._query_systemctl",
        lambda _name: {"service": "ark-rag.service", "status": "not_run"},
    )

    result = collect_appliance_receipt(
        env_file=rag_env,
        run_smoke=True,
    )

    connectivity = result.payload["active_smoke"]["connectivity"]
    assert connectivity["status"] == "pass"
    assert connectivity["ok"] is True


def test_run_ask_smoke_embeds_structured_result(
    rag_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(*_args: object, **_kwargs: object) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={"choices": [{"message": {"content": "copper lantern"}}]},
            request=httpx.Request("POST", "http://example.test/v1/chat/completions"),
        )

    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", fake_post)
    monkeypatch.setattr(
        "ark_pi.appliance_receipt._query_systemctl",
        lambda _name: {"service": "ark-rag.service", "status": "not_run"},
    )

    result = collect_appliance_receipt(
        env_file=rag_env,
        run_ask_smoke=True,
    )

    ask = result.payload["active_smoke"]["ask"]
    assert ask["status"] == "pass"
    assert ask["llm_ok"] is True


def test_allow_smoke_failure_overall_warning(
    rag_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_post(*_args: object, **_kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", fail_post)
    monkeypatch.setattr(
        "ark_pi.appliance_receipt._query_systemctl",
        lambda _name: {"service": "ark-rag.service", "status": "not_run"},
    )

    result = collect_appliance_receipt(
        env_file=rag_env,
        run_smoke=True,
        allow_smoke_failure=True,
    )

    assert result.payload["active_smoke"]["connectivity"]["status"] == "fail"
    assert result.overall_status == "warning"


def test_smoke_failure_without_allow_is_overall_fail(
    rag_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_post(*_args: object, **_kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", fail_post)
    monkeypatch.setattr(
        "ark_pi.appliance_receipt._query_systemctl",
        lambda _name: {"service": "ark-rag.service", "status": "not_run"},
    )

    result = collect_appliance_receipt(
        env_file=rag_env,
        run_smoke=True,
    )

    assert result.overall_status == "fail"


def test_llm_role_rejects_run_ask_smoke(tmp_path: Path) -> None:
    env_path = tmp_path / "ark-llm.env"
    env_path.write_text("ARK_ROLE=llm\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported on LLM-only role"):
        collect_appliance_receipt(env_file=env_path, run_ask_smoke=True)


def test_exec_start_literal_pass_and_fail(tmp_path: Path) -> None:
    from ark_pi.appliance_receipt import _check_exec_start_literal

    literal = tmp_path / "literal.service"
    literal.write_text(
        "ExecStart=/srv/ark-pi/vendor/llama.cpp/build/bin/llama-server --model x\n",
        encoding="utf-8",
    )
    broken = tmp_path / "broken.service"
    broken.write_text(
        "ExecStart=${ARK_LLAMA_BIN} --model x\n",
        encoding="utf-8",
    )

    pass_check = _check_exec_start_literal(literal)
    fail_check = _check_exec_start_literal(broken)

    assert pass_check["status"] == "pass"
    assert fail_check["status"] == "fail"
    assert "${ARK_LLAMA_BIN}" in fail_check["message"]


def test_hash_model_includes_sha256(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = tmp_path / "data"
    model_path = data / "model.gguf"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"tiny-model")
    generated = data / "deploy" / "generated"
    generated.mkdir(parents=True)
    env_path = tmp_path / "ark-llm.env"
    env_path.write_text(
        f"ARK_ROLE=llm\nARK_DATA_DIR={data}\nARK_MODEL_PATH={model_path}\n",
        encoding="utf-8",
    )
    (generated / "ark-llm.env").write_text(env_path.read_text(encoding="utf-8"), encoding="utf-8")
    clear_settings_cache()
    monkeypatch.setattr(
        "ark_pi.appliance_receipt._query_systemctl",
        lambda _name: {"service": "ark-llm.service", "status": "not_run"},
    )

    without_hash = collect_appliance_receipt(env_file=env_path)
    with_hash = collect_appliance_receipt(
        env_file=env_path,
        hash_model=True,
    )

    assert "model_sha256" not in without_hash.payload["role_readiness"]
    assert "model_sha256" in with_hash.payload["role_readiness"]
    clear_settings_cache()


def test_redact_url_credentials() -> None:
    assert redact_url_credentials("http://user:secret@example.test:8080") == "http://example.test:8080"


def test_write_receipt_atomic(tmp_path: Path) -> None:
    path = tmp_path / "receipt.json"
    payload = {"schema_name": RECEIPT_SCHEMA_NAME, "schema_version": RECEIPT_SCHEMA_VERSION}
    write_receipt_atomic(path, payload)
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8")) == payload
    assert not path.with_name("receipt.json.tmp").exists()


def test_resolve_receipt_output_path_timestamped(tmp_path: Path) -> None:
    path = resolve_receipt_output_path(receipt_dir=tmp_path)
    assert path is not None
    assert path.parent == tmp_path
    assert path.name.startswith("ark-pi-receipt-")
