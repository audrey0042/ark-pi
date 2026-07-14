import json

import pytest
from typer.testing import CliRunner

from ark_pi.cli import app
from ark_pi.config import clear_settings_cache
from ark_pi.embeddings import run_embeddings_evaluate

runner = CliRunner()


@pytest.fixture(autouse=True)
def reset_settings() -> None:
    clear_settings_cache()


def test_evaluation_computes_top1_accuracy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "mock")
    clear_settings_cache()

    result = run_embeddings_evaluate()
    assert 0.0 <= result.top1_accuracy <= 1.0


def test_evaluation_computes_recall_at_3(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "mock")
    clear_settings_cache()

    result = run_embeddings_evaluate()
    assert 0.0 <= result.recall_at_3 <= 1.0


def test_evaluation_computes_mean_reciprocal_rank(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "mock")
    clear_settings_cache()

    result = run_embeddings_evaluate()
    assert 0.0 <= result.mean_reciprocal_rank <= 1.0


def test_evaluation_cli_json_reports_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "mock")
    clear_settings_cache()

    result = runner.invoke(app, ["embeddings", "evaluate", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["query_count"] == 4
    assert data["documents_count"] == 12
    assert "top1_accuracy" in data
    assert "recall_at_3" in data
    assert "mean_reciprocal_rank" in data
