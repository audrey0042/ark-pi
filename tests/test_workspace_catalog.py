from pathlib import Path

import pytest

from ark_pi.config import clear_settings_cache
from ark_pi.workspace import catalog as workspace_catalog
from ark_pi.workspace.paths import index_paths, slugify_index_name, validate_index_name


@pytest.fixture
def workspace_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ws = tmp_path / "workspace"
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(ws))
    clear_settings_cache()
    yield ws
    clear_settings_cache()


def test_slugify_index_name_deterministic() -> None:
    assert slugify_index_name("My Index") == "my-index"
    assert slugify_index_name("Sample_01") == "sample_01"


def test_validate_index_name_rejects_traversal() -> None:
    with pytest.raises(ValueError, match="invalid index name"):
        validate_index_name("../escape")
    with pytest.raises(ValueError, match="invalid index name"):
        validate_index_name("foo/bar")


def test_load_catalog_missing_returns_empty(workspace_dir: Path) -> None:
    assert workspace_catalog.load_catalog(workspace_dir) == []


def test_upsert_and_list_indexes(workspace_dir: Path) -> None:
    entry = workspace_catalog.CatalogIndexEntry(
        name="Sample",
        slug="sample",
        backend="simple",
        chunks_path=str(workspace_dir / "indexes/sample/chunks.jsonl"),
        index_dir=str(workspace_dir / "indexes/sample/index"),
        chunk_count=2,
        source_count=1,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    workspace_catalog.upsert_index(workspace_dir, entry)
    entries = workspace_catalog.list_indexes(workspace_dir)
    assert len(entries) == 1
    assert entries[0].slug == "sample"


def test_get_index_missing_returns_none(workspace_dir: Path) -> None:
    assert workspace_catalog.get_index(workspace_dir, "missing") is None


def test_index_paths_stay_inside_workspace(workspace_dir: Path) -> None:
    chunks_path, index_dir = index_paths(workspace_dir, "sample")
    root = workspace_dir.resolve()
    assert chunks_path.resolve().is_relative_to(root)
    assert index_dir.resolve().is_relative_to(root)
