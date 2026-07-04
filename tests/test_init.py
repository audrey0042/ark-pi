import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ark_pi.config import ArkSettings, clear_settings_cache
from ark_pi.init import SAMPLE_SOURCE_FILENAME, initialize_appliance
from ark_pi.workspace import catalog as workspace_catalog


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


def test_init_creates_workspace_indexes_and_source_dirs(
    unset_paths: tuple[Path, Path],
) -> None:
    workspace, source = unset_paths

    result = initialize_appliance()

    assert workspace.is_dir()
    assert (workspace / "indexes").is_dir()
    assert source.is_dir()
    assert str(workspace) in result.created_paths
    assert str(workspace / "indexes") in result.created_paths
    assert str(source) in result.created_paths


def test_init_creates_empty_catalog_by_default(unset_paths: tuple[Path, Path]) -> None:
    workspace, _source = unset_paths

    result = initialize_appliance()

    catalog_file = workspace / "catalog.json"
    assert catalog_file.is_file()
    assert str(catalog_file) in result.created_paths
    entries = workspace_catalog.load_catalog(workspace)
    assert entries == []


def test_init_with_create_catalog_false_skips_catalog(
    unset_paths: tuple[Path, Path],
) -> None:
    workspace, _source = unset_paths

    result = initialize_appliance(create_catalog=False)

    assert not (workspace / "catalog.json").exists()
    assert str(workspace / "catalog.json") in result.skipped


def test_init_with_sample_creates_sample_file(unset_paths: tuple[Path, Path]) -> None:
    _workspace, source = unset_paths

    result = initialize_appliance(create_sample_source=True)

    sample_path = source / SAMPLE_SOURCE_FILENAME
    assert sample_path.is_file()
    assert result.sample_source_path == str(sample_path)
    assert str(sample_path) in result.created_paths


def test_init_does_not_overwrite_valid_catalog(unset_paths: tuple[Path, Path]) -> None:
    workspace, _source = unset_paths
    catalog_file = workspace / "catalog.json"
    workspace.mkdir(parents=True)
    catalog_file.write_text(
        json.dumps({"schema_version": 1, "indexes": []}, indent=2) + "\n",
        encoding="utf-8",
    )

    result = initialize_appliance()

    assert str(catalog_file) in result.existing_paths
    assert str(catalog_file) not in result.created_paths


def test_init_fails_on_invalid_catalog_without_force(
    unset_paths: tuple[Path, Path],
) -> None:
    workspace, _source = unset_paths
    workspace.mkdir(parents=True)
    (workspace / "catalog.json").write_text("{invalid", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid workspace catalog"):
        initialize_appliance()


def test_init_with_force_replaces_invalid_catalog(unset_paths: tuple[Path, Path]) -> None:
    workspace, _source = unset_paths
    workspace.mkdir(parents=True)
    catalog_file = workspace / "catalog.json"
    catalog_file.write_text("{invalid", encoding="utf-8")

    result = initialize_appliance(force=True)

    assert str(catalog_file) in result.created_paths
    entries = workspace_catalog.load_catalog(workspace)
    assert entries == []


def test_init_fails_if_workspace_dir_is_file(tmp_path: Path) -> None:
    blocked = tmp_path / "workspace-file"
    blocked.write_text("not a dir", encoding="utf-8")
    settings = ArkSettings.model_construct(
        workspace_dir=blocked,
        source_dir=tmp_path / "sources",
    )

    with pytest.raises(ValueError, match="workspace_dir exists but is not a directory"):
        initialize_appliance(settings=settings)


def test_init_fails_if_source_dir_is_file(tmp_path: Path) -> None:
    blocked = tmp_path / "source-file"
    blocked.write_text("not a dir", encoding="utf-8")
    settings = ArkSettings.model_construct(
        workspace_dir=tmp_path / "workspace",
        source_dir=blocked,
    )

    with pytest.raises(ValueError, match="source_dir exists but is not a directory"):
        initialize_appliance(settings=settings)


def test_init_runs_passive_preflight_after_initialization(
    unset_paths: tuple[Path, Path],
) -> None:
    result = initialize_appliance()

    assert result.preflight.network_checks_performed is False
    assert result.preflight.overall_status in {"ready", "warning", "blocked"}
    check_ids = {check.id for check in result.preflight.checks}
    assert "workspace_dir" in check_ids
    assert "source_dir" in check_ids


def test_init_does_not_perform_network_calls(unset_paths: tuple[Path, Path]) -> None:
    with patch("ark_pi.llm_client.openai_compat.httpx.post") as post:
        initialize_appliance()

    post.assert_not_called()
