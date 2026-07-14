from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ark_pi.config import ArkSettings, clear_settings_cache
from ark_pi.preflight import (
    _check_embeddings,
    _check_import_limit,
    _check_llm,
    _check_source_dir,
    _check_workspace_dir,
    run_preflight,
)
from ark_pi.workspace import catalog as workspace_catalog


@pytest.fixture
def dev_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    source = tmp_path / "sources"
    workspace.mkdir()
    source.mkdir()
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("ARK_SOURCE_DIR", str(source))
    monkeypatch.setenv("ARK_LLM_BACKEND", "mock")
    monkeypatch.setenv("ARK_INDEX_BACKEND", "simple")
    clear_settings_cache()
    yield workspace, source
    clear_settings_cache()


def test_clean_dev_setup_is_ready_or_warning(dev_paths: tuple[Path, Path]) -> None:
    _workspace, source = dev_paths
    (source / "sample.txt").write_text("Sample source text.\n", encoding="utf-8")

    result = run_preflight()

    assert result.overall_status in {"ready", "warning"}
    assert result.network_checks_performed is False
    check_ids = {check.id for check in result.checks}
    assert "config" in check_ids
    assert "llm" in check_ids


def test_missing_workspace_dir_produces_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(tmp_path / "missing-workspace"))
    monkeypatch.setenv("ARK_SOURCE_DIR", str(tmp_path / "sources"))
    clear_settings_cache()

    result = run_preflight()
    workspace_check = next(c for c in result.checks if c.id == "workspace_dir")

    assert workspace_check.status == "warning"
    assert not Path(str(workspace_check.details["path"])).exists()


def test_workspace_dir_file_path_produces_fail(tmp_path: Path) -> None:
    blocked = tmp_path / "workspace-file"
    blocked.write_text("not a dir", encoding="utf-8")
    settings = ArkSettings.model_construct(
        workspace_dir=blocked,
        source_dir=tmp_path / "sources",
    )

    check = _check_workspace_dir(settings)

    assert check.status == "fail"


def test_missing_source_dir_produces_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("ARK_SOURCE_DIR", str(tmp_path / "missing-sources"))
    clear_settings_cache()

    result = run_preflight()
    source_check = next(c for c in result.checks if c.id == "source_dir")

    assert source_check.status == "warning"


def test_source_dir_file_path_produces_fail(tmp_path: Path) -> None:
    blocked = tmp_path / "source-file"
    blocked.write_text("not a dir", encoding="utf-8")
    settings = ArkSettings.model_construct(
        workspace_dir=tmp_path / "workspace",
        source_dir=blocked,
    )

    check = _check_source_dir(settings)

    assert check.status == "fail"


def test_missing_catalog_produces_warning(dev_paths: tuple[Path, Path]) -> None:
    result = run_preflight()
    catalog_check = next(c for c in result.checks if c.id == "workspace_catalog")

    assert catalog_check.status == "warning"


def test_invalid_catalog_json_produces_fail(dev_paths: tuple[Path, Path]) -> None:
    workspace, _source = dev_paths
    (workspace / "catalog.json").write_text("{bad json", encoding="utf-8")

    result = run_preflight()
    catalog_check = next(c for c in result.checks if c.id == "workspace_catalog")

    assert catalog_check.status == "fail"
    assert result.overall_status == "blocked"


def test_catalog_with_missing_index_root_produces_fail(
    dev_paths: tuple[Path, Path],
) -> None:
    workspace, _source = dev_paths
    entry = workspace_catalog.CatalogIndexEntry(
        name="sample",
        slug="sample",
        backend="simple",
        chunks_path=str(workspace / "indexes/sample/chunks.jsonl"),
        index_dir=str(workspace / "indexes/sample/index"),
        chunk_count=1,
        source_count=1,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    workspace_catalog.upsert_index(workspace, entry)

    result = run_preflight()
    indexes_check = next(c for c in result.checks if c.id == "workspace_indexes")

    assert indexes_check.status == "fail"
    assert result.overall_status == "blocked"


def test_simple_backend_passes(dev_paths: tuple[Path, Path]) -> None:
    result = run_preflight()
    backend_check = next(c for c in result.checks if c.id == "index_backend")

    assert backend_check.status == "pass"


def test_chroma_backend_without_dependency_fails_with_install_hint(
    dev_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_INDEX_BACKEND", "chroma")
    clear_settings_cache()

    with patch("ark_pi.preflight._chroma_importable", return_value=False):
        result = run_preflight()

    backend_check = next(c for c in result.checks if c.id == "index_backend")
    assert backend_check.status == "fail"
    assert "chroma" in backend_check.message.lower()
    assert result.overall_status == "blocked"


def test_openai_compatible_without_base_url_fails(
    dev_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_LLM_BACKEND", "openai-compatible")
    monkeypatch.setenv("ARK_LLM_BASE_URL", "")
    clear_settings_cache()

    result = run_preflight()
    llm_check = next(c for c in result.checks if c.id == "llm")

    assert llm_check.status == "fail"
    assert result.overall_status == "blocked"


def test_openai_compatible_with_base_url_warns_without_network(
    dev_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_LLM_BACKEND", "openai-compatible")
    monkeypatch.setenv("ARK_LLM_BASE_URL", "http://192.168.50.2:8080")
    clear_settings_cache()

    with patch("ark_pi.llm_client.openai_compat.httpx.post") as post:
        result = run_preflight()

    post.assert_not_called()
    llm_check = next(c for c in result.checks if c.id == "llm")
    assert llm_check.status == "warning"
    assert llm_check.details["network_check_performed"] is False


def test_max_import_bytes_non_positive_fails() -> None:
    settings = SimpleNamespace(max_import_bytes=0)
    check = _check_import_limit(settings)  # type: ignore[arg-type]

    assert check.status == "fail"


def test_preflight_performs_no_network_checks(dev_paths: tuple[Path, Path]) -> None:
    with patch("ark_pi.llm_client.openai_compat.httpx.post") as post:
        result = run_preflight()

    post.assert_not_called()
    assert result.network_checks_performed is False


def test_mock_llm_check_passes(dev_paths: tuple[Path, Path]) -> None:
    from ark_pi.config import get_settings

    check = _check_llm(get_settings())
    assert check.status == "pass"


def test_mock_embeddings_check_warns_when_optional_dependency_missing(
    dev_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "mock")
    clear_settings_cache()

    with patch("ark_pi.preflight._sentence_transformers_importable", return_value=False):
        result = run_preflight()

    embeddings_check = next(c for c in result.checks if c.id == "embeddings")
    assert embeddings_check.status == "warning"


def test_sentence_transformers_embeddings_check_fails_without_dependency(
    dev_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "sentence-transformers")
    clear_settings_cache()

    with patch("ark_pi.preflight._sentence_transformers_importable", return_value=False):
        result = run_preflight()

    embeddings_check = next(c for c in result.checks if c.id == "embeddings")
    assert embeddings_check.status == "fail"


def test_embeddings_preflight_performs_no_model_load(
    dev_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "mock")
    clear_settings_cache()

    with patch("ark_pi.embeddings.factory.create_embedder") as create:
        result = run_preflight()

    create.assert_not_called()
    embeddings_check = next(c for c in result.checks if c.id == "embeddings")
    assert embeddings_check.details["model_load_performed"] is False
