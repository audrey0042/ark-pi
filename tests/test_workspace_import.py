import json
import zipfile
from pathlib import Path

import pytest

from ark_pi.config import clear_settings_cache
from ark_pi.rag import index as rag_index
from ark_pi.workspace import catalog as workspace_catalog
from ark_pi.workspace import ingest as workspace_ingest
from ark_pi.workspace.export import export_workspace
from ark_pi.workspace.importer import WorkspaceImportError, import_workspace
from ark_pi.workspace.paths import index_root_dir

SAMPLE_TEXT = "Ark Pi workspace import test content for indexing and search."
OTHER_TEXT = "Unrelated existing index content stays untouched during merge."


@pytest.fixture
def workspace_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ws = tmp_path / "workspace"
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(ws))
    clear_settings_cache()
    yield ws
    clear_settings_cache()


@pytest.fixture
def empty_workspace_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ws = tmp_path / "empty-workspace"
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


def _export_to(source_workspace: Path, output: Path, *, slug: str | None = None) -> None:
    export_workspace(source_workspace, output, slug=slug)


def test_export_then_import_into_empty_workspace_restores_catalog_entry(
    workspace_dir: Path,
    empty_workspace_dir: Path,
    tmp_path: Path,
) -> None:
    slug = _create_index(workspace_dir, index_name="sample")
    archive = tmp_path / "export.zip"
    _export_to(workspace_dir, archive)

    result = import_workspace(empty_workspace_dir, archive)

    assert result.imported_count == 1
    assert result.imported_slugs == [slug]
    entry = workspace_catalog.get_index(empty_workspace_dir, slug)
    assert entry is not None
    assert entry.name == "sample"
    assert Path(entry.chunks_path).is_file()
    assert Path(entry.index_dir).is_dir()


def test_imported_index_can_be_searched(
    workspace_dir: Path,
    empty_workspace_dir: Path,
    tmp_path: Path,
) -> None:
    slug = _create_index(workspace_dir, index_name="searchable")
    archive = tmp_path / "export.zip"
    _export_to(workspace_dir, archive)

    import_workspace(empty_workspace_dir, archive)
    entry = workspace_catalog.get_index(empty_workspace_dir, slug)
    assert entry is not None

    results = rag_index.search_index(Path(entry.index_dir), "import test content", limit=3)
    assert len(results) >= 1


def test_import_merges_with_existing_unrelated_catalog_entries(
    workspace_dir: Path,
    tmp_path: Path,
) -> None:
    existing_slug = _create_index(workspace_dir, index_name="existing", text=OTHER_TEXT)
    export_source = tmp_path / "source-workspace"
    export_source.mkdir()
    imported_slug = _create_index(export_source, index_name="imported")
    archive = tmp_path / "export.zip"
    _export_to(export_source, archive)

    result = import_workspace(workspace_dir, archive)

    assert result.imported_count == 1
    assert result.imported_slugs == [imported_slug]
    assert workspace_catalog.get_index(workspace_dir, existing_slug) is not None
    assert workspace_catalog.get_index(workspace_dir, imported_slug) is not None
    assert len(workspace_catalog.list_indexes(workspace_dir)) == 2


def test_import_conflict_without_force_fails(
    workspace_dir: Path,
    tmp_path: Path,
) -> None:
    slug = _create_index(workspace_dir, index_name="sample")
    archive = tmp_path / "export.zip"
    _export_to(workspace_dir, archive)

    with pytest.raises(WorkspaceImportError, match="already exists"):
        import_workspace(workspace_dir, archive)


def test_import_conflict_with_force_replaces_only_imported_slug(
    workspace_dir: Path,
    tmp_path: Path,
) -> None:
    slug = _create_index(workspace_dir, index_name="alpha", text="Original alpha content.")
    other_slug = _create_index(workspace_dir, index_name="beta", text="Beta stays.")
    original_alpha_chunks = workspace_catalog.get_index(workspace_dir, slug)
    assert original_alpha_chunks is not None
    original_mtime = Path(original_alpha_chunks.chunks_path).stat().st_mtime

    export_source = tmp_path / "source-workspace"
    export_source.mkdir()
    _create_index(export_source, index_name="alpha", text="Replacement alpha content.")
    archive = tmp_path / "export.zip"
    _export_to(export_source, archive, slug=slug)

    result = import_workspace(workspace_dir, archive, force=True)

    assert result.imported_slugs == [slug]
    assert workspace_catalog.get_index(workspace_dir, other_slug) is not None
    alpha = workspace_catalog.get_index(workspace_dir, slug)
    assert alpha is not None
    new_mtime = Path(alpha.chunks_path).stat().st_mtime
    assert new_mtime >= original_mtime
    results = rag_index.search_index(Path(alpha.index_dir), "Replacement alpha", limit=3)
    assert len(results) >= 1


