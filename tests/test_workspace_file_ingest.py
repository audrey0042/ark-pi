from pathlib import Path

import pytest

from ark_pi.config import clear_settings_cache, get_settings
from ark_pi.rag import index as rag_index
from ark_pi.workspace import catalog as workspace_catalog
from ark_pi.workspace import ingest as workspace_ingest
from ark_pi.workspace.paths import resolve_source_path


SAMPLE_TEXT = (
    "Ark Pi splits work across two Raspberry Pis. "
    "The RAG Pi owns document ingestion, chunking, indexing, retrieval, and prompt assembly. "
    "The LLM Pi runs llama.cpp and generates text from assembled prompts."
)


@pytest.fixture
def source_and_workspace_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    src = tmp_path / "sources"
    ws = tmp_path / "workspace"
    src.mkdir()
    monkeypatch.setenv("ARK_SOURCE_DIR", str(src))
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(ws))
    clear_settings_cache()
    yield src, ws
    clear_settings_cache()


def _ingest_file(
    source_dir: Path,
    workspace_dir: Path,
    *,
    source_path: str,
    index_name: str = "sample",
    force: bool = False,
) -> workspace_ingest.WorkspacePathIngestResult:
    return workspace_ingest.ingest_source_path_to_workspace_index(
        source_path,
        index_name,
        source_dir,
        workspace_dir,
        force=force,
    )


def test_ingest_txt_file_into_named_workspace_index(
    source_and_workspace_env: tuple[Path, Path],
) -> None:
    source_dir, workspace_dir = source_and_workspace_env
    txt_path = source_dir / "note.txt"
    txt_path.write_text(SAMPLE_TEXT, encoding="utf-8")

    result = _ingest_file(source_dir, workspace_dir, source_path="note.txt")

    assert result.index_name == "sample"
    assert result.index_slug == "sample"
    assert result.source_count == 1
    assert result.chunk_count >= 1
    assert result.catalog_updated is True
    assert (workspace_dir / "catalog.json").is_file()
    assert (workspace_dir / "indexes" / "sample" / "index" / "manifest.json").is_file()

    entry = workspace_catalog.get_index(workspace_dir, "sample")
    assert entry is not None
    assert entry.source_count == 1
    assert entry.chunk_count == result.chunk_count

    search_results = rag_index.search_index(result.index_dir, "prompt assembly", limit=3)
    assert len(search_results) >= 1


def test_ingest_directory_of_txt_files(source_and_workspace_env: tuple[Path, Path]) -> None:
    source_dir, workspace_dir = source_and_workspace_env
    docs = source_dir / "docs"
    docs.mkdir()
    (docs / "a.txt").write_text("First document about retrieval.", encoding="utf-8")
    (docs / "b.txt").write_text("Second document about indexing.", encoding="utf-8")

    result = _ingest_file(source_dir, workspace_dir, source_path="docs", index_name="docs-index")

    assert result.source_count == 2
    assert result.chunk_count >= 2

    entry = workspace_catalog.get_index(workspace_dir, "docs-index")
    assert entry is not None
    assert entry.source_count == 2


def test_reject_source_path_outside_source_dir(
    source_and_workspace_env: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    source_dir, workspace_dir = source_and_workspace_env
    outside = tmp_path / "outside.txt"
    outside.write_text(SAMPLE_TEXT, encoding="utf-8")

    with pytest.raises(ValueError, match="inside configured source_dir"):
        resolve_source_path(source_dir, str(outside))


def test_reject_traversal_path(source_and_workspace_env: tuple[Path, Path]) -> None:
    source_dir, workspace_dir = source_and_workspace_env
    subdir = source_dir / "subdir"
    subdir.mkdir()
    (subdir / "note.txt").write_text(SAMPLE_TEXT, encoding="utf-8")

    with pytest.raises(ValueError, match="inside configured source_dir"):
        _ingest_file(source_dir, workspace_dir, source_path="subdir/../../etc/passwd")


def test_reject_unsupported_extension(source_and_workspace_env: tuple[Path, Path]) -> None:
    source_dir, workspace_dir = source_and_workspace_env
    (source_dir / "data.jsonl").write_text(
        '{"title":"T","text":"Body"}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Only .txt files and directories"):
        _ingest_file(source_dir, workspace_dir, source_path="data.jsonl")


def test_reject_unsupported_pdf_extension(source_and_workspace_env: tuple[Path, Path]) -> None:
    source_dir, workspace_dir = source_and_workspace_env
    (source_dir / "doc.pdf").write_bytes(b"%PDF-1.4")

    with pytest.raises(ValueError, match="Only .txt files and directories"):
        _ingest_file(source_dir, workspace_dir, source_path="doc.pdf")


def test_reject_missing_file(source_and_workspace_env: tuple[Path, Path]) -> None:
    source_dir, workspace_dir = source_and_workspace_env

    with pytest.raises(FileNotFoundError, match="does not exist"):
        _ingest_file(source_dir, workspace_dir, source_path="missing.txt")


def test_reject_directory_with_no_txt_files(source_and_workspace_env: tuple[Path, Path]) -> None:
    source_dir, workspace_dir = source_and_workspace_env
    empty_dir = source_dir / "empty"
    empty_dir.mkdir()

    with pytest.raises(ValueError, match="No .txt files found"):
        _ingest_file(source_dir, workspace_dir, source_path="empty")


def test_rebuild_without_force_fails(source_and_workspace_env: tuple[Path, Path]) -> None:
    source_dir, workspace_dir = source_and_workspace_env
    (source_dir / "note.txt").write_text(SAMPLE_TEXT, encoding="utf-8")

    _ingest_file(source_dir, workspace_dir, source_path="note.txt")

    with pytest.raises(ValueError, match="already exists"):
        _ingest_file(source_dir, workspace_dir, source_path="note.txt")


def test_rebuild_with_force_succeeds(source_and_workspace_env: tuple[Path, Path]) -> None:
    source_dir, workspace_dir = source_and_workspace_env
    (source_dir / "note.txt").write_text(SAMPLE_TEXT, encoding="utf-8")

    first = _ingest_file(source_dir, workspace_dir, source_path="note.txt")
    second = _ingest_file(source_dir, workspace_dir, source_path="note.txt", force=True)

    assert second.chunk_count == first.chunk_count
    assert workspace_catalog.get_index(workspace_dir, "sample") is not None


def test_settings_include_source_dir(source_and_workspace_env: tuple[Path, Path]) -> None:
    source_dir, _workspace_dir = source_and_workspace_env
    settings = get_settings()
    assert settings.source_dir.resolve() == source_dir.resolve()
