import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from ark_pi.cli import app
from ark_pi.rag import chroma_index
from ark_pi.rag.index import IndexDependencyError

runner = CliRunner()


def _write_chunks(path: Path) -> None:
    record = {
        "id": "sample:000000:abc123def456",
        "title": "Sample",
        "source": "sample.txt",
        "chunk_index": 0,
        "text": "The RAG Pi owns retrieval and prompt assembly.",
        "sha256": "abc123def456789012345678901234567890123456789012345678901234567890",
    }
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")


def test_chroma_index_module_imports_without_chromadb() -> None:
    assert chroma_index.BACKEND_NAME == "chroma"


def test_missing_chromadb_raises_index_dependency_error() -> None:
    import builtins

    original_import = builtins.__import__

    def blocked_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "chromadb" or name.startswith("chromadb."):
            raise ImportError("chromadb is not installed")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=blocked_import):
        with pytest.raises(IndexDependencyError, match="pip install -e '.\\[chroma\\]'"):
            chroma_index._import_chromadb()


def test_chroma_backend_build_without_chromadb_exits_nonzero(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "chroma_index"
    _write_chunks(chunks_path)

    import builtins

    original_import = builtins.__import__

    def blocked_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "chromadb" or name.startswith("chromadb."):
            raise ImportError("chromadb is not installed")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=blocked_import):
        result = runner.invoke(
            app,
            [
                "index",
                "build",
                "--backend",
                "chroma",
                "--chunks",
                str(chunks_path),
                "--index-dir",
                str(index_dir),
                "--force",
            ],
        )

    assert result.exit_code != 0
    assert "pip install -e '.[chroma]'" in result.stderr or "pip install -e '.[chroma]'" in result.stdout
