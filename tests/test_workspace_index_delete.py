from pathlib import Path

import pytest

from ark_pi.config import clear_settings_cache
from ark_pi.workspace import catalog as workspace_catalog
from ark_pi.workspace import ingest as workspace_ingest
from ark_pi.workspace.catalog import WorkspaceError, WorkspaceIndexNotFoundError
from ark_pi.workspace.paths import index_root_dir, validate_slug

SAMPLE_TEXT = "Ark Pi workspace index deletion test content."


@pytest.fixture
def workspace_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ws = tmp_path / "workspace"
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(ws))
    clear_settings_cache()
    yield ws
    clear_settings_cache()


def _create_index(workspace_dir: Path, *, index_name: str, text: str = SAMPLE_TEXT) -> str:
    result = workspace_ingest.ingest_text_to_workspace_index(
        index_name,
        text,
        index_name,
        workspace_dir,
    )
    return result.index_slug


def test_delete_existing_index_removes_directory_and_catalog_entry(
    workspace_dir: Path,
) -> None:
    slug = _create_index(workspace_dir, index_name="sample")
    index_root = index_root_dir(workspace_dir, slug)
    assert index_root.is_dir()
    assert workspace_catalog.get_index(workspace_dir, slug) is not None

    result = workspace_catalog.delete_index(workspace_dir, slug)

    assert result.deleted is True
    assert result.slug == slug
    assert not index_root.exists()
    assert workspace_catalog.get_index(workspace_dir, slug) is None


def test_delete_missing_slug_raises_not_found(workspace_dir: Path) -> None:
    with pytest.raises(WorkspaceIndexNotFoundError, match="Workspace index not found"):
        workspace_catalog.delete_index(workspace_dir, "missing")


def test_delete_catalog_entry_with_missing_directory_cleans_up(
    workspace_dir: Path,
) -> None:
    import shutil

    slug = _create_index(workspace_dir, index_name="orphan")
    index_root = index_root_dir(workspace_dir, slug)
    shutil.rmtree(index_root)
    assert workspace_catalog.get_index(workspace_dir, slug) is not None

    result = workspace_catalog.delete_index(workspace_dir, slug)

    assert result.deleted is True
    assert "already missing" in result.message
    assert workspace_catalog.get_index(workspace_dir, slug) is None


def test_delete_rejects_traversal_slug(workspace_dir: Path) -> None:
    with pytest.raises(WorkspaceError, match="invalid slug"):
        workspace_catalog.delete_index(workspace_dir, "../escape")


def test_delete_cannot_remove_workspace_root(workspace_dir: Path) -> None:
    with pytest.raises(WorkspaceError):
        workspace_catalog.delete_index(workspace_dir, "..")


def test_delete_uses_derived_path_not_catalog_paths(
    workspace_dir: Path,
    tmp_path: Path,
) -> None:
    slug = _create_index(workspace_dir, index_name="safe")
    entry = workspace_catalog.get_index(workspace_dir, slug)
    assert entry is not None

    malicious_dir = tmp_path / "outside"
    malicious_dir.mkdir()
    (malicious_dir / "manifest.json").write_text("{}", encoding="utf-8")

    tampered = workspace_catalog.CatalogIndexEntry(
        name=entry.name,
        slug=entry.slug,
        backend=entry.backend,
        chunks_path=str(malicious_dir / "chunks.jsonl"),
        index_dir=str(malicious_dir),
        chunk_count=entry.chunk_count,
        source_count=entry.source_count,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )
    workspace_catalog.upsert_index(workspace_dir, tampered)

    workspace_catalog.delete_index(workspace_dir, slug)

    assert malicious_dir.is_dir()
    assert not index_root_dir(workspace_dir, slug).exists()
    assert workspace_catalog.get_index(workspace_dir, slug) is None


def test_delete_one_index_does_not_remove_another(workspace_dir: Path) -> None:
    slug_a = _create_index(workspace_dir, index_name="alpha", text="Alpha content here.")
    slug_b = _create_index(workspace_dir, index_name="beta", text="Beta content here.")

    workspace_catalog.delete_index(workspace_dir, slug_a)

    assert workspace_catalog.get_index(workspace_dir, slug_a) is None
    assert not index_root_dir(workspace_dir, slug_a).exists()
    assert workspace_catalog.get_index(workspace_dir, slug_b) is not None
    assert index_root_dir(workspace_dir, slug_b).is_dir()


def test_validate_slug_rejects_empty_and_traversal() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        validate_slug("")
    with pytest.raises(ValueError, match="invalid slug"):
        validate_slug("../bad")