def test_import_missing_export_manifest_fails(
    workspace_dir: Path,
    tmp_path: Path,
) -> None:
    _create_index(workspace_dir, index_name="sample")
    archive = tmp_path / "export.zip"
    _export_to(workspace_dir, archive)

    with zipfile.ZipFile(archive, "r") as zf:
        entries = {
            name: zf.read(name)
            for name in zf.namelist()
            if name != "export_manifest.json"
        }
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            zf.writestr(name, content)

    target = tmp_path / "target-workspace"
    with pytest.raises(WorkspaceImportError, match="missing export_manifest"):
        import_workspace(target, archive)


def test_import_unsupported_schema_version_fails(
    workspace_dir: Path,
    tmp_path: Path,
) -> None:
    _create_index(workspace_dir, index_name="sample")
    archive = tmp_path / "export.zip"
    _export_to(workspace_dir, archive)

    with zipfile.ZipFile(archive, "r") as zf:
        entries = {name: zf.read(name) for name in zf.namelist()}
    manifest = json.loads(entries["export_manifest.json"])
    manifest["schema_version"] = 99
    entries["export_manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            zf.writestr(name, content)

    target = tmp_path / "target-workspace"
    with pytest.raises(WorkspaceImportError, match="Unsupported workspace export schema"):
        import_workspace(target, archive)


def test_import_path_traversal_entry_fails(
    workspace_dir: Path,
    tmp_path: Path,
) -> None:
    _create_index(workspace_dir, index_name="sample")
    archive = tmp_path / "export.zip"
    _export_to(workspace_dir, archive)

    with zipfile.ZipFile(archive, "a") as zf:
        zf.writestr("indexes/../escape.txt", "bad")

    target = tmp_path / "target-workspace"
    with pytest.raises(WorkspaceImportError, match="unsafe path"):
        import_workspace(target, archive)


def test_import_absolute_path_entry_fails(
    workspace_dir: Path,
    tmp_path: Path,
) -> None:
    _create_index(workspace_dir, index_name="sample")
    archive = tmp_path / "export.zip"
    _export_to(workspace_dir, archive)

    with zipfile.ZipFile(archive, "a") as zf:
        zf.writestr("/etc/passwd", "bad")

    target = tmp_path / "target-workspace"
    with pytest.raises(WorkspaceImportError, match="unsafe path"):
        import_workspace(target, archive)


def test_import_catalog_paths_outside_workspace_still_imports_safely(
    workspace_dir: Path,
    empty_workspace_dir: Path,
    tmp_path: Path,
) -> None:
    slug = _create_index(workspace_dir, index_name="safe")
    archive = tmp_path / "export.zip"
    _export_to(workspace_dir, archive)

    outside = tmp_path / "outside"
    outside.mkdir()
    with zipfile.ZipFile(archive, "r") as zf:
        entries = {name: zf.read(name) for name in zf.namelist()}
    catalog = json.loads(entries["catalog.json"])
    catalog["indexes"][0]["chunks_path"] = str(outside / "fake-chunks.jsonl")
    catalog["indexes"][0]["index_dir"] = str(outside)
    entries["catalog.json"] = (json.dumps(catalog, indent=2) + "\n").encode("utf-8")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            zf.writestr(name, content)

    import_workspace(empty_workspace_dir, archive)
    entry = workspace_catalog.get_index(empty_workspace_dir, slug)
    assert entry is not None
    assert str(index_root_dir(empty_workspace_dir, slug)) in entry.chunks_path
    assert str(index_root_dir(empty_workspace_dir, slug)) in entry.index_dir
    assert Path(entry.chunks_path).is_file()


def test_import_invalid_zip_fails(tmp_path: Path) -> None:
    bad = tmp_path / "not-a-zip.zip"
    bad.write_text("not a zip file", encoding="utf-8")
    target = tmp_path / "workspace"

    with pytest.raises(WorkspaceImportError, match="not a valid zip"):
        import_workspace(target, bad)


def test_import_missing_archive_fails(tmp_path: Path) -> None:
    target = tmp_path / "workspace"
    missing = tmp_path / "missing.zip"

    with pytest.raises(WorkspaceImportError, match="does not exist"):
        import_workspace(target, missing)
