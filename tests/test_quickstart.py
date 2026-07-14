from pathlib import Path
from unittest.mock import patch

import pytest

from ark_pi.config import clear_settings_cache
from ark_pi.init import SAMPLE_SOURCE_FILENAME
from ark_pi.quickstart import DEFAULT_INDEX_NAME, DEFAULT_QUESTION, run_quickstart
from ark_pi.rag import index as rag_index
from ark_pi.workspace import catalog as workspace_catalog
from ark_pi.workspace import ingest as workspace_ingest


@pytest.fixture
def unset_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    source = tmp_path / "sources"
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("ARK_SOURCE_DIR", str(source))
    monkeypatch.setenv("ARK_LLM_BACKEND", "mock")
    monkeypatch.setenv("ARK_INDEX_BACKEND", "simple")
    clear_settings_cache()
    yield workspace, source
    clear_settings_cache()


def test_quickstart_creates_storage_sample_catalog_and_index(
    unset_paths: tuple[Path, Path],
) -> None:
    workspace, source = unset_paths

    result = run_quickstart()

    assert workspace.is_dir()
    assert (workspace / "indexes").is_dir()
    assert source.is_dir()
    assert (source / SAMPLE_SOURCE_FILENAME).is_file()
    assert (workspace / "catalog.json").is_file()
    assert workspace_catalog.get_index(workspace, result.index_slug) is not None
    assert result.index_name == DEFAULT_INDEX_NAME
    assert result.chunk_count > 0
    assert result.source_count >= 1


def test_quickstart_answer_uses_mock_backend(unset_paths: tuple[Path, Path]) -> None:
    result = run_quickstart()

    assert "Mock LLM backend" in result.ask_answer
    assert result.retrieved_count > 0


def test_quickstart_created_index_can_be_searched(
    unset_paths: tuple[Path, Path],
) -> None:
    result = run_quickstart()

    results = rag_index.search_index(
        Path(result.index_dir),
        "Ark Pi",
        limit=3,
    ).results

    assert len(results) > 0


def test_quickstart_returns_preflight_result(unset_paths: tuple[Path, Path]) -> None:
    result = run_quickstart()

    assert result.preflight.network_checks_performed is False
    assert result.preflight.overall_status in {"ready", "warning", "blocked"}


def test_quickstart_fails_if_sample_index_exists_and_force_false(
    unset_paths: tuple[Path, Path],
) -> None:
    run_quickstart()

    with pytest.raises(ValueError, match="Index already exists"):
        run_quickstart()


def test_quickstart_with_force_rebuilds_sample_index(
    unset_paths: tuple[Path, Path],
) -> None:
    first = run_quickstart()
    second = run_quickstart(force=True)

    assert second.index_slug == first.index_slug
    assert second.chunk_count > 0
    assert workspace_catalog.get_index(unset_paths[0], second.index_slug) is not None


def test_quickstart_does_not_delete_unrelated_indexes(
    unset_paths: tuple[Path, Path],
) -> None:
    workspace, source = unset_paths
    workspace.mkdir(parents=True, exist_ok=True)
    source.mkdir(parents=True, exist_ok=True)
    (source / "other.txt").write_text(
        "Unrelated index content about widgets and gadgets.\n",
        encoding="utf-8",
    )
    other = workspace_ingest.ingest_source_path_to_workspace_index(
        "other.txt",
        "other-index",
        source,
        workspace,
    )

    run_quickstart(force=True)

    assert workspace_catalog.get_index(workspace, other.index_slug) is not None
    assert workspace_catalog.get_index(workspace, DEFAULT_INDEX_NAME) is not None


def test_quickstart_does_not_perform_network_calls(
    unset_paths: tuple[Path, Path],
) -> None:
    with patch("ark_pi.llm_client.openai_compat.httpx.post") as post:
        run_quickstart()

    post.assert_not_called()


def test_quickstart_uses_default_question(unset_paths: tuple[Path, Path]) -> None:
    result = run_quickstart()

    assert result.ask_question == DEFAULT_QUESTION
