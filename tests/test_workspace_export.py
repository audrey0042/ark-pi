import json
import zipfile
from pathlib import Path

import pytest

from ark_pi.config import clear_settings_cache
from ark_pi.workspace import catalog as workspace_catalog
from ark_pi.workspace import ingest as workspace_ingest
from ark_pi.workspace.catalog import WorkspaceIndexNotFoundError
from ark_pi.workspace.export import WorkspaceExportError, export_workspace
from ark_pi.workspace.paths import index_root_dir

SAMPLE_TEXT = "Ark Pi workspace export test content for indexing."


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


def test_export_all_indexes_writes_zip(workspace_dir: Path, tmp_path: Path) -> None:
    _create_index(workspace_dir, index_name="alpha")
    output = tmp_path / "export-all.zip"

    result = export_workspace(workspace_dir, output)

    assert result.output_path == output.resolve()
    assert result.index_count == 1
    assert result.archive_size_bytes > 0
    assert output.is_file()


def test_export_archive_includes_catalog_and_manifest(
    workspace_dir: Path,
    tmp_path: Path,
) -> None:
    slug = _create_index(workspace_dir, index_name="sample")
    output = tmp_path / "export.zip"

    export_workspace(workspace_dir, output)

    with zipfile.ZipFile(output, "r") as archive:
        names = set(archive.namelist())
        assert "catalog.json" in names
        assert "export_manifest.json" in names
        catalog = json.loads(archive.read("catalog.json"))
        assert catalog["schema_version"] == 1
        assert len(catalog["indexes"]) == 1
        assert catalog["indexes"][0]["slug"] == slug
        manifest = json.loads(archive.read("export_manifest.json"))
        assert manifest["created_by"] == "ark-pi"
        assert manifest["export_type"] == "workspace"
        assert manifest["index_count"] == 1


def test_export_archive_includes_chunks_jsonl(
    workspace_dir: Path,
    tmp_path: Path,
) -> None:
    slug = _create_index(workspace_dir, index_name="sample")
    output = tmp_path / "export.zip"

    export_workspace(workspace_dir, output)

    with zipfile.ZipFile(output, "r") as archive:
        chunks_path = f"indexes/{slug}/chunks.jsonl"
        assert chunks_path in archive.namelist()
        index_manifest = f"indexes/{slug}/index/manifest.json"
        assert index_manifest in archive.namelist()


def test_export_one_slug_includes_only_that_index(
    workspace_dir: Path,
    tmp_path: Path,
) -> None:
    slug_a = _create_index(workspace_dir, index_name="alpha", text="Alpha export content.")
    _create_index(workspace_dir, index_name="beta", text="Beta export content.")
    output = tmp_path / "export-one.zip"

    result = export_workspace(workspace_dir, output, slug=slug_a)

    assert result.index_count == 1
    with zipfile.ZipFile(output, "r") as archive:
        catalog = json.loads(archive.read("catalog.json"))
        assert len(catalog["indexes"]) == 1
        assert catalog["indexes"][0]["slug"] == slug_a
        names = archive.namelist()
        assert any(name.startswith(f"indexes/{slug_a}/") for name in names)
        assert not any(name.startswith("indexes/beta/") for name in names)


def test_export_missing_slug_fails(workspace_dir: Path, tmp_path: Path) -> None:
    _create_index(workspace_dir, index_name="sample")
    output = tmp_path / "export.zip"

    with pytest.raises(WorkspaceIndexNotFoundError, match="Workspace index not found"):
        export_workspace(workspace_dir, output, slug="missing")


def test_export_empty_catalog_fails(workspace_dir: Path, tmp_path: Path) -> None:
    output = tmp_path / "export.zip"

    with pytest.raises(WorkspaceExportError, match="catalog is empty"):
        export_workspace(workspace_dir, output)


def test_export_existing_output_without_force_fails(
    workspace_dir: Path,
    tmp_path: Path,
) -> None:
    _create_index(workspace_dir, index_name="sample")
    output = tmp_path / "export.zip"
    output.write_text("existing", encoding="utf-8")

    with pytest.raises(WorkspaceExportError, match="already exists"):
        export_workspace(workspace_dir, output)


def test_export_existing_output_with_force_succeeds(
    workspace_dir: Path,
    tmp_path: Path,
) -> None:
    _create_index(workspace_dir, index_name="sample")
    output = tmp_path / "export.zip"
    output.write_text("existing", encoding="utf-8")

    result = export_workspace(workspace_dir, output, force=True)

    assert result.index_count == 1
    with zipfile.ZipFile(output, "r") as archive:
        assert "catalog.json" in archive.namelist()


def test_export_ignores_catalog_paths_outside_workspace(
    workspace_dir: Path,
    tmp_path: Path,
) -> None:
    slug = _create_index(workspace_dir, index_name="safe")
    entry = workspace_catalog.get_index(workspace_dir, slug)
    assert entry is not None

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "fake-chunks.jsonl").write_text("{}", encoding="utf-8")

    tampered = workspace_catalog.CatalogIndexEntry(
        name=entry.name,
        slug=entry.slug,
        backend=entry.backend,
        chunks_path=str(outside / "fake-chunks.jsonl"),
        index_dir=str(outside),
        chunk_count=entry.chunk_count,
        source_count=entry.source_count,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )
    workspace_catalog.upsert_index(workspace_dir, tampered)

    output = tmp_path / "export.zip"
    export_workspace(workspace_dir, output, slug=slug)

    with zipfile.ZipFile(output, "r") as archive:
        chunks_path = f"indexes/{slug}/chunks.jsonl"
        assert chunks_path in archive.namelist()
        assert not any("outside" in name for name in archive.namelist())

    assert index_root_dir(workspace_dir, slug).is_dir()
