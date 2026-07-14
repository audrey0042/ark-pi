import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from ark_pi.cli import app
from ark_pi.config import clear_settings_cache

runner = CliRunner()


@pytest.fixture(autouse=True)
def reset_settings() -> None:
    clear_settings_cache()


def test_embeddings_status_help() -> None:
    result = runner.invoke(app, ["embeddings", "status", "--help"])
    assert result.exit_code == 0
    assert "passive" in result.stdout.lower() or "embedding" in result.stdout.lower()


def test_embeddings_test_help() -> None:
    result = runner.invoke(app, ["embeddings", "test", "--help"])
    assert result.exit_code == 0
    assert "--text" in result.stdout
    assert "--model-path" in result.stdout


def test_embeddings_evaluate_help() -> None:
    result = runner.invoke(app, ["embeddings", "evaluate", "--help"])
    assert result.exit_code == 0
    assert "--fixture" in result.stdout


def test_embeddings_status_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "mock")
    clear_settings_cache()

    result = runner.invoke(app, ["embeddings", "status"])
    assert result.exit_code == 0
    assert "mock" in result.stdout


def test_embeddings_status_json_emits_valid_json_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "mock")
    clear_settings_cache()

    with patch("ark_pi.embeddings.factory.create_embedder") as create:
        result = runner.invoke(app, ["embeddings", "status", "--json"])

    create.assert_not_called()
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["backend"] == "mock"
    assert data["model_load_performed"] is False


def test_embeddings_test_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "mock")
    clear_settings_cache()

    result = runner.invoke(app, ["embeddings", "test", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["ok"] is True
    assert data["texts_embedded"] == 3


def test_embeddings_evaluate_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "mock")
    clear_settings_cache()

    result = runner.invoke(app, ["embeddings", "evaluate", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["ok"] is True
    assert data["query_count"] == 4


def test_embeddings_status_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_path = tmp_path / "ark-rag.env"
    env_path.write_text(
        "\n".join(
            [
                "ARK_ROLE=rag",
                "ARK_EMBEDDING_BACKEND=mock",
                "ARK_EMBEDDING_MODEL=custom-model",
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["embeddings", "status", "--env-file", str(env_path), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["model"] == "custom-model"


def test_embeddings_test_fails_on_missing_model_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = tmp_path / "missing-model"
    env_path = tmp_path / "ark-rag.env"
    env_path.write_text(
        "\n".join(
            [
                "ARK_ROLE=rag",
                "ARK_EMBEDDING_BACKEND=sentence-transformers",
                f"ARK_EMBEDDING_MODEL_PATH={missing}",
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["embeddings", "test", "--env-file", str(env_path)])
    assert result.exit_code == 1
    assert "does not exist" in result.stderr
